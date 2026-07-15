from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Callable, Literal, TypeVar, cast


TrainingLabel = Literal["NO_TRADE", "LONG", "SHORT", "AMBIGUOUS"]


class SplitRole(str, Enum):
    INNER_TRAIN = "INNER_TRAIN"
    INNER_VALIDATION = "INNER_VALIDATION"
    OUTER_TEST = "OUTER_TEST"


_AUTHORITY_DOMAIN = "tmf-phase4-fold-authority-v2"
_MATERIALIZER_SEAL = object()
_GENERATED_PREDICTION_SEAL = object()


class _SealedAuthority:
    __slots__ = ()

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("sealed Phase 4 authority objects cannot be constructed directly")


@dataclass(frozen=True, slots=True)
class Phase4SourceRow:
    row_id: str
    available_at: datetime
    features: Mapping[str, float | None]
    label: TrainingLabel
    net_return: float
    is_complete: bool = True

    def __post_init__(self) -> None:
        if not self.row_id.strip():
            raise ValueError("source row id is required")
        _aware(self.available_at, "available_at")
        if self.label not in ("NO_TRADE", "LONG", "SHORT", "AMBIGUOUS"):
            raise ValueError("unknown source label")
        if not math.isfinite(self.net_return):
            raise ValueError("source net return must be finite")
        object.__setattr__(self, "features", _frozen_features(self.features, "source"))

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.payload())

    def payload(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "available_at": self.available_at.isoformat(),
            "features": dict(sorted(self.features.items())),
            "label": self.label,
            "net_return": self.net_return,
            "is_complete": self.is_complete,
        }


@dataclass(frozen=True, slots=True, init=False)
class RoleCommitment(_SealedAuthority):
    role: SplitRole
    start: datetime
    end: datetime
    row_hashes: tuple[tuple[str, str], ...]
    row_ids_hash: str
    rows_hash: str
    count: int
    _authority: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.role, SplitRole):
            raise ValueError("invalid split role")
        _aware(self.start, "role start")
        _aware(self.end, "role end")
        if self.end <= self.start or self.count <= 0 or self.count != len(self.row_hashes):
            raise ValueError("role commitment range and count are invalid")
        if len({row_id for row_id, _ in self.row_hashes}) != self.count:
            raise ValueError("role commitment row ids must be unique")
        if any(not row_id.strip() for row_id, _ in self.row_hashes):
            raise ValueError("role commitment row ids are required")
        for _, row_hash in self.row_hashes:
            validate_sha256(row_hash, "source row hash")
        validate_sha256(self.row_ids_hash, "role row ids hash")
        validate_sha256(self.rows_hash, "role rows hash")
        if self.row_ids_hash != canonical_hash([row_id for row_id, _ in self.row_hashes]):
            raise ValueError("role row ids hash does not match committed ids")
        if self.rows_hash != _row_commitment_hash(self.row_hashes):
            raise ValueError("role rows hash does not match committed source hashes")
        _verify_authority("role", self._payload(), self._authority)

    def to_dict(self) -> dict[str, object]:
        return self._payload()

    def _payload(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "row_hashes": [list(item) for item in self.row_hashes],
            "row_ids_hash": self.row_ids_hash,
            "rows_hash": self.rows_hash,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True, init=False)
