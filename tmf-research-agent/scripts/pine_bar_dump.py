"""Replay the existing Pine signal over stored Shioaji one-minute kbars.

Usage:
    pine_bar_dump.py <raw-root> <calendar.json> <start> <end> <out.ndjson>

The script deliberately imports ``PineState`` and its constants from
``pine_signal_report.py``.  It does not contain a second copy of the signal.
Stored kbar ``Volume`` values are preserved as the vendor supplied them and
summed when a Pine timeframe bar is formed.  Shioaji's ``ts`` is the minute's
closing label (the first day row is 08:46 for the 08:45-08:46 interval); the
decoder normalizes it to the interval start, and the close/volume observation
is placed on the tape at ``timestamp + 1 minute``.  Entry is the first such
close strictly after a signal, and exits use the latest such close at or
before each horizon/session close.

The output uses the same rows as ``pine_control_dump.py``: original and V1
PineState signals, the existing V2/V3 scanners applied to one-minute
observations, and twenty random controls per session.  The random stream uses
the pre-registered bar-path seed 20260806 (the historical tick dump has a
different, already committed seed).
"""

from __future__ import annotations

import json
import random
import sys
from bisect import bisect_left
from collections.abc import Collection
from datetime import timedelta
from json import JSONDecodeError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pine_control_dump import (  # noqa: E402
    RANDOM_ENTRIES_PER_SESSION,
    _deltas,
)
from pine_signal_report import (  # noqa: E402
    HORIZONS,
    PRESETS,
    TIMEFRAMES,
    PineState,
    SegmentManifest,
    SessionTape,
    SignalEvent,
    _period,
    v2_scan,
    v3_scan,
)
from tmf_research.features.context_builder import ResearchBuildSpec  # noqa: E402
from tmf_research.infrastructure.raw_store import (  # noqa: E402
    AppendOnlyRawStore,
)
from tmf_research.processing.kbar_aggregation import (  # noqa: E402
    PineBarSession,
    build_pine_bar_sessions,
    minute_kbars_from_records,
)


SEED = 20260806
KBAR_EVENT_TYPE = "historical-kbar-1m"
DEFAULT_DATASET_VERSION = "tx-holdout-kbars-v1"
DEFAULT_ALIAS_CODE = "TXFR1"


def _manifest_day(segment_id: str, alias_code: str) -> str | None:
    prefix = f"backfill-kbar-1m-{alias_code}-"
    if not segment_id.startswith(prefix):
        return None
    suffix = segment_id[len(prefix) :]
    return suffix[:10] if len(suffix) >= 10 else None


def _load_sessions(
    raw_root: Path,
    *,
    dataset_version: str,
    alias_code: str,
    calendar_path: Path,
    start_day: str,
    end_day: str,
    trading_days: Collection[str] | None = None,
    intervals: tuple[int, ...] = TIMEFRAMES,
) -> tuple[tuple[PineBarSession, ...], int]:
    """Read only the requested kbar segments, never the locked holdout prefix."""

    manifest_path = raw_root / "manifest.ndjson"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifests: list[SegmentManifest] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError("raw-store manifest row is not an object")
        if (
            payload.get("event_type") != KBAR_EVENT_TYPE
            or payload.get("dataset_version") != dataset_version
        ):
            continue
        segment_id = str(payload.get("segment_id", ""))
        day = _manifest_day(segment_id, alias_code)
        if day is None or not start_day <= day <= end_day:
            continue
        manifests.append(SegmentManifest(**payload))
    manifests.sort(key=lambda manifest: manifest.segment_id)
    if not manifests:
        return (), 0

    store = AppendOnlyRawStore(
        raw_root,
        writer_version=manifests[0].writer_version,
        dataset_version=dataset_version,
    )
    records: list[dict[str, object]] = []
    for manifest in manifests:
        records.extend(store.read_verified(manifest))
    calendar = ResearchBuildSpec(calendar=calendar_path).trading_calendar()
    sessions = build_pine_bar_sessions(
        minute_kbars_from_records(records),
        calendar=calendar,
        target_code=alias_code,
        intervals=intervals,
    )
    if trading_days is not None:
        selected_days = frozenset(trading_days)
        sessions = tuple(
            session
            for session in sessions
            if session.trading_date.isoformat() in selected_days
        )
    return sessions, len(records)


def _bar_points(session: PineBarSession, bar_start, bar_end):
    """Use raw one-minute intervals as the only intrabar observations."""

    lo = bisect_left(
        session.minute_bars,
        bar_start,
        key=lambda bar: bar.timestamp,
    )
    hi = bisect_left(
        session.minute_bars,
        bar_end,
        key=lambda bar: bar.timestamp,
    )
    return [
        (
            minute.timestamp + timedelta(minutes=1),
            minute.close,
            minute.volume,
        )
        for minute in session.minute_bars[lo:hi]
    ]


def _row(
    event: SignalEvent,
    tape: SessionTape,
    session: PineBarSession,
) -> dict[str, object] | None:
    deltas = _deltas(tape, event.time, session.session_end)
    if deltas is None:
        return None
    return {
        "trading_date": event.trading_date,
        "session": event.session,
        "period": _period(event.trading_date),
        "kind": "random" if event.variant == "random" else "signal",
        "timeframe": event.timeframe,
        "signal": event.signal,
        "variant": event.variant,
        "direction": event.direction,
        "when": event.time.isoformat(),
        "minute_of_session": int(
            (event.time - session.session_start).total_seconds() // 60
        ),
        "deltas": {
            key: round(deltas[key], 4)
            for key in (*tuple(str(h) for h in HORIZONS), "sclose")
            if key in deltas
        },
    }


