"""Produce the single pre-registered TXF holdout verdict.

This script is deliberately a report-only consumer.  It does not fetch data,
generate events, or recompute the crash-month list.  The input must be the
event NDJSON emitted by the already-reviewed Pine bar path; ``kind=random``
rows are the controls constructed by that dump with the same per-session
uniform sampling as ``pine_control_dump.py``.

The protocol below is copied from
``docs/pre-registration-2026-08-06-pine-holdout-2020-2024.md``:

* candidate: 15-minute ``rejection``, ``orig``, SHORT;
* horizons: 60, 240, and session close;
* round-trip cost: 3.0 points;
* no fallback candidate or session subset;
* nine fixed periods, 7/9 for P1 and P3, 6/9 for P4;
* 10,000 bootstrap resamples with seed 20260806; and
* fixed crash months 2020-03, 2021-05, and 2022-06.

P1 and P2 are evaluated against both reported control forms.  For the
time-matched bootstrap, each eligible signal observation is paired with the
mean of its control bucket (period × session × 30-minute-of-session).  This
is the same weighting used by ``pine_control_test.py``'s
``matched_control_mean`` while applying its bootstrap machinery to the
matched sample.

Usage:
    pine_holdout_verdict.py <holdout-events.ndjson> [more.ndjson ...]

Redirect stdout to retain the standalone report.  The script refuses rows
outside the registered holdout window, so passing a reconciliation dump is a
failure rather than a silently mixed result.
"""

from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path


COST = 3.0
HORIZONS = ("60", "240", "sclose")
BOOTSTRAP = 10_000
SEED = 20260806
BUCKET_MINUTES = 30
SIGNAL_TIMEFRAME = 15
SIGNAL_NAME = "rejection"
SIGNAL_VARIANT = "orig"
SIGNAL_DIRECTION = -1
P1_REQUIRED_PERIODS = 7
P4_MIN_N = 100
P4_REQUIRED_PERIODS = 6
HOLDOUT_START = date(2020, 3, 2)
HOLDOUT_END = date(2024, 7, 26)
CRASH_MONTHS = frozenset({"2020-03", "2021-05", "2022-06"})


@dataclass(frozen=True, slots=True)
class PeriodSpec:
    name: str
    start: date
    end: date


PERIODS = (
    PeriodSpec("2020H1", date(2020, 3, 2), date(2020, 6, 30)),
    PeriodSpec("2020H2", date(2020, 7, 1), date(2020, 12, 31)),
    PeriodSpec("2021H1", date(2021, 1, 1), date(2021, 6, 30)),
    PeriodSpec("2021H2", date(2021, 7, 1), date(2021, 12, 31)),
    PeriodSpec("2022H1", date(2022, 1, 1), date(2022, 6, 30)),
    PeriodSpec("2022H2", date(2022, 7, 1), date(2022, 12, 31)),
    PeriodSpec("2023H1", date(2023, 1, 1), date(2023, 6, 30)),
    PeriodSpec("2023H2", date(2023, 7, 1), date(2023, 12, 31)),
    PeriodSpec("2024H1", date(2024, 1, 1), date(2024, 7, 26)),
)
PERIOD_NAMES = tuple(period.name for period in PERIODS)


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    timeframe: int
    signal: str
    variant: str
    direction: int
    trading_date: date
    period: str
    session: str
    minute_of_session: int
    deltas: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    lower: float
    upper: float

    @property
    def excludes_zero(self) -> bool:
        return self.lower > 0.0 or self.upper < 0.0


@dataclass(frozen=True, slots=True)
class PeriodStats:
    period: str
    signal_n: int
    control_n: int
    matched_n: int
    signal_mean: float | None
    control_plain_mean: float | None
    control_matched_mean: float | None
    difference_plain: float | None
    difference_matched: float | None