class NestedFoldManifest(_SealedAuthority):
    outer_fold_id: str
    inner_fold_id: str
    source_version: str
    source_dataset_hash: str
    plan_hash: str
    inner_train: RoleCommitment
    inner_validation: RoleCommitment
    outer_test: RoleCommitment
    content_hash: str
    _authority: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.outer_fold_id.strip() or not self.inner_fold_id.strip():
            raise ValueError("structured fold identifiers are required")
        if not self.source_version.strip():
            raise ValueError("source dataset version is required")
        validate_sha256(self.source_dataset_hash, "source dataset hash")
        if self.source_version != _source_dataset_version(self.source_dataset_hash):
            raise ValueError("source dataset version does not match its canonical hash")
        validate_sha256(self.plan_hash, "fold plan hash")
        validate_sha256(self.content_hash, "fold manifest hash")
        if (
            self.inner_train.role is not SplitRole.INNER_TRAIN
            or self.inner_validation.role is not SplitRole.INNER_VALIDATION
            or self.outer_test.role is not SplitRole.OUTER_TEST
        ):
            raise ValueError("fold manifest role commitments are invalid")
        if not (
            self.inner_train.start < self.inner_train.end
            < self.inner_validation.start < self.inner_validation.end
            < self.outer_test.start < self.outer_test.end
        ):
            raise ValueError("fold manifest intervals must be ordered and disjoint")
        expected_plan_hash = canonical_hash(
            _fold_plan_payload(
                outer_fold_id=self.outer_fold_id,
                inner_fold_id=self.inner_fold_id,
                source_dataset_hash=self.source_dataset_hash,
                train_start=self.inner_train.start,
                train_end=self.inner_train.end,
                validation_start=self.inner_validation.start,
                validation_end=self.inner_validation.end,
                outer_test_start=self.outer_test.start,
                outer_test_end=self.outer_test.end,
            )
        )
        if self.plan_hash != expected_plan_hash:
            raise ValueError("fold plan hash does not match committed intervals")
        payload = self._payload()
        if canonical_hash(payload) != self.content_hash:
            raise ValueError("fold manifest content hash mismatch")
        _verify_authority("manifest", {**payload, "content_hash": self.content_hash}, self._authority)

    @property
    def dataset_hash(self) -> str:
        return self.source_dataset_hash

    @property
    def train_start(self) -> datetime:
        return self.inner_train.start

    @property
    def train_end(self) -> datetime:
        return self.inner_train.end

    @property
    def validation_start(self) -> datetime:
        return self.inner_validation.start

    @property
    def validation_end(self) -> datetime:
        return self.inner_validation.end

    @property
    def outer_test_start(self) -> datetime:
        return self.outer_test.start

    @property
    def outer_test_end(self) -> datetime:
        return self.outer_test.end

    def fold(self, role: SplitRole) -> FoldIdentity:
        if not isinstance(role, SplitRole):
            raise ValueError("invalid split role")
        payload = {
            "outer_fold_id": self.outer_fold_id,
            "inner_fold_id": self.inner_fold_id,
            "role": role.value,
            "manifest_hash": self.content_hash,
        }
        return _sealed_instance(
            FoldIdentity,
            outer_fold_id=self.outer_fold_id,
            inner_fold_id=self.inner_fold_id,
            role=role,
            manifest_hash=self.content_hash,
            _authority=_authority_tag("fold", payload),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "content_hash": self.content_hash}

    @classmethod
    def _from_dict(cls, payload: Mapping[str, object]) -> NestedFoldManifest:
        inner_train = _role_from_dict(_mapping(payload["inner_train"]))
        inner_validation = _role_from_dict(_mapping(payload["inner_validation"]))
        outer_test = _role_from_dict(_mapping(payload["outer_test"]))
        values = {
            "outer_fold_id": str(payload["outer_fold_id"]),
            "inner_fold_id": str(payload["inner_fold_id"]),
            "source_version": str(payload["source_version"]),
            "source_dataset_hash": str(payload["source_dataset_hash"]),
            "plan_hash": str(payload["plan_hash"]),
            "inner_train": inner_train,
            "inner_validation": inner_validation,
            "outer_test": outer_test,
            "content_hash": str(payload["content_hash"]),
        }
        authority_payload = {
            "outer_fold_id": values["outer_fold_id"],
            "inner_fold_id": values["inner_fold_id"],
            "source_version": values["source_version"],
            "source_dataset_hash": values["source_dataset_hash"],
            "plan_hash": values["plan_hash"],
            "inner_train": inner_train.to_dict(),
            "inner_validation": inner_validation.to_dict(),
            "outer_test": outer_test.to_dict(),
            "content_hash": values["content_hash"],
        }
        return _sealed_instance(
            cls,
            **values,
            _authority=_authority_tag("manifest", authority_payload),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "outer_fold_id": self.outer_fold_id,
            "inner_fold_id": self.inner_fold_id,
            "source_version": self.source_version,
            "source_dataset_hash": self.source_dataset_hash,
            "plan_hash": self.plan_hash,
            "inner_train": self.inner_train.to_dict(),
            "inner_validation": self.inner_validation.to_dict(),
            "outer_test": self.outer_test.to_dict(),
        }


