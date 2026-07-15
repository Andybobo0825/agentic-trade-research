from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from tmf_research.models.inference import ClassProbabilities, combine_probabilities


ModelLabel = Literal["NO_TRADE", "LONG", "SHORT", "AMBIGUOUS"]


@dataclass(frozen=True, slots=True)
class BinaryTrainingSample:
    values: tuple[float, ...]
    target: int

    def __post_init__(self) -> None:
        if self.target not in (0, 1):
            raise ValueError("binary target must be zero or one")


@dataclass(frozen=True, slots=True)
class ModelTrainingSample:
    values: tuple[float, ...]
    label: ModelLabel
    is_complete: bool = True


@dataclass(frozen=True, slots=True)
class BinaryTrainingRecord:
    sample_count: int
    class_counts: tuple[tuple[int, int], ...]
    loss_history: tuple[float, ...]
    iterations: int
    converged: bool
    final_loss: float
    fit_scope: str = "INNER_TRAIN"


@dataclass(frozen=True, slots=True)
class BinaryLogisticModel:
    feature_order: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    l2: float
    class_weights: tuple[tuple[int, float], ...]
    max_iterations: int
    tolerance: float
    learning_rate: float
    random_seed: int
    classes: tuple[str, str]
    record: BinaryTrainingRecord

    def predict_probability(self, values: Sequence[float]) -> float:
        if len(values) != len(self.coefficients):
            raise ValueError("model input dimension mismatch")
        score = self.intercept + sum(coefficient * float(value) for coefficient, value in zip(self.coefficients, values, strict=True))
        return _sigmoid(score)

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_order": list(self.feature_order),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
            "l2": self.l2,
            "class_weights": [[key, value] for key, value in self.class_weights],
            "max_iterations": self.max_iterations,
            "tolerance": self.tolerance,
            "learning_rate": self.learning_rate,
            "random_seed": self.random_seed,
            "classes": list(self.classes),
            "record": {
                "sample_count": self.record.sample_count,
                "class_counts": [list(item) for item in self.record.class_counts],
                "loss_history": list(self.record.loss_history),
                "iterations": self.record.iterations,
                "converged": self.record.converged,
                "final_loss": self.record.final_loss,
                "fit_scope": self.record.fit_scope,
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> BinaryLogisticModel:
        record_payload = _mapping(payload["record"])
        return cls(
            feature_order=tuple(_strings(payload["feature_order"])),
            coefficients=tuple(_floats(payload["coefficients"])),
            intercept=_number(payload["intercept"]),
            l2=_number(payload["l2"]),
            class_weights=tuple((_integer(item[0]), _number(item[1])) for item in _pairs(payload["class_weights"])),
            max_iterations=_integer(payload["max_iterations"]),
            tolerance=_number(payload["tolerance"]),
            learning_rate=_number(payload["learning_rate"]),
            random_seed=_integer(payload["random_seed"]),
            classes=cast(tuple[str, str], tuple(_strings(payload["classes"]))),
            record=BinaryTrainingRecord(
                sample_count=_integer(record_payload["sample_count"]),
                class_counts=tuple((_integer(item[0]), _integer(item[1])) for item in _pairs(record_payload["class_counts"])),
                loss_history=tuple(_floats(record_payload["loss_history"])),
                iterations=_integer(record_payload["iterations"]),
                converged=bool(record_payload["converged"]),
                final_loss=_number(record_payload["final_loss"]),
                fit_scope=str(record_payload["fit_scope"]),
            ),
        )


@dataclass(frozen=True, slots=True)
class TwoStageTrainingRecord:
    input_count: int
    eligible_count: int
    excluded_ambiguous: int
    excluded_incomplete: int
    model_a_target: str = "TRADE_VS_NO_TRADE"
    model_b_target: str = "LONG_VS_SHORT_TRADE_ONLY"


@dataclass(frozen=True, slots=True)
class TwoStageLogisticModel:
    trade_model: BinaryLogisticModel
    direction_model: BinaryLogisticModel
    record: TwoStageTrainingRecord

    def predict(self, values: Sequence[float]) -> ClassProbabilities:
        return combine_probabilities(
            p_trade=self.trade_model.predict_probability(values),
            p_long_given_trade=self.direction_model.predict_probability(values),
        )


def fit_binary_logistic(
    samples: Sequence[BinaryTrainingSample],
    *,
    feature_order: tuple[str, ...],
    l2: float = 1.0,
    class_weights: Mapping[int, float] | None = None,
    max_iterations: int = 500,
    tolerance: float = 1e-9,
    learning_rate: float = 0.1,
    random_seed: int = 0,
    classes: tuple[str, str] = ("NEGATIVE", "POSITIVE"),
) -> BinaryLogisticModel:
    if not samples:
        raise ValueError("logistic training requires samples")
    if not feature_order or len(feature_order) != len(set(feature_order)) or len(feature_order) > 35:
        raise ValueError("fixed feature order must be unique and contain at most 35 declared features")
    if l2 < 0.0 or max_iterations <= 0 or tolerance <= 0.0 or learning_rate <= 0.0:
        raise ValueError("invalid logistic training configuration")
    if any(len(sample.values) != len(feature_order) for sample in samples):
        raise ValueError("training feature dimension mismatch")
    targets = {sample.target for sample in samples}
    if targets != {0, 1}:
        raise ValueError("logistic training requires both classes")
    weights = {0: 1.0, 1: 1.0} if class_weights is None else {0: float(class_weights[0]), 1: float(class_weights[1])}
    if any(value <= 0.0 for value in weights.values()):
        raise ValueError("class weights must be positive")
    coefficients = [0.0] * len(feature_order)
    intercept = 0.0
    history: list[float] = []
    converged = False
    for _ in range(max_iterations):
        gradient = [0.0] * len(feature_order)
        intercept_gradient = 0.0
        weighted_count = 0.0
        for sample in samples:
            probability = _sigmoid(intercept + sum(coefficient * value for coefficient, value in zip(coefficients, sample.values, strict=True)))
            weight = weights[sample.target]
            error = weight * (probability - sample.target)
            intercept_gradient += error
            weighted_count += weight
            for index, value in enumerate(sample.values):
                gradient[index] += error * value
        for index, coefficient in enumerate(coefficients):
            gradient[index] = gradient[index] / weighted_count + l2 * coefficient / len(samples)
        intercept_gradient /= weighted_count
        previous = (intercept, *coefficients)
        intercept -= learning_rate * intercept_gradient
        coefficients = [coefficient - learning_rate * gradient[index] for index, coefficient in enumerate(coefficients)]
        loss = _binary_loss(samples, coefficients, intercept, l2, weights)
        history.append(loss)
        change = max(abs(current - prior) for current, prior in zip((intercept, *coefficients), previous, strict=True))
        if change <= tolerance:
            converged = True
            break
    class_counts = ((0, sum(sample.target == 0 for sample in samples)), (1, sum(sample.target == 1 for sample in samples)))
    return BinaryLogisticModel(
        feature_order=feature_order,
        coefficients=tuple(coefficients),
        intercept=intercept,
        l2=l2,
        class_weights=tuple(sorted(weights.items())),
        max_iterations=max_iterations,
        tolerance=tolerance,
        learning_rate=learning_rate,
        random_seed=random_seed,
        classes=classes,
        record=BinaryTrainingRecord(
            sample_count=len(samples), class_counts=class_counts, loss_history=tuple(history),
            iterations=len(history), converged=converged, final_loss=history[-1],
        ),
    )


def fit_two_stage_logistic(
    samples: Sequence[ModelTrainingSample],
    *,
    feature_order: tuple[str, ...],
    l2: float = 1.0,
    class_weights: Mapping[int, float] | None = None,
    max_iterations: int = 500,
    tolerance: float = 1e-9,
    learning_rate: float = 0.1,
    random_seed: int = 0,
) -> TwoStageLogisticModel:
    eligible = tuple(sample for sample in samples if sample.is_complete and sample.label != "AMBIGUOUS")
    trade_samples = tuple(BinaryTrainingSample(sample.values, int(sample.label in ("LONG", "SHORT"))) for sample in eligible)
    direction_samples = tuple(BinaryTrainingSample(sample.values, int(sample.label == "LONG")) for sample in eligible if sample.label in ("LONG", "SHORT"))
    trade_model = fit_binary_logistic(
        trade_samples, feature_order=feature_order, l2=l2, class_weights=class_weights,
        max_iterations=max_iterations, tolerance=tolerance, learning_rate=learning_rate,
        random_seed=random_seed, classes=("NO_TRADE", "TRADE"),
    )
    direction_model = fit_binary_logistic(
        direction_samples, feature_order=feature_order, l2=l2, class_weights=class_weights,
        max_iterations=max_iterations, tolerance=tolerance, learning_rate=learning_rate,
        random_seed=random_seed, classes=("SHORT", "LONG"),
    )
    return TwoStageLogisticModel(
        trade_model=trade_model,
        direction_model=direction_model,
        record=TwoStageTrainingRecord(
            input_count=len(samples), eligible_count=len(eligible),
            excluded_ambiguous=sum(sample.label == "AMBIGUOUS" for sample in samples),
            excluded_incomplete=sum(not sample.is_complete for sample in samples),
        ),
    )


def _binary_loss(samples: Sequence[BinaryTrainingSample], coefficients: Sequence[float], intercept: float, l2: float, weights: Mapping[int, float]) -> float:
    epsilon = 1e-15
    total = 0.0
    weighted_count = 0.0
    for sample in samples:
        probability = min(1.0 - epsilon, max(epsilon, _sigmoid(intercept + sum(coefficient * value for coefficient, value in zip(coefficients, sample.values, strict=True)))))
        weight = weights[sample.target]
        total += -weight * (sample.target * math.log(probability) + (1 - sample.target) * math.log(1.0 - probability))
        weighted_count += weight
    return total / weighted_count + 0.5 * l2 * sum(value * value for value in coefficients) / len(samples)


def _sigmoid(score: float) -> float:
    if score >= 0.0:
        exponential = math.exp(-score)
        return 1.0 / (1.0 + exponential)
    exponential = math.exp(score)
    return exponential / (1.0 + exponential)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expected mapping")
    return cast(Mapping[str, object], value)


def _strings(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected string list")
    return cast(list[str], value)


def _floats(value: object) -> list[float]:
    if not isinstance(value, list) or not all(isinstance(item, (int, float)) for item in value):
        raise ValueError("expected number list")
    return [float(item) for item in value]


def _pairs(value: object) -> list[list[object]]:
    if not isinstance(value, list) or not all(isinstance(item, list) and len(item) == 2 for item in value):
        raise ValueError("expected pair list")
    return cast(list[list[object]], value)


def _number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("expected number")
    return float(value)


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected integer")
    return value