@dataclass(frozen=True, slots=True)
class HorizonResult:
    horizon: str
    periods: tuple[PeriodStats, ...]
    p1_plain_periods: int
    p1_matched_periods: int
    p1_joint_periods: int
    p1_pass: bool
    p2_plain: ConfidenceInterval | None
    p2_matched: ConfidenceInterval | None
    p2_pass: bool
    p2_plain_without_crash: ConfidenceInterval | None
    p2_matched_without_crash: ConfidenceInterval | None
    crash_p2_pass: bool
    p3_positive_periods: int
    p3_pass: bool
    p4_sufficient_periods: int
    p4_pass: bool
    full_pass: bool
    label: str


@dataclass(frozen=True, slots=True)
class VerdictReport:
    horizons: tuple[HorizonResult, ...]
    label: str


def period_for_date(trading_date: date) -> str:
    """Resolve the registered nine-period split, including the 2024 stub."""

    if trading_date < HOLDOUT_START or trading_date > HOLDOUT_END:
        raise ValueError(
            "event date is outside the registered holdout window: "
            f"{trading_date.isoformat()}"
        )
    for period in PERIODS:
        if period.start <= trading_date <= period.end:
            return period.name
    raise ValueError(f"event date is not in a registered period: {trading_date}")


def _month(trading_date: date) -> str:
    return trading_date.strftime("%Y-%m")


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"event field {field!r} must be an integer")
    return value


def _parse_event(row: Mapping[str, object]) -> Event:
    raw_date = row.get("trading_date")
    if not isinstance(raw_date, str):
        raise ValueError("event trading_date is required")
    try:
        trading_date = date.fromisoformat(raw_date)
    except ValueError as error:
        raise ValueError(f"invalid event trading_date: {raw_date}") from error
    if trading_date.isoformat() != raw_date:
        raise ValueError(f"event trading_date is not canonical: {raw_date}")
    period = period_for_date(trading_date)
    # The verdict owns the registered split.  Do not inherit a stale emitter
    # label: the existing gate dump used a later-window reporting period.

    kind = row.get("kind")
    session = row.get("session")
    if not isinstance(kind, str) or not kind:
        raise ValueError("event kind is required")
    if not isinstance(session, str) or not session:
        raise ValueError("event session is required")
    minute = _as_int(row.get("minute_of_session"), "minute_of_session")
    if minute < 0:
        raise ValueError("event minute_of_session must be non-negative")

    deltas = row.get("deltas")
    if not isinstance(deltas, Mapping):
        raise ValueError("event deltas must be an object")
    parsed_deltas: dict[str, float] = {}
    for key, value in deltas.items():
        if not isinstance(key, str):
            raise ValueError("event delta keys must be strings")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"event delta {key!r} must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError(f"event delta {key!r} must be finite")
        parsed_deltas[key] = float(value)

    timeframe = _as_int(row.get("timeframe"), "timeframe")
    direction = _as_int(row.get("direction"), "direction")
    signal = row.get("signal")
    variant = row.get("variant")
    if not isinstance(signal, str) or not isinstance(variant, str):
        raise ValueError("event signal and variant are required strings")
    return Event(
        kind=kind,
        timeframe=timeframe,
        signal=signal,
        variant=variant,
        direction=direction,
        trading_date=trading_date,
        period=period,
        session=session,
        minute_of_session=minute,
        deltas=parsed_deltas,
    )


def load(paths: Sequence[Path]) -> tuple[Event, ...]:
    """Load and validate only the registered holdout event rows."""

    if not paths:
        raise ValueError("at least one event NDJSON path is required")
    events: list[Event] = []
    for path in paths:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON in {path}:{line_number}") from error
            if not isinstance(payload, dict):
                raise ValueError(f"event row is not an object: {path}:{line_number}")
            events.append(_parse_event(payload))
    if not events:
        raise ValueError("event input contains no rows")
    return tuple(events)


def net(delta: float, direction: int = SIGNAL_DIRECTION) -> float:
    """Apply the registered direction and 3.0-point round-trip cost."""

    return direction * delta - COST


def _bucket(event: Event) -> tuple[str, str, int]:
    return (
        event.period,
        event.session,
        event.minute_of_session // BUCKET_MINUTES,
    )


def _net_values(events: Iterable[Event], horizon: str) -> list[float]:
    return [
        net(event.deltas[horizon])
        for event in events
        if horizon in event.deltas
    ]