@dataclass(frozen=True, slots=True, init=False)
class FoldIdentity(_SealedAuthority):
    outer_fold_id: str
    inner_fold_id: str
    role: SplitRole
    manifest_hash: str
    _authority: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.role, SplitRole):
            raise ValueError("invalid split role")
        validate_sha256(self.manifest_hash, "fold manifest hash")
        payload = {
            "outer_fold_id": self.outer_fold_id,
            "inner_fold_id": self.inner_fold_id,
            "role": self.role.value,
            "manifest_hash": self.manifest_hash,
        }
        _verify_authority("fold", payload, self._authority)

    @property
    def stable_id(self) -> str:
        return f"{self.outer_fold_id}/{self.inner_fold_id}"

    def same_fold(self, other: FoldIdentity) -> bool:
        return (
            self.outer_fold_id == other.outer_fold_id
            and self.inner_fold_id == other.inner_fold_id
            and self.manifest_hash == other.manifest_hash
        )


@dataclass(frozen=True, slots=True)
class TrainingProvenance:
    manifest: NestedFoldManifest
    train_hash: str

    def __post_init__(self) -> None:
        validate_sha256(self.train_hash, "train hash")
        if self.train_hash != self.manifest.inner_train.rows_hash:
            raise ValueError("training hash does not match committed inner-train rows")

    @property
    def fold(self) -> FoldIdentity:
        return self.manifest.fold(SplitRole.INNER_TRAIN)

    @property
    def fold_id(self) -> str:
        return self.fold.stable_id

    @property
    def dataset_hash(self) -> str:
        return self.manifest.source_dataset_hash

    @property
    def fit_start(self) -> datetime:
        return self.manifest.inner_train.start

    @property
    def fit_end(self) -> datetime:
        return self.manifest.inner_train.end

    def to_dict(self) -> dict[str, object]:
        return {"manifest": self.manifest.to_dict(), "train_hash": self.train_hash}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> TrainingProvenance:
        return cls(
            NestedFoldManifest._from_dict(_mapping(payload["manifest"])),
            str(payload["train_hash"]),
        )


@dataclass(frozen=True, slots=True, init=False)
class InnerTrainDataset(_SealedAuthority):
    manifest: NestedFoldManifest
    rows: tuple[Phase4SourceRow, ...]
    train_hash: str
    _authority: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _verify_capability(self.manifest.inner_train, self.rows, self.train_hash)
        payload = _capability_payload(self.manifest, SplitRole.INNER_TRAIN, self.rows, self.train_hash)
        _verify_authority("inner-train-dataset", payload, self._authority)

    @property
    def fold(self) -> FoldIdentity:
        return self.manifest.fold(SplitRole.INNER_TRAIN)

    @property
    def fold_id(self) -> str:
        return self.fold.stable_id

    @property
    def dataset_hash(self) -> str:
        return self.manifest.source_dataset_hash

    @property
    def fit_start(self) -> datetime:
        return self.manifest.inner_train.start

    @property
    def fit_end(self) -> datetime:
        return self.manifest.inner_train.end

    @property
    def provenance(self) -> TrainingProvenance:
        return TrainingProvenance(self.manifest, self.train_hash)


