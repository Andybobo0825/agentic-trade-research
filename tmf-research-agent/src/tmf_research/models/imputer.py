from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from statistics import median
from typing import Literal, cast

from tmf_research.models.provenance import InnerTrainDataset, TrainingProvenance, canonical_hash


@dataclass(frozen=True, slots=True)
class ImputationResult:
    values: tuple[float, ...]
    output_feature_order: tuple[str, ...]
    is_eligible: bool
    signal: Literal["NO_TRADE"] | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MedianImputer:
    feature_order: tuple[str, ...]
    required_features: tuple[str, ...]
    optional_features: tuple[str, ...]
    medians: tuple[tuple[str, float], ...]
    provenance: TrainingProvenance
    content_hash: str

    @property
    def output_feature_order(self) -> tuple[str, ...]:
        return self.feature_order + tuple(f"{name}__missing" for name in self.optional_features)

    @property
    def input_dimension(self) -> int:
        return len(self.feature_order)

    @property
    def output_dimension(self) -> int:
        return len(self.output_feature_order)

    @classmethod
    def fit_inner_train(
        cls,
        dataset: InnerTrainDataset,
        *,
        feature_order: tuple[str, ...],
        required_features: tuple[str, ...],
    ) -> MedianImputer:
        if not feature_order or len(feature_order) != len(set(feature_order)):
            raise ValueError("feature order must be non-empty and unique")
        if not set(required_features).issubset(feature_order):
            raise ValueError("required features must belong to feature order")
        optional_features = tuple(name for name in feature_order if name not in required_features)
        medians: list[tuple[str, float]] = []
        for name in feature_order:
            values = tuple(float(value) for row in dataset.rows if (value := row.features.get(name)) is not None)
            if not values:
                raise ValueError(f"feature has no inner-train observations:{name}")
            medians.append((name, float(median(values))))
        payload = {
            "feature_order": list(feature_order),
            "required_features": list(required_features),
            "optional_features": list(optional_features),
            "medians": [list(item) for item in medians],
            "provenance": dataset.provenance.to_dict(),
        }
        return cls(feature_order, required_features, optional_features, tuple(medians), dataset.provenance, canonical_hash(payload))

    def transform(self, row: Mapping[str, float | None]) -> ImputationResult:
        nonfinite = tuple(name for name in self.feature_order if (value := row.get(name)) is not None and not math.isfinite(value))
        if nonfinite:
            return ImputationResult((), self.output_feature_order, False, "NO_TRADE", tuple(f"NONFINITE_FEATURE:{name}" for name in nonfinite))
        missing_required = tuple(name for name in self.required_features if row.get(name) is None)
        if missing_required:
            return ImputationResult(
                (), self.output_feature_order, False, "NO_TRADE",
                tuple(f"REQUIRED_FEATURE_MISSING:{name}" for name in missing_required),
            )
        medians = dict(self.medians)
        values = tuple(medians[name] if row.get(name) is None else _finite_value(row[name]) for name in self.feature_order)
        indicators = tuple(1.0 if row.get(name) is None else 0.0 for name in self.optional_features)
        return ImputationResult(values + indicators, self.output_feature_order, True, None, ())

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_order": list(self.feature_order),
            "required_features": list(self.required_features),
            "optional_features": list(self.optional_features),
            "medians": [list(item) for item in self.medians],
            "provenance": self.provenance.to_dict(),
            "input_dimension": self.input_dimension,
            "output_dimension": self.output_dimension,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> MedianImputer:
        instance = cls(
            feature_order=tuple(_strings(payload["feature_order"])),
            required_features=tuple(_strings(payload["required_features"])),
            optional_features=tuple(_strings(payload["optional_features"])),
            medians=tuple((str(item[0]), _number(item[1])) for item in _pairs(payload["medians"])),
            provenance=TrainingProvenance.from_dict(_mapping(payload["provenance"])),
            content_hash=str(payload["content_hash"]),
        )
        if (
            _integer(payload["input_dimension"]) != instance.input_dimension
            or _integer(payload["output_dimension"]) != instance.output_dimension
        ):
            raise ValueError("declared imputer dimension mismatch")
        expected = instance.to_dict()
        expected.pop("content_hash")
        expected.pop("input_dimension")
        expected.pop("output_dimension")
        if canonical_hash(expected) != instance.content_hash:
            raise ValueError("imputer content hash mismatch")
        return instance


def _finite_value(value: float | None) -> float:
    if value is None or not math.isfinite(value):
        raise ValueError("feature value must be finite")
    return float(value)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expected mapping")
    return cast(Mapping[str, object], value)


def _strings(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected string list")
    return cast(list[str], value)


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