def _signal_event(
    session: PineBarSession,
    timeframe: int,
    signal: str,
    variant: str,
    direction: int,
    when,
    level: float,
) -> SignalEvent:
    return SignalEvent(
        timeframe=timeframe,
        signal=signal,
        variant=variant,
        direction=direction,
        time=when,
        level=level,
        trading_date=session.trading_date.isoformat(),
        session=session.session,
    )


def dump(
    raw_root: Path,
    calendar_path: Path,
    start_day: str,
    end_day: str,
    out_path: Path,
    *,
    dataset_version: str = DEFAULT_DATASET_VERSION,
    alias_code: str = DEFAULT_ALIAS_CODE,
    trading_days: Collection[str] | None = None,
    timeframes: tuple[int, ...] = TIMEFRAMES,
    include_controls: bool = True,
    seed: int = SEED,
) -> int:
    sessions, source_records = _load_sessions(
        raw_root,
        dataset_version=dataset_version,
        alias_code=alias_code,
        calendar_path=calendar_path,
        start_day=start_day,
        end_day=end_day,
        trading_days=trading_days,
        intervals=timeframes,
    )
    if not sessions:
        print(f"{start_day}..{end_day} has no stored kbar sessions", file=sys.stderr)
        return 1

    engines: dict[tuple[int, str], PineState] = {}
    for timeframe in timeframes:
        engines[(timeframe, "orig")] = PineState(PRESETS[timeframe])
        engines[(timeframe, "v1")] = PineState(
            PRESETS[timeframe],
            right_bars=2,
        )

    rng = random.Random(seed)
    sessions_written = 0
    written = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for session in sessions:
            if not session.minute_bars:
                continue
            minute_points = session.minute_points
            tape = SessionTape(
                [point[0] for point in minute_points],
                [point[1] for point in minute_points],
            )
            emitted: list[SignalEvent] = []
            for timeframe in timeframes:
                params = PRESETS[timeframe]
                orig_engine = engines[(timeframe, "orig")]
                v1_engine = engines[(timeframe, "v1")]
                fired_levels: set[tuple[str, float]] = set()
                for bar in session.bars_by_interval[timeframe]:
                    ctx = orig_engine.forming_context()
                    bar_points = _bar_points(
                        session,
                        bar.bar_start,
                        bar.bar_end,
                    )
                    for name, direction, level, when in v2_scan(
                        ctx,
                        bar_points,
                        bar.bar_start,
                        timeframe,
                        params,
                    ):
                        emitted.append(
                            _signal_event(
                                session,
                                timeframe,
                                name,
                                "v2",
                                direction,
                                when,
                                level,
                            )
                        )
                    for name, direction, level, when in v3_scan(
                        ctx,
                        bar_points,
                        params,
                        fired_levels,
                    ):
                        emitted.append(
                            _signal_event(
                                session,
                                timeframe,
                                name,
                                "v3",
                                direction,
                                when,
                                level,
                            )
                        )
                    for name, direction, level in orig_engine.update(bar):
                        emitted.append(
                            _signal_event(
                                session,
                                timeframe,
                                name,
                                "orig",
                                direction,
                                bar.bar_end,
                                level,
                            )
                        )
                    for name, direction, level in v1_engine.update(bar):
                        emitted.append(
                            _signal_event(
                                session,
                                timeframe,
                                name,
                                "v1",
                                direction,
                                bar.bar_end,
                                level,
                            )
                        )

            # Exactly the same uniform construction and per-session count as
            # pine_control_dump.py, with only the pre-registered seed changed.
            if include_controls:
                for _ in range(RANDOM_ENTRIES_PER_SESSION):
                    when = minute_points[rng.randrange(len(minute_points))][0]
                    emitted.append(
                        _signal_event(
                            session,
                            0,
                            "random",
                            "random",
                            1,
                            when,
                            0.0,
                        )
                    )

            for event in emitted:
                row = _row(event, tape, session)
                if row is None:
                    continue
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
            sessions_written += 1
            print(
                f"  [{sessions_written}] {session.trading_date} {session.session}"
                f"  wrote {written:,} rows",
                file=sys.stderr,
                flush=True,
            )
    print(
        f"complete: {sessions_written} sessions, source_records={source_records:,},"
        f" rows={written:,} -> {out_path}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (5, 7):
        print(__doc__, file=sys.stderr)
        return 2
    dataset_version = DEFAULT_DATASET_VERSION
    alias_code = DEFAULT_ALIAS_CODE
    if len(args) == 7:
        if args[5] != "--dataset-version" or not args[6]:
            print(__doc__, file=sys.stderr)
            return 2
        dataset_version = args[6]
    try:
        return dump(
            Path(args[0]),
            Path(args[1]),
            args[2],
            args[3],
            Path(args[4]),
            dataset_version=dataset_version,
            alias_code=alias_code,
        )
    except (OSError, ValueError, TypeError, JSONDecodeError) as error:
        print(f"PINE BAR DUMP FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
