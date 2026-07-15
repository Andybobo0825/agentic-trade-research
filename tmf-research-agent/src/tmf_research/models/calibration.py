from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from tmf_research.models.logistic import BinaryTrainingSample, fit_binary_logistic


class Calibrator(Protocol):
    @property
    def method(self) -> str: ...

    def calibrate(self, probability: float) -> float: ...

    def to_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    probability: float
    outcome: int
    net_return: float

    def __post_init__(self) -> None:
        if self.probability < 0.0 or self.probability > 1.0:
            raise ValueError("probability must be between zero and one")
        if self.outcome not in (0, 1):
            raise ValueError("calibration outcome must be binary")


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

    @property
    def sort_key(self) -> tuple[float, float, float, float]:
        return (self.brier_score, self.log_loss, self.expected_calibration_error, -self.expected_value)


@dataclass(frozen=True, slots=True)
class IdentityCalibrator:
    method: str = "UNCALIBRATED"
    fit_scope: str = "INNER_VALIDATION"

    def calibrate(self, probability: float) -> float:
        return _bounded(probability)

    def to_dict(self) -> dict[str, object]:
        return {"method": self.method, "fit_scope": self.fit_scope}


@dataclass(frozen=True, slots=True)
class PlattCalibrator:
    coefficient: float
    intercept: float
    method: str = "PLATT"
    fit_scope: str = "INNER_VALIDATION"

    def calibrate(self, probability: float) -> float:
        clipped = min(1.0 - 1e-12, max(1e-12, probability))
        logit = math.log(clipped / (1.0 - clipped))
        score = self.intercept + self.coefficient * logit
        if score >= 0.0:
            return 1.0 / (1.0 + math.exp(-score))
        exponential = math.exp(score)
        return exponential / (1.0 + exponential)

    def to_dict(self) -> dict[str, object]:
        return {"method": self.method, "fit_scope": self.fit_scope, "coefficient": self.coefficient, "intercept": self.intercept}


@dataclass(frozen=True, slots=True)
class IsotonicCalibrator:
    upper_bounds: tuple[float, ...]
    values: tuple[float, ...]
    method: str = "ISOTONIC"
    fit_scope: str = "INNER_VALIDATION"

    def calibrate(self, probability: float) -> float:
        bounded = _bounded(probability)
        for upper, value in zip(self.upper_bounds, self.values, strict=True):
            if bounded <= upper:
                return value
        return self.values[-1]

    def to_dict(self) -> dict[str, object]:
        return {"method": self.method, "fit_scope": self.fit_scope, "upper_bounds": list(self.upper_bounds), "values": list(self.values)}


@dataclass(frozen=True, slots=True)
class CalibrationCandidate:
    method: str
    calibrator: Calibrator
    metrics: CalibrationMetrics
    bins: tuple[CalibrationBin, ...]


@dataclass(frozen=True, slots=True)
class CalibrationSelection:
    selected: CalibrationCandidate
    candidates: tuple[CalibrationCandidate, ...]
    insufficient_evidence: bool
    reason: str | None
    fit_scope: str = "INNER_VALIDATION"


def fit_and_select_calibrator(
    samples: Sequence[CalibrationSample],
    *,
    scope: str,
    bin_count: int = 10,
    minimum_bin_size: int = 20,
) -> CalibrationSelection:
    if scope != "INNER_VALIDATION":
        raise ValueError("calibrator fit scope must be INNER_VALIDATION")
    if not samples or bin_count <= 0 or minimum_bin_size <= 0:
        raise ValueError("invalid calibration evidence configuration")
    if {sample.outcome for sample in samples} != {0, 1}:
        raise ValueError("calibration requires both outcomes")
    calibrators: tuple[Calibrator, ...] = (
        IdentityCalibrator(),
        _fit_platt(samples),
        _fit_isotonic(samples),
    )
    candidates = tuple(_evaluate(calibrator, samples, bin_count, minimum_bin_size) for calibrator in calibrators)
    selected = min(candidates, key=lambda candidate: candidate.metrics.sort_key)
    insufficient = any(
        calibration_bin.count > 0 and not calibration_bin.sufficient
        for calibration_bin in selected.bins
    )
    return CalibrationSelection(
        selected=selected, candidates=candidates, insufficient_evidence=insufficient,
        reason="SPARSE_CALIBRATION_BIN" if insufficient else None,
    )


def calibrator_from_dict(payload: Mapping[str, object]) -> Calibrator:
    method = str(payload["method"])
    scope = str(payload.get("fit_scope", "INNER_VALIDATION"))
    if scope != "INNER_VALIDATION":
        raise ValueError("serialized calibrator scope mismatch")
    if method == "UNCALIBRATED":
        return IdentityCalibrator(fit_scope=scope)
    if method == "PLATT":
        return PlattCalibrator(_number(payload["coefficient"]), _number(payload["intercept"]), fit_scope=scope)
    if method == "ISOTONIC":
        return IsotonicCalibrator(tuple(_floats(payload["upper_bounds"])), tuple(_floats(payload["values"])), fit_scope=scope)
    raise ValueError("unknown calibration method")


def _fit_platt(samples: Sequence[CalibrationSample]) -> PlattCalibrator:
    training = tuple(
        BinaryTrainingSample((math.log(clipped / (1.0 - clipped)),), sample.outcome)
        for sample in samples
        for clipped in (min(1.0 - 1e-12, max(1e-12, sample.probability)),)
    )
    model = fit_binary_logistic(
        training, feature_order=("uncalibrated_logit",), l2=1e-6,
        max_iterations=1000, tolerance=1e-10, learning_rate=0.05,
    )
    return PlattCalibrator(model.coefficients[0], model.intercept)


def _fit_isotonic(samples: Sequence[CalibrationSample]) -> IsotonicCalibrator:
    ordered = sorted(samples, key=lambda sample: (sample.probability, sample.outcome, sample.net_return))
    blocks: list[list[float]] = []
    for sample in ordered:
        blocks.append([sample.probability, sample.probability, float(sample.outcome), 1.0])
        while len(blocks) >= 2 and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]:
            right = blocks.pop()
            left = blocks.pop()
            blocks.append([left[0], right[1], left[2] + right[2], left[3] + right[3]])
    return IsotonicCalibrator(
        upper_bounds=tuple(block[1] for block in blocks),
        values=tuple(block[2] / block[3] for block in blocks),
    )


def _evaluate(calibrator: Calibrator, samples: Sequence[CalibrationSample], bin_count: int, minimum_bin_size: int) -> CalibrationCandidate:
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
    metrics = CalibrationMetrics(brier, log_loss, ece, expected_value)
    return CalibrationCandidate(calibrator.method, calibrator, metrics, tuple(bins))


def _bounded(probability: float) -> float:
    if probability < 0.0 or probability > 1.0:
        raise ValueError("probability must be between zero and one")
    return probability


def _floats(value: object) -> list[float]:
    if not isinstance(value, list) or not all(isinstance(item, (int, float)) for item in value):
        raise ValueError("expected number list")
    return [_number(item) for item in cast(list[object], value)]


def _number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("expected number")
    return float(value)
