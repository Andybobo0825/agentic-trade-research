from __future__ import annotations

import math
from dataclasses import dataclass

from tmf_research.models.logistic import ModelTrainingSample, TwoStageLogisticModel, _fit_two_stage_logistic
from tmf_research.models.provenance import InnerTrainDataset, canonical_hash
from tmf_research.models.scaler import FoldPreprocessor


@dataclass(frozen=True, slots=True)
class InteractionRole:
    name: str
    inputs: tuple[str, str]
    mechanism: str
    ablation_evidence: str

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.inputs) != 2 or len(set(self.inputs)) != 2:
            raise ValueError("interaction requires a name and two distinct inputs")
        if not self.mechanism.strip() or not self.ablation_evidence.strip():
            raise ValueError("interaction requires mechanism and ablation evidence")


@dataclass(frozen=True, slots=True)
class Phase4TrainingSpec:
    primary_features: tuple[str, ...]
    required_features: tuple[str, ...]
    interactions: tuple[InteractionRole, ...] = ()
    large_trade_features: tuple[str, ...] = ()
    l2: float = 1.0
    class_weights: tuple[tuple[int, float], ...] = ((0, 1.0), (1, 1.0))
    max_iterations: int = 500
    tolerance: float = 1e-9
    learning_rate: float = 0.1
    random_seed: int = 0

    def __post_init__(self) -> None:
        primary = set(self.primary_features)
        interaction_names = {item.name for item in self.interactions}
        if not self.primary_features or len(primary) != len(self.primary_features) or len(primary) > 30:
            raise ValueError("formal model requires 1 to 30 unique primary features")
        if len(interaction_names) != len(self.interactions) or interaction_names & primary or len(self.interactions) > 5:
            raise ValueError("formal model permits at most 5 unique declared interactions")
        if any(not set(item.inputs).issubset(primary) for item in self.interactions):
            raise ValueError("interaction inputs must be declared primary features")
        if not set(self.required_features).issubset(self.raw_feature_order):
            raise ValueError("required features must be declared")
        if len(self.optional_features) > 10:
            raise ValueError("formal model permits at most 10 missing indicators")
        if not set(self.large_trade_features).issubset(self.raw_feature_order):
            raise ValueError("large-trade features must be declared")
        if not math.isfinite(self.l2) or self.l2 <= 0.0:
            raise ValueError("formal model requires positive L2 regularization")
        if tuple(key for key, _ in self.class_weights) != (0, 1) or any(not math.isfinite(value) or value <= 0.0 for _, value in self.class_weights):
            raise ValueError("class weights must be finite and positive")
        if self.max_iterations <= 0 or not math.isfinite(self.tolerance) or self.tolerance <= 0.0:
            raise ValueError("invalid fixed convergence configuration")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0.0:
            raise ValueError("learning rate must be finite and positive")

    @property
    def raw_feature_order(self) -> tuple[str, ...]:
        return self.primary_features + tuple(item.name for item in self.interactions)

    @property
    def optional_features(self) -> tuple[str, ...]:
        return tuple(name for name in self.primary_features if name not in self.required_features)

    @property
    def preprocessor_required_features(self) -> tuple[str, ...]:
        return self.required_features + tuple(item.name for item in self.interactions)

    @property
    def content_hash(self) -> str:
        return canonical_hash({
            "primary_features": list(self.primary_features),
            "required_features": list(self.required_features),
            "interactions": [
                {"name": item.name, "inputs": list(item.inputs), "mechanism": item.mechanism, "ablation_evidence": item.ablation_evidence}
                for item in self.interactions
            ],
            "large_trade_features": list(self.large_trade_features),
            "l2": self.l2, "class_weights": [list(item) for item in self.class_weights],
            "max_iterations": self.max_iterations, "tolerance": self.tolerance,
            "learning_rate": self.learning_rate, "random_seed": self.random_seed,
        })


@dataclass(frozen=True, slots=True)
class Phase4TrainingResult:
    preprocessor: FoldPreprocessor
    model: TwoStageLogisticModel
    specification_hash: str


def train_phase4_model(dataset: InnerTrainDataset, specification: Phase4TrainingSpec) -> Phase4TrainingResult:
    expected_order = specification.raw_feature_order
    if any(tuple(row.features) != expected_order for row in dataset.rows):
        raise ValueError("inner-train feature order does not match declared formal roles")
    preprocessor = FoldPreprocessor.fit_inner_train(
        dataset,
        feature_order=expected_order,
        required_features=specification.preprocessor_required_features,
        large_trade_features=specification.large_trade_features,
    )
    samples: list[ModelTrainingSample] = []
    excluded_required_missing = 0
    for row in dataset.rows:
        transformed = preprocessor.transform(row.features)
        if not transformed.is_eligible:
            excluded_required_missing += 1
            continue
        samples.append(ModelTrainingSample(transformed.values, row.label, row.is_complete))
    weights = dict(specification.class_weights)
    model = _fit_two_stage_logistic(
        tuple(samples),
        feature_order=preprocessor.output_feature_order,
        provenance=dataset.provenance,
        preprocessor_hash=preprocessor.content_hash,
        input_count=len(dataset.rows),
        excluded_required_missing=excluded_required_missing,
        l2=specification.l2,
        class_weights=weights,
        max_iterations=specification.max_iterations,
        tolerance=specification.tolerance,
        learning_rate=specification.learning_rate,
        random_seed=specification.random_seed,
    )
    return Phase4TrainingResult(preprocessor, model, specification.content_hash)
