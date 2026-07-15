from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Literal, cast


TrainingLabel = Literal["NO_TRADE", "LONG", "SHORT", "AMBIGUOUS"]
ValidationLabel = Literal["NO_TRADE", "LONG", "SHORT"]


class SplitRole(str, Enum):
    INNER_TRAIN = "INNER_TRAIN"
    INNER_VALIDATION = "INNER_VALIDATION"
    OUTER_TEST = "OUTER_TEST"


_FOLD_IDENTITY_SEAL = object()
_FOLD_MANIFEST_SEAL = object()


@dataclass(frozen=True, slots=True)
class FoldIdentity:
    outer_fold_id: str
    inner_fold_id: str
    role: SplitRole
    manifest_hash: str = ""
    _seal: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.outer_fold_id.strip() or not self.inner_fold_id.strip():
            raise ValueError("structured fold identifiers are required")
        if not isinstance(self.role, SplitRole):
            raise ValueError("invalid split role")
        if self._seal is not _FOLD_IDENTITY_SEAL:
            raise ValueError("fold identity requires sealed fold-manifest authority")
        validate_sha256(self.manifest_hash, "fold manifest hash")

    @property
    def stable_id(self) -> str:
        return f"{self.outer_fold_id}/{self.inner_fold_id}"

    def same_fold(self, other: FoldIdentity) -> bool:
        return (
            self.outer_fold_id == other.outer_fold_id
            and self.inner_fold_id == other.inner_fold_id
            and self.manifest_hash == other.manifest_hash
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "outer_fold_id": self.outer_fold_id,
            "inner_fold_id": self.inner_fold_id,
            "role": self.role.value,
            "manifest_hash": self.manifest_hash,
        }


