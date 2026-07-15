from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from tmf_research.models.provenance import (
    InnerValidationPredictions,
    InnerValidationProvenance,
    TrainingProvenance,
    validate_sha256,
)


class Calibrator(Protocol):
    @property
    def method(self) -> str: ...

    def calibrate(self, probability: float) -> float: ...

    def to_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_probability: float | None
    observed_rate: float | None
    mean_net_return: float | None
    sufficient: bool


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    expected_value: float

    def __post_init__(self) -> None:
        if any(
            not math.isfinite(value)
            for value in (
                self.brier_score,
                self.log_loss,
                self.expected_calibration_error,
                self.expected_value,
            )
        ):
            raise ValueError("calibration metrics must be finite")
        if self.brier_score < 0.0 or self.log_loss < 0.0 or self.expected_calibration_error < 0.0:
            raise ValueError("calibration loss/error metrics must be non-negative")

    @property
    def sort_key(self) -> tuple[float, float, float, float]:
        return (self.brier_score, self.log_loss, self.expected_calibration_error, -self.expected_value)


@dataclass(frozen=True, slots=True)
class IdentityCalibrator:
    method: str = "UNCALIBRATED"

    def __post_init__(self) -> None:
        if self.method != "UNCALIBRATED":
            raise ValueError("invalid uncalibrated contract")

    def calibrate(self, probability: float) -> float:
        return _bounded(probability)

    def to_dict(self) -> dict[str, object]:
        return {"method": self.method}


@dataclass(frozen=True, slots=True)
class PlattCalibrator:
    coefficient: float
    intercept: float
    method: str = "PLATT"

    def __post_init__(self) -> None:
        if self.method != "PLATT" or not math.isfinite(self.coefficient) or not math.isfinite(self.intercept):
            raise ValueError("Platt parameters must be finite")

    def calibrate(self, probability: float) -> float:
        clipped = min(1.0 - 1e-12, max(1e-12, _bounded(probability)))
        score = self.intercept + self.coefficient * math.log(clipped / (1.0 - clipped))
        return _sigmoid(score)

    def to_dict(self) -> dict[str, object]:
        return {"method": self.method, "coefficient": self.coefficient, "intercept": self.intercept}


@dataclass(frozen=True, slots=True)
class IsotonicCalibrator:
    upper_bounds: tuple[float, ...]
    values: tuple[float, ...]
    method: str = "ISOTONIC"

    def __post_init__(self) -> None:
        if self.method != "ISOTONIC" or not self.upper_bounds or len(self.upper_bounds) != len(self.values):
            raise ValueError("isotonic calibration requires non-empty paired state")
        if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in (*self.upper_bounds, *self.values)):
            raise ValueError("isotonic state must be bounded and finite")
        if any(current <= previous for previous, current in zip(self.upper_bounds, self.upper_bounds[1:])):
            raise ValueError("isotonic upper bounds must be strictly increasing")
        if any(current < previous for previous, current in zip(self.values, self.values[1:])):
            raise ValueError("isotonic values must be nondecreasing")

    def calibrate(self, probability: float) -> float:
        bounded = _bounded(probability)
        for upper, value in zip(self.upper_bounds, self.values, strict=True):
            if bounded <= upper:
                return value
        return self.values[-1]

    def to_dict(self) -> dict[str, object]:
        return {"method": self.method, "upper_bounds": list(self.upper_bounds), "values": list(self.values)}


@dataclass(frozen=True, slots=True)
class CalibrationCandidate:
    method: str
    calibrator: Calibrator
    metrics: CalibrationMetrics
    bins: tuple[CalibrationBin, ...]


