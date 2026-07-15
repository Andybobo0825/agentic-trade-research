from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from tmf_research.models.calibration import Calibrator, calibrator_from_dict
from tmf_research.models.inference import ClassProbabilities, combine_probabilities
from tmf_research.models.logistic import BinaryLogisticModel, TwoStageLogisticModel, TwoStageTrainingRecord
from tmf_research.models.scaler import FoldPreprocessor


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

    def __post_init__(self) -> None:
        for name in ("created_at", "training_start", "training_end"):
            value = cast(datetime, getattr(self, name))
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.training_end <= self.training_start:
            raise ValueError("training interval must be positive")
        if not all(str(getattr(self, item.name)).strip() for item in fields(self) if item.type == "str"):
            raise ValueError("model metadata strings are required")

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id, "model_version": self.model_version,
            "created_at": self.created_at.isoformat(), "training_start": self.training_start.isoformat(),
            "training_end": self.training_end.isoformat(), "instrument": self.instrument, "session": self.session,
            "horizon": self.horizon, "feature_version": self.feature_version, "label_version": self.label_version,
            "schema_version": self.schema_version, "code_commit": self.code_commit, "random_seed": self.random_seed,
            "training_data_hash": self.training_data_hash, "experiment_id": self.experiment_id,
            "outer_fold_count": self.outer_fold_count, "locked_holdout_status": self.locked_holdout_status,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ModelMetadata:
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
        )


@dataclass(frozen=True, slots=True)
class ModelInference:
    signal: Literal["NO_TRADE", "LONG", "SHORT"]
    probabilities: ClassProbabilities
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelBundle:
    metadata: ModelMetadata
    feature_names: tuple[str, ...]
    feature_manifest: Mapping[str, object]
    preprocessor: FoldPreprocessor
    model: TwoStageLogisticModel
    calibrator: Calibrator

    def __post_init__(self) -> None:
        if self.feature_manifest.get("version") != self.metadata.feature_version:
            raise ValueError("feature manifest version mismatch")
        if self.feature_names != self.preprocessor.feature_order:
            raise ValueError("feature order and preprocessor mismatch")
        if self.model.trade_model.feature_order != self.preprocessor.output_feature_order:
            raise ValueError("trade model feature order mismatch")
        if self.model.direction_model.feature_order != self.preprocessor.output_feature_order:
            raise ValueError("direction model feature order mismatch")

    def predict(self, row: Mapping[str, float | None]) -> ModelInference:
        transformed = self.preprocessor.transform(row)
        if not transformed.is_eligible:
            return ModelInference("NO_TRADE", ClassProbabilities(1.0, 0.0, 0.0), transformed.reasons)
        p_trade = self.calibrator.calibrate(self.model.trade_model.predict_probability(transformed.values))
        probabilities = combine_probabilities(
            p_trade=p_trade,
            p_long_given_trade=self.model.direction_model.predict_probability(transformed.values),
        )
        signal: Literal["NO_TRADE", "LONG", "SHORT"]
        maximum = max(probabilities.as_tuple())
        signal = "NO_TRADE" if probabilities.p_no_trade == maximum else ("LONG" if probabilities.p_long == maximum else "SHORT")
        return ModelInference(signal, probabilities)


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
            "feature_version": bundle.metadata.feature_version,
            "feature_order": bundle.feature_names,
            "instrument": bundle.metadata.instrument,
            "session": bundle.metadata.session,
            "horizon": bundle.metadata.horizon,
            "schema_version": bundle.metadata.schema_version,
            "scaler_dimension": bundle.preprocessor.scaler.dimension,
            "imputer_dimension": bundle.preprocessor.imputer.output_dimension,
            "model_checksum": None,
        }
        unknown = set(overrides) - set(values)
        if unknown:
            raise ValueError(f"unknown expected contract override:{sorted(unknown)}")
        values.update(overrides)
        return cls(
            feature_version=_string(values["feature_version"]),
            feature_order=_string_tuple(values["feature_order"]),
            instrument=_string(values["instrument"]), session=_string(values["session"]),
            horizon=_string(values["horizon"]), schema_version=_string(values["schema_version"]),
            scaler_dimension=_integer(values["scaler_dimension"]),
            imputer_dimension=_integer(values["imputer_dimension"]),
            model_checksum=_optional_string(values["model_checksum"]),
        )


