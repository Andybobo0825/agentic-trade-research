from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tmf_research.processing.one_second import OneSecondState


Direction = Literal["LONG", "SHORT"]


@dataclass(frozen=True, slots=True)
class ExecutableSnapshot:
    bid: float
    ask: float
    spread: float


@dataclass(frozen=True, slots=True)
class ExecutablePrices:
    direction: Direction
    entry: float
    exit: float
    entry_bid: float
    entry_ask: float
    entry_spread: float


class ExecutablePricePolicy:
    def __init__(self, *, entry_slippage: float, exit_slippage: float) -> None:
        if entry_slippage < 0 or exit_slippage < 0:
            raise ValueError("slippage cannot be negative")
        self._entry_slippage = entry_slippage
        self._exit_slippage = exit_slippage

    @property
    def estimated_round_trip_cost(self) -> float:
        return self._entry_slippage + self._exit_slippage

    def snapshot(self, state: OneSecondState) -> ExecutableSnapshot:
        if (
            not state.bidask_available
            or state.last_bid is None
            or state.last_ask is None
            or state.last_ask < state.last_bid
        ):
            raise ValueError("executable bid/ask quote is required")
        return ExecutableSnapshot(
            bid=state.last_bid,
            ask=state.last_ask,
            spread=state.last_ask - state.last_bid,
        )

    def prices(self, direction: Direction, state: OneSecondState) -> ExecutablePrices:
        quote = self.snapshot(state)
        if direction == "LONG":
            entry = quote.ask + self._entry_slippage
            exit_price = quote.bid - self._exit_slippage
        else:
            entry = quote.bid - self._entry_slippage
            exit_price = quote.ask + self._exit_slippage
        return ExecutablePrices(
            direction=direction,
            entry=entry,
            exit=exit_price,
            entry_bid=quote.bid,
            entry_ask=quote.ask,
            entry_spread=quote.spread,
        )