@dataclass(frozen=True, slots=True)
class BinaryCalibrationSelection:
    selected: CalibrationCandidate
    candidates: tuple[CalibrationCandidate, ...]
    insufficient_evidence: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class TwoStageCalibrator:
    trade_calibrator: Calibrator
    direction_calibrator: Calibrator
    validation_provenance: InnerValidationProvenance
    preprocessor_hash: str
    model_hash: str
    validation_hash: str
    insufficient_evidence: bool

    def __post_init__(self) -> None:
        validate_sha256(self.preprocessor_hash, "preprocessor hash")
        validate_sha256(self.model_hash, "model hash")
        validate_sha256(self.validation_hash, "validation hash")

    @property
    def provenance(self) -> TrainingProvenance:
        return self.validation_provenance.parent_provenance

    def calibrate(self, p_trade: float, p_long_given_trade: float) -> tuple[float, float]:
        return (
            self.trade_calibrator.calibrate(p_trade),
            self.direction_calibrator.calibrate(p_long_given_trade),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "trade": self.trade_calibrator.to_dict(), "direction": self.direction_calibrator.to_dict(),
            "validation_provenance": self.validation_provenance.to_dict(),
            "preprocessor_hash": self.preprocessor_hash,
            "model_hash": self.model_hash, "validation_hash": self.validation_hash,
            "insufficient_evidence": self.insufficient_evidence,
        }

    @classmethod
    def _from_dict(
        cls,
        payload: Mapping[str, object],
        *,
        deserialization_authority: object,
    ) -> TwoStageCalibrator:
        return cls(
            trade_calibrator=calibrator_from_dict(_mapping(payload["trade"])),
            direction_calibrator=calibrator_from_dict(_mapping(payload["direction"])),
            validation_provenance=InnerValidationProvenance._from_dict(
                _mapping(payload["validation_provenance"]),
                deserialization_authority=deserialization_authority,
            ),
            preprocessor_hash=str(payload["preprocessor_hash"]), model_hash=str(payload["model_hash"]),
            validation_hash=str(payload["validation_hash"]), insufficient_evidence=_boolean(payload["insufficient_evidence"]),
        )


@dataclass(frozen=True, slots=True)
class TwoStageCalibrationSelection:
    calibrator: TwoStageCalibrator
    trade: BinaryCalibrationSelection
    direction: BinaryCalibrationSelection
    candidate_eligible: bool


def fit_two_stage_calibrators(
    predictions: InnerValidationPredictions,
    *,
    bin_count: int = 10,
    minimum_bin_size: int = 20,
) -> TwoStageCalibrationSelection:
    if not isinstance(predictions, InnerValidationPredictions):
        raise ValueError("calibration requires sealed generated inner-validation predictions")
    trade_samples = tuple(
        _CalibrationSample(row.p_trade, row.trade_outcome, row.net_return)
        for row in predictions.rows
    )
    direction_samples = tuple(
        _CalibrationSample(row.p_long_given_trade, row.direction_outcome, row.net_return)
        for row in predictions.rows
        if row.p_long_given_trade is not None and row.direction_outcome is not None
    )
    trade = _fit_and_select_binary(trade_samples, bin_count, minimum_bin_size)
    direction = _fit_and_select_binary(direction_samples, bin_count, minimum_bin_size)
    insufficient = trade.insufficient_evidence or direction.insufficient_evidence
    calibrator = TwoStageCalibrator(
        trade.selected.calibrator, direction.selected.calibrator, predictions.provenance,
        predictions.preprocessor_hash, predictions.model_hash, predictions.validation_hash, insufficient,
    )
    return TwoStageCalibrationSelection(calibrator, trade, direction, not insufficient)


def calibrator_from_dict(payload: Mapping[str, object]) -> Calibrator:
    method = str(payload["method"])
    if method == "UNCALIBRATED":
        return IdentityCalibrator()
    if method == "PLATT":
        return PlattCalibrator(_number(payload["coefficient"]), _number(payload["intercept"]))
    if method == "ISOTONIC":
        return IsotonicCalibrator(tuple(_floats(payload["upper_bounds"])), tuple(_floats(payload["values"])))
    raise ValueError("unknown calibration method")


@dataclass(frozen=True, slots=True)
class _CalibrationSample:
    probability: float
    outcome: int
    net_return: float

    def __post_init__(self) -> None:
        _bounded(self.probability)
        if self.outcome not in (0, 1):
            raise ValueError("calibration outcome must be binary")
        if not math.isfinite(self.net_return):
            raise ValueError("calibration return must be finite")


def _fit_and_select_binary(
    samples: Sequence[_CalibrationSample],
    bin_count: int,
    minimum_bin_size: int,
) -> BinaryCalibrationSelection:
    if not samples or bin_count <= 0 or minimum_bin_size <= 0:
        raise ValueError("invalid calibration evidence configuration")
    if {sample.outcome for sample in samples} != {0, 1}:
        raise ValueError("calibration requires both outcomes")
    calibrators: tuple[Calibrator, ...] = (IdentityCalibrator(), _fit_platt(samples), _fit_isotonic(samples))
    candidates = tuple(_evaluate(calibrator, samples, bin_count, minimum_bin_size) for calibrator in calibrators)
    selected = min(candidates, key=lambda candidate: candidate.metrics.sort_key)
    insufficient = any(item.count > 0 and not item.sufficient for item in selected.bins)
    return BinaryCalibrationSelection(selected, candidates, insufficient, "SPARSE_CALIBRATION_BIN" if insufficient else None)