@dataclass(frozen=True, slots=True)
class NestedFoldManifest:
    outer_fold_id: str
    inner_fold_id: str
    dataset_hash: str
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    outer_test_start: datetime
    outer_test_end: datetime
    _seal: object = field(repr=False, compare=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self._seal is not _FOLD_MANIFEST_SEAL:
            raise ValueError("nested fold manifest must be created by the fold planner")
        if not self.outer_fold_id.strip() or not self.inner_fold_id.strip():
            raise ValueError("structured fold identifiers are required")
        validate_sha256(self.dataset_hash, "dataset hash")
        for name in (
            "train_start", "train_end", "validation_start", "validation_end",
            "outer_test_start", "outer_test_end",
        ):
            _aware(cast(datetime, getattr(self, name)), name)
        if not (
            self.train_start < self.train_end
            < self.validation_start < self.validation_end
            < self.outer_test_start < self.outer_test_end
        ):
            raise ValueError("nested fold intervals must be positive, ordered, and disjoint")
        object.__setattr__(self, "content_hash", canonical_hash(self._payload()))

    @classmethod
    def plan(
        cls,
        *,
        outer_fold_id: str,
        inner_fold_id: str,
        dataset_hash: str,
        train_start: datetime,
        train_end: datetime,
        validation_start: datetime,
        validation_end: datetime,
        outer_test_start: datetime,
        outer_test_end: datetime,
    ) -> NestedFoldManifest:
        return cls(
            outer_fold_id, inner_fold_id, dataset_hash, train_start, train_end,
            validation_start, validation_end, outer_test_start, outer_test_end,
            _FOLD_MANIFEST_SEAL,
        )

    def fold(self, role: SplitRole) -> FoldIdentity:
        if not isinstance(role, SplitRole):
            raise ValueError("invalid split role")
        return FoldIdentity(
            self.outer_fold_id,
            self.inner_fold_id,
            role,
            self.content_hash,
            _FOLD_IDENTITY_SEAL,
        )

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload["content_hash"] = self.content_hash
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> NestedFoldManifest:
        instance = cls.plan(
            outer_fold_id=str(payload["outer_fold_id"]),
            inner_fold_id=str(payload["inner_fold_id"]),
            dataset_hash=str(payload["dataset_hash"]),
            train_start=datetime.fromisoformat(str(payload["train_start"])),
            train_end=datetime.fromisoformat(str(payload["train_end"])),
            validation_start=datetime.fromisoformat(str(payload["validation_start"])),
            validation_end=datetime.fromisoformat(str(payload["validation_end"])),
            outer_test_start=datetime.fromisoformat(str(payload["outer_test_start"])),
            outer_test_end=datetime.fromisoformat(str(payload["outer_test_end"])),
        )
        if str(payload["content_hash"]) != instance.content_hash:
            raise ValueError("fold manifest content hash mismatch")
        return instance

    def _payload(self) -> dict[str, object]:
        return {
            "outer_fold_id": self.outer_fold_id,
            "inner_fold_id": self.inner_fold_id,
            "dataset_hash": self.dataset_hash,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "outer_test_start": self.outer_test_start.isoformat(),
            "outer_test_end": self.outer_test_end.isoformat(),
        }


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
        frozen = _frozen_features(self.features, "inner-train")
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
    manifest: NestedFoldManifest
    train_hash: str

    def __post_init__(self) -> None:
        validate_sha256(self.train_hash, "train hash")

    @property
    def fold(self) -> FoldIdentity:
        return self.manifest.fold(SplitRole.INNER_TRAIN)

    @property
    def dataset_hash(self) -> str:
        return self.manifest.dataset_hash

    @property
    def fit_start(self) -> datetime:
        return self.manifest.train_start

    @property
    def fit_end(self) -> datetime:
        return self.manifest.train_end

    @property
    def fold_id(self) -> str:
        return self.fold.stable_id

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest": self.manifest.to_dict(),
            "train_hash": self.train_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> TrainingProvenance:
        return cls(
            manifest=NestedFoldManifest.from_dict(_mapping(payload["manifest"])),
            train_hash=str(payload["train_hash"]),
        )


@dataclass(frozen=True, slots=True)
class InnerTrainDataset:
    manifest: NestedFoldManifest
    rows: tuple[InnerTrainRow, ...]
    train_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("inner-train rows are required")
        if any(row.available_at < self.fit_start or row.available_at > self.fit_end for row in self.rows):
            raise ValueError("inner-train row lies outside fit interval")
        _exact_feature_order(self.rows, "inner-train")
        payload = {
            "manifest": self.manifest.to_dict(),
            "dataset_hash": self.dataset_hash,
            "fit_start": self.fit_start.isoformat(),
            "fit_end": self.fit_end.isoformat(),
            "rows": [row.payload() for row in self.rows],
        }
        object.__setattr__(self, "train_hash", canonical_hash(payload))

    @classmethod
    def create(
        cls,
        *,
        manifest: NestedFoldManifest,
        rows: Sequence[InnerTrainRow],
    ) -> InnerTrainDataset:
        return cls(manifest, tuple(rows))

    @property
    def fold(self) -> FoldIdentity:
        return self.manifest.fold(SplitRole.INNER_TRAIN)

    @property
    def dataset_hash(self) -> str:
        return self.manifest.dataset_hash

    @property
    def fit_start(self) -> datetime:
        return self.manifest.train_start

    @property
    def fit_end(self) -> datetime:
        return self.manifest.train_end

    @property
    def fold_id(self) -> str:
        return self.fold.stable_id

    @property
    def provenance(self) -> TrainingProvenance:
        return TrainingProvenance(self.manifest, self.train_hash)


_VALIDATION_RANGE_SEAL = object()
_VALIDATION_DATASET_SEAL = object()
_GENERATED_PREDICTION_SEAL = object()


@dataclass(frozen=True, slots=True)
class InnerValidationRange:
    parent_provenance: TrainingProvenance
    fold: FoldIdentity
    dataset_hash: str
    validation_start: datetime
    validation_end: datetime
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _VALIDATION_RANGE_SEAL:
            raise ValueError("inner-validation range must be derived from training provenance")
        if self.fold.role is not SplitRole.INNER_VALIDATION:
            raise ValueError("inner-validation range requires INNER_VALIDATION role")
        if not self.fold.same_fold(self.parent_provenance.fold):
            raise ValueError("inner-validation fold does not match parent training fold")
        if self.dataset_hash != self.parent_provenance.dataset_hash:
            raise ValueError("inner-validation dataset hash does not match parent training data")
        _aware(self.validation_start, "validation_start")
        _aware(self.validation_end, "validation_end")
        manifest = self.parent_provenance.manifest
        if (
            self.validation_start != manifest.validation_start
            or self.validation_end != manifest.validation_end
        ):
            raise ValueError("inner-validation interval does not match fold manifest")

    @classmethod
    def for_parent(
        cls,
        parent_provenance: TrainingProvenance,
    ) -> InnerValidationRange:
        manifest = parent_provenance.manifest
        return cls(
            parent_provenance,
            manifest.fold(SplitRole.INNER_VALIDATION),
            parent_provenance.dataset_hash,
            manifest.validation_start,
            manifest.validation_end,
            _VALIDATION_RANGE_SEAL,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "parent_provenance": self.parent_provenance.to_dict(),
            "fold": self.fold.to_dict(),
            "dataset_hash": self.dataset_hash,
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> InnerValidationRange:
        parent = TrainingProvenance.from_dict(_mapping(payload["parent_provenance"]))
        instance = cls.for_parent(parent)
        fold_payload = _mapping(payload["fold"])
        if fold_payload != instance.fold.to_dict():
            raise ValueError("serialized inner-validation fold mismatch")
        if str(payload["dataset_hash"]) != instance.dataset_hash:
            raise ValueError("serialized inner-validation dataset hash mismatch")
        if (
            str(payload["validation_start"]) != instance.validation_start.isoformat()
            or str(payload["validation_end"]) != instance.validation_end.isoformat()
        ):
            raise ValueError("serialized inner-validation interval mismatch")
        return instance


@dataclass(frozen=True, slots=True)
class OuterTestRange:
    manifest: NestedFoldManifest

    @property
    def fold(self) -> FoldIdentity:
        return self.manifest.fold(SplitRole.OUTER_TEST)

    @property
    def start(self) -> datetime:
        return self.manifest.outer_test_start

    @property
    def end(self) -> datetime:
        return self.manifest.outer_test_end


@dataclass(frozen=True, slots=True)
class InnerValidationRow:
    available_at: datetime
    features: Mapping[str, float | None]
    label: ValidationLabel
    net_return: float

    def __post_init__(self) -> None:
        _aware(self.available_at, "available_at")
        if self.label not in ("NO_TRADE", "LONG", "SHORT"):
            raise ValueError("unknown inner-validation label")
        if not math.isfinite(self.net_return):
            raise ValueError("inner-validation return must be finite")
        object.__setattr__(self, "features", _frozen_features(self.features, "inner-validation"))

    def payload(self) -> dict[str, object]:
        return {
            "available_at": self.available_at.isoformat(),
            "features": dict(sorted(self.features.items())),
            "label": self.label,
            "net_return": self.net_return,
        }


@dataclass(frozen=True, slots=True)
class InnerValidationProvenance:
    validation_range: InnerValidationRange
    validation_dataset_hash: str

    def __post_init__(self) -> None:
        validate_sha256(self.validation_dataset_hash, "validation dataset hash")

    @property
    def parent_provenance(self) -> TrainingProvenance:
        return self.validation_range.parent_provenance

    def to_dict(self) -> dict[str, object]:
        return {
            "validation_range": self.validation_range.to_dict(),
            "validation_dataset_hash": self.validation_dataset_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> InnerValidationProvenance:
        return cls(
            InnerValidationRange.from_dict(_mapping(payload["validation_range"])),
            str(payload["validation_dataset_hash"]),
        )


@dataclass(frozen=True, slots=True)
class InnerValidationDataset:
    validation_range: InnerValidationRange
    rows: tuple[InnerValidationRow, ...]
    _seal: object = field(repr=False, compare=False)
    validation_dataset_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self._seal is not _VALIDATION_DATASET_SEAL:
            raise ValueError("inner-validation dataset requires a sealed range capability")
        if not self.rows:
            raise ValueError("inner-validation rows are required")
        if any(
            row.available_at < self.validation_range.validation_start
            or row.available_at > self.validation_range.validation_end
            for row in self.rows
        ):
            raise ValueError("inner-validation row lies outside validation interval")
        _exact_feature_order(self.rows, "inner-validation")
        object.__setattr__(self, "validation_dataset_hash", canonical_hash({
            "validation_range": self.validation_range.to_dict(),
            "rows": [row.payload() for row in self.rows],
        }))

    @classmethod
    def create(
        cls,
        validation_range: InnerValidationRange,
        *,
        rows: Sequence[InnerValidationRow],
    ) -> InnerValidationDataset:
        if not isinstance(validation_range, InnerValidationRange):
            raise ValueError("outer-test capability cannot be used as inner-validation")
        return cls(validation_range, tuple(rows), _VALIDATION_DATASET_SEAL)

    @property
    def provenance(self) -> InnerValidationProvenance:
        return InnerValidationProvenance(self.validation_range, self.validation_dataset_hash)


@dataclass(frozen=True, slots=True)
class InnerValidationPrediction:
    available_at: datetime
    p_trade: float
    trade_outcome: int
    p_long_given_trade: float | None
    direction_outcome: int | None
    net_return: float
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _GENERATED_PREDICTION_SEAL:
            raise ValueError("inner-validation predictions must be generated by Phase 4 composition")
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
            "available_at": self.available_at.isoformat(),
            "p_trade": self.p_trade,
            "trade_outcome": self.trade_outcome,
            "p_long_given_trade": self.p_long_given_trade,
            "direction_outcome": self.direction_outcome,
            "net_return": self.net_return,
        }


@dataclass(frozen=True, slots=True)
class InnerValidationPredictions:
    provenance: InnerValidationProvenance
    preprocessor_hash: str
    model_hash: str
    rows: tuple[InnerValidationPrediction, ...]
    _seal: object = field(repr=False, compare=False)
    validation_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self._seal is not _GENERATED_PREDICTION_SEAL:
            raise ValueError("inner-validation predictions must be generated by Phase 4 composition")
        validate_sha256(self.preprocessor_hash, "preprocessor hash")
        validate_sha256(self.model_hash, "model hash")
        if not self.rows:
            raise ValueError("inner-validation predictions are required")
        validation_range = self.provenance.validation_range
        if any(
            row.available_at < validation_range.validation_start
            or row.available_at > validation_range.validation_end
            for row in self.rows
        ):
            raise ValueError("inner-validation prediction lies outside validation interval")
        object.__setattr__(self, "validation_hash", canonical_hash({
            "provenance": self.provenance.to_dict(),
            "preprocessor_hash": self.preprocessor_hash,
            "model_hash": self.model_hash,
            "rows": [row.payload() for row in self.rows],
        }))


def _generated_prediction(
    *,
    available_at: datetime,
    p_trade: float,
    trade_outcome: int,
    p_long_given_trade: float | None,
    direction_outcome: int | None,
    net_return: float,
) -> InnerValidationPrediction:
    return InnerValidationPrediction(
        available_at,
        p_trade,
        trade_outcome,
        p_long_given_trade,
        direction_outcome,
        net_return,
        _GENERATED_PREDICTION_SEAL,
    )


def _generated_predictions(
    *,
    provenance: InnerValidationProvenance,
    preprocessor_hash: str,
    model_hash: str,
    rows: Sequence[InnerValidationPrediction],
) -> InnerValidationPredictions:
    return InnerValidationPredictions(
        provenance,
        preprocessor_hash,
        model_hash,
        tuple(rows),
        _GENERATED_PREDICTION_SEAL,
    )


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be lowercase SHA-256")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _probability(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be a finite probability")


def _frozen_features(
    features: Mapping[str, float | None],
    name: str,
) -> Mapping[str, float | None]:
    frozen = MappingProxyType(dict(features))
    if not frozen:
        raise ValueError(f"{name} features are required")
    if any(value is not None and not math.isfinite(value) for value in frozen.values()):
        raise ValueError(f"{name} feature values must be finite")
    return frozen


def _exact_feature_order(rows: Sequence[object], name: str) -> None:
    feature_orders = {
        tuple(cast(Mapping[str, float | None], getattr(row, "features")))
        for row in rows
    }
    if len(feature_orders) != 1:
        raise ValueError(f"{name} rows must share exact feature order")


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expected mapping")
    return cast(Mapping[str, object], value)
