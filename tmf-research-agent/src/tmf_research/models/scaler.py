from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from tmf_research.models.imputer import ImputationResult, MedianImputer


@dataclass(frozen=True, slots=True)
class StandardScaler:
    feature_order: tuple[str, ...]
    means: tuple[float, ...]
    standard_deviations: tuple[float, ...]
    fit_scope: str = "INNER_TRAIN"

    def __post_init__(self) -> None:
        if len(self.feature_order) != len(self.means) or len(self.means) != len(self.standard_deviations):
            raise ValueError("scaler dimension mismatch")
        if any(value <= 0.0 or not math.isfinite(value) for value in self.standard_deviations):
            raise ValueError("scaler deviation must be finite and positive")
        if self.fit_scope != "INNER_TRAIN":
            raise ValueError("scaler fit scope must be INNER_TRAIN")

    @property
    def dimension(self) -> int:
        return len(self.feature_order)

    def transform(self, values: Sequence[float]) -> tuple[float, ...]:
        if len(values) != self.dimension:
            raise ValueError("scaler dimension mismatch")
        return tuple((float(value) - mean) / deviation for value, mean, deviation in zip(values, self.means, self.standard_deviations, strict=True))


@dataclass(frozen=True, slots=True)
class OutlierLimits:
    limits: tuple[tuple[str, float, float], ...]
    fit_scope: str = "INNER_TRAIN"

    def clip(self, feature_order: tuple[str, ...], values: Sequence[float]) -> tuple[float, ...]:
        by_name = {name: (lower, upper) for name, lower, upper in self.limits}
        return tuple(min(by_name[name][1], max(by_name[name][0], float(value))) for name, value in zip(feature_order, values, strict=True))