def _fit_platt(samples: Sequence[_CalibrationSample]) -> PlattCalibrator:
    values = tuple(math.log(min(1.0 - 1e-12, max(1e-12, item.probability)) / (1.0 - min(1.0 - 1e-12, max(1e-12, item.probability)))) for item in samples)
    coefficient = 0.0
    intercept = 0.0
    for _ in range(1000):
        gradient_coefficient = 0.0
        gradient_intercept = 0.0
        for value, sample in zip(values, samples, strict=True):
            error = _sigmoid(intercept + coefficient * value) - sample.outcome
            gradient_intercept += error
            gradient_coefficient += error * value
        intercept -= 0.05 * gradient_intercept / len(samples)
        coefficient -= 0.05 * (gradient_coefficient / len(samples) + 1e-6 * coefficient)
    return PlattCalibrator(coefficient, intercept)


def _fit_isotonic(samples: Sequence[_CalibrationSample]) -> IsotonicCalibrator:
    ordered = sorted(samples, key=lambda sample: (sample.probability, sample.outcome, sample.net_return))
    grouped: list[list[float]] = []
    for sample in ordered:
        if grouped and sample.probability == grouped[-1][0]:
            grouped[-1][1] += sample.outcome
            grouped[-1][2] += 1.0
        else:
            grouped.append([sample.probability, float(sample.outcome), 1.0])
    blocks: list[list[float]] = []
    for probability, outcome_total, count in grouped:
        blocks.append([probability, probability, outcome_total, count])
        while len(blocks) >= 2 and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]:
            right = blocks.pop()
            left = blocks.pop()
            blocks.append([left[0], right[1], left[2] + right[2], left[3] + right[3]])
    return IsotonicCalibrator(tuple(block[1] for block in blocks), tuple(block[2] / block[3] for block in blocks))


def _evaluate(calibrator: Calibrator, samples: Sequence[_CalibrationSample], bin_count: int, minimum_bin_size: int) -> CalibrationCandidate:
    probabilities = tuple(calibrator.calibrate(sample.probability) for sample in samples)
    epsilon = 1e-15
    brier = sum((probability - sample.outcome) ** 2 for probability, sample in zip(probabilities, samples, strict=True)) / len(samples)
    log_loss = -sum(
        sample.outcome * math.log(min(1.0 - epsilon, max(epsilon, probability)))
        + (1 - sample.outcome) * math.log(min(1.0 - epsilon, max(epsilon, 1.0 - probability)))
        for probability, sample in zip(probabilities, samples, strict=True)
    ) / len(samples)
    bins: list[CalibrationBin] = []
    ece = 0.0
    for index in range(bin_count):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        members = tuple(
            (probability, sample) for probability, sample in zip(probabilities, samples, strict=True)
            if lower <= probability <= upper and (index == bin_count - 1 or probability < upper)
        )
        if not members:
            bins.append(CalibrationBin(lower, upper, 0, None, None, None, False))
            continue
        mean_probability = sum(item[0] for item in members) / len(members)
        observed = sum(item[1].outcome for item in members) / len(members)
        mean_return = sum(item[1].net_return for item in members) / len(members)
        ece += len(members) / len(samples) * abs(mean_probability - observed)
        bins.append(CalibrationBin(lower, upper, len(members), mean_probability, observed, mean_return, len(members) >= minimum_bin_size))
    expected_value = sum(probability * sample.net_return for probability, sample in zip(probabilities, samples, strict=True)) / len(samples)
    return CalibrationCandidate(calibrator.method, calibrator, CalibrationMetrics(brier, log_loss, ece, expected_value), tuple(bins))


def _bounded(probability: float) -> float:
    if not math.isfinite(probability) or probability < 0.0 or probability > 1.0:
        raise ValueError("probability must be finite and between zero and one")
    return probability


def _sigmoid(score: float) -> float:
    if not math.isfinite(score):
        raise ValueError("calibration score must be finite")
    if score >= 0.0:
        return 1.0 / (1.0 + math.exp(-score))
    exponential = math.exp(score)
    return exponential / (1.0 + exponential)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expected mapping")
    return cast(Mapping[str, object], value)


def _floats(value: object) -> list[float]:
    if not isinstance(value, list):
        raise ValueError("expected number list")
    return [_number(item) for item in cast(list[object], value)]


def _number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("expected finite number")
    return float(value)


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected boolean")
    return value
