from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
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

    @property
    def max_quote_age(self) -> timedelta:
        return self._max_quote_age

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
        return self._result(tick, None if matched is None else matched[1])

    def join_sorted(
        self,
        ticks: Sequence[TickEvent],
        bidasks: tuple[BidAskEvent, ...],
    ) -> tuple[QuoteJoinResult, ...]:
        """Equivalent to joining each tick against the full bidask window, for
        ticks visited in non-decreasing exchange_datetime order; one shared
        sweep replaces the per-tick rescan."""

        grouped: dict[tuple[str, str], list[BidAskEvent]] = {}
        for bidask in bidasks:
            grouped.setdefault(
                (bidask.target_code, bidask.delivery_month), [],
            ).append(bidask)
        for entries in grouped.values():
            entries.sort(key=lambda event: event.exchange_datetime)
        pointers: dict[tuple[str, str], int] = {}
        # Per group, quotes already at or before the tick time, kept with
        # received_at strictly increasing: a quote dominated by a later one
        # with an equal-or-earlier received_at can never win the backward
        # as-of join, so it is dropped.
        stacks: dict[tuple[str, str], list[BidAskEvent]] = {}
        received: dict[tuple[str, str], list[datetime]] = {}
        results = []
        for tick in ticks:
            key = (tick.target_code, tick.delivery_month)
            entries = grouped.get(key, [])
            stack = stacks.setdefault(key, [])
            stamps = received.setdefault(key, [])
            position = pointers.get(key, 0)
            while (
                position < len(entries)
                and entries[position].exchange_datetime <= tick.exchange_datetime
            ):
                bidask = entries[position]
                while stack and stamps[-1] >= bidask.received_at:
                    stack.pop()
                    stamps.pop()
                stack.append(bidask)
                stamps.append(bidask.received_at)
                position += 1
            pointers[key] = position
            index = bisect_right(stamps, tick.received_at) - 1
            results.append(self._result(tick, stack[index] if index >= 0 else None))
        return tuple(results)

    def _result(
        self,
        tick: TickEvent,
        bidask: BidAskEvent | None,
    ) -> QuoteJoinResult:
        if bidask is None:
            return QuoteJoinResult(
                tick=tick,
                bidask=None,
                matched_bidask_at=None,
                quote_age_ms=None,
                bidask_available=False,
                unavailable_reason="MISSING_BIDASK",
            )
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