@dataclass(frozen=True, slots=True, init=False)
class InnerValidationProvenance(_SealedAuthority):
    manifest: NestedFoldManifest
    validation_dataset_hash: str
    _authority: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        validate_sha256(self.validation_dataset_hash, "validation dataset hash")
        if self.validation_dataset_hash != self.manifest.inner_validation.rows_hash:
            raise ValueError("validation hash does not match committed rows")
        payload = {
            "manifest_hash": self.manifest.content_hash,
            "validation_dataset_hash": self.validation_dataset_hash,
        }
        _verify_authority("validation-provenance", payload, self._authority)

    @property
    def parent_provenance(self) -> TrainingProvenance:
        return TrainingProvenance(self.manifest, self.manifest.inner_train.rows_hash)

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest": self.manifest.to_dict(),
            "validation_dataset_hash": self.validation_dataset_hash,
        }

    @classmethod
    def _from_dict(cls, payload: Mapping[str, object]) -> InnerValidationProvenance:
        manifest = NestedFoldManifest._from_dict(_mapping(payload["manifest"]))
        validation_hash = str(payload["validation_dataset_hash"])
        authority_payload = {
            "manifest_hash": manifest.content_hash,
            "validation_dataset_hash": validation_hash,
        }
        return _sealed_instance(
            cls,
            manifest=manifest,
            validation_dataset_hash=validation_hash,
            _authority=_authority_tag("validation-provenance", authority_payload),
        )


@dataclass(frozen=True, slots=True, init=False)
class InnerValidationDataset(_SealedAuthority):
    manifest: NestedFoldManifest
    rows: tuple[Phase4SourceRow, ...]
    validation_dataset_hash: str
    _authority: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _verify_capability(
            self.manifest.inner_validation,
            self.rows,
            self.validation_dataset_hash,
        )
        if any(row.label == "AMBIGUOUS" or not row.is_complete for row in self.rows):
            raise ValueError("validation rows require complete known outcomes")
        payload = _capability_payload(
            self.manifest,
            SplitRole.INNER_VALIDATION,
            self.rows,
            self.validation_dataset_hash,
        )
        _verify_authority("inner-validation-dataset", payload, self._authority)

    @property
    def provenance(self) -> InnerValidationProvenance:
        payload = {
            "manifest_hash": self.manifest.content_hash,
            "validation_dataset_hash": self.validation_dataset_hash,
        }
        return _sealed_instance(
            InnerValidationProvenance,
            manifest=self.manifest,
            validation_dataset_hash=self.validation_dataset_hash,
            _authority=_authority_tag("validation-provenance", payload),
        )


@dataclass(frozen=True, slots=True, init=False)
class OuterTestDataset(_SealedAuthority):
    manifest: NestedFoldManifest
    rows: tuple[Phase4SourceRow, ...]
    outer_test_hash: str
    _authority: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _verify_capability(self.manifest.outer_test, self.rows, self.outer_test_hash)
        payload = _capability_payload(
            self.manifest,
            SplitRole.OUTER_TEST,
            self.rows,
            self.outer_test_hash,
        )
        _verify_authority("outer-test-dataset", payload, self._authority)


