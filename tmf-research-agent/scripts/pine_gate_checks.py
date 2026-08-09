"""Run the Amendment 4, same-15-minute-bar Pine reconciliation checks.

The two checks deliberately use only the post-2024-07-29 sampled days:

* Gate A compares TXF kbar replay with TXF tick replay.
* Gate B compares TMF tick replay with TXF tick replay.

Gate A follows Amendment 4: it excludes weekend kbar segments and intersects
the source minute starts per session before rebuilding either Pine history.
Thus a tick-only stretch is absent from both replays rather than being
silently supplied by the 2026 Saturday kbar files.

Each replay keeps one ``PineState`` per variant alive while it walks the
available sampled sessions in chronological order.  It does not read an
unsampled day to warm up a state.  That is necessary because the supplied TXF
tick store contains the sample, not a continuous tick history.  A missing day
is removed from that check's common day set and reported.

The signal implementation is not here: the two dump functions import and use
the authoritative ``PineState``, presets, scanners, horizons, period helper,
and row-building conventions from the existing scripts.

Usage:
    pine_gate_checks.py [--gate-a-only] <raw-root> <calendar.json> <gate-days.txt> <output-dir>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pine_bar_dump  # noqa: E402
import pine_control_dump  # noqa: E402
from tmf_research.collection.live_calendar import (  # noqa: E402
    synthetic_near_term_calendar,
)
from tmf_research.infrastructure.raw_store import (  # noqa: E402
    AppendOnlyRawStore,
    SegmentManifest,
)
from tmf_research.processing.bars import Bar  # noqa: E402
from tmf_research.processing.kbar_aggregation import (  # noqa: E402
    PineBarSession,
    build_pine_bar_sessions,
    minute_kbars_from_records,
)
from tmf_research.processing.pipeline import ProcessingPipeline  # noqa: E402
from tmf_research.processing.quote_joiner import QuoteJoiner  # noqa: E402
from tmf_research.domain.sessions import SessionResolution  # noqa: E402

if TYPE_CHECKING:
    from tmf_research.validation.dataset_lineage import _SessionBatch


GATE_START = date(2024, 7, 29)
GATE_END = date(2026, 7, 31)
GATE_TIMEFRAME = 15
GATE_SIGNAL = "rejection"
GATE_VARIANT = "orig"
GATE_DIRECTION = -1
GATE_SEED = 20260806
GATE_A_THRESHOLD = 95.0
GATE_B_CLAIM_THRESHOLD = 80.0

TX_TICK_DATASET = "tx-gate-ticks-v1"
TX_TICK_ALIAS = "TXFR1"
TMF_TICK_DATASET = "dataset-v1"
TMF_TICK_ALIAS = "TMFR1"
TX_KBAR_DATASET = "tx-holdout-kbars-v1"
TX_KBAR_ALIAS = "TXFR1"
SessionKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class Comparison:
    left_label: str
    right_label: str
    left_count: int
    right_count: int
    matched: int
    left_only: int
    right_only: int
    left_agreement_pct: float | None
    right_agreement_pct: float | None
    left_only_examples: tuple[dict[str, object], ...]
    right_only_examples: tuple[dict[str, object], ...]

    @property
    def gate_a_pass(self) -> bool:
        return (
            self.left_agreement_pct is not None
            and self.right_agreement_pct is not None
            and self.left_agreement_pct >= GATE_A_THRESHOLD
            and self.right_agreement_pct >= GATE_A_THRESHOLD
        )

    @property
    def claim_threshold_met(self) -> bool:
        return (
            self.left_agreement_pct is not None
            and self.right_agreement_pct is not None
            and self.left_agreement_pct >= GATE_B_CLAIM_THRESHOLD
            and self.right_agreement_pct >= GATE_B_CLAIM_THRESHOLD
        )


@dataclass(frozen=True, slots=True)
class GateARun:
    comparison: Comparison
    requested_days: tuple[str, ...]
    missing_days: Mapping[str, tuple[str, ...]]
    first_divergence: dict[str, object] | None


def _intersect_source_minutes(
    kbar_minutes: Mapping[SessionKey, Iterable[datetime]],
    tick_minutes: Mapping[SessionKey, Iterable[datetime]],
) -> dict[SessionKey, frozenset[datetime]]:
    """Keep only minute starts present in both source streams per session."""

    result: dict[SessionKey, frozenset[datetime]] = {}
    for key in kbar_minutes.keys() & tick_minutes.keys():
        common = frozenset(kbar_minutes[key]) & frozenset(tick_minutes[key])
        if common:
            result[key] = common
    return result


def _read_gate_days(path: Path) -> tuple[str, ...]:
    values = tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    normalized: list[str] = []
    for value in values:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError(f"gate day is not canonical YYYY-MM-DD: {value}")
        if parsed < GATE_START or parsed > GATE_END:
            raise ValueError(
                "gate days may only cover 2024-07-29..2026-07-31; "
                f"refusing {value} to protect the holdout"
            )
        normalized.append(value)
    if not normalized:
        raise ValueError("gate day list is empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("gate day list contains duplicates")
    return tuple(sorted(normalized))


def _manifest_days(
    raw_root: Path,
    *,
    dataset_version: str,
    event_type: str,
    alias_code: str,
    gate_days: Iterable[str],
) -> set[str]:
    wanted = set(gate_days)
    prefix = f"backfill-{'kbar-1m' if event_type == 'historical-kbar-1m' else 'tick'}-{alias_code}-"
    found: set[str] = set()
    for line in (raw_root / "manifest.ndjson").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        segment_id = str(payload.get("segment_id", ""))
        if (
            payload.get("dataset_version") == dataset_version
            and payload.get("event_type") == event_type
            and segment_id.startswith(prefix)
        ):
            day = segment_id[len(prefix) :][:10]
            if day in wanted:
                found.add(day)
    return found


def _write_gate_calendar(
    source_path: Path,
    gate_days: Iterable[str],
    destination: Path,
) -> None:
    """Fill only missing sampled dates using the repo's live calendar helper.

    The checked-in evidence calendar has a provenance-shaped gap in 2025-07
    through 2026-06.  The supplied gate days in that gap are known trading
    days because both raw stores contain them.  Preserve every existing
    calendar row and fill only those sampled dates with the repository's
    ``synthetic_near_term_calendar`` rules; this is not used for the holdout.
    """

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("days"), list):
        raise ValueError("calendar must contain an object with a days list")
    existing = {
        str(row.get("trading_date")) for row in payload["days"] if isinstance(row, dict)
    }
    for day_text in sorted(set(gate_days) - existing):
        day = date.fromisoformat(day_text)
        synthetic = synthetic_near_term_calendar(day, days_ahead=0, days_behind=0)
        match = next(
            (item for item in synthetic.days if item.trading_date == day),
            None,
        )
        if match is None:
            raise ValueError(f"cannot make a calendar row for gate day {day_text}")
        night_close = (
            datetime.combine(
                match.night_open.date() + timedelta(days=1),
                match.night_close.timetz(),
            )
            if match.night_open is not None and match.night_close is not None
            else None
        )
        payload["days"].append(
            {
                "trading_date": day_text,
                "day_open": match.day_open.isoformat(),
                "day_close": match.day_close.isoformat(),
                "night_open": (
                    match.night_open.isoformat()
                    if match.night_open is not None
                    else None
                ),
                "night_close": (
                    night_close.isoformat() if night_close is not None else None
                ),
                "is_expiry": match.is_expiry,
            }
        )
    payload["days"].sort(key=lambda row: str(row["trading_date"]))
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def _manifest_segment_day(
    segment_id: str,
    *,
    event_type: str,
    alias_code: str,
) -> str | None:
    prefix = (
        f"backfill-{'kbar-1m' if event_type == 'historical-kbar-1m' else 'tick'}"
        f"-{alias_code}-"
    )
    if not segment_id.startswith(prefix):
        return None
    suffix = segment_id[len(prefix) :]
    return suffix[:10] if len(suffix) >= 10 else None


def _selected_manifests(
    raw_root: Path,
    *,
    dataset_version: str,
    event_type: str,
    alias_code: str,
    start_day: str,
    end_day: str,
    exact_days: frozenset[str] | None = None,
    weekdays_only: bool = False,
) -> tuple[SegmentManifest, ...]:
    manifests: list[SegmentManifest] = []
    for line in (raw_root / "manifest.ndjson").read_text(
        encoding="utf-8",
    ).splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        segment_id = str(payload.get("segment_id", ""))
        day = _manifest_segment_day(
            segment_id,
            event_type=event_type,
            alias_code=alias_code,
        )
        if (
            payload.get("event_type") != event_type
            or payload.get("dataset_version") != dataset_version
            or day is None
            or not start_day <= day <= end_day
            or (exact_days is not None and day not in exact_days)
            or (weekdays_only and date.fromisoformat(day).weekday() >= 5)
        ):
            continue
        manifests.append(SegmentManifest(**payload))
    return tuple(sorted(manifests, key=lambda manifest: manifest.segment_id))


def _load_gate_kbar_sessions(
    raw_root: Path,
    calendar_path: Path,
    days: tuple[str, ...],
) -> tuple[tuple[PineBarSession, ...], tuple[SegmentManifest, ...]]:
    """Load weekday calendar files, deliberately excluding Saturday kbars."""

    manifests = _selected_manifests(
        raw_root,
        dataset_version=TX_KBAR_DATASET,
        event_type="historical-kbar-1m",
        alias_code=TX_KBAR_ALIAS,
        start_day=days[0],
        end_day=days[-1],
        weekdays_only=True,
    )
    if not manifests:
        raise RuntimeError("Gate A has no weekday kbar manifests")
    first_manifest = manifests[0]
    store = AppendOnlyRawStore(
        raw_root,
        writer_version=first_manifest.writer_version,
        dataset_version=TX_KBAR_DATASET,
    )
    records: list[dict[str, object]] = []
    for manifest in manifests:
        records.extend(store.read_verified(manifest))
    calendar = pine_bar_dump.ResearchBuildSpec(
        calendar=calendar_path,
    ).trading_calendar()
    sessions = build_pine_bar_sessions(
        minute_kbars_from_records(records),
        calendar=calendar,
        target_code=TX_KBAR_ALIAS,
        intervals=(GATE_TIMEFRAME,),
    )
    selected = frozenset(days)
    return (
        tuple(
            session
            for session in sessions
            if session.trading_date.isoformat() in selected
        ),
        manifests,
    )


def _load_gate_tick_batches(
    raw_root: Path,
    calendar_path: Path,
    days: tuple[str, ...],
) -> tuple[tuple[_SessionBatch, ...], tuple[SegmentManifest, ...], int]:
    manifests = _selected_manifests(
        raw_root,
        dataset_version=TX_TICK_DATASET,
        event_type="historical-tick",
        alias_code=TX_TICK_ALIAS,
        start_day=days[0],
        end_day=days[-1],
        exact_days=frozenset(days),
    )
    if not manifests:
        raise RuntimeError("Gate A has no TXF tick manifests")
    first_manifest = manifests[0]
    store = AppendOnlyRawStore(
        raw_root,
        writer_version=first_manifest.writer_version,
        dataset_version=TX_TICK_DATASET,
    )
    calendar = pine_control_dump.ResearchBuildSpec(
        calendar=calendar_path,
    ).trading_calendar()
    resolver = pine_control_dump.SessionResolver(calendar)
    filtered_store = pine_control_dump._CalendarFilteredStore(store, resolver)
    reasons: set[str] = set()
    batches = tuple(
        pine_control_dump._session_batches(
            filtered_store,
            manifests,
            calendar,
            resolver,
            reasons,
        )  # type: ignore[arg-type]
    )
    selected = frozenset(days)
    return (
        tuple(batch for batch in batches if batch.trading_date in selected),
        manifests,
        filtered_store.closed_records,
    )


def _minute_start(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def _source_minute_maps(
    kbar_sessions: Iterable[PineBarSession],
    tick_batches: Iterable[_SessionBatch],
) -> tuple[
    dict[SessionKey, tuple[datetime, ...]],
    dict[SessionKey, tuple[datetime, ...]],
]:
    kbar_minutes: dict[SessionKey, tuple[datetime, ...]] = {}
    for session in kbar_sessions:
        key: SessionKey = (
            session.trading_date.isoformat(),
            str(session.session),
        )
        kbar_minutes[key] = tuple(
            minute.timestamp for minute in session.minute_bars
        )
    tick_minutes: dict[SessionKey, tuple[datetime, ...]] = {}
    for batch in tick_batches:
        key = (batch.trading_date, batch.session)
        tick_minutes[key] = tuple(
            _minute_start(tick.exchange_datetime) for tick in batch.ticks
        )
    return kbar_minutes, tick_minutes


def _rebuild_common_kbar_sessions(
    kbar_sessions: Iterable[PineBarSession],
    common_minutes: Mapping[SessionKey, frozenset[datetime]],
    calendar_path: Path,
) -> tuple[PineBarSession, ...]:
    minutes = tuple(
        minute
        for session in kbar_sessions
        for minute in session.minute_bars
        if minute.timestamp
        in common_minutes.get(
            (session.trading_date.isoformat(), session.session),
            frozenset(),
        )
    )
    calendar = pine_bar_dump.ResearchBuildSpec(
        calendar=calendar_path,
    ).trading_calendar()
    return build_pine_bar_sessions(
        minutes,
        calendar=calendar,
        target_code=TX_KBAR_ALIAS,
        intervals=(GATE_TIMEFRAME,),
    )


def _tick_bucket_starts(
    resolution: SessionResolution,
    common_minutes: frozenset[datetime],
) -> frozenset[datetime]:
    if resolution.session_start is None:
        return frozenset()
    starts: set[datetime] = set()
    for minute in common_minutes:
        offset_minutes = int(
            (minute - resolution.session_start).total_seconds() // 60
        )
        starts.add(
            resolution.session_start
            + timedelta(minutes=(offset_minutes // GATE_TIMEFRAME) * GATE_TIMEFRAME)
        )
    return frozenset(starts)


def _process_aligned_tick_batch(
    batch: _SessionBatch,
    common_minutes: frozenset[datetime],
    manifests: tuple[SegmentManifest, ...],
) -> tuple[Bar, ...]:
    resolution = batch.resolution
    if resolution.session_start is None or resolution.session_end is None:
        return ()
    ticks = tuple(
        tick
        for tick in batch.ticks
        if _minute_start(tick.exchange_datetime) in common_minutes
    )
    quotes = tuple(
        quote
        for quote in batch.quotes
        if _minute_start(quote.exchange_datetime) in common_minutes
    )
    if not ticks:
        return ()
    pipeline = ProcessingPipeline(
        quote_joiner=QuoteJoiner(max_quote_age=timedelta(minutes=2)),
    )
    try:
        processed = pipeline.process(
            ticks=ticks,
            bidasks=quotes,
            resolution=resolution,
            start_second=resolution.session_start,
            end_second=resolution.session_end - timedelta(seconds=1),
            source_manifests=manifests,
            intervals=(GATE_TIMEFRAME,),
        )
    except ValueError:
        fallback = min(tick.exchange_datetime for tick in ticks).replace(
            second=0,
            microsecond=0,
        )
        processed = pipeline.process(
            ticks=ticks,
            bidasks=quotes,
            resolution=resolution,
            start_second=fallback,
            end_second=resolution.session_end - timedelta(seconds=1),
            source_manifests=manifests,
            intervals=(GATE_TIMEFRAME,),
        )
    starts = _tick_bucket_starts(resolution, common_minutes)
    return tuple(
        bar
        for bar in processed.bar_sets[0].bars
        if bar.bar_start in starts
    )


def _aligned_gate_bar_sequences(
    raw_root: Path,
    calendar_path: Path,
    days: tuple[str, ...],
) -> tuple[
    dict[SessionKey, tuple[Bar, ...]],
    dict[SessionKey, tuple[Bar, ...]],
    dict[SessionKey, frozenset[datetime]],
    int,
    dict[SessionKey, datetime],
]:
    kbar_sessions, _kbar_manifests = _load_gate_kbar_sessions(
        raw_root,
        calendar_path,
        days,
    )
    tick_batches, tick_manifests, closed_records = _load_gate_tick_batches(
        raw_root,
        calendar_path,
        days,
    )
    kbar_minutes, tick_minutes = _source_minute_maps(
        kbar_sessions,
        tick_batches,
    )
    common_minutes = _intersect_source_minutes(kbar_minutes, tick_minutes)
    session_starts: dict[SessionKey, datetime] = {}
    for session in kbar_sessions:
        key: SessionKey = (
            session.trading_date.isoformat(),
            str(session.session),
        )
        session_starts[key] = session.session_start
    for batch in tick_batches:
        if batch.resolution.session_start is not None:
            key = (batch.trading_date, batch.session)
            session_starts[key] = batch.resolution.session_start
    aligned_kbar_sessions = _rebuild_common_kbar_sessions(
        kbar_sessions,
        common_minutes,
        calendar_path,
    )
    kbar_bars: dict[SessionKey, tuple[Bar, ...]] = {
        (
            session.trading_date.isoformat(),
            str(session.session),
        ): tuple(
            session.bars_by_interval[GATE_TIMEFRAME]
        )
        for session in aligned_kbar_sessions
    }
    tick_bars: dict[SessionKey, tuple[Bar, ...]] = {
        (batch.trading_date, batch.session): _process_aligned_tick_batch(
            batch,
            common_minutes.get((batch.trading_date, batch.session), frozenset()),
            tick_manifests,
        )
        for batch in tick_batches
        if (batch.trading_date, batch.session) in common_minutes
    }
    return kbar_bars, tick_bars, common_minutes, closed_records, session_starts


def _bar_trace_row(
    side: str,
    key: SessionKey,
    session_index: int,
    sequence_index: int,
    bar: Bar,
) -> dict[str, object]:
    return {
        "side": side,
        "trading_date": key[0],
        "session": key[1],
        "session_index": session_index,
        "sequence_index": sequence_index,
        "bar_start": bar.bar_start.isoformat(),
        "bar_end": bar.bar_end.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


def _ordered_session_keys(
    kbar_bars: Mapping[SessionKey, tuple[Bar, ...]],
    tick_bars: Mapping[SessionKey, tuple[Bar, ...]],
    session_starts: Mapping[SessionKey, datetime],
) -> tuple[SessionKey, ...]:
    return tuple(
        sorted(
            kbar_bars.keys() | tick_bars.keys(),
            key=lambda key: session_starts[key],
        )
    )


def _bar_sequences(
    bars: Mapping[SessionKey, tuple[Bar, ...]],
    keys: Iterable[SessionKey],
) -> tuple[tuple[SessionKey, int, Bar], ...]:
    return tuple(
        (key, index, bar)
        for key in keys
        for index, bar in enumerate(bars.get(key, ()))
    )


def _first_bar_divergence(
    tick_bars: Mapping[SessionKey, tuple[Bar, ...]],
    kbar_bars: Mapping[SessionKey, tuple[Bar, ...]],
    keys: Iterable[SessionKey],
) -> dict[str, object] | None:
    tick_sequence = _bar_sequences(tick_bars, keys)
    kbar_sequence = _bar_sequences(kbar_bars, keys)

    def signature(item: tuple[SessionKey, int, Bar] | None) -> tuple[object, ...] | None:
        if item is None:
            return None
        _key, _index, bar = item
        return (
            bar.bar_start,
            bar.bar_end,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
        )

    def payload(
        side: str,
        item: tuple[SessionKey, int, Bar] | None,
        sequence_index: int,
    ) -> dict[str, object] | None:
        if item is None:
            return None
        key, session_index, bar = item
        return _bar_trace_row(
            side,
            key,
            session_index,
            sequence_index,
            bar,
        )

    for sequence_index in range(max(len(tick_sequence), len(kbar_sequence))):
        tick_item = (
            tick_sequence[sequence_index]
            if sequence_index < len(tick_sequence)
            else None
        )
        kbar_item = (
            kbar_sequence[sequence_index]
            if sequence_index < len(kbar_sequence)
            else None
        )
        if signature(tick_item) != signature(kbar_item):
            return {
                "sequence_index": sequence_index,
                "tick": payload("tick", tick_item, sequence_index),
                "kbar": payload("kbar", kbar_item, sequence_index),
            }
    return None


def _candidate_rows_from_bars(
    bars: Mapping[SessionKey, tuple[Bar, ...]],
    session_starts: Mapping[SessionKey, datetime],
    keys: Iterable[SessionKey],
) -> list[dict[str, object]]:
    engine = pine_bar_dump.PineState(
        pine_bar_dump.PRESETS[GATE_TIMEFRAME],
    )
    output: list[dict[str, object]] = []
    for key in keys:
        session_start = session_starts[key]
        for bar in bars.get(key, ()):
            for name, direction, _level in engine.update(bar):
                if name != GATE_SIGNAL or direction != GATE_DIRECTION:
                    continue
                when = bar.bar_end
                output.append({
                    "trading_date": key[0],
                    "session": key[1],
                    "period": pine_bar_dump._period(key[0]),
                    "kind": "signal",
                    "timeframe": GATE_TIMEFRAME,
                    "signal": name,
                    "variant": GATE_VARIANT,
                    "direction": direction,
                    "when": when.isoformat(),
                    "minute_of_session": int(
                        (when - session_start).total_seconds() // 60
                    ),
                    "deltas": {},
                })
    return output


def _write_ndjson(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_bar_trace(
    path: Path,
    side: str,
    bars: Mapping[SessionKey, tuple[Bar, ...]],
    keys: Iterable[SessionKey],
) -> None:
    sequence_index = 0
    rows: list[dict[str, object]] = []
    for key in keys:
        for session_index, bar in enumerate(bars.get(key, ())):
            rows.append(_bar_trace_row(
                side,
                key,
                session_index,
                sequence_index,
                bar,
            ))
            sequence_index += 1
    _write_ndjson(path, rows)


def run_gate_a(
    raw_root: Path,
    calendar_path: Path,
    gate_days_path: Path,
    output_dir: Path,
) -> GateARun:
    requested = _read_gate_days(gate_days_path)
    requested_set = set(requested)
    tx_tick_available = _manifest_days(
        raw_root,
        dataset_version=TX_TICK_DATASET,
        event_type="historical-tick",
        alias_code=TX_TICK_ALIAS,
        gate_days=requested,
    )
    tx_kbar_available = _manifest_days(
        raw_root,
        dataset_version=TX_KBAR_DATASET,
        event_type="historical-kbar-1m",
        alias_code=TX_KBAR_ALIAS,
        gate_days=requested,
    )
    gate_days = tuple(sorted(requested_set & tx_tick_available & tx_kbar_available))
    if not gate_days:
        raise RuntimeError("Gate A has no common stored days")
    missing = {
        "tx-gate-ticks-v1": tuple(sorted(requested_set - tx_tick_available)),
        "tx-holdout-kbars-v1": tuple(sorted(requested_set - tx_kbar_available)),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="pine-gate-a-") as temporary:
        gate_calendar = Path(temporary) / "calendar.json"
        _write_gate_calendar(calendar_path, gate_days, gate_calendar)
        (
            kbar_bars,
            tick_bars,
            common_minutes,
            closed_records,
            session_starts,
        ) = (
            _aligned_gate_bar_sequences(
                raw_root,
                gate_calendar,
                gate_days,
            )
        )
        keys = _ordered_session_keys(kbar_bars, tick_bars, session_starts)
        tick_rows = _candidate_rows_from_bars(tick_bars, session_starts, keys)
        kbar_rows = _candidate_rows_from_bars(kbar_bars, session_starts, keys)
        tick_path = output_dir / "gate-a-tick.ndjson"
        kbar_path = output_dir / "gate-a-bar.ndjson"
        _write_ndjson(tick_path, tick_rows)
        _write_ndjson(kbar_path, kbar_rows)
        _write_bar_trace(
            output_dir / "gate-a-tick-bars.ndjson",
            "tick",
            tick_bars,
            keys,
        )
        _write_bar_trace(
            output_dir / "gate-a-bar-bars.ndjson",
            "kbar",
            kbar_bars,
            keys,
        )
        first_divergence = _first_bar_divergence(tick_bars, kbar_bars, keys)
        (output_dir / "gate-a-first-divergence.json").write_text(
            json.dumps(first_divergence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "gate-a-source-summary.json").write_text(
            json.dumps(
                {
                    "requested_days": gate_days,
                    "session_count": len(keys),
                    "common_source_minute_count": sum(
                        len(value) for value in common_minutes.values()
                    ),
                    "closed_tick_records_dropped": closed_records,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    return GateARun(
        comparison=compare(
            tick_path,
            kbar_path,
            left_label="TXF tick",
            right_label="TXF bar",
        ),
        requested_days=gate_days,
        missing_days=missing,
        first_divergence=first_divergence,
    )


def _print_first_divergence(first_divergence: dict[str, object] | None) -> None:
    print("First 15-minute bar divergence (zero-based sequence index):")
    if first_divergence is None:
        print("- none")
    else:
        print(json.dumps(first_divergence, ensure_ascii=False, sort_keys=True))


def _run_bar_dump(
    raw_root: Path,
    calendar_path: Path,
    days: tuple[str, ...],
    out_path: Path,
) -> None:
    status = pine_bar_dump.dump(
        raw_root,
        calendar_path,
        days[0],
        days[-1],
        out_path,
        dataset_version=TX_KBAR_DATASET,
        alias_code=TX_KBAR_ALIAS,
        trading_days=days,
        timeframes=(GATE_TIMEFRAME,),
        include_controls=False,
        seed=GATE_SEED,
    )
    if status != 0:
        raise RuntimeError(f"TXF bar replay failed with status {status}")


def _run_tick_dump(
    raw_root: Path,
    calendar_path: Path,
    days: tuple[str, ...],
    out_path: Path,
    *,
    dataset_version: str,
    alias_code: str,
) -> None:
    status = pine_control_dump.dump(
        raw_root,
        calendar_path,
        days[0],
        days[-1],
        out_path,
        dataset_version=dataset_version,
        alias_code=alias_code,
        trading_days=days,
        timeframes=(GATE_TIMEFRAME,),
        include_controls=False,
        seed=GATE_SEED,
        skip_closed_records=True,
    )
    if status != 0:
        raise RuntimeError(f"{alias_code} tick replay failed with status {status}")


def _candidate_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"event row is not an object: {path}")
        if (
            row.get("kind") == "signal"
            and row.get("timeframe") == GATE_TIMEFRAME
            and row.get("signal") == GATE_SIGNAL
            and row.get("variant") == GATE_VARIANT
            and row.get("direction") == GATE_DIRECTION
        ):
            rows.append(row)
    return rows


def _bar_key(row: Mapping[str, object]) -> tuple[str, str, int]:
    trading_date = row.get("trading_date")
    session = row.get("session")
    minute = row.get("minute_of_session")
    if (
        not isinstance(trading_date, str)
        or not isinstance(session, str)
        or isinstance(minute, bool)
        or not isinstance(minute, int)
    ):
        raise ValueError(f"candidate row lacks a valid 15-minute bar key: {row}")
    return trading_date, session, minute


def _example(row: Mapping[str, object], label: str) -> dict[str, object]:
    return {
        "side": label,
        "trading_date": row["trading_date"],
        "session": row["session"],
        "bar_minute_of_session": row["minute_of_session"],
        "when": row["when"],
    }


def compare(
    left_path: Path,
    right_path: Path,
    *,
    left_label: str,
    right_label: str,
    example_limit: int = 5,
) -> Comparison:
    left_rows = _candidate_rows(left_path)
    right_rows = _candidate_rows(right_path)
    left_counts = Counter(_bar_key(row) for row in left_rows)
    right_counts = Counter(_bar_key(row) for row in right_rows)
    matched = sum(
        min(left_counts[key], right_counts[key])
        for key in left_counts.keys() & right_counts.keys()
    )
    left_only_rows: list[dict[str, object]] = []
    right_only_rows: list[dict[str, object]] = []
    for row in sorted(
        left_rows, key=lambda value: (str(value["when"]), str(value["session"]))
    ):
        key = _bar_key(row)
        if left_counts[key] > right_counts[key]:
            left_only_rows.append(_example(row, left_label))
            left_counts[key] -= 1
    for row in sorted(
        right_rows, key=lambda value: (str(value["when"]), str(value["session"]))
    ):
        key = _bar_key(row)
        if right_counts[key] > left_counts[key]:
            right_only_rows.append(_example(row, right_label))
            right_counts[key] -= 1

    def pct(value: int, total: int) -> float | None:
        return None if total == 0 else round(100.0 * value / total, 4)

    return Comparison(
        left_label=left_label,
        right_label=right_label,
        left_count=len(left_rows),
        right_count=len(right_rows),
        matched=matched,
        left_only=len(left_only_rows),
        right_only=len(right_only_rows),
        left_agreement_pct=pct(matched, len(left_rows)),
        right_agreement_pct=pct(matched, len(right_rows)),
        left_only_examples=tuple(left_only_rows[:example_limit]),
        right_only_examples=tuple(right_only_rows[:example_limit]),
    )


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def _print_comparison(name: str, comparison: Comparison) -> None:
    print(f"\n{name}")
    print(
        "| left N | right N | matched | left-only | right-only | "
        "left agreement | right agreement | result |"
    )
    print("|---:|---:|---:|---:|---:|---:|---:|---|")
    result = (
        "PASS"
        if comparison.gate_a_pass
        else "FAIL"
        if name == "Gate A — granularity"
        else (
            f"claim threshold met: {GATE_B_CLAIM_THRESHOLD:.0f}%"
            if comparison.claim_threshold_met
            else f"below claim threshold: {GATE_B_CLAIM_THRESHOLD:.0f}%"
        )
    )
    print(
        f"| {comparison.left_count} | {comparison.right_count} | "
        f"{comparison.matched} | {comparison.left_only} | "
        f"{comparison.right_only} | "
        f"{_pct(comparison.left_agreement_pct)} | "
        f"{_pct(comparison.right_agreement_pct)} | {result} |"
    )
    print("Mismatches (same-bar key is trading_date/session/minute_of_session):")
    for row in (*comparison.left_only_examples, *comparison.right_only_examples):
        print(f"- {json.dumps(row, ensure_ascii=False, sort_keys=True)}")
    if not comparison.left_only_examples and not comparison.right_only_examples:
        print("- none")


def run(
    raw_root: Path,
    calendar_path: Path,
    gate_days_path: Path,
    output_dir: Path,
) -> tuple[
    Comparison,
    Comparison,
    dict[str, tuple[str, ...]],
    dict[str, object] | None,
]:
    requested = _read_gate_days(gate_days_path)
    requested_set = set(requested)
    gate_a = run_gate_a(raw_root, calendar_path, gate_days_path, output_dir)
    tx_tick_available = set(requested) - set(
        gate_a.missing_days["tx-gate-ticks-v1"]
    )
    tmf_tick_available = _manifest_days(
        raw_root,
        dataset_version=TMF_TICK_DATASET,
        event_type="historical-tick",
        alias_code=TMF_TICK_ALIAS,
        gate_days=requested,
    )

    gate_b_days = tuple(sorted(requested_set & tx_tick_available & tmf_tick_available))
    missing = {
        **gate_a.missing_days,
        "dataset-v1": tuple(sorted(requested_set - tmf_tick_available)),
    }
    if not gate_b_days:
        raise RuntimeError("Gate B has no common stored days")

    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="pine-gates-") as temporary:
        temp_dir = Path(temporary)
        gate_calendar = temp_dir / "calendar.json"
        _write_gate_calendar(calendar_path, requested, gate_calendar)
        gate_b_tmf = temp_dir / "gate-b-tmf.ndjson"
        gate_b_txf = temp_dir / "gate-b-txf.ndjson"
        _run_tick_dump(
            raw_root,
            gate_calendar,
            gate_b_days,
            gate_b_tmf,
            dataset_version=TMF_TICK_DATASET,
            alias_code=TMF_TICK_ALIAS,
        )
        _run_tick_dump(
            raw_root,
            gate_calendar,
            gate_b_days,
            gate_b_txf,
            dataset_version=TX_TICK_DATASET,
            alias_code=TX_TICK_ALIAS,
        )

        gate_b = compare(
            gate_b_tmf,
            gate_b_txf,
            left_label="TMF",
            right_label="TXF",
        )
        for source, path in (
            ("gate-b-tmf", gate_b_tmf),
            ("gate-b-txf", gate_b_txf),
        ):
            (output_dir / f"{source}.ndjson").write_bytes(path.read_bytes())

    return (
        gate_a.comparison,
        gate_b,
        {
            **missing,
            "gate-a-days": gate_a.requested_days,
            "gate-b-days": gate_b_days,
        },
        gate_a.first_divergence,
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    gate_a_only = bool(args and args[0] == "--gate-a-only")
    if gate_a_only:
        args = args[1:]
    if len(args) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        if gate_a_only:
            result = run_gate_a(
                Path(args[0]),
                Path(args[1]),
                Path(args[2]),
                Path(args[3]),
            )
            print("Requested gate days: " + ", ".join(result.requested_days))
            for dataset, missing in result.missing_days.items():
                if missing:
                    print(f"Missing from {dataset}: {', '.join(missing)}")
            _print_comparison("Gate A — granularity", result.comparison)
            _print_first_divergence(result.first_divergence)
            return 0

        gate_a, gate_b, days, first_divergence = run(
            Path(args[0]), Path(args[1]), Path(args[2]), Path(args[3]),
        )
        print("Requested gate days: " + ", ".join(days["gate-a-days"]))
        for dataset, missing in days.items():
            if dataset.startswith("gate-") or not missing:
                continue
            print(f"Missing from {dataset}: {', '.join(missing) or 'none'}")
        _print_comparison("Gate A — granularity", gate_a)
        _print_first_divergence(first_divergence)
        _print_comparison("Gate B — instrument portability", gate_b)
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        RuntimeError,
    ) as error:
        print(f"PINE GATE CHECK FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
