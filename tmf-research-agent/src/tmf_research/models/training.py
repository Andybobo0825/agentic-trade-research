from __future__ import annotations

import math
from dataclasses import dataclass

from tmf_research.models.logistic import ModelTrainingSample, TwoStageLogisticModel, _fit_two_stage_logistic
from tmf_research.models.provenance import (
    InnerTrainDataset,
    InnerValidationDataset,
    InnerValidationPredictions,
    FrozenDecisionPolicy,
    OuterTestDataset,
    OuterTestPredictions,
    _generated_prediction,
    _generated_predictions,
    _generated_outer_predictions,
    canonical_hash,
)
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
        if not _is_finite_real(self.l2) or self.l2 <= 0.0:
            raise ValueError("formal model requires positive L2 regularization")
        if (
            tuple(key for key, _ in self.class_weights) != (0, 1)
            or any(not _is_int(key) for key, _ in self.class_weights)
            or any(
                not _is_finite_real(value) or value <= 0.0
                for _, value in self.class_weights
            )
        ):
            raise ValueError("class weights must be finite and positive")
        if not _is_int(self.max_iterations) or self.max_iterations <= 0:
            raise ValueError("invalid fixed convergence configuration")
        if not _is_finite_real(self.tolerance) or self.tolerance <= 0.0:
            raise ValueError("invalid fixed convergence configuration")
        if not _is_finite_real(self.learning_rate) or self.learning_rate <= 0.0:
            raise ValueError("learning rate must be finite and positive")
        if not _is_int(self.random_seed):
            raise ValueError("random seed must be an exact integer")

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

    def predict_inner_validation(
        self,
        dataset: InnerValidationDataset,
    ) -> InnerValidationPredictions:
        if not isinstance(dataset, InnerValidationDataset):
            raise ValueError("only sealed inner-validation datasets can be scored")
        if dataset.manifest != self.preprocessor.provenance.manifest:
            raise ValueError("inner-validation parent training provenance mismatch")
        if self.model.record.provenance != self.preprocessor.provenance:
            raise ValueError("model training provenance mismatch")
        if self.model.record.preprocessor_hash != self.preprocessor.content_hash:
            raise ValueError("model preprocessor provenance mismatch")
        generated = []
        for row in dataset.rows:
            if tuple(row.features) != self.preprocessor.feature_order:
                raise ValueError("inner-validation feature order mismatch")
            transformed = self.preprocessor.transform(row.features)
            if not transformed.is_eligible:
                raise ValueError("inner-validation row is not eligible for model calibration")
            p_trade = self.model.trade_model.predict_probability(transformed.values)
            trade_outcome = int(row.label in ("LONG", "SHORT"))
            p_long = (
                self.model.direction_model.predict_probability(transformed.values)
                if trade_outcome
                else None
            )
            direction_outcome = int(row.label == "LONG") if trade_outcome else None
            generated.append(_generated_prediction(
                source_row=row,
                p_trade=p_trade,
                trade_outcome=trade_outcome,
                p_long_given_trade=p_long,
                direction_outcome=direction_outcome,
            ))
        return _generated_predictions(
            provenance=dataset.provenance,
            preprocessor_hash=self.preprocessor.content_hash,
            model_hash=self.model.content_hash,
            rows=generated,
        )

    def predict_outer_test(
        self,
        dataset: OuterTestDataset,
        calibration: object,
        policy: FrozenDecisionPolicy,
    ) -> OuterTestPredictions:
        from tmf_research.models.calibration import TwoStageCalibrationSelection

        if not isinstance(dataset, OuterTestDataset):
            raise TypeError("outer scoring requires the sealed outer-test capability")
        if not isinstance(calibration, TwoStageCalibrationSelection):
            raise TypeError("outer scoring requires sealed inner-validation calibration")
        if not isinstance(policy, FrozenDecisionPolicy):
            raise TypeError("outer scoring requires a frozen decision policy")
        if (
            dataset.manifest != self.preprocessor.provenance.manifest
            or calibration.calibrator.provenance != self.preprocessor.provenance
            or calibration.calibrator.preprocessor_hash != self.preprocessor.content_hash
            or calibration.calibrator.model_hash != self.model.content_hash
        ):
            raise ValueError("outer model/calibration/fold provenance mismatch")
        calibration_hash = canonical_hash(calibration.calibrator.to_dict())
        if policy.calibration_hash != calibration_hash:
            raise ValueError("outer decision policy does not bind exact calibration")
        values: list[tuple[float, float]] = []
        for row in dataset.rows:
            if tuple(row.features) != self.preprocessor.feature_order:
                raise ValueError("outer feature order mismatch")
            transformed = self.preprocessor.transform(row.features)
            if not transformed.is_eligible:
                values.append((0.0, 0.5))
                continue
            values.append(calibration.calibrator.calibrate(
                self.model.trade_model.predict_probability(transformed.values),
                self.model.direction_model.predict_probability(transformed.values),
            ))
        return _generated_outer_predictions(
            dataset=dataset,
            model_hash=self.model.content_hash,
            calibration_hash=calibration_hash,
            policy=policy,
            values=values,
        )


def train_phase4_model(dataset: InnerTrainDataset, specification: Phase4TrainingSpec) -> Phase4TrainingResult:
    if not isinstance(dataset, InnerTrainDataset):
        raise ValueError("training requires a materialized inner-train capability")
    expected_order = specification.raw_feature_order
    if any(tuple(row.features) != expected_order for row in dataset.rows):
        raise ValueError("inner-train feature order does not match declared formal roles")
    return _fit_phase4(dataset, specification)


def _train_phase4_feature_subset(
    dataset: InnerTrainDataset,
    specification: Phase4TrainingSpec,
) -> Phase4TrainingResult:
    if not isinstance(dataset, InnerTrainDataset):
        raise ValueError("subset training requires a materialized inner-train capability")
    expected = set(specification.raw_feature_order)
    if not expected or any(not expected.issubset(row.features) for row in dataset.rows):
        raise ValueError("subset training features do not belong to exact issued rows")
    return _fit_phase4(dataset, specification)


def _fit_phase4(
    dataset: InnerTrainDataset,
    specification: Phase4TrainingSpec,
) -> Phase4TrainingResult:
    expected_order = specification.raw_feature_order
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


def _is_finite_real(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
