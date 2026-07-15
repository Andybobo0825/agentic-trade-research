from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from tmf_research.models.inference import ClassProbabilities, combine_probabilities
from tmf_research.models.provenance import TrainingProvenance, canonical_hash


ModelLabel = Literal["NO_TRADE", "LONG", "SHORT", "AMBIGUOUS"]


@dataclass(frozen=True, slots=True)
class BinaryTrainingSample:
    values: tuple[float, ...]
    target: int

    def __post_init__(self) -> None:
        if self.target not in (0, 1):
            raise ValueError("binary target must be zero or one")
        if not self.values or any(not math.isfinite(value) for value in self.values):
            raise ValueError("training values must be finite and non-empty")


@dataclass(frozen=True, slots=True)
class ModelTrainingSample:
    values: tuple[float, ...]
    label: ModelLabel
    is_complete: bool = True

    def __post_init__(self) -> None:
        if self.label not in ("NO_TRADE", "LONG", "SHORT", "AMBIGUOUS"):
            raise ValueError("unknown model training label")
        if not self.values or any(not math.isfinite(value) for value in self.values):
            raise ValueError("training values must be finite and non-empty")


@dataclass(frozen=True, slots=True)
class BinaryTrainingRecord:
    sample_count: int
    class_counts: tuple[tuple[int, int], ...]
    loss_history: tuple[float, ...]
    iterations: int
    converged: bool
    final_loss: float
    fold_id: str
    dataset_hash: str
    train_hash: str
    preprocessor_hash: str
    fit_start: str
    fit_end: str

    def __post_init__(self) -> None:
        if self.sample_count <= 0 or sum(count for _, count in self.class_counts) != self.sample_count:
            raise ValueError("training record sample counts are inconsistent")
        if tuple(key for key, _ in self.class_counts) != (0, 1):
            raise ValueError("training record classes are invalid")
        if self.iterations <= 0 or self.iterations != len(self.loss_history):
            raise ValueError("training record iteration history is inconsistent")
        if not self.loss_history or any(not math.isfinite(value) for value in self.loss_history):
            raise ValueError("training record loss history must be finite")
        if not math.isfinite(self.final_loss) or self.final_loss != self.loss_history[-1]:
            raise ValueError("training record final loss is inconsistent")
        TrainingProvenance.from_dict({
            "fold_id": self.fold_id, "dataset_hash": self.dataset_hash, "train_hash": self.train_hash,
            "fit_start": self.fit_start, "fit_end": self.fit_end,
        })
        _sha256(self.preprocessor_hash, "preprocessor hash")

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_count": self.sample_count,
            "class_counts": [list(item) for item in self.class_counts],
            "loss_history": list(self.loss_history),
            "iterations": self.iterations,
            "converged": self.converged,
            "final_loss": self.final_loss,
            "fold_id": self.fold_id,
            "dataset_hash": self.dataset_hash,
            "train_hash": self.train_hash,
            "preprocessor_hash": self.preprocessor_hash,
            "fit_start": self.fit_start,
            "fit_end": self.fit_end,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> BinaryTrainingRecord:
        return cls(
            sample_count=_integer(payload["sample_count"]),
            class_counts=tuple((_integer(item[0]), _integer(item[1])) for item in _pairs(payload["class_counts"])),
            loss_history=tuple(_floats(payload["loss_history"])),
            iterations=_integer(payload["iterations"]),
            converged=_boolean(payload["converged"]),
            final_loss=_number(payload["final_loss"]),
            fold_id=str(payload["fold_id"]), dataset_hash=str(payload["dataset_hash"]),
            train_hash=str(payload["train_hash"]), preprocessor_hash=str(payload["preprocessor_hash"]),
            fit_start=str(payload["fit_start"]), fit_end=str(payload["fit_end"]),
        )


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

    def __post_init__(self) -> None:
        if not self.feature_order or len(self.feature_order) != len(set(self.feature_order)):
            raise ValueError("model feature order must be non-empty and unique")
        if len(self.feature_order) != len(self.coefficients):
            raise ValueError("model coefficient dimension mismatch")
        if any(not math.isfinite(value) for value in (*self.coefficients, self.intercept)):
            raise ValueError("model coefficients must be finite")
        if not math.isfinite(self.l2) or self.l2 <= 0.0:
            raise ValueError("formal model requires positive L2 regularization")
        if tuple(key for key, _ in self.class_weights) != (0, 1) or any(not math.isfinite(value) or value <= 0.0 for _, value in self.class_weights):
            raise ValueError("model class weights must be positive for both classes")
        if self.max_iterations <= 0 or self.tolerance <= 0.0 or self.learning_rate <= 0.0:
            raise ValueError("model convergence configuration is invalid")
        if len(self.classes) != 2 or len(set(self.classes)) != 2:
            raise ValueError("model classes must contain two distinct values")

    def predict_probability(self, values: Sequence[float]) -> float:
        if len(values) != len(self.coefficients):
            raise ValueError("model input dimension mismatch")
        if any(not math.isfinite(value) for value in values):
            raise ValueError("model input must be finite")
        score = self.intercept + sum(coefficient * float(value) for coefficient, value in zip(self.coefficients, values, strict=True))
        if not math.isfinite(score):
            raise ValueError("model score must be finite")
        return _sigmoid(score)

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_order": list(self.feature_order), "coefficients": list(self.coefficients),
            "intercept": self.intercept, "l2": self.l2,
            "class_weights": [[key, value] for key, value in self.class_weights],
            "max_iterations": self.max_iterations, "tolerance": self.tolerance,
            "learning_rate": self.learning_rate, "random_seed": self.random_seed,
            "classes": list(self.classes), "record": self.record.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> BinaryLogisticModel:
        classes = tuple(_strings(payload["classes"]))
        if len(classes) != 2:
            raise ValueError("serialized classes must contain two values")
        return cls(
            feature_order=tuple(_strings(payload["feature_order"])), coefficients=tuple(_floats(payload["coefficients"])),
            intercept=_number(payload["intercept"]), l2=_number(payload["l2"]),
            class_weights=tuple((_integer(item[0]), _number(item[1])) for item in _pairs(payload["class_weights"])),
            max_iterations=_integer(payload["max_iterations"]), tolerance=_number(payload["tolerance"]),
            learning_rate=_number(payload["learning_rate"]), random_seed=_integer(payload["random_seed"]),
            classes=classes, record=BinaryTrainingRecord.from_dict(_mapping(payload["record"])),
        )