def _matched_values(
    signal_events: Iterable[Event],
    control_events: Iterable[Event],
    horizon: str,
) -> tuple[list[float], list[float]]:
    """Return signal values and bucket means with signal-derived weights."""

    controls_by_bucket: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for event in control_events:
        if horizon in event.deltas:
            controls_by_bucket[_bucket(event)].append(net(event.deltas[horizon]))

    signal_values: list[float] = []
    matched_control_values: list[float] = []
    for event in signal_events:
        if horizon not in event.deltas:
            continue
        values = controls_by_bucket.get(_bucket(event))
        if not values:
            continue
        signal_values.append(net(event.deltas[horizon]))
        matched_control_values.append(sum(values) / len(values))
    return signal_values, matched_control_values


def bootstrap_ci(
    sample_a: Sequence[float],
    sample_b: Sequence[float],
    rng: random.Random,
) -> ConfidenceInterval | None:
    """Use the original test's independent pooled bootstrap machinery."""

    if not sample_a or not sample_b:
        return None
    differences: list[float] = []
    n_a, n_b = len(sample_a), len(sample_b)
    for _ in range(BOOTSTRAP):
        mean_a = sum(sample_a[rng.randrange(n_a)] for _ in range(n_a)) / n_a
        mean_b = sum(sample_b[rng.randrange(n_b)] for _ in range(n_b)) / n_b
        differences.append(mean_a - mean_b)
    differences.sort()
    tail = (1.0 - 0.95) / 2.0
    lower = differences[int(tail * BOOTSTRAP)]
    upper = differences[
        min(BOOTSTRAP - 1, int((1.0 - tail) * BOOTSTRAP))
    ]
    return ConfidenceInterval(lower, upper)


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _without_crash(events: Iterable[Event]) -> tuple[Event, ...]:
    return tuple(
        event
        for event in events
        if _month(event.trading_date) not in CRASH_MONTHS
    )


def _period_stats(
    signal_events: Sequence[Event],
    control_events: Sequence[Event],
    horizon: str,
) -> tuple[PeriodStats, ...]:
    output: list[PeriodStats] = []
    for period in PERIOD_NAMES:
        signal = [event for event in signal_events if event.period == period]
        controls = [event for event in control_events if event.period == period]
        signal_values = _net_values(signal, horizon)
        control_values = _net_values(controls, horizon)
        _matched_signal, matched_values = _matched_values(
            signal,
            controls,
            horizon,
        )
        signal_mean = _mean(signal_values)
        control_plain_mean = _mean(control_values)
        control_matched_mean = _mean(matched_values)
        output.append(PeriodStats(
            period=period,
            signal_n=len(signal_values),
            control_n=len(control_values),
            matched_n=len(matched_values),
            signal_mean=signal_mean,
            control_plain_mean=control_plain_mean,
            control_matched_mean=control_matched_mean,
            difference_plain=(
                None
                if signal_mean is None or control_plain_mean is None
                else signal_mean - control_plain_mean
            ),
            difference_matched=(
                None
                if signal_mean is None or control_matched_mean is None
                else signal_mean - control_matched_mean
            ),
        ))
    return tuple(output)


