from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from tmf_research.models.calibration import TwoStageCalibrator
from tmf_research.models.inference import ClassProbabilities, combine_probabilities
from tmf_research.models.logistic import BinaryLogisticModel, TwoStageLogisticModel, TwoStageTrainingRecord
from tmf_research.models.provenance import validate_sha256
from tmf_research.models.scaler import FoldPreprocessor


ModelStatus = Literal["DRAFT_PHASE4", "REJECTED_INSUFFICIENT_CALIBRATION"]
REGISTRY_FILES = (
    "metadata.json", "feature_names.json", "feature_manifest.json", "scaler.json", "imputer.json",
    "trade_model.json", "direction_model.json", "calibrator.json", "fold_metrics.json",
    "stability_report.json", "ablation_report.json", "overfitting_report.json",
)


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    model_id: str
    model_version: str
    created_at: datetime
    training_start: datetime
    training_end: datetime
    instrument: str
    session: str
    horizon: str
    feature_version: str
    label_version: str
    schema_version: str
    code_commit: str
    random_seed: int
    training_data_hash: str
    experiment_id: str
    outer_fold_count: int
    locked_holdout_status: str
    model_status: ModelStatus

    def __post_init__(self) -> None:
        for name in ("created_at", "training_start", "training_end"):
            value = cast(datetime, getattr(self, name))
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.training_end <= self.training_start:
            raise ValueError("training interval must be positive")
        validate_sha256(self.training_data_hash, "training data hash")
        if self.model_status not in ("DRAFT_PHASE4", "REJECTED_INSUFFICIENT_CALIBRATION"):
            raise ValueError("Phase 4 cannot persist an approved model status")

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id, "model_version": self.model_version,
            "created_at": self.created_at.isoformat(), "training_start": self.training_start.isoformat(),
            "training_end": self.training_end.isoformat(), "instrument": self.instrument, "session": self.session,
            "horizon": self.horizon, "feature_version": self.feature_version, "label_version": self.label_version,
            "schema_version": self.schema_version, "code_commit": self.code_commit, "random_seed": self.random_seed,
            "training_data_hash": self.training_data_hash, "experiment_id": self.experiment_id,
            "outer_fold_count": self.outer_fold_count, "locked_holdout_status": self.locked_holdout_status,
            "model_status": self.model_status,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ModelMetadata:
        status = str(payload["model_status"])
        if status not in ("DRAFT_PHASE4", "REJECTED_INSUFFICIENT_CALIBRATION"):
            raise ValueError("serialized model status is not allowed in Phase 4")
        return cls(
            model_id=str(payload["model_id"]), model_version=str(payload["model_version"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            training_start=datetime.fromisoformat(str(payload["training_start"])),
            training_end=datetime.fromisoformat(str(payload["training_end"])), instrument=str(payload["instrument"]),
            session=str(payload["session"]), horizon=str(payload["horizon"]), feature_version=str(payload["feature_version"]),
            label_version=str(payload["label_version"]), schema_version=str(payload["schema_version"]),
            code_commit=str(payload["code_commit"]), random_seed=_integer(payload["random_seed"]),
            training_data_hash=str(payload["training_data_hash"]), experiment_id=str(payload["experiment_id"]),
            outer_fold_count=_integer(payload["outer_fold_count"]), locked_holdout_status=str(payload["locked_holdout_status"]),
            model_status=cast(ModelStatus, status),
        )


@dataclass(frozen=True, slots=True)
class ModelInference:
    signal: Literal["NO_TRADE"]
    probabilities: ClassProbabilities
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelBundle:
    metadata: ModelMetadata
    feature_names: tuple[str, ...]
    feature_manifest: Mapping[str, object]
    preprocessor: FoldPreprocessor
    model: TwoStageLogisticModel
    calibrator: TwoStageCalibrator

    def __post_init__(self) -> None:
        if self.feature_manifest.get("version") != self.metadata.feature_version:
            raise ValueError("feature manifest version mismatch")
        if self.feature_names != self.preprocessor.feature_order:
            raise ValueError("feature order and preprocessor mismatch")
        if self.model.trade_model.feature_order != self.preprocessor.output_feature_order:
            raise ValueError("trade model feature order mismatch")
        if self.model.direction_model.feature_order != self.preprocessor.output_feature_order:
            raise ValueError("direction model feature order mismatch")
        if self.model.record.preprocessor_hash != self.preprocessor.content_hash:
            raise ValueError("model and preprocessor provenance mismatch")
        if self.model.record.provenance != self.preprocessor.provenance:
            raise ValueError("model and fold-manifest provenance mismatch")
        if self.metadata.training_data_hash != self.model.record.train_hash:
            raise ValueError("metadata training data provenance mismatch")
        if (
            self.metadata.training_start != self.preprocessor.provenance.fit_start
            or self.metadata.training_end != self.preprocessor.provenance.fit_end
        ):
            raise ValueError("metadata training interval provenance mismatch")
        if any(
            binary.random_seed != self.metadata.random_seed
            for binary in (self.model.trade_model, self.model.direction_model)
        ):
            raise ValueError("metadata random seed provenance mismatch")
        if self.calibrator.provenance != self.preprocessor.provenance:
            raise ValueError("calibrator fold provenance mismatch")
        if self.calibrator.preprocessor_hash != self.preprocessor.content_hash or self.calibrator.model_hash != self.model.content_hash:
            raise ValueError("calibrator model provenance mismatch")
        if self.calibrator.insufficient_evidence != (self.metadata.model_status == "REJECTED_INSUFFICIENT_CALIBRATION"):
            raise ValueError("model status and calibration evidence disagree")

    def predict(self, row: Mapping[str, float | None]) -> ModelInference:
        transformed = self.preprocessor.transform(row)
        if not transformed.is_eligible:
            return ModelInference("NO_TRADE", ClassProbabilities(1.0, 0.0, 0.0), transformed.reasons)
        try:
            p_trade, p_long = self.calibrator.calibrate(
                self.model.trade_model.predict_probability(transformed.values),
                self.model.direction_model.predict_probability(transformed.values),
            )
            probabilities = combine_probabilities(p_trade=p_trade, p_long_given_trade=p_long)
        except (ArithmeticError, ValueError):
            return ModelInference("NO_TRADE", ClassProbabilities(1.0, 0.0, 0.0), ("NONFINITE_MODEL_INFERENCE",))
        reason = (
            "INSUFFICIENT_CALIBRATION_EVIDENCE"
            if self.metadata.model_status == "REJECTED_INSUFFICIENT_CALIBRATION"
            else "PHASE4_RESEARCH_ONLY_DRAFT"
        )
        return ModelInference("NO_TRADE", probabilities, (reason,))


@dataclass(frozen=True, slots=True)
class ExpectedModelContract:
    feature_version: str
    feature_order: tuple[str, ...]
    instrument: str
    session: str
    horizon: str
    schema_version: str
    scaler_dimension: int
    imputer_dimension: int
    model_checksum: str | None = None

    @classmethod
    def from_bundle(cls, bundle: ModelBundle, **overrides: object) -> ExpectedModelContract:
        values: dict[str, object] = {
            "feature_version": bundle.metadata.feature_version, "feature_order": bundle.feature_names,
            "instrument": bundle.metadata.instrument, "session": bundle.metadata.session,
            "horizon": bundle.metadata.horizon, "schema_version": bundle.metadata.schema_version,
            "scaler_dimension": bundle.preprocessor.scaler.dimension,
            "imputer_dimension": bundle.preprocessor.imputer.output_dimension, "model_checksum": None,
        }
        if set(overrides) - set(values):
            raise ValueError("unknown expected contract override")
        values.update(overrides)
        return cls(
            _string(values["feature_version"]), _string_tuple(values["feature_order"]),
            _string(values["instrument"]), _string(values["session"]), _string(values["horizon"]),
            _string(values["schema_version"]), _integer(values["scaler_dimension"]),
            _integer(values["imputer_dimension"]), _optional_string(values["model_checksum"]),
        )


@dataclass(frozen=True, slots=True)
class ModelLoadResult:
    bundle: ModelBundle | None
    signal: Literal["NO_TRADE"] | None
    reasons: tuple[str, ...]
    checksum: str | None


def save_model_bundle(bundle: ModelBundle, root: Path) -> str:
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(exist_ok=False)
    record = bundle.model.record
    payloads: dict[str, object] = {
        "metadata.json": bundle.metadata.to_dict(), "feature_names.json": list(bundle.feature_names),
        "feature_manifest.json": dict(bundle.feature_manifest), "scaler.json": bundle.preprocessor.to_dict(),
        "imputer.json": bundle.preprocessor.imputer.to_dict(),
        "trade_model.json": {"model": bundle.model.trade_model.to_dict(), "two_stage_record": record.to_dict()},
        "direction_model.json": bundle.model.direction_model.to_dict(), "calibrator.json": bundle.calibrator.to_dict(),
        "fold_metrics.json": {"status": "PHASE5_NOT_RUN"}, "stability_report.json": {"status": "PHASE5_NOT_RUN"},
        "ablation_report.json": {"status": "PHASE5_NOT_RUN"}, "overfitting_report.json": {"status": "PHASE5_NOT_RUN"},
    }
    for name in REGISTRY_FILES:
        _write_exclusive(root / name, _canonical(payloads[name]))
    checksum = _bundle_checksum(root)
    _write_exclusive(root / "checksum.sha256", (checksum + "\n").encode("ascii"))
    return checksum


def load_model_bundle(root: Path, expected: ExpectedModelContract) -> ModelLoadResult:
    actual: str | None = None
    try:
        missing = tuple(name for name in (*REGISTRY_FILES, "checksum.sha256") if not (root / name).is_file())
        if missing:
            return _rejected(*(f"MODEL_FILE_MISSING:{name}" for name in missing))
        declared = (root / "checksum.sha256").read_text(encoding="ascii").strip()
        actual = _bundle_checksum(root)
        if len(declared) != 64 or declared != actual:
            return _rejected("MODEL_CHECKSUM_MISMATCH", checksum=actual)
        if expected.model_checksum is not None and expected.model_checksum != actual:
            return _rejected("EXPECTED_MODEL_CHECKSUM_MISMATCH", checksum=actual)
        metadata = ModelMetadata.from_dict(_object(root / "metadata.json"))
        feature_names = tuple(_string_list(root / "feature_names.json"))
        manifest = _object(root / "feature_manifest.json")
        preprocessor = FoldPreprocessor.from_dict(_object(root / "scaler.json"))
        if _canonical(_object(root / "imputer.json")) != _canonical(preprocessor.imputer.to_dict()):
            return _rejected("IMPUTER_FILE_MISMATCH", checksum=actual)
        trade_payload = _object(root / "trade_model.json")
        model = TwoStageLogisticModel(
            BinaryLogisticModel.from_dict(_mapping(trade_payload["model"])),
            BinaryLogisticModel.from_dict(_object(root / "direction_model.json")),
            TwoStageTrainingRecord.from_dict(_mapping(trade_payload["two_stage_record"])),
        )
        bundle = ModelBundle(
            metadata, feature_names, manifest, preprocessor, model,
            TwoStageCalibrator.from_dict(_object(root / "calibrator.json")),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return _rejected("MODEL_BUNDLE_INVALID", checksum=actual)
    except (OSError, UnicodeError):
        return _rejected("MODEL_BUNDLE_IO_ERROR")
    reasons = _contract_mismatches(bundle, expected)
    if reasons:
        return _rejected(*reasons, checksum=actual)
    return ModelLoadResult(bundle, None, (), actual)


def load_approved_model_bundle(_root: Path, _expected: ExpectedModelContract) -> ModelLoadResult:
    return _rejected("PHASE6_APPROVED_LOADER_NOT_IMPLEMENTED")


def _contract_mismatches(bundle: ModelBundle, expected: ExpectedModelContract) -> tuple[str, ...]:
    checks = (
        (bundle.metadata.feature_version == expected.feature_version, "FEATURE_VERSION_MISMATCH"),
        (bundle.feature_names == expected.feature_order, "FEATURE_ORDER_MISMATCH"),
        (bundle.metadata.instrument == expected.instrument, "INSTRUMENT_MISMATCH"),
        (bundle.metadata.session == expected.session, "SESSION_MISMATCH"),
        (bundle.metadata.horizon == expected.horizon, "HORIZON_MISMATCH"),
        (bundle.metadata.schema_version == expected.schema_version, "SCHEMA_VERSION_MISMATCH"),
        (bundle.preprocessor.scaler.dimension == expected.scaler_dimension, "SCALER_DIMENSION_MISMATCH"),
        (bundle.preprocessor.imputer.output_dimension == expected.imputer_dimension, "IMPUTER_DIMENSION_MISMATCH"),
    )
    return tuple(reason for valid, reason in checks if not valid)


def _bundle_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    for name in REGISTRY_FILES:
        payload = (root / name).read_bytes()
        digest.update(name.encode("utf-8") + b"\0" + str(len(payload)).encode("ascii") + b"\0" + payload)
    return digest.hexdigest()


def _canonical(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _object(path: Path) -> Mapping[str, object]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")))


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expected mapping")
    return cast(Mapping[str, object], value)


def _string_list(path: Path) -> list[str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected string list")
    return cast(list[str], value)


def _rejected(*reasons: str, checksum: str | None = None) -> ModelLoadResult:
    return ModelLoadResult(None, "NO_TRADE", tuple(reasons), checksum)


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected integer")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected string")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected string tuple")
    return cast(tuple[str, ...], value)


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)
