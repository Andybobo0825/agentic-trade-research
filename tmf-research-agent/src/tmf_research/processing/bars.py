from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from tmf_research.processing.one_second import OneSecondState


@dataclass(frozen=True, slots=True)
class Bar:
    target_code: str | None
    bar_start: datetime
    bar_end: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int
    trade_count: int
    buy_volume: int
    sell_volume: int
    unknown_volume: int
    vwap: float | None
    bidask_coverage_ratio: float
    tick_coverage_ratio: float
    is_complete: bool


class BarAggregator:
    """Aggregates one-second states on an explicit session anchor."""

    def __init__(self, *, interval_minutes: int) -> None:
        if interval_minutes not in (1, 5, 15, 60):
            raise ValueError("interval_minutes must be one of 1, 5, 15, 60")
        self._interval_minutes = interval_minutes

    def aggregate(
        self,
        states: tuple[OneSecondState, ...],
        *,
        session_start: datetime,
    ) -> tuple[Bar, ...]:
        _require_aware(session_start)
        if not states:
            return ()
        ordered = tuple(sorted(states, key=lambda state: state.second))
        if len({state.second for state in ordered}) != len(ordered):
            raise ValueError("one-second states must have unique timestamps")
        grouped: dict[datetime, list[OneSecondState]] = {}
        interval_seconds = self._interval_minutes * 60
        for state in ordered:
            if state.second < session_start:
                raise ValueError("state precedes the session anchor")
            offset = int((state.second - session_start).total_seconds())
            start = session_start + timedelta(
                seconds=(offset // interval_seconds) * interval_seconds
            )
            grouped.setdefault(start, []).append(state)
        return tuple(
            self._bar(start, tuple(grouped[start])) for start in sorted(grouped)
        )

    def research_bars(
        self,
        states: tuple[OneSecondState, ...],
        *,
        session_start: datetime,
    ) -> tuple[Bar, ...]:
        return tuple(
            bar
            for bar in self.aggregate(states, session_start=session_start)
            if bar.is_complete
        )

    def _bar(self, start: datetime, states: tuple[OneSecondState, ...]) -> Bar:
        expected = self._interval_minutes * 60
        end = start + timedelta(seconds=expected)
        prices = tuple(
            price
            for state in states
            for price in ((state.open,) if state.open is not None else ())
        )
        high_values = tuple(
            state.high for state in states if state.high is not None
        )
        low_values = tuple(state.low for state in states if state.low is not None)
        closes = tuple(state.close for state in states if state.close is not None)
        volume = sum(state.volume for state in states)
        target_codes = {
            state.target_code for state in states if state.target_code is not None
        }
        if len(target_codes) > 1:
            raise ValueError("bar cannot mix target contracts")
        expected_seconds = {
            start + timedelta(seconds=offset) for offset in range(expected)
        }
        actual_seconds = {state.second for state in states}
        return Bar(
            target_code=next(iter(target_codes), None),
            bar_start=start,
            bar_end=end,
            open=prices[0] if prices else None,
            high=max(high_values) if high_values else None,
            low=min(low_values) if low_values else None,
            close=closes[-1] if closes else None,
            volume=volume,
            trade_count=sum(state.trade_count for state in states),
            buy_volume=sum(state.buy_volume for state in states),
            sell_volume=sum(state.sell_volume for state in states),
            unknown_volume=sum(state.unknown_volume for state in states),
            vwap=(
                sum(state.notional for state in states) / volume
                if volume > 0
                else None
            ),
            bidask_coverage_ratio=sum(
                state.last_bid is not None and state.last_ask is not None
                for state in states
            )
            / expected,
            tick_coverage_ratio=sum(state.trade_count > 0 for state in states)
            / expected,
            is_complete=actual_seconds == expected_seconds,
        )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("session_start must be timezone-aware")
