from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from tmf_research.domain.events import BidAskEvent, TickEvent


@dataclass(frozen=True, slots=True)
class QuoteJoinResult:
    tick: TickEvent
    bidask: BidAskEvent | None
    matched_bidask_at: datetime | None
    quote_age_ms: float | None
    bidask_available: bool
    unavailable_reason: str | None


class QuoteJoiner:
    """Performs a deterministic backward as-of join for one target contract."""

    def __init__(self, *, max_quote_age: timedelta) -> None:
        if max_quote_age < timedelta(0):
            raise ValueError("max_quote_age cannot be negative")
        self._max_quote_age = max_quote_age

    def join(
        self,
        tick: TickEvent,
        bidasks: tuple[BidAskEvent, ...],
    ) -> QuoteJoinResult:
        candidates = (
            (index, bidask)
            for index, bidask in enumerate(bidasks)
            if bidask.target_code == tick.target_code
            and bidask.delivery_month == tick.delivery_month
            and bidask.exchange_datetime <= tick.exchange_datetime
            and bidask.received_at <= tick.received_at
        )
        matched = max(
            candidates,
            key=lambda item: (item[1].exchange_datetime, item[0]),
            default=None,
        )
        if matched is None:
            return QuoteJoinResult(
                tick=tick,
                bidask=None,
                matched_bidask_at=None,
                quote_age_ms=None,
                bidask_available=False,
                unavailable_reason="MISSING_BIDASK",
            )
        bidask = matched[1]
        age = tick.exchange_datetime - bidask.exchange_datetime
        age_ms = age.total_seconds() * 1000.0
        if age > self._max_quote_age:
            return QuoteJoinResult(
                tick=tick,
                bidask=None,
                matched_bidask_at=bidask.exchange_datetime,
                quote_age_ms=age_ms,
                bidask_available=False,
                unavailable_reason="STALE_BIDASK",
            )
        return QuoteJoinResult(
            tick=tick,
            bidask=bidask,
            matched_bidask_at=bidask.exchange_datetime,
            quote_age_ms=age_ms,
            bidask_available=True,
            unavailable_reason=None,
        )