@dataclass(frozen=True, slots=True)
class TwoStageTrainingRecord:
    input_count: int
    eligible_count: int
    excluded_ambiguous: int
    excluded_incomplete: int
    excluded_required_missing: int
    fold_id: str
    dataset_hash: str
    train_hash: str
    preprocessor_hash: str
    model_a_target: str = "TRADE_VS_NO_TRADE"
    model_b_target: str = "LONG_VS_SHORT_TRADE_ONLY"

    def __post_init__(self) -> None:
        if min(self.input_count, self.eligible_count, self.excluded_ambiguous, self.excluded_incomplete, self.excluded_required_missing) < 0:
            raise ValueError("two-stage training counts are invalid")
        if self.eligible_count > self.input_count:
            raise ValueError("two-stage eligible count is invalid")
        if self.model_a_target != "TRADE_VS_NO_TRADE" or self.model_b_target != "LONG_VS_SHORT_TRADE_ONLY":
            raise ValueError("two-stage targets are invalid")
        _sha256(self.dataset_hash, "dataset hash")
        _sha256(self.train_hash, "train hash")
        _sha256(self.preprocessor_hash, "preprocessor hash")

    def to_dict(self) -> dict[str, object]:
        return {
            "input_count": self.input_count, "eligible_count": self.eligible_count,
            "excluded_ambiguous": self.excluded_ambiguous, "excluded_incomplete": self.excluded_incomplete,
            "excluded_required_missing": self.excluded_required_missing,
            "fold_id": self.fold_id, "dataset_hash": self.dataset_hash, "train_hash": self.train_hash,
            "preprocessor_hash": self.preprocessor_hash,
            "model_a_target": self.model_a_target, "model_b_target": self.model_b_target,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> TwoStageTrainingRecord:
        return cls(
            input_count=_integer(payload["input_count"]), eligible_count=_integer(payload["eligible_count"]),
            excluded_ambiguous=_integer(payload["excluded_ambiguous"]), excluded_incomplete=_integer(payload["excluded_incomplete"]),
            excluded_required_missing=_integer(payload["excluded_required_missing"]),
            fold_id=str(payload["fold_id"]), dataset_hash=str(payload["dataset_hash"]),
            train_hash=str(payload["train_hash"]), preprocessor_hash=str(payload["preprocessor_hash"]),
            model_a_target=str(payload["model_a_target"]), model_b_target=str(payload["model_b_target"]),
        )


@dataclass(frozen=True, slots=True)
class TwoStageLogisticModel:
    trade_model: BinaryLogisticModel
    direction_model: BinaryLogisticModel
    record: TwoStageTrainingRecord
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.trade_model.feature_order != self.direction_model.feature_order:
            raise ValueError("two-stage feature order mismatch")
        if self.trade_model.classes != ("NO_TRADE", "TRADE") or self.direction_model.classes != ("SHORT", "LONG"):
            raise ValueError("two-stage classes are invalid")
        for binary in (self.trade_model, self.direction_model):
            if (
                binary.record.fold_id != self.record.fold_id
                or binary.record.dataset_hash != self.record.dataset_hash
                or binary.record.train_hash != self.record.train_hash
                or binary.record.preprocessor_hash != self.record.preprocessor_hash
            ):
                raise ValueError("two-stage training provenance mismatch")
        object.__setattr__(self, "content_hash", canonical_hash(self.to_dict()))

    def predict(self, values: Sequence[float]) -> ClassProbabilities:
        return combine_probabilities(
            p_trade=self.trade_model.predict_probability(values),
            p_long_given_trade=self.direction_model.predict_probability(values),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "trade_model": self.trade_model.to_dict(),
            "direction_model": self.direction_model.to_dict(),
            "record": self.record.to_dict(),
        }


def _fit_two_stage_logistic(
    samples: Sequence[ModelTrainingSample],
    *,
    feature_order: tuple[str, ...],
    provenance: TrainingProvenance,
    preprocessor_hash: str,
    input_count: int,
    excluded_required_missing: int,
    l2: float,
    class_weights: Mapping[int, float],
    max_iterations: int,
    tolerance: float,
    learning_rate: float,
    random_seed: int,
) -> TwoStageLogisticModel:
    eligible = tuple(sample for sample in samples if sample.is_complete and sample.label != "AMBIGUOUS")
    trade_samples = tuple(BinaryTrainingSample(sample.values, int(sample.label in ("LONG", "SHORT"))) for sample in eligible)
    direction_samples = tuple(BinaryTrainingSample(sample.values, int(sample.label == "LONG")) for sample in eligible if sample.label in ("LONG", "SHORT"))
    trade_model = _fit_binary_logistic(
        trade_samples, feature_order=feature_order, provenance=provenance,
        preprocessor_hash=preprocessor_hash, l2=l2, class_weights=class_weights,
        max_iterations=max_iterations, tolerance=tolerance, learning_rate=learning_rate,
        random_seed=random_seed, classes=("NO_TRADE", "TRADE"),
    )
    direction_model = _fit_binary_logistic(
        direction_samples, feature_order=feature_order, provenance=provenance,
        preprocessor_hash=preprocessor_hash, l2=l2, class_weights=class_weights,
        max_iterations=max_iterations, tolerance=tolerance, learning_rate=learning_rate,
        random_seed=random_seed, classes=("SHORT", "LONG"),
    )
    record = TwoStageTrainingRecord(
        input_count=input_count, eligible_count=len(eligible),
        excluded_ambiguous=sum(sample.label == "AMBIGUOUS" for sample in samples),
        excluded_incomplete=sum(not sample.is_complete for sample in samples),
        excluded_required_missing=excluded_required_missing,
        fold_id=provenance.fold_id, dataset_hash=provenance.dataset_hash,
        train_hash=provenance.train_hash, preprocessor_hash=preprocessor_hash,
    )
    return TwoStageLogisticModel(trade_model, direction_model, record)


def _fit_binary_logistic(
    samples: Sequence[BinaryTrainingSample],
    *,
    feature_order: tuple[str, ...],
    provenance: TrainingProvenance,
    preprocessor_hash: str,
    l2: float,
    class_weights: Mapping[int, float],
    max_iterations: int,
    tolerance: float,
    learning_rate: float,
    random_seed: int,
    classes: tuple[str, str],
) -> BinaryLogisticModel:
    if not samples:
        raise ValueError("logistic training requires samples")
    if not feature_order or len(feature_order) != len(set(feature_order)) or len(feature_order) > 45:
        raise ValueError("fixed feature order must contain at most 45 declared features")
    if not math.isfinite(l2) or l2 <= 0.0:
        raise ValueError("formal model requires positive L2 regularization")
    if max_iterations <= 0 or not math.isfinite(tolerance) or tolerance <= 0.0 or not math.isfinite(learning_rate) or learning_rate <= 0.0:
        raise ValueError("invalid logistic training configuration")
    if any(len(sample.values) != len(feature_order) for sample in samples):
        raise ValueError("training feature dimension mismatch")
    if {sample.target for sample in samples} != {0, 1}:
        raise ValueError("logistic training requires both classes")
    weights = {0: float(class_weights[0]), 1: float(class_weights[1])}
    if any(not math.isfinite(value) or value <= 0.0 for value in weights.values()):
        raise ValueError("class weights must be finite and positive")
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
        if max(abs(current - prior) for current, prior in zip((intercept, *coefficients), previous, strict=True)) <= tolerance:
            converged = True
            break
    record = BinaryTrainingRecord(
        sample_count=len(samples),
        class_counts=((0, sum(sample.target == 0 for sample in samples)), (1, sum(sample.target == 1 for sample in samples))),
        loss_history=tuple(history), iterations=len(history), converged=converged, final_loss=history[-1],
        fold_id=provenance.fold_id, dataset_hash=provenance.dataset_hash, train_hash=provenance.train_hash,
        preprocessor_hash=preprocessor_hash, fit_start=provenance.fit_start.isoformat(), fit_end=provenance.fit_end.isoformat(),
    )
    return BinaryLogisticModel(
        feature_order, tuple(coefficients), intercept, l2, tuple(sorted(weights.items())),
        max_iterations, tolerance, learning_rate, random_seed, classes, record,
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
    if not math.isfinite(score):
        raise ValueError("logistic score must be finite")
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
    if not isinstance(value, list):
        raise ValueError("expected number list")
    return [_number(item) for item in cast(list[object], value)]


def _pairs(value: object) -> list[list[object]]:
    if not isinstance(value, list) or not all(isinstance(item, list) and len(item) == 2 for item in value):
        raise ValueError("expected pair list")
    return cast(list[list[object]], value)


def _number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("expected finite number")
    return float(value)


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected integer")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected boolean")
    return value


def _sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be lowercase SHA-256")
