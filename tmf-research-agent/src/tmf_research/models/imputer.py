from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Literal, cast


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
    fit_start: datetime
    fit_end: datetime
    fit_scope: str
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
    def fit(
        cls,
        rows: Sequence[Mapping[str, float | None]],
        *,
        feature_order: tuple[str, ...],
        required_features: tuple[str, ...],
        fit_start: datetime,
        fit_end: datetime,
        fit_scope: str = "INNER_TRAIN",
    ) -> MedianImputer:
        _validate_fit(feature_order, required_features, fit_start, fit_end, fit_scope)
        if not rows:
            raise ValueError("imputer fit requires train rows")
        optional_features = tuple(name for name in feature_order if name not in required_features)
        medians: list[tuple[str, float]] = []
        for name in feature_order:
            values = tuple(float(value) for row in rows if (value := row.get(name)) is not None)
            if not values:
                raise ValueError(f"feature has no train observations:{name}")
            medians.append((name, float(median(values))))
        payload = {
            "feature_order": list(feature_order), "required_features": list(required_features),
            "optional_features": list(optional_features), "medians": [list(item) for item in medians],
            "fit_start": fit_start.isoformat(), "fit_end": fit_end.isoformat(), "fit_scope": fit_scope,
        }
        return cls(feature_order, required_features, optional_features, tuple(medians), fit_start, fit_end, fit_scope, _hash(payload))

    def transform(self, row: Mapping[str, float | None]) -> ImputationResult:
        medians = dict(self.medians)
        missing_required = tuple(name for name in self.required_features if row.get(name) is None)
        if missing_required:
            return ImputationResult(
                values=(), output_feature_order=self.output_feature_order, is_eligible=False, signal="NO_TRADE",
                reasons=tuple(f"REQUIRED_FEATURE_MISSING:{name}" for name in missing_required),
            )
        values = tuple(_imputed_value(row.get(name), medians[name]) for name in self.feature_order)
        indicators = tuple(1.0 if row.get(name) is None else 0.0 for name in self.optional_features)
        return ImputationResult(values + indicators, self.output_feature_order, True, None, ())

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_order": list(self.feature_order), "required_features": list(self.required_features),
            "optional_features": list(self.optional_features), "medians": [list(item) for item in self.medians],
            "fit_start": self.fit_start.isoformat(), "fit_end": self.fit_end.isoformat(),
            "fit_scope": self.fit_scope, "input_dimension": self.input_dimension,
            "output_dimension": self.output_dimension, "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> MedianImputer:
        instance = cls(
            feature_order=tuple(_strings(payload["feature_order"])),
            required_features=tuple(_strings(payload["required_features"])),
            optional_features=tuple(_strings(payload["optional_features"])),
            medians=tuple((str(item[0]), _number(item[1])) for item in _pairs(payload["medians"])),
            fit_start=datetime.fromisoformat(str(payload["fit_start"])), fit_end=datetime.fromisoformat(str(payload["fit_end"])),
            fit_scope=str(payload["fit_scope"]), content_hash=str(payload["content_hash"]),
        )
        expected = dict(instance.to_dict())
        expected.pop("content_hash")
        expected.pop("input_dimension")
        expected.pop("output_dimension")
        if _hash(expected) != instance.content_hash:
            raise ValueError("imputer content hash mismatch")
        return instance


def _validate_fit(feature_order: tuple[str, ...], required_features: tuple[str, ...], fit_start: datetime, fit_end: datetime, fit_scope: str) -> None:
    if not feature_order or len(feature_order) != len(set(feature_order)):
        raise ValueError("feature order must be non-empty and unique")
    if not set(required_features).issubset(feature_order):
        raise ValueError("required features must belong to feature order")
    if fit_start.tzinfo is None or fit_end.tzinfo is None or fit_end <= fit_start:
        raise ValueError("fit interval must be timezone-aware and positive")
    if fit_scope != "INNER_TRAIN":
        raise ValueError("transform fit scope must be INNER_TRAIN")


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strings(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected string list")
    return cast(list[str], value)


def _pairs(value: object) -> list[list[object]]:
    if not isinstance(value, list) or not all(isinstance(item, list) and len(item) == 2 for item in value):
        raise ValueError("expected pair list")
    return cast(list[list[object]], value)


def _imputed_value(value: float | None, fallback: float) -> float:
    return fallback if value is None else float(value)


def _number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("expected number")
    return float(value)