@dataclass(frozen=True, slots=True, init=False)
class Phase4FoldMaterializer(_SealedAuthority):
    source_version: str
    source_rows: tuple[Phase4SourceRow, ...]
    source_dataset_hash: str
    manifest: NestedFoldManifest
    inner_train: InnerTrainDataset
    inner_validation: InnerValidationDataset
    outer_test: OuterTestDataset
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _MATERIALIZER_SEAL:
            raise ValueError("fold materialization requires trusted source planner")
        if self.source_dataset_hash != _source_dataset_hash(self.source_rows):
            raise ValueError("materializer source dataset hash mismatch")
        if self.source_version != _source_dataset_version(self.source_dataset_hash):
            raise ValueError("materializer source dataset version mismatch")
        if self.manifest.source_dataset_hash != self.source_dataset_hash:
            raise ValueError("materializer manifest source mismatch")
        if (
            self.inner_train.manifest != self.manifest
            or self.inner_validation.manifest != self.manifest
            or self.outer_test.manifest != self.manifest
        ):
            raise ValueError("materializer capabilities do not share the committed manifest")

    @classmethod
    def materialize(
        cls,
        *,
        source_rows: Sequence[Phase4SourceRow],
        outer_fold_id: str,
        inner_fold_id: str,
        train_start: datetime,
        train_end: datetime,
        validation_start: datetime,
        validation_end: datetime,
        outer_test_start: datetime,
        outer_test_end: datetime,
    ) -> Phase4FoldMaterializer:
        ordered = tuple(sorted(source_rows, key=lambda row: (row.available_at, row.row_id)))
        if not ordered or len({row.row_id for row in ordered}) != len(ordered):
            raise ValueError("materializer requires unique immutable source rows")
        _exact_feature_order(ordered, "source")
        if not (
            train_start < train_end
            < validation_start < validation_end
            < outer_test_start < outer_test_end
        ):
            raise ValueError("fold plan intervals must be ordered and disjoint")
        source_hash = _source_dataset_hash(ordered)
        source_version = _source_dataset_version(source_hash)
        plan_payload = _fold_plan_payload(
            outer_fold_id=outer_fold_id,
            inner_fold_id=inner_fold_id,
            source_dataset_hash=source_hash,
            train_start=train_start,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            outer_test_start=outer_test_start,
            outer_test_end=outer_test_end,
        )
        plan_hash = canonical_hash(plan_payload)
        train_rows = _slice(ordered, train_start, train_end)
        validation_rows = _slice(ordered, validation_start, validation_end)
        outer_rows = _slice(ordered, outer_test_start, outer_test_end)
        train_commitment = _commit_role(SplitRole.INNER_TRAIN, train_start, train_end, train_rows)
        validation_commitment = _commit_role(
            SplitRole.INNER_VALIDATION,
            validation_start,
            validation_end,
            validation_rows,
        )
        outer_commitment = _commit_role(SplitRole.OUTER_TEST, outer_test_start, outer_test_end, outer_rows)
        manifest_payload = {
            "outer_fold_id": outer_fold_id,
            "inner_fold_id": inner_fold_id,
            "source_version": source_version,
            "source_dataset_hash": source_hash,
            "plan_hash": plan_hash,
            "inner_train": train_commitment.to_dict(),
            "inner_validation": validation_commitment.to_dict(),
            "outer_test": outer_commitment.to_dict(),
        }
        manifest_hash = canonical_hash(manifest_payload)
        manifest = _sealed_instance(
            NestedFoldManifest,
            outer_fold_id=outer_fold_id,
            inner_fold_id=inner_fold_id,
            source_version=source_version,
            source_dataset_hash=source_hash,
            plan_hash=plan_hash,
            inner_train=train_commitment,
            inner_validation=validation_commitment,
            outer_test=outer_commitment,
            content_hash=manifest_hash,
            _authority=_authority_tag(
                "manifest",
                {**manifest_payload, "content_hash": manifest_hash},
            ),
        )
        inner_train = _inner_train_dataset(manifest, train_rows)
        inner_validation = _inner_validation_dataset(manifest, validation_rows)
        outer_test = _outer_test_dataset(manifest, outer_rows)
        return _sealed_instance(
            cls,
            source_version=source_version,
            source_rows=ordered,
            source_dataset_hash=source_hash,
            manifest=manifest,
            inner_train=inner_train,
            inner_validation=inner_validation,
            outer_test=outer_test,
            _seal=_MATERIALIZER_SEAL,
        )


@dataclass(frozen=True, slots=True, init=False)
class InnerValidationPrediction(_SealedAuthority):
    source_row_id: str
    source_row_hash: str
    available_at: datetime
    p_trade: float
    trade_outcome: int
    p_long_given_trade: float | None
    direction_outcome: int | None
    net_return: float
    _seal: object = field(repr=False, compare=False)
    _authority: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _GENERATED_PREDICTION_SEAL:
            raise ValueError("inner-validation predictions must be generated by Phase 4 composition")
        validate_sha256(self.source_row_hash, "prediction source row hash")
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
        _verify_authority("prediction-row", self._payload(), self._authority)

    def payload(self) -> dict[str, object]:
        return self._payload()

    def _payload(self) -> dict[str, object]:
        return {
            "source_row_id": self.source_row_id,
            "source_row_hash": self.source_row_hash,
            "available_at": self.available_at.isoformat(),
            "p_trade": self.p_trade,
            "trade_outcome": self.trade_outcome,
            "p_long_given_trade": self.p_long_given_trade,
            "direction_outcome": self.direction_outcome,
            "net_return": self.net_return,
        }


