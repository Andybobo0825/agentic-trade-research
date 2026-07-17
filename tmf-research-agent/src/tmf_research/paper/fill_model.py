from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from tmf_research.domain.paper_trades import PaperDirection, PaperFill, PaperQuote


@dataclass(frozen=True, slots=True)
class PaperFillModel:
    """Deterministic executable-side paper fills with fixed slippage."""

    entry_slippage_points: float
    exit_slippage_points: float

    def __post_init__(self) -> None:
        for value in (self.entry_slippage_points, self.exit_slippage_points):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0.0
            ):
                raise ValueError("slippage must be finite and non-negative")

    def entry_fill(
        self,
        direction: PaperDirection,
        quote: PaperQuote,
        at: datetime,
    ) -> PaperFill:
        if direction == "LONG":
            price = quote.ask_price_1 + self.entry_slippage_points
        else:
            price = quote.bid_price_1 - self.entry_slippage_points
        return PaperFill(direction=direction, price=price, filled_at=at)

    def exit_fill(
        self,
        direction: PaperDirection,
        reference_price: float,
        at: datetime,
    ) -> PaperFill:
        if (
            isinstance(reference_price, bool)
            or not isinstance(reference_price, (int, float))
            or not math.isfinite(reference_price)
        ):
            raise ValueError("exit reference price must be finite")
        if direction == "LONG":
            price = reference_price - self.exit_slippage_points
        else:
            price = reference_price + self.exit_slippage_points
        return PaperFill(direction=direction, price=price, filled_at=at)
