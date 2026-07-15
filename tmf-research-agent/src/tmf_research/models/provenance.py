from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Literal


TrainingLabel = Literal["NO_TRADE", "LONG", "SHORT", "AMBIGUOUS"]


@dataclass(frozen=True, slots=True)
class InnerTrainRow:
    available_at: datetime
    features: Mapping[str, float | None]
    label: TrainingLabel
    is_complete: bool = True

    def __post_init__(self) -> None:
        _aware(self.available_at, "available_at")
        if self.label not in ("NO_TRADE", "LONG", "SHORT", "AMBIGUOUS"):
            raise ValueError("unknown inner-train label")
        frozen = MappingProxyType(dict(self.features))
        if not frozen:
            raise ValueError("inner-train features are required")
        if any(value is not None and not math.isfinite(value) for value in frozen.values()):
            raise ValueError("inner-train feature values must be finite")
        object.__setattr__(self, "features", frozen)

    def payload(self) -> dict[str, object]:
        return {
            "available_at": self.available_at.isoformat(),
            "features": dict(sorted(self.features.items())),
            "label": self.label,
            "is_complete": self.is_complete,
        }


@dataclass(frozen=True, slots=True)
class TrainingProvenance:
    fold_id: str
    dataset_hash: str
    train_hash: str
    fit_start: datetime
    fit_end: datetime

    def __post_init__(self) -> None:
        if not self.fold_id.strip():
            raise ValueError("fold id is required")
        validate_sha256(self.dataset_hash, "dataset hash")
        validate_sha256(self.train_hash, "train hash")
        _aware(self.fit_start, "fit_start")
        _aware(self.fit_end, "fit_end")
        if self.fit_end <= self.fit_start:
            raise ValueError("fit interval must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "fold_id": self.fold_id,
            "dataset_hash": self.dataset_hash,
            "train_hash": self.train_hash,
            "fit_start": self.fit_start.isoformat(),
            "fit_end": self.fit_end.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> TrainingProvenance:
        return cls(
            fold_id=str(payload["fold_id"]),
            dataset_hash=str(payload["dataset_hash"]),
            train_hash=str(payload["train_hash"]),
            fit_start=datetime.fromisoformat(str(payload["fit_start"])),
            fit_end=datetime.fromisoformat(str(payload["fit_end"])),
        )


@dataclass(frozen=True, slots=True)
class InnerTrainDataset:
    fold_id: str
    dataset_hash: str
    fit_start: datetime
    fit_end: datetime
    rows: tuple[InnerTrainRow, ...]
    train_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.fold_id.strip():
            raise ValueError("fold id is required")
        validate_sha256(self.dataset_hash, "dataset hash")
        _aware(self.fit_start, "fit_start")
        _aware(self.fit_end, "fit_end")
        if self.fit_end <= self.fit_start:
            raise ValueError("fit interval must be positive")
        if not self.rows:
            raise ValueError("inner-train rows are required")
        if any(row.available_at < self.fit_start or row.available_at > self.fit_end for row in self.rows):
            raise ValueError("inner-train row lies outside fit interval")
        feature_orders = {tuple(row.features) for row in self.rows}
        if len(feature_orders) != 1:
            raise ValueError("inner-train rows must share exact feature order")
        payload = {
            "fold_id": self.fold_id,
            "dataset_hash": self.dataset_hash,
            "fit_start": self.fit_start.isoformat(),
            "fit_end": self.fit_end.isoformat(),
            "rows": [row.payload() for row in self.rows],
        }
        object.__setattr__(self, "train_hash", _hash(payload))

    @classmethod
    def create(
        cls,
        *,
        fold_id: str,
        dataset_hash: str,
        fit_start: datetime,
        fit_end: datetime,
        rows: Sequence[InnerTrainRow],
    ) -> InnerTrainDataset:
        return cls(fold_id, dataset_hash, fit_start, fit_end, tuple(rows))

    @property
    def provenance(self) -> TrainingProvenance:
        return TrainingProvenance(self.fold_id, self.dataset_hash, self.train_hash, self.fit_start, self.fit_end)


@dataclass(frozen=True, slots=True)
class InnerValidationPrediction:
    available_at: datetime
    p_trade: float
    trade_outcome: int
    p_long_given_trade: float | None
    direction_outcome: int | None
    net_return: float

    def __post_init__(self) -> None:
        _aware(self.available_at, "available_at")
        _probability(self.p_trade, "p_trade")
        if self.trade_outcome not in (0, 1):
            raise ValueError("trade outcome must be binary")
        if (self.p_long_given_trade is None) != (self.direction_outcome is None):
            raise ValueError("direction probability and outcome must be present together")
        if self.trade_outcome == 0 and self.direction_outcome is not None:
            raise ValueError("direction calibration evidence is valid only for trade outcomes")
        if self.trade_outcome == 1 and self.direction_outcome is None:
            raise ValueError("trade outcomes require conditional direction evidence")
        if self.p_long_given_trade is not None:
            _probability(self.p_long_given_trade, "p_long_given_trade")
        if self.direction_outcome is not None and self.direction_outcome not in (0, 1):
            raise ValueError("direction outcome must be binary")
        if not math.isfinite(self.net_return):
            raise ValueError("validation return must be finite")

    def payload(self) -> dict[str, object]:
        return {
            "available_at": self.available_at.isoformat(), "p_trade": self.p_trade,
            "trade_outcome": self.trade_outcome, "p_long_given_trade": self.p_long_given_trade,
            "direction_outcome": self.direction_outcome, "net_return": self.net_return,
        }


@dataclass(frozen=True, slots=True)
class InnerValidationPredictions:
    provenance: TrainingProvenance
    preprocessor_hash: str
    model_hash: str
    rows: tuple[InnerValidationPrediction, ...]
    validation_hash: str = field(init=False)

    def __post_init__(self) -> None:
        validate_sha256(self.preprocessor_hash, "preprocessor hash")
        validate_sha256(self.model_hash, "model hash")
        if not self.rows:
            raise ValueError("inner-validation predictions are required")
        if any(row.available_at <= self.provenance.fit_end for row in self.rows):
            raise ValueError("inner-validation predictions must follow inner-train fit interval")
        object.__setattr__(self, "validation_hash", _hash({
            "provenance": self.provenance.to_dict(), "preprocessor_hash": self.preprocessor_hash,
            "model_hash": self.model_hash, "rows": [row.payload() for row in self.rows],
        }))

    @classmethod
    def create(
        cls,
        *,
        provenance: TrainingProvenance,
        preprocessor_hash: str,
        model_hash: str,
        rows: Sequence[InnerValidationPrediction],
    ) -> InnerValidationPredictions:
        return cls(provenance, preprocessor_hash, model_hash, tuple(rows))


def canonical_hash(payload: object) -> str:
    return _hash(payload)


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def validate_sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be lowercase SHA-256")


def _probability(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be a finite probability")


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
