from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from tmf_research.models.imputer import MedianImputer
from tmf_research.models.provenance import InnerTrainDataset, TrainingProvenance, canonical_hash


@dataclass(frozen=True, slots=True)
class StandardScaler:
    feature_order: tuple[str, ...]
    means: tuple[float, ...]
    standard_deviations: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.feature_order) != len(self.means) or len(self.means) != len(self.standard_deviations):
            raise ValueError("scaler dimension mismatch")
        if any(not math.isfinite(value) for value in self.means):
            raise ValueError("scaler means must be finite")
        if any(value <= 0.0 or not math.isfinite(value) for value in self.standard_deviations):
            raise ValueError("scaler deviation must be finite and positive")

    @property
    def dimension(self) -> int:
        return len(self.feature_order)

    def transform(self, values: Sequence[float]) -> tuple[float, ...]:
        if len(values) != self.dimension:
            raise ValueError("scaler dimension mismatch")
        if any(not math.isfinite(value) for value in values):
            raise ValueError("scaler input must be finite")
        transformed = tuple(
            (float(value) - mean) / deviation
            for value, mean, deviation in zip(
                values,
                self.means,
                self.standard_deviations,
                strict=True,
            )
        )
        if any(not math.isfinite(value) for value in transformed):
            raise ValueError("scaler output must be finite")
        return transformed


@dataclass(frozen=True, slots=True)
class OutlierLimits:
    limits: tuple[tuple[str, float, float], ...]

    def __post_init__(self) -> None:
        if any(not math.isfinite(lower) or not math.isfinite(upper) or upper < lower for _, lower, upper in self.limits):
            raise ValueError("outlier limits must be finite and ordered")

    def clip(self, feature_order: tuple[str, ...], values: Sequence[float]) -> tuple[float, ...]:
        if any(not math.isfinite(value) for value in values):
            raise ValueError("outlier input must be finite")
        by_name = {name: (lower, upper) for name, lower, upper in self.limits}
        if set(by_name) != set(feature_order):
            raise ValueError("outlier feature order mismatch")
        return tuple(min(by_name[name][1], max(by_name[name][0], float(value))) for name, value in zip(feature_order, values, strict=True))


@dataclass(frozen=True, slots=True)
class LargeTradeThresholds:
    thresholds: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) for _, value in self.thresholds):
            raise ValueError("large-trade thresholds must be finite")


