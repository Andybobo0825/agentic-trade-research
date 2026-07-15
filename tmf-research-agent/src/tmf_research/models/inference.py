from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClassProbabilities:
    p_no_trade: float
    p_long: float
    p_short: float

    def __post_init__(self) -> None:
        values = self.as_tuple()
        if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in values):
            raise ValueError("probability must be between zero and one")
        if abs(sum(values) - 1.0) > 1e-12:
            raise ValueError("class probabilities must sum to one")

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.p_no_trade, self.p_long, self.p_short)


def combine_probabilities(*, p_trade: float, p_long_given_trade: float) -> ClassProbabilities:
    for value in (p_trade, p_long_given_trade):
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            raise ValueError("probability must be between zero and one")
    p_long = p_trade * p_long_given_trade
    p_short = p_trade * (1.0 - p_long_given_trade)
    return ClassProbabilities(p_no_trade=1.0 - p_trade, p_long=p_long, p_short=p_short)