def _horizon_result(
    signal_events: Sequence[Event],
    control_events: Sequence[Event],
    horizon: str,
    rng: random.Random,
) -> HorizonResult:
    periods = _period_stats(signal_events, control_events, horizon)
    signal_all = _net_values(signal_events, horizon)
    control_all = _net_values(control_events, horizon)
    matched_signal_all, matched_control_all = _matched_values(
        signal_events,
        control_events,
        horizon,
    )

    p1_plain_periods = sum(
        period.signal_mean is not None
        and period.control_plain_mean is not None
        and period.signal_mean > period.control_plain_mean
        for period in periods
    )
    p1_matched_periods = sum(
        period.signal_mean is not None
        and period.control_matched_mean is not None
        and period.signal_mean > period.control_matched_mean
        for period in periods
    )
    p1_joint_periods = sum(
        period.signal_mean is not None
        and period.control_plain_mean is not None
        and period.control_matched_mean is not None
        and period.signal_mean > period.control_plain_mean
        and period.signal_mean > period.control_matched_mean
        for period in periods
    )
    p1_pass = p1_joint_periods >= P1_REQUIRED_PERIODS

    p2_plain = bootstrap_ci(signal_all, control_all, rng)
    p2_matched = bootstrap_ci(matched_signal_all, matched_control_all, rng)
    p2_pass = (
        p2_plain is not None
        and p2_matched is not None
        and p2_plain.excludes_zero
        and p2_matched.excludes_zero
    )

    signal_without_crash = _without_crash(signal_events)
    control_without_crash = _without_crash(control_events)
    crash_signal_all = _net_values(signal_without_crash, horizon)
    crash_control_all = _net_values(control_without_crash, horizon)
    (
        crash_matched_signal_all,
        crash_matched_control_all,
    ) = _matched_values(
        signal_without_crash,
        control_without_crash,
        horizon,
    )
    p2_plain_without_crash = bootstrap_ci(
        crash_signal_all,
        crash_control_all,
        rng,
    )
    p2_matched_without_crash = bootstrap_ci(
        crash_matched_signal_all,
        crash_matched_control_all,
        rng,
    )
    crash_p2_pass = (
        p2_plain_without_crash is not None
        and p2_matched_without_crash is not None
        and p2_plain_without_crash.excludes_zero
        and p2_matched_without_crash.excludes_zero
    )

    p3_positive_periods = sum(
        period.signal_mean is not None and period.signal_mean > 0.0
        for period in periods
    )
    p3_pass = p3_positive_periods >= P1_REQUIRED_PERIODS
    p4_sufficient_periods = sum(
        period.signal_n >= P4_MIN_N
        for period in periods
    )
    p4_pass = p4_sufficient_periods >= P4_REQUIRED_PERIODS
    full_pass = p1_pass and p2_pass and p3_pass and p4_pass
    label = (
        "PASS"
        if full_pass and crash_p2_pass
        else "PASS (crash-dependent)"
        if full_pass
        else "FAIL"
    )
    return HorizonResult(
        horizon=horizon,
        periods=periods,
        p1_plain_periods=p1_plain_periods,
        p1_matched_periods=p1_matched_periods,
        p1_joint_periods=p1_joint_periods,
        p1_pass=p1_pass,
        p2_plain=p2_plain,
        p2_matched=p2_matched,
        p2_pass=p2_pass,
        p2_plain_without_crash=p2_plain_without_crash,
        p2_matched_without_crash=p2_matched_without_crash,
        crash_p2_pass=crash_p2_pass,
        p3_positive_periods=p3_positive_periods,
        p3_pass=p3_pass,
        p4_sufficient_periods=p4_sufficient_periods,
        p4_pass=p4_pass,
        full_pass=full_pass,
        label=label,
    )


def evaluate(events: Sequence[Event] | Sequence[Mapping[str, object]]) -> VerdictReport:
    """Evaluate the fixed candidate at all three registered horizons."""

    parsed = tuple(
        event if isinstance(event, Event) else _parse_event(event)
        for event in events
    )
    signal_events = tuple(
        event
        for event in parsed
        if (
            event.kind == "signal"
            and event.timeframe == SIGNAL_TIMEFRAME
            and event.signal == SIGNAL_NAME
            and event.variant == SIGNAL_VARIANT
            and event.direction == SIGNAL_DIRECTION
        )
    )
    control_events = tuple(event for event in parsed if event.kind == "random")
    if not signal_events:
        raise ValueError("input contains no registered candidate signal rows")
    if not control_events:
        raise ValueError("input contains no random control rows")

    rng = random.Random(SEED)
    horizons = tuple(
        _horizon_result(signal_events, control_events, horizon, rng)
        for horizon in HORIZONS
    )
    passing = tuple(result for result in horizons if result.full_pass)
    if not passing:
        label = "FAIL"
    elif any(result.crash_p2_pass for result in passing):
        label = "PASS"
    else:
        label = "PASS (crash-dependent)"
    return VerdictReport(horizons=horizons, label=label)


def _number(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.{digits}f}"