@dataclass(frozen=True, slots=True, init=False)
class InnerValidationPredictions(_SealedAuthority):
    provenance: InnerValidationProvenance
    preprocessor_hash: str
    model_hash: str
    rows: tuple[InnerValidationPrediction, ...]
    validation_hash: str
    _seal: object = field(repr=False, compare=False)
    _authority: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _GENERATED_PREDICTION_SEAL:
            raise ValueError("inner-validation predictions must be generated by Phase 4 composition")
        validate_sha256(self.preprocessor_hash, "preprocessor hash")
        validate_sha256(self.model_hash, "model hash")
        validate_sha256(self.validation_hash, "validation prediction hash")
        if not self.rows:
            raise ValueError("inner-validation predictions are required")
        committed = self.provenance.manifest.inner_validation.row_hashes
        actual = tuple((row.source_row_id, row.source_row_hash) for row in self.rows)
        if actual != committed:
            raise ValueError("predictions do not match committed validation source rows")
        payload = self._payload()
        if canonical_hash(payload) != self.validation_hash:
            raise ValueError("validation prediction hash mismatch")
        _verify_authority(
            "predictions",
            {**payload, "validation_hash": self.validation_hash},
            self._authority,
        )

    def _payload(self) -> dict[str, object]:
        return {
            "provenance": self.provenance.to_dict(),
            "preprocessor_hash": self.preprocessor_hash,
            "model_hash": self.model_hash,
            "rows": [row.payload() for row in self.rows],
        }


def _generated_prediction(
    *,
    source_row: Phase4SourceRow,
    p_trade: float,
    trade_outcome: int,
    p_long_given_trade: float | None,
    direction_outcome: int | None,
) -> InnerValidationPrediction:
    payload = {
        "source_row_id": source_row.row_id,
        "source_row_hash": source_row.content_hash,
        "available_at": source_row.available_at.isoformat(),
        "p_trade": p_trade,
        "trade_outcome": trade_outcome,
        "p_long_given_trade": p_long_given_trade,
        "direction_outcome": direction_outcome,
        "net_return": source_row.net_return,
    }
    return _sealed_instance(
        InnerValidationPrediction,
        source_row_id=source_row.row_id,
        source_row_hash=source_row.content_hash,
        available_at=source_row.available_at,
        p_trade=p_trade,
        trade_outcome=trade_outcome,
        p_long_given_trade=p_long_given_trade,
        direction_outcome=direction_outcome,
        net_return=source_row.net_return,
        _seal=_GENERATED_PREDICTION_SEAL,
        _authority=_authority_tag("prediction-row", payload),
    )


def _generated_predictions(
    *,
    provenance: InnerValidationProvenance,
    preprocessor_hash: str,
    model_hash: str,
    rows: Sequence[InnerValidationPrediction],
) -> InnerValidationPredictions:
    frozen_rows = tuple(rows)
    payload = {
        "provenance": provenance.to_dict(),
        "preprocessor_hash": preprocessor_hash,
        "model_hash": model_hash,
        "rows": [row.payload() for row in frozen_rows],
    }
    validation_hash = canonical_hash(payload)
    return _sealed_instance(
        InnerValidationPredictions,
        provenance=provenance,
        preprocessor_hash=preprocessor_hash,
        model_hash=model_hash,
        rows=frozen_rows,
        validation_hash=validation_hash,
        _seal=_GENERATED_PREDICTION_SEAL,
        _authority=_authority_tag(
            "predictions",
            {**payload, "validation_hash": validation_hash},
        ),
    )