@dataclass(frozen=True, slots=True)
class PreprocessingResult:
    values: tuple[float, ...]
    output_feature_order: tuple[str, ...]
    is_eligible: bool
    signal: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FoldPreprocessor:
    imputer: MedianImputer
    scaler: StandardScaler
    outlier_limits: OutlierLimits
    large_trade_thresholds: LargeTradeThresholds
    provenance: TrainingProvenance
    content_hash: str

    def __post_init__(self) -> None:
        if self.imputer.provenance != self.provenance:
            raise ValueError("imputer provenance mismatch")
        if self.scaler.feature_order != self.imputer.output_feature_order:
            raise ValueError("scaler and imputer feature order mismatch")

    @property
    def feature_order(self) -> tuple[str, ...]:
        return self.imputer.feature_order

    @property
    def output_feature_order(self) -> tuple[str, ...]:
        return self.imputer.output_feature_order

    @classmethod
    def fit_inner_train(
        cls,
        dataset: InnerTrainDataset,
        *,
        feature_order: tuple[str, ...],
        required_features: tuple[str, ...],
        large_trade_features: tuple[str, ...] = (),
        lower_quantile: float = 0.01,
        upper_quantile: float = 0.99,
        large_trade_quantile: float = 0.95,
    ) -> FoldPreprocessor:
        if not 0.0 <= lower_quantile < upper_quantile <= 1.0 or not 0.0 <= large_trade_quantile <= 1.0:
            raise ValueError("invalid inner-train quantile")
        if not set(large_trade_features).issubset(feature_order):
            raise ValueError("large trade features must belong to feature order")
        imputer = MedianImputer.fit_inner_train(dataset, feature_order=feature_order, required_features=required_features)
        complete_train = tuple(
            result.values
            for row in dataset.rows
            for result in (imputer.transform(row.features),)
            if result.is_eligible and row.is_complete and row.label != "AMBIGUOUS"
        )
        if not complete_train:
            raise ValueError("preprocessor requires eligible inner-train rows")
        limits = tuple(
            (name, _quantile(sorted(row[index] for row in complete_train), lower_quantile), _quantile(sorted(row[index] for row in complete_train), upper_quantile))
            for index, name in enumerate(feature_order)
        )
        outliers = OutlierLimits(limits)
        clipped = tuple(outliers.clip(feature_order, row[: len(feature_order)]) + row[len(feature_order) :] for row in complete_train)
        means = tuple(sum(row[index] for row in clipped) / len(clipped) for index in range(imputer.output_dimension))
        deviations = tuple(
            math.sqrt(sum((row[index] - means[index]) ** 2 for row in clipped) / len(clipped)) or 1.0
            for index in range(len(means))
        )
        scaler = StandardScaler(imputer.output_feature_order, means, deviations)
        thresholds = LargeTradeThresholds(tuple(
            (name, _quantile(sorted(_present_values(dataset, name)), large_trade_quantile))
            for name in large_trade_features
        ))
        payload = _state_payload(imputer, scaler, outliers, thresholds, dataset.provenance)
        return cls(imputer, scaler, outliers, thresholds, dataset.provenance, canonical_hash(payload))

    def transform(self, row: Mapping[str, float | None]) -> PreprocessingResult:
        imputed = self.imputer.transform(row)
        if not imputed.is_eligible:
            return PreprocessingResult((), self.output_feature_order, False, "NO_TRADE", imputed.reasons)
        original_dimension = len(self.feature_order)
        try:
            clipped = self.outlier_limits.clip(
                self.feature_order,
                imputed.values[:original_dimension],
            ) + imputed.values[original_dimension:]
            scaled = self.scaler.transform(clipped)
        except (ArithmeticError, ValueError):
            return PreprocessingResult(
                (),
                self.output_feature_order,
                False,
                "NO_TRADE",
                ("NONFINITE_TRANSFORM",),
            )
        if any(not math.isfinite(value) for value in scaled):
            return PreprocessingResult((), self.output_feature_order, False, "NO_TRADE", ("NONFINITE_TRANSFORM",))
        return PreprocessingResult(scaled, self.output_feature_order, True, None, ())

    def to_dict(self) -> dict[str, object]:
        payload = _state_payload(self.imputer, self.scaler, self.outlier_limits, self.large_trade_thresholds, self.provenance)
        payload["content_hash"] = self.content_hash
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> FoldPreprocessor:
        imputer = MedianImputer.from_dict(_mapping(payload["imputer"]))
        scaler_payload = _mapping(payload["scaler"])
        scaler_feature_order = tuple(_strings(scaler_payload["feature_order"]))
        scaler_means = tuple(_floats(scaler_payload["means"]))
        scaler_deviations = tuple(_floats(scaler_payload["standard_deviations"]))
        if _integer(scaler_payload["dimension"]) != len(scaler_feature_order):
            raise ValueError("declared scaler dimension mismatch")
        outlier_payload = _mapping(payload["outlier_limits"])
        large_payload = _mapping(payload["large_trade_thresholds"])
        instance = cls(
            imputer=imputer,
            scaler=StandardScaler(
                scaler_feature_order,
                scaler_means,
                scaler_deviations,
            ),
            outlier_limits=OutlierLimits(tuple((str(item[0]), _number(item[1]), _number(item[2])) for item in _triples(outlier_payload["limits"]))),
            large_trade_thresholds=LargeTradeThresholds(tuple((str(item[0]), _number(item[1])) for item in _pairs(large_payload["thresholds"]))),
            provenance=TrainingProvenance.from_dict(_mapping(payload["provenance"])),
            content_hash=str(payload["content_hash"]),
        )
        expected = instance.to_dict()
        expected.pop("content_hash")
        if canonical_hash(expected) != instance.content_hash:
            raise ValueError("preprocessor content hash mismatch")
        return instance


def _state_payload(
    imputer: MedianImputer,
    scaler: StandardScaler,
    outliers: OutlierLimits,
    large_thresholds: LargeTradeThresholds,
    provenance: TrainingProvenance,
) -> dict[str, object]:
    return {
        "imputer": imputer.to_dict(),
        "scaler": {
            "feature_order": list(scaler.feature_order),
            "means": list(scaler.means),
            "standard_deviations": list(scaler.standard_deviations),
            "dimension": scaler.dimension,
        },
        "outlier_limits": {"limits": [list(item) for item in outliers.limits]},
        "large_trade_thresholds": {"thresholds": [list(item) for item in large_thresholds.thresholds]},
        "provenance": provenance.to_dict(),
    }


def _quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("quantile requires inner-train values")
    if len(values) == 1:
        return float(values[0])
    position = fraction * (len(values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(values[lower])
    return float(values[lower] + (values[upper] - values[lower]) * (position - lower))


def _present_values(dataset: InnerTrainDataset, name: str) -> tuple[float, ...]:
    values = tuple(float(value) for row in dataset.rows if (value := row.features.get(name)) is not None)
    if not values:
        raise ValueError(f"large-trade feature has no inner-train values:{name}")
    return values


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


def _triples(value: object) -> list[list[object]]:
    if not isinstance(value, list) or not all(isinstance(item, list) and len(item) == 3 for item in value):
        raise ValueError("expected triple list")
    return cast(list[list[object]], value)


def _number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("expected finite number")
    return float(value)


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected integer")
    return value
