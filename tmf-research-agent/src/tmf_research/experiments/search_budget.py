from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchBudgetLimits:
    model_families: int = 2
    feature_sets: int = 8
    hyperparameter_combinations: int = 30
    barrier_combinations: int = 12
    threshold_combinations: int = 12
    calibration_methods: int = 3

    def __post_init__(self) -> None:
        if self.as_dict() != {
            "model_families": 2,
            "feature_sets": 8,
            "hyperparameter_combinations": 30,
            "barrier_combinations": 12,
            "threshold_combinations": 12,
            "calibration_methods": 3,
        }:
            raise ValueError("Phase 5 search budgets are fixed at 2/8/30/12/12/3")

    def as_dict(self) -> dict[str, int]:
        return {
            "model_families": self.model_families,
            "feature_sets": self.feature_sets,
            "hyperparameter_combinations": self.hyperparameter_combinations,
            "barrier_combinations": self.barrier_combinations,
            "threshold_combinations": self.threshold_combinations,
            "calibration_methods": self.calibration_methods,
        }


@dataclass(frozen=True, slots=True)
class SearchSpaceManifest:
    model_families: tuple[str, ...]
    feature_sets: tuple[str, ...]
    hyperparameter_combinations: tuple[str, ...]
    barrier_combinations: tuple[str, ...]
    threshold_combinations: tuple[str, ...]
    calibration_methods: tuple[str, ...]
    limits: SearchBudgetLimits = SearchBudgetLimits()

    def __post_init__(self) -> None:
        for field, limit in self.limits.as_dict().items():
            values = getattr(self, field)
            if not values or len(values) > limit or len(set(values)) != len(values):
                raise ValueError(f"{field} must be non-empty, unique, and within preregistered budget {limit}")
            if any(not value.strip() for value in values):
                raise ValueError(f"{field} identifiers are required")

    def to_dict(self) -> dict[str, object]:
        return {
            **{field: list(getattr(self, field)) for field in self.limits.as_dict()},
            "limits": self.limits.as_dict(),
        }

    @property
    def canonical_hash(self) -> str:
        return _hash(self.to_dict())

    def permits(self, dimension: str, identifier: str) -> bool:
        if dimension not in self.limits.as_dict():
            raise ValueError("unknown search dimension")
        return identifier in getattr(self, dimension)


def canonical_hash(payload: Mapping[str, object]) -> str:
    return _hash(dict(payload))


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()
