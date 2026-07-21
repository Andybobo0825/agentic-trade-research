from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from tmf_research.collection.event_queue import BoundedEventQueue
from tmf_research.collection.live_calendar import synthetic_near_term_calendar
from tmf_research.collection.live_collector import LiveCollector, LiveGateway
from tmf_research.collection.raw_writer import RawWriter
from tmf_research.domain.events import BidAskEvent, MarketEvent, TickEvent
from tmf_research.infrastructure.contract_resolver import ContractTracker
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore
from tmf_research.processing.session_resolver import SessionResolver


_TAIPEI = ZoneInfo("Asia/Taipei")
TICK_EVENT_TYPE = "live-tick"
BIDASK_EVENT_TYPE = "live-bidask"

Clock = Callable[[], datetime]
Sleep = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class LiveRunSummary:
    alias_code: str
    dataset_version: str
    stored_records: int
    stored_segments: int
    dropped_event_count: int


def run_live_collection(
    gateway: LiveGateway,
    store: AppendOnlyRawStore,
    *,
    until: datetime,
    flush_interval_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
    clock: Clock | None = None,
    sleep: Sleep | None = None,
    on_flush: Callable[[str, int], None] | None = None,
) -> LiveRunSummary:
    """Drain the live queue into create-once raw segments until a bound time.

    Buffers per (event type, trading date, session) and periodically flushes
    each non-empty buffer as its own immutable segment, so a crash mid-run
    only loses the still-unflushed tail. Events whose exchange time falls
    outside the synthetic calendar are still stored, tagged CLOSED/"" --
    fail-closed rejection happens downstream at decode time, not here.
    """

    if until.tzinfo is None or until.utcoffset() is None:
        raise ValueError("until must be timezone-aware")
    now = clock or (lambda: datetime.now(timezone.utc))
    wait = sleep or time.sleep
    writer = RawWriter(store)

    queue: BoundedEventQueue[MarketEvent] = BoundedEventQueue(capacity=20_000, clock=now)
    tracker = ContractTracker(gateway, clock=now)
    collector = LiveCollector(gateway, tracker, queue, clock=now)
    resolution = collector.start()
    alias_code = resolution.contract.alias_code

    calendar = synthetic_near_term_calendar(now().astimezone(_TAIPEI).date())
    resolver = SessionResolver(calendar)

    buffers: dict[tuple[str, str, str], list[TickEvent | BidAskEvent]] = {}
    sequence: dict[tuple[str, str, str], int] = {}
    stored_records = 0
    stored_segments = 0

    def flush_all() -> None:
        nonlocal stored_records, stored_segments
        for key, events in buffers.items():
            if not events:
                continue
            event_type, trading_date, session = key
            prefix = f"{event_type}-{alias_code}-{trading_date or 'unresolved'}-{session}"
            seq = sequence.get(key)
            if seq is None:
                seq = _first_free_sequence(store, event_type, prefix)
            segment_id = f"{prefix}-{seq:06d}"
            writer.write(event_type, tuple(events), segment_id=segment_id, created_at=now())
            sequence[key] = seq + 1
            stored_records += len(events)
            stored_segments += 1
            events.clear()
            if on_flush is not None:
                on_flush(segment_id, stored_records)

    last_flush = now()
    while now() < until:
        event = queue.pop()
        if event is None:
            if (now() - last_flush).total_seconds() >= flush_interval_seconds:
                flush_all()
                last_flush = now()
            wait(poll_interval_seconds)
            continue
        if not isinstance(event, (TickEvent, BidAskEvent)):
            continue
        resolution_info = resolver.resolve(event.exchange_datetime)
        tagged = replace(
            event,
            trading_date=(
                resolution_info.trading_date.isoformat()
                if resolution_info.trading_date
                else ""
            ),
            session=resolution_info.session,
        )
        event_type = TICK_EVENT_TYPE if isinstance(tagged, TickEvent) else BIDASK_EVENT_TYPE
        key = (event_type, tagged.trading_date, tagged.session)
        buffers.setdefault(key, []).append(tagged)

    flush_all()
    return LiveRunSummary(
        alias_code=alias_code,
        dataset_version=store.dataset_version,
        stored_records=stored_records,
        stored_segments=stored_segments,
        dropped_event_count=queue.dropped_event_count,
    )


def _first_free_sequence(store: AppendOnlyRawStore, event_type: str, prefix: str) -> int:
    """Resume numbering after any segments a previous run already wrote.

    Segments are create-once and this loop runs once per (event type,
    trading date, session) key per process, so a linear scan from zero is
    cheap even after many runs in the same session.
    """

    seq = 0
    while store.has_segment(event_type, f"{prefix}-{seq:06d}"):
        seq += 1
    return seq