@dataclass(frozen=True, slots=True)
class ModelLoadResult:
    bundle: ModelBundle | None
    signal: Literal["NO_TRADE"] | None
    reasons: tuple[str, ...]
    checksum: str | None


def save_model_bundle(bundle: ModelBundle, root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    if any((root / name).exists() for name in (*REGISTRY_FILES, "checksum.sha256")):
        raise FileExistsError("model bundle is immutable")
    record = bundle.model.record
    payloads: dict[str, object] = {
        "metadata.json": bundle.metadata.to_dict(),
        "feature_names.json": list(bundle.feature_names),
        "feature_manifest.json": dict(bundle.feature_manifest),
        "scaler.json": bundle.preprocessor.to_dict(),
        "imputer.json": bundle.preprocessor.imputer.to_dict(),
        "trade_model.json": {
            "model": bundle.model.trade_model.to_dict(),
            "two_stage_record": {
                "input_count": record.input_count, "eligible_count": record.eligible_count,
                "excluded_ambiguous": record.excluded_ambiguous, "excluded_incomplete": record.excluded_incomplete,
                "model_a_target": record.model_a_target, "model_b_target": record.model_b_target,
            },
        },
        "direction_model.json": bundle.model.direction_model.to_dict(),
        "calibrator.json": bundle.calibrator.to_dict(),
        "fold_metrics.json": {"status": "PHASE5_NOT_RUN"},
        "stability_report.json": {"status": "PHASE5_NOT_RUN"},
        "ablation_report.json": {"status": "PHASE5_NOT_RUN"},
        "overfitting_report.json": {"status": "PHASE5_NOT_RUN"},
    }
    for name in REGISTRY_FILES:
        _write_once(root / name, _canonical(payloads[name]))
    checksum = _bundle_checksum(root)
    _write_once(root / "checksum.sha256", (checksum + "\n").encode("ascii"))
    return checksum


def load_model_bundle(root: Path, expected: ExpectedModelContract) -> ModelLoadResult:
    missing = tuple(name for name in (*REGISTRY_FILES, "checksum.sha256") if not (root / name).is_file())
    if missing:
        return _rejected(*(f"MODEL_FILE_MISSING:{name}" for name in missing))
    declared = (root / "checksum.sha256").read_text(encoding="ascii").strip()
    actual = _bundle_checksum(root)
    if len(declared) != 64 or declared != actual:
        return _rejected("MODEL_CHECKSUM_MISMATCH", checksum=actual)
    if expected.model_checksum is not None and expected.model_checksum != actual:
        return _rejected("EXPECTED_MODEL_CHECKSUM_MISMATCH", checksum=actual)
    try:
        metadata = ModelMetadata.from_dict(_object(root / "metadata.json"))
        feature_names = tuple(_string_list(root / "feature_names.json"))
        manifest = _object(root / "feature_manifest.json")
        preprocessor = FoldPreprocessor.from_dict(_object(root / "scaler.json"))
        imputer_payload = _object(root / "imputer.json")
        if _canonical(imputer_payload) != _canonical(preprocessor.imputer.to_dict()):
            return _rejected("IMPUTER_FILE_MISMATCH", checksum=actual)
        trade_payload = _object(root / "trade_model.json")
        trade_model = BinaryLogisticModel.from_dict(_mapping(trade_payload["model"]))
        direction_model = BinaryLogisticModel.from_dict(_object(root / "direction_model.json"))
        record_payload = _mapping(trade_payload["two_stage_record"])
        record = TwoStageTrainingRecord(
            input_count=_integer(record_payload["input_count"]), eligible_count=_integer(record_payload["eligible_count"]),
            excluded_ambiguous=_integer(record_payload["excluded_ambiguous"]), excluded_incomplete=_integer(record_payload["excluded_incomplete"]),
            model_a_target=str(record_payload["model_a_target"]), model_b_target=str(record_payload["model_b_target"]),
        )
        bundle = ModelBundle(
            metadata, feature_names, manifest, preprocessor,
            TwoStageLogisticModel(trade_model, direction_model, record),
            calibrator_from_dict(_object(root / "calibrator.json")),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _rejected(f"MODEL_BUNDLE_INVALID:{type(error).__name__}", checksum=actual)
    reasons = _contract_mismatches(bundle, expected)
    if reasons:
        return _rejected(*reasons, checksum=actual)
    return ModelLoadResult(bundle, None, (), actual)


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
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(payload)
    return digest.hexdigest()


def _canonical(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _write_once(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


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
    if value is None:
        return None
    return _string(value)