_SealedAuthorityType = TypeVar("_SealedAuthorityType", bound=_SealedAuthority)


def _sealed_instance(
    cls: type[_SealedAuthorityType],
    /,
    **values: object,
) -> _SealedAuthorityType:
    instance = object.__new__(cls)
    for name, value in values.items():
        object.__setattr__(instance, name, value)
    post_init = cast(Callable[[], None], getattr(instance, "__post_init__"))
    post_init()
    return instance


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


def _source_dataset_hash(rows: Sequence[Phase4SourceRow]) -> str:
    return canonical_hash({"rows": [row.payload() for row in rows]})


def _source_dataset_version(source_dataset_hash: str) -> str:
    validate_sha256(source_dataset_hash, "source dataset hash")
    return f"phase4-source-{source_dataset_hash[:16]}"


def _fold_plan_payload(
    *,
    outer_fold_id: str,
    inner_fold_id: str,
    source_dataset_hash: str,
    train_start: datetime,
    train_end: datetime,
    validation_start: datetime,
    validation_end: datetime,
    outer_test_start: datetime,
    outer_test_end: datetime,
) -> dict[str, str]:
    return {
        "outer_fold_id": outer_fold_id,
        "inner_fold_id": inner_fold_id,
        "source_dataset_hash": source_dataset_hash,
        "train_start": train_start.isoformat(),
        "train_end": train_end.isoformat(),
        "validation_start": validation_start.isoformat(),
        "validation_end": validation_end.isoformat(),
        "outer_test_start": outer_test_start.isoformat(),
        "outer_test_end": outer_test_end.isoformat(),
    }


def _row_commitment_hash(row_hashes: Sequence[tuple[str, str]]) -> str:
    return canonical_hash([list(item) for item in row_hashes])


def _slice(
    rows: Sequence[Phase4SourceRow],
    start: datetime,
    end: datetime,
) -> tuple[Phase4SourceRow, ...]:
    selected = tuple(row for row in rows if start <= row.available_at <= end)
    if not selected:
        raise ValueError("every committed fold role requires source rows")
    return selected


def _commit_role(
    role: SplitRole,
    start: datetime,
    end: datetime,
    rows: Sequence[Phase4SourceRow],
) -> RoleCommitment:
    row_hashes = tuple((row.row_id, row.content_hash) for row in rows)
    payload = {
        "role": role.value,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "row_hashes": [list(item) for item in row_hashes],
        "row_ids_hash": canonical_hash([row.row_id for row in rows]),
        "rows_hash": _row_commitment_hash(row_hashes),
        "count": len(rows),
    }
    return _sealed_instance(
        RoleCommitment,
        role=role,
        start=start,
        end=end,
        row_hashes=row_hashes,
        row_ids_hash=cast(str, payload["row_ids_hash"]),
        rows_hash=cast(str, payload["rows_hash"]),
        count=len(rows),
        _authority=_authority_tag("role", payload),
    )


def _role_from_dict(payload: Mapping[str, object]) -> RoleCommitment:
    try:
        role = SplitRole(str(payload["role"]))
    except ValueError as error:
        raise ValueError("invalid split role") from error
    row_hashes = tuple(
        (str(item[0]), str(item[1]))
        for item in _pairs(payload["row_hashes"])
    )
    start_text = str(payload["start"])
    end_text = str(payload["end"])
    row_ids_hash = str(payload["row_ids_hash"])
    rows_hash = str(payload["rows_hash"])
    count = _integer(payload["count"])
    values = {
        "role": role.value,
        "start": start_text,
        "end": end_text,
        "row_hashes": [list(item) for item in row_hashes],
        "row_ids_hash": row_ids_hash,
        "rows_hash": rows_hash,
        "count": count,
    }
    return _sealed_instance(
        RoleCommitment,
        role=role,
        start=datetime.fromisoformat(start_text),
        end=datetime.fromisoformat(end_text),
        row_hashes=row_hashes,
        row_ids_hash=row_ids_hash,
        rows_hash=rows_hash,
        count=count,
        _authority=_authority_tag("role", values),
    )