@dataclass(frozen=True, slots=True)
class LargeTradeThresholds:
    thresholds: tuple[tuple[str, float], ...]
    fit_scope: str = "INNER_TRAIN"


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
    fit_start: datetime
    fit_end: datetime
    fit_scope: str
    content_hash: str

    @property
    def feature_order(self) -> tuple[str, ...]:
        return self.imputer.feature_order

    @property
    def output_feature_order(self) -> tuple[str, ...]:
        return self.imputer.output_feature_order

    @classmethod
    def fit(
        cls,
        rows: Sequence[Mapping[str, float | None]],
        *,
        feature_order: tuple[str, ...],
        required_features: tuple[str, ...],
        fit_start: datetime,
        fit_end: datetime,
        large_trade_features: tuple[str, ...] = (),
        lower_quantile: float = 0.01,
        upper_quantile: float = 0.99,
        large_trade_quantile: float = 0.95,
    ) -> FoldPreprocessor:
        if not 0.0 <= lower_quantile < upper_quantile <= 1.0 or not 0.0 <= large_trade_quantile <= 1.0:
            raise ValueError("invalid train quantile")
        if not set(large_trade_features).issubset(feature_order):
            raise ValueError("large trade features must belong to feature order")
        imputer = MedianImputer.fit(
            rows, feature_order=feature_order, required_features=required_features,
            fit_start=fit_start, fit_end=fit_end,
        )
        complete_train: list[tuple[float, ...]] = []
        for row in rows:
            result = imputer.transform(row)
            if result.is_eligible:
                complete_train.append(result.values)
        if not complete_train:
            raise ValueError("preprocessor requires complete train rows")
        limits = tuple(
            (name, _quantile(sorted(row[index] for row in complete_train), lower_quantile), _quantile(sorted(row[index] for row in complete_train), upper_quantile))
            for index, name in enumerate(feature_order)
        )
        outliers = OutlierLimits(limits)
        clipped = tuple(
            outliers.clip(feature_order, row[: len(feature_order)]) + row[len(feature_order) :]
            for row in complete_train
        )
        means = tuple(sum(row[index] for row in clipped) / len(clipped) for index in range(len(imputer.output_feature_order)))
        deviations = tuple(
            math.sqrt(sum((row[index] - means[index]) ** 2 for row in clipped) / len(clipped)) or 1.0
            for index in range(len(means))
        )
        scaler = StandardScaler(imputer.output_feature_order, means, deviations)
        thresholds = LargeTradeThresholds(tuple(
            (name, _quantile(sorted(_present_values(rows, name)), large_trade_quantile))
            for name in large_trade_features
        ))
        payload = _state_payload(imputer, scaler, outliers, thresholds, fit_start, fit_end, "INNER_TRAIN")
        return cls(imputer, scaler, outliers, thresholds, fit_start, fit_end, "INNER_TRAIN", _hash(payload))

    def transform(self, row: Mapping[str, float | None]) -> PreprocessingResult:
        imputed: ImputationResult = self.imputer.transform(row)
        if not imputed.is_eligible:
            return PreprocessingResult((), self.output_feature_order, False, "NO_TRADE", imputed.reasons)
        original_dimension = len(self.feature_order)
        clipped = self.outlier_limits.clip(self.feature_order, imputed.values[:original_dimension]) + imputed.values[original_dimension:]
        return PreprocessingResult(self.scaler.transform(clipped), self.output_feature_order, True, None, ())

    def to_dict(self) -> dict[str, object]:
        payload = _state_payload(self.imputer, self.scaler, self.outlier_limits, self.large_trade_thresholds, self.fit_start, self.fit_end, self.fit_scope)
        payload["content_hash"] = self.content_hash
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> FoldPreprocessor:
        imputer = MedianImputer.from_dict(_mapping(payload["imputer"]))
        scaler_payload = _mapping(payload["scaler"])
        outlier_payload = _mapping(payload["outlier_limits"])
        large_payload = _mapping(payload["large_trade_thresholds"])
        instance = cls(
            imputer=imputer,
            scaler=StandardScaler(
                tuple(_strings(scaler_payload["feature_order"])), tuple(_floats(scaler_payload["means"])),
                tuple(_floats(scaler_payload["standard_deviations"])), str(scaler_payload["fit_scope"]),
            ),
            outlier_limits=OutlierLimits(tuple((str(item[0]), _number(item[1]), _number(item[2])) for item in _triples(outlier_payload["limits"])), str(outlier_payload["fit_scope"])),
            large_trade_thresholds=LargeTradeThresholds(tuple((str(item[0]), _number(item[1])) for item in _pairs(large_payload["thresholds"])), str(large_payload["fit_scope"])),
            fit_start=datetime.fromisoformat(str(payload["fit_start"])), fit_end=datetime.fromisoformat(str(payload["fit_end"])),
            fit_scope=str(payload["fit_scope"]), content_hash=str(payload["content_hash"]),
        )
        expected = instance.to_dict()
        expected.pop("content_hash")
        if _hash(expected) != instance.content_hash:
            raise ValueError("preprocessor content hash mismatch")
        return instance


def _state_payload(
    imputer: MedianImputer, scaler: StandardScaler, outliers: OutlierLimits,
    large_thresholds: LargeTradeThresholds, fit_start: datetime, fit_end: datetime, fit_scope: str,
) -> dict[str, object]:
    return {
        "imputer": imputer.to_dict(),
        "scaler": {
            "feature_order": list(scaler.feature_order), "means": list(scaler.means),
            "standard_deviations": list(scaler.standard_deviations), "dimension": scaler.dimension,
            "fit_scope": scaler.fit_scope,
        },
        "outlier_limits": {"limits": [list(item) for item in outliers.limits], "fit_scope": outliers.fit_scope},
        "large_trade_thresholds": {"thresholds": [list(item) for item in large_thresholds.thresholds], "fit_scope": large_thresholds.fit_scope},
        "fit_start": fit_start.isoformat(), "fit_end": fit_end.isoformat(), "fit_scope": fit_scope,
    }


def _quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("quantile requires train values")
    if len(values) == 1:
        return float(values[0])
    position = fraction * (len(values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(values[lower])
    return float(values[lower] + (values[upper] - values[lower]) * (position - lower))


def _hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


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


def _triples(value: object) -> list[list[object]]:
    if not isinstance(value, list) or not all(isinstance(item, list) and len(item) == 3 for item in value):
        raise ValueError("expected triple list")
    return cast(list[list[object]], value)


def _present_values(rows: Sequence[Mapping[str, float | None]], name: str) -> tuple[float, ...]:
    values: list[float] = []
    for row in rows:
        value = row.get(name)
        if value is not None:
            values.append(float(value))
    return tuple(values)


def _number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("expected number")
    return float(value)