def _ci(value: ConfidenceInterval | None) -> str:
    if value is None:
        return "n/a"
    return f"[{value.lower:+.2f}, {value.upper:+.2f}]"


def _pass(value: bool) -> str:
    return "PASS" if value else "FAIL"


def render_report(report: VerdictReport, *, inputs: Sequence[Path] = ()) -> str:
    """Render a self-contained markdown report for the one run."""

    lines = [
        "# Pine TXF holdout verdict",
        "",
        "Protocol: `docs/pre-registration-2026-08-06-pine-holdout-2020-2024.md`",
        "",
        f"- Input: {', '.join(str(path) for path in inputs) or '(synthetic/test input)'}",
        f"- Holdout: {HOLDOUT_START.isoformat()}..{HOLDOUT_END.isoformat()}",
        "- Candidate: timeframe 15, `rejection`, `orig`, SHORT",
        f"- Horizons: {', '.join(HORIZONS)}; round-trip cost: {COST:.1f} points",
        f"- Bootstrap: {BOOTSTRAP:,} resamples; seed: {SEED}",
        "- Periods: " + ", ".join(
            f"{period.name} ({period.start.isoformat()}..{period.end.isoformat()})"
            for period in PERIODS
        ),
        "- Fixed crash months excluded for the second P2 check: "
        + ", ".join(sorted(CRASH_MONTHS)),
        "",
        "Controls are the stored `kind=random` rows: uniform session moments, "
        "reported both plainly and matched by period × session × "
        "30-minute-of-session bucket.",
    ]
    for result in report.horizons:
        lines.extend([
            "",
            f"## Horizon {result.horizon}",
            "",
            "All means and differences below are net after the 3.0-point cost.",
            "",
            "| period | signal N | control N | matched N | signal mean | "
            "control plain | control time-matched | Δ signal−plain | "
            "Δ signal−matched |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for period in result.periods:
            lines.append(
                f"| {period.period} | {period.signal_n} | {period.control_n} | "
                f"{period.matched_n} | {_number(period.signal_mean)} | "
                f"{_number(period.control_plain_mean)} | "
                f"{_number(period.control_matched_mean)} | "
                f"{_number(period.difference_plain)} | "
                f"{_number(period.difference_matched)} |"
            )
        lines.extend([
            "",
            "### Criteria",
            "",
            f"- **P1** signal beats plain control in "
            f"{result.p1_plain_periods}/9 and time-matched control in "
            f"{result.p1_matched_periods}/9; joint {result.p1_joint_periods}/9 "
            f"(required ≥7): **{_pass(result.p1_pass)}**",
            f"- **P2** pooled 95% CI, plain: `{_ci(result.p2_plain)}`; "
            f"time-matched: `{_ci(result.p2_matched)}`; both exclude zero: "
            f"**{_pass(result.p2_pass)}**",
            f"- **P3** signal mean net > 0 in "
            f"{result.p3_positive_periods}/9 periods (required ≥7): "
            f"**{_pass(result.p3_pass)}**",
            f"- **P4** signal N ≥ {P4_MIN_N} in "
            f"{result.p4_sufficient_periods}/9 periods (required ≥6): "
            f"**{_pass(result.p4_pass)}**",
            "",
            "### P2 with crash months excluded",
            "",
            f"- Plain pooled 95% CI: `{_ci(result.p2_plain_without_crash)}`",
            f"- Time-matched pooled 95% CI: `{_ci(result.p2_matched_without_crash)}`",
            f"- Both exclude zero: **{_pass(result.crash_p2_pass)}**",
            "",
            f"**Horizon verdict: {result.label}**",
        ])
    lines.extend([
        "",
        "## Overall verdict",
        "",
        f"**{report.label}**",
    ])
    return "\n".join(lines) + "\n"


def main(paths: Sequence[Path]) -> int:
    events = load(paths)
    report = evaluate(events)
    print(render_report(report, inputs=paths), end="")
    return 0


if __name__ == "__main__":
    arguments = tuple(Path(arg) for arg in sys.argv[1:])
    if not arguments:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    try:
        raise SystemExit(main(arguments))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"PINE HOLDOUT VERDICT FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