def _inner_train_dataset(
    manifest: NestedFoldManifest,
    rows: tuple[Phase4SourceRow, ...],
) -> InnerTrainDataset:
    train_hash = manifest.inner_train.rows_hash
    payload = _capability_payload(manifest, SplitRole.INNER_TRAIN, rows, train_hash)
    return _sealed_instance(
        InnerTrainDataset,
        manifest=manifest,
        rows=rows,
        train_hash=train_hash,
        _authority=_authority_tag("inner-train-dataset", payload),
    )


def _inner_validation_dataset(
    manifest: NestedFoldManifest,
    rows: tuple[Phase4SourceRow, ...],
) -> InnerValidationDataset:
    validation_hash = manifest.inner_validation.rows_hash
    payload = _capability_payload(
        manifest,
        SplitRole.INNER_VALIDATION,
        rows,
        validation_hash,
    )
    return _sealed_instance(
        InnerValidationDataset,
        manifest=manifest,
        rows=rows,
        validation_dataset_hash=validation_hash,
        _authority=_authority_tag("inner-validation-dataset", payload),
    )


def _outer_test_dataset(
    manifest: NestedFoldManifest,
    rows: tuple[Phase4SourceRow, ...],
) -> OuterTestDataset:
    outer_hash = manifest.outer_test.rows_hash
    payload = _capability_payload(manifest, SplitRole.OUTER_TEST, rows, outer_hash)
    return _sealed_instance(
        OuterTestDataset,
        manifest=manifest,
        rows=rows,
        outer_test_hash=outer_hash,
        _authority=_authority_tag("outer-test-dataset", payload),
    )


def _verify_capability(
    commitment: RoleCommitment,
    rows: Sequence[Phase4SourceRow],
    rows_hash: str,
) -> None:
    if not rows or len(rows) != commitment.count:
        raise ValueError("capability row count does not match committed role")
    if rows_hash != commitment.rows_hash:
        raise ValueError("capability row hash does not match committed role")
    if tuple((row.row_id, row.content_hash) for row in rows) != commitment.row_hashes:
        raise ValueError("capability source rows contradict committed row hashes")
    if _row_commitment_hash(tuple((row.row_id, row.content_hash) for row in rows)) != commitment.rows_hash:
        raise ValueError("capability source content contradicts committed rows")
    if any(row.available_at < commitment.start or row.available_at > commitment.end for row in rows):
        raise ValueError("capability row lies outside committed role interval")


def _capability_payload(
    manifest: NestedFoldManifest,
    role: SplitRole,
    rows: Sequence[Phase4SourceRow],
    rows_hash: str,
) -> dict[str, object]:
    return {
        "manifest_hash": manifest.content_hash,
        "role": role.value,
        "rows_hash": rows_hash,
        "rows": [row.payload() for row in rows],
    }


def _authority_tag(kind: str, payload: object) -> str:
    return canonical_hash({"domain": _AUTHORITY_DOMAIN, "kind": kind, "payload": payload})


def _verify_authority(kind: str, payload: object, authority: str) -> None:
    validate_sha256(authority, "authority tag")
    if authority != _authority_tag(kind, payload):
        raise ValueError("authority authentication mismatch")


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


def _exact_feature_order(rows: Sequence[Phase4SourceRow], name: str) -> None:
    feature_orders = {tuple(row.features) for row in rows}
    if len(feature_orders) != 1:
        raise ValueError(f"{name} rows must share exact feature order")


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expected mapping")
    return cast(Mapping[str, object], value)


def _pairs(value: object) -> list[list[object]]:
    if not isinstance(value, list) or not all(
        isinstance(item, list) and len(item) == 2
        for item in value
    ):
        raise ValueError("expected pair list")
    return cast(list[list[object]], value)


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected integer")
    return value
