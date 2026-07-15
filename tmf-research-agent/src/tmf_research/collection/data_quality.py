from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from tmf_research.domain.events import BidAskEvent, RejectedEvent, TickEvent


@dataclass(frozen=True, slots=True)
class QualityDecision:
    accepted: bool
    reasons: tuple[str, ...]


class DataQualityMonitor:
    """Rejects invalid collection events while retaining explicit evidence."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._seen_event_ids: set[str] = set()
        self._last_time: dict[tuple[str, str], datetime] = {}
        self._rejections: list[RejectedEvent] = []

    @property
    def quality_status(self) -> str:
        return "VALID" if not self._rejections else "INVALID"

    @property
    def rejections(self) -> tuple[RejectedEvent, ...]:
        return tuple(self._rejections)

    def evaluate(self, event: TickEvent | BidAskEvent) -> QualityDecision:
        reasons: list[str] = []
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
            if event.bid_prices and event.ask_prices and event.ask_prices[0] < event.bid_prices[0]:
                reasons.append("CROSSED_BOOK")
            if (
                any(price <= 0 for price in (*event.bid_prices, *event.ask_prices))
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
        if event.simtrade:
            reasons.append("SIMTRADE")
        if not event.target_code.strip():
            reasons.append("MISSING_TARGET_CODE")

        decision = QualityDecision(not reasons, tuple(reasons))
        if reasons:
            self._rejections.append(
                RejectedEvent(
                    event_id=event.event_id,
                    rejected_at=self._clock(),
                    reasons=tuple(reasons),
                    raw_payload=event.raw_payload,
                )
            )
        return decision
