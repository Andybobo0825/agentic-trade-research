from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from tmf_research.domain.events import (
    BidAskEvent,
    ConnectionEvent,
    QueueBackpressureEvent,
    RejectedEvent,
    Session,
    TickEvent,
)


@dataclass(frozen=True, slots=True)
class QualityDecision:
    accepted: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    trading_date: str
    session: Session
    tick_count: int
    bidask_count: int
    duplicate_count: int
    out_of_order_count: int
    invalid_price_count: int
    invalid_depth_count: int
    stale_tick_count: int
    stale_bidask_count: int
    simtrade_count: int
    queue_drop_count: int
    connection_drop_count: int
    maximum_gap_seconds: float
    tick_coverage_ratio: float
    bidask_coverage_ratio: float
    quality_status: str


@dataclass(slots=True)
class _SessionStats:
    tick_count: int = 0
    bidask_count: int = 0
    queue_drop_count: int = 0
    connection_drop_count: int = 0
    event_times: list[datetime] = field(default_factory=list)
    reason_counts: dict[str, int] = field(default_factory=dict)

    def retain_reasons(self, reasons: tuple[str, ...]) -> None:
        for reason in reasons:
            self.reason_counts[reason] = self.reason_counts.get(reason, 0) + 1


class DataQualityMonitor:
    """Rejects invalid collection events while retaining explicit evidence."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        stale_after: timedelta = timedelta(seconds=5),
    ) -> None:
        if stale_after < timedelta(0):
            raise ValueError("stale_after cannot be negative")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._stale_after = stale_after
        self._seen_event_ids: set[str] = set()
        self._last_time: dict[tuple[str, str], datetime] = {}
        self._rejections: list[RejectedEvent] = []
        self._sessions: dict[tuple[str, Session], _SessionStats] = {}

    @property
    def quality_status(self) -> str:
        return "VALID" if not self._rejections else "INVALID"

    @property
    def rejections(self) -> tuple[RejectedEvent, ...]:
        return tuple(self._rejections)

    def evaluate(self, event: TickEvent | BidAskEvent) -> QualityDecision:
        reasons: list[str] = []
        stats = self._session_stats(event.trading_date, event.session)
        stats.event_times.append(event.exchange_datetime)
        if isinstance(event, TickEvent):
            stats.tick_count += 1
        else:
            stats.bidask_count += 1
        if event.event_id in self._seen_event_ids:
            reasons.append("DUPLICATE")
        else:
            self._seen_event_ids.add(event.event_id)

        if isinstance(event, TickEvent):
            if event.close <= 0:
                reasons.append("INVALID_PRICE")
            if event.volume < 0:
                reasons.append("NEGATIVE_VOLUME")
        else:
            crossed_book = bool(
                event.bid_prices
                and event.ask_prices
                and event.ask_prices[0] < event.bid_prices[0]
            )
            if crossed_book:
                reasons.append("CROSSED_BOOK")
            if (
                crossed_book
                or any(price <= 0 for price in (*event.bid_prices, *event.ask_prices))
                or any(volume < 0 for volume in (*event.bid_volumes, *event.ask_volumes))
                or len(event.bid_prices) != len(event.bid_volumes)
                or len(event.ask_prices) != len(event.ask_volumes)
            ):
                reasons.append("INVALID_DEPTH")

        key = (type(event).__name__, event.target_code)
        previous_time = self._last_time.get(key)
        if previous_time is not None and event.exchange_datetime < previous_time:
            reasons.append("OUT_OF_ORDER")
        else:
            self._last_time[key] = event.exchange_datetime
        if self._clock() - event.exchange_datetime > self._stale_after:
            reasons.append("STALE_TICK" if isinstance(event, TickEvent) else "STALE_BIDASK")
        if event.simtrade:
            reasons.append("SIMTRADE")
        if event.session == "CLOSED" or not event.trading_date.strip():
            reasons.append("OUT_OF_SESSION")
        if not event.target_code.strip():
            reasons.append("UNKNOWN_TARGET")

        decision = QualityDecision(not reasons, tuple(reasons))
        if reasons:
            retained = tuple(reasons)
            stats.retain_reasons(retained)
            self._retain_rejection(event.event_id, retained, event.raw_payload)
        return decision

    def record_queue_backpressure(
        self,
        event: QueueBackpressureEvent,
        *,
        trading_date: str,
        session: Session,
    ) -> None:
        stats = self._session_stats(trading_date, session)
        stats.queue_drop_count = max(
            stats.queue_drop_count,
            event.dropped_event_count,
        )
        stats.retain_reasons(("QUEUE_LOSS",))
        self._retain_rejection(
            event.event_id,
            ("QUEUE_LOSS",),
            {
                "event_type": event.event_type,
                "queue_size": event.queue_size,
                "dropped_event_count": event.dropped_event_count,
            },
        )

    def record_connection_drop(
        self,
        event: ConnectionEvent,
        *,
        trading_date: str,
        session: Session,
    ) -> None:
        stats = self._session_stats(trading_date, session)
        stats.connection_drop_count += 1
        stats.retain_reasons(("CONNECTION_DROP",))
        self._retain_rejection(
            event.event_id,
            ("CONNECTION_DROP",),
            {
                "event_type": event.event_type,
                "connection_status": event.connection_status,
                "attempt_number": event.attempt_number,
                "reason": event.reason,
            },
        )

    def report(
        self,
        *,
        trading_date: str,
        session: Session,
        expected_seconds: int,
    ) -> DataQualityReport:
        if expected_seconds <= 0:
            raise ValueError("expected_seconds must be positive")
        stats = self._sessions.get((trading_date, session), _SessionStats())
        tick_coverage = min(1.0, stats.tick_count / expected_seconds)
        bidask_coverage = min(1.0, stats.bidask_count / expected_seconds)
        reason_counts = stats.reason_counts
        invalid = bool(reason_counts) or tick_coverage < 1.0 or bidask_coverage < 1.0
        return DataQualityReport(
            trading_date=trading_date,
            session=session,
            tick_count=stats.tick_count,
            bidask_count=stats.bidask_count,
            duplicate_count=reason_counts.get("DUPLICATE", 0),
            out_of_order_count=reason_counts.get("OUT_OF_ORDER", 0),
            invalid_price_count=reason_counts.get("INVALID_PRICE", 0),
            invalid_depth_count=reason_counts.get("INVALID_DEPTH", 0),
            stale_tick_count=reason_counts.get("STALE_TICK", 0),
            stale_bidask_count=reason_counts.get("STALE_BIDASK", 0),
            simtrade_count=reason_counts.get("SIMTRADE", 0),
            queue_drop_count=stats.queue_drop_count,
            connection_drop_count=stats.connection_drop_count,
            maximum_gap_seconds=_maximum_gap_seconds(stats.event_times),
            tick_coverage_ratio=tick_coverage,
            bidask_coverage_ratio=bidask_coverage,
            quality_status="INVALID" if invalid else "VALID",
        )

    def _session_stats(self, trading_date: str, session: Session) -> _SessionStats:
        return self._sessions.setdefault((trading_date, session), _SessionStats())

    def _retain_rejection(
        self,
        event_id: str,
        reasons: tuple[str, ...],
        raw_payload: Mapping[str, object],
    ) -> None:
        self._rejections.append(
            RejectedEvent(
                event_id=event_id,
                rejected_at=self._clock(),
                reasons=reasons,
                raw_payload=raw_payload,
            )
        )


def _maximum_gap_seconds(event_times: list[datetime]) -> float:
    ordered = sorted(set(event_times))
    return max(
        (
            (current - previous).total_seconds()
            for previous, current in zip(ordered, ordered[1:], strict=False)
        ),
        default=0.0,
    )
