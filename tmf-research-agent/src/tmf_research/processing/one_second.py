from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from tmf_research.domain.events import BidAskEvent, TickEvent


@dataclass(frozen=True, slots=True)
class OneSecondState:
    second: datetime
    target_code: str | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int
    trade_count: int
    buy_volume: int
    sell_volume: int
    unknown_volume: int
    last_bid: float | None
    last_ask: float | None
    spread: float | None
    midpoint: float | None
    microprice: float | None
    level1_imbalance: float | None
    level3_imbalance: float | None
    level5_imbalance: float | None
    underlying_price: float | None
    basis: float | None
    last_tick_age_ms: float | None
    last_bidask_age_ms: float | None
    notional: float
    last_tick_at: datetime | None
    last_bidask_at: datetime | None
    bid_prices: tuple[float, ...] = ()
    bid_volumes: tuple[int, ...] = ()
    ask_prices: tuple[float, ...] = ()
    ask_volumes: tuple[int, ...] = ()


class OneSecondAggregator:
    """Builds causal one-second states without inventing empty-second trades."""

    def aggregate(
        self,
        second: datetime,
        ticks: tuple[TickEvent, ...],
        bidasks: tuple[BidAskEvent, ...],
        *,
        previous: OneSecondState | None = None,
    ) -> OneSecondState:
        _require_aware(second)
        end = second + timedelta(seconds=1)
        ordered_ticks = tuple(
            sorted(
                (event for event in ticks if second <= event.exchange_datetime < end),
                key=lambda event: (event.exchange_datetime, event.event_id),
            )
        )
        ordered_quotes = tuple(
            sorted(
                (
                    event
                    for event in bidasks
                    if second <= event.exchange_datetime < end
                ),
                key=lambda event: (event.exchange_datetime, event.event_id),
            )
        )
        target_code = _target_code(ordered_ticks, ordered_quotes, previous)

        prices = tuple(event.close for event in ordered_ticks)
        volume = sum(event.volume for event in ordered_ticks)
        buy_volume = sum(
            event.volume for event in ordered_ticks if event.tick_type == 1
        )
        sell_volume = sum(
            event.volume for event in ordered_ticks if event.tick_type == 2
        )
        unknown_volume = volume - buy_volume - sell_volume
        notional = sum(event.close * event.volume for event in ordered_ticks)
        last_tick = ordered_ticks[-1] if ordered_ticks else None
        last_quote = ordered_quotes[-1] if ordered_quotes else None

        bid_prices = (
            last_quote.bid_prices
            if last_quote is not None
            else previous.bid_prices if previous is not None else ()
        )
        bid_volumes = (
            last_quote.bid_volumes
            if last_quote is not None
            else previous.bid_volumes if previous is not None else ()
        )
        ask_prices = (
            last_quote.ask_prices
            if last_quote is not None
            else previous.ask_prices if previous is not None else ()
        )
        ask_volumes = (
            last_quote.ask_volumes
            if last_quote is not None
            else previous.ask_volumes if previous is not None else ()
        )
        last_bid = bid_prices[0] if bid_prices else None
        last_ask = ask_prices[0] if ask_prices else None
        spread = (
            last_ask - last_bid
            if last_bid is not None and last_ask is not None
            else None
        )
        midpoint = (
            (last_bid + last_ask) / 2.0
            if last_bid is not None and last_ask is not None
            else None
        )
        underlying_price = _underlying(last_tick, last_quote, previous)
        basis = (
            midpoint - underlying_price
            if midpoint is not None and underlying_price is not None
            else previous.basis if previous is not None and not prices else None
        )
        last_tick_at = (
            last_tick.exchange_datetime
            if last_tick is not None
            else previous.last_tick_at if previous is not None else None
        )
        last_bidask_at = (
            last_quote.exchange_datetime
            if last_quote is not None
            else previous.last_bidask_at if previous is not None else None
        )
        return OneSecondState(
            second=second,
            target_code=target_code,
            open=prices[0] if prices else None,
            high=max(prices) if prices else None,
            low=min(prices) if prices else None,
            close=prices[-1] if prices else None,
            volume=volume,
            trade_count=len(ordered_ticks),
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            unknown_volume=unknown_volume,
            last_bid=last_bid,
            last_ask=last_ask,
            spread=spread,
            midpoint=midpoint,
            microprice=_microprice(
                last_bid,
                last_ask,
                bid_volumes,
                ask_volumes,
            ),
            level1_imbalance=_imbalance(bid_volumes, ask_volumes, 1),
            level3_imbalance=_imbalance(bid_volumes, ask_volumes, 3),
            level5_imbalance=_imbalance(bid_volumes, ask_volumes, 5),
            underlying_price=underlying_price,
            basis=basis,
            last_tick_age_ms=_age_ms(end, last_tick_at),
            last_bidask_age_ms=_age_ms(end, last_bidask_at),
            notional=notional,
            last_tick_at=last_tick_at,
            last_bidask_at=last_bidask_at,
            bid_prices=bid_prices,
            bid_volumes=bid_volumes,
            ask_prices=ask_prices,
            ask_volumes=ask_volumes,
        )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("second must be timezone-aware")


def _target_code(
    ticks: tuple[TickEvent, ...],
    bidasks: tuple[BidAskEvent, ...],
    previous: OneSecondState | None,
) -> str | None:
    values = {event.target_code for event in ticks}
    values.update(event.target_code for event in bidasks)
    if previous is not None and previous.target_code is not None:
        values.add(previous.target_code)
    if len(values) > 1:
        raise ValueError("one-second state cannot mix target contracts")
    return next(iter(values), None)


def _underlying(
    tick: TickEvent | None,
    bidask: BidAskEvent | None,
    previous: OneSecondState | None,
) -> float | None:
    if tick is not None and tick.underlying_price is not None:
        return tick.underlying_price
    if bidask is not None and bidask.underlying_price is not None:
        return bidask.underlying_price
    return previous.underlying_price if previous is not None else None


def _microprice(
    bid: float | None,
    ask: float | None,
    bid_volumes: tuple[int, ...],
    ask_volumes: tuple[int, ...],
) -> float | None:
    if bid is None or ask is None or not bid_volumes or not ask_volumes:
        return None
    total = bid_volumes[0] + ask_volumes[0]
    if total <= 0:
        return None
    return (ask * bid_volumes[0] + bid * ask_volumes[0]) / total


def _imbalance(
    bid_volumes: tuple[int, ...],
    ask_volumes: tuple[int, ...],
    levels: int,
) -> float | None:
    bid = sum(bid_volumes[:levels])
    ask = sum(ask_volumes[:levels])
    total = bid + ask
    return (bid - ask) / total if total > 0 else None


def _age_ms(end: datetime, occurred_at: datetime | None) -> float | None:
    if occurred_at is None:
        return None
    return max(0.0, (end - occurred_at).total_seconds() * 1000.0)
