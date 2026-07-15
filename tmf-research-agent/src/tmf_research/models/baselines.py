from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from tmf_research.models.logistic import BinaryLogisticModel


Signal = Literal["NO_TRADE", "LONG", "SHORT"]


@dataclass(frozen=True, slots=True)
class BaselineObservation:
    price: float
    previous_price: float
    vwap: float
    ema_slope: float
    returns: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.returns or any(
            not math.isfinite(value)
            for value in (self.price, self.previous_price, self.vwap, self.ema_slope, *self.returns)
        ):
            raise ValueError("baseline inputs must be finite and non-empty")


def baseline_0(_observation: BaselineObservation) -> Signal:
    return "NO_TRADE"


def baseline_1(observation: BaselineObservation) -> Signal:
    return _direction(observation.price - observation.previous_price)


def baseline_2(observation: BaselineObservation) -> Signal:
    return _direction(observation.price - observation.vwap)


def baseline_3(observation: BaselineObservation) -> Signal:
    return _direction(observation.ema_slope)


@dataclass(frozen=True, slots=True)
class ReturnOnlyBaseline:
    model: BinaryLogisticModel

    def __post_init__(self) -> None:
        if not self.model.feature_order or any(not name.startswith("return_") for name in self.model.feature_order):
            raise ValueError("baseline four may use only price return features")

    @property
    def feature_order(self) -> tuple[str, ...]:
        return self.model.feature_order

    def predict(self, observation: BaselineObservation) -> Signal:
        probability = self.model.predict_probability(observation.returns)
        if abs(probability - 0.5) <= 1e-15:
            return "NO_TRADE"
        return "LONG" if probability > 0.5 else "SHORT"


@dataclass(frozen=True, slots=True)
class BaselineFoldReport:
    outer_fold_id: str
    predictions: tuple[tuple[str, tuple[Signal, ...]], ...]


def report_outer_fold(
    *,
    outer_fold_id: str,
    observations: tuple[BaselineObservation, ...],
    return_only: ReturnOnlyBaseline,
) -> BaselineFoldReport:
    if not outer_fold_id.strip():
        raise ValueError("outer fold id is required")
    return BaselineFoldReport(
        outer_fold_id=outer_fold_id,
        predictions=(
            ("BASELINE_0", tuple(baseline_0(item) for item in observations)),
            ("BASELINE_1", tuple(baseline_1(item) for item in observations)),
            ("BASELINE_2", tuple(baseline_2(item) for item in observations)),
            ("BASELINE_3", tuple(baseline_3(item) for item in observations)),
            ("BASELINE_4", tuple(return_only.predict(item) for item in observations)),
        ),
    )


def _direction(value: float) -> Signal:
    if value > 0.0:
        return "LONG"
    if value < 0.0:
        return "SHORT"
    return "NO_TRADE"
