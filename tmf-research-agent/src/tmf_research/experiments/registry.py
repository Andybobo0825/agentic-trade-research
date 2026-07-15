from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from tmf_research.experiments.comparison import ComparisonContext
from tmf_research.experiments.search_budget import SearchSpaceManifest


AttemptStatus = Literal["SUCCEEDED", "FAILED"]
DataProvenance = Literal["REAL_READONLY_MARKET_DATA", "SYNTHETIC_TEST_ONLY"]
ModelStatus = Literal[
    "DRAFT",
    "VALIDATING",
    "REJECTED_LEAKAGE",
    "REJECTED_INSUFFICIENT_DATA",
    "REJECTED_OVERFIT_RISK",
    "REJECTED_UNSTABLE",
    "CANDIDATE",
    "LOCKED_TEST_PENDING",
    "LOCKED_TEST_FAILED",
    "APPROVED_FOR_PAPER",
    "RETIRED",
]
MODEL_STATUSES = (
    "DRAFT",
    "VALIDATING",
    "REJECTED_LEAKAGE",
    "REJECTED_INSUFFICIENT_DATA",
    "REJECTED_OVERFIT_RISK",
    "REJECTED_UNSTABLE",
    "CANDIDATE",
    "LOCKED_TEST_PENDING",
    "LOCKED_TEST_FAILED",
    "APPROVED_FOR_PAPER",
    "RETIRED",
)
_ALLOWED_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "DRAFT": frozenset({"VALIDATING", "REJECTED_LEAKAGE", "REJECTED_INSUFFICIENT_DATA", "RETIRED"}),
    "VALIDATING": frozenset({"REJECTED_LEAKAGE", "REJECTED_INSUFFICIENT_DATA", "REJECTED_OVERFIT_RISK", "REJECTED_UNSTABLE", "CANDIDATE", "RETIRED"}),
    "CANDIDATE": frozenset({"LOCKED_TEST_PENDING", "REJECTED_OVERFIT_RISK", "REJECTED_UNSTABLE", "RETIRED"}),
    "LOCKED_TEST_PENDING": frozenset({"LOCKED_TEST_FAILED", "APPROVED_FOR_PAPER", "RETIRED"}),
    "APPROVED_FOR_PAPER": frozenset({"RETIRED"}),
    "REJECTED_LEAKAGE": frozenset({"RETIRED"}),
    "REJECTED_INSUFFICIENT_DATA": frozenset({"RETIRED"}),
    "REJECTED_OVERFIT_RISK": frozenset({"RETIRED"}),
    "REJECTED_UNSTABLE": frozenset({"RETIRED"}),
    "LOCKED_TEST_FAILED": frozenset({"RETIRED"}),
    "RETIRED": frozenset(),
}


def transition_model_status(
    current: ModelStatus,
    target: ModelStatus,
    *,
    data_provenance: DataProvenance,
) -> ModelStatus:
    if current not in MODEL_STATUSES or target not in MODEL_STATUSES:
        raise ValueError("model state is outside fixed SPEC 42 states")
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"forbidden model state transition: {current}->{target}")
    if data_provenance == "SYNTHETIC_TEST_ONLY" and target in ("LOCKED_TEST_PENDING", "APPROVED_FOR_PAPER"):
        raise ValueError("synthetic evidence cannot enter a production approval path")
    return target


@dataclass(frozen=True, slots=True)
class ExperimentDefinition:
    experiment_id: str
    created_at: datetime
    hypothesis: str
    feature_set_id: str
    label_version: str
    model_family: str
    parameter_space: SearchSpaceManifest
    primary_metric: str
    secondary_metrics: tuple[str, ...]
    train_period: str
    locked_holdout_status: str
    comparison: ComparisonContext

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("experiment created_at must be timezone-aware")
        strings = (
            self.experiment_id,
            self.hypothesis,
            self.feature_set_id,
            self.label_version,
            self.model_family,
            self.primary_metric,
            self.train_period,
            self.locked_holdout_status,
        )
        if any(not value.strip() for value in strings) or not self.secondary_metrics:
            raise ValueError("complete experiment preregistration is required")
        if not self.parameter_space.permits("feature_sets", self.feature_set_id):
            raise ValueError("feature set is outside preregistered space")
        if not self.parameter_space.permits("model_families", self.model_family):
            raise ValueError("model family is outside preregistered space")

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "created_at": self.created_at.isoformat(),
            "hypothesis": self.hypothesis,
            "feature_set_id": self.feature_set_id,
            "label_version": self.label_version,
            "model_family": self.model_family,
            "parameter_space": self.parameter_space.to_dict(),
            "search_budget": self.parameter_space.limits.as_dict(),
            "search_manifest_hash": self.parameter_space.canonical_hash,
            "primary_metric": self.primary_metric,
            "secondary_metrics": list(self.secondary_metrics),
            "train_period": self.train_period,
            "locked_holdout_status": self.locked_holdout_status,
            "comparison": {
                name: getattr(self.comparison, name)
                for name in (
                    "dataset_version",
                    "outer_fold_plan_hash",
                    "cost_assumption_hash",
                    "label_version",
                    "evaluation_period",
                )
            },
        }


@dataclass(frozen=True, slots=True)
class ExperimentAttempt:
    attempt_id: str
    created_at: datetime
    model_family: str
    feature_set: str
    hyperparameter_combination: str
    barrier_combination: str
    threshold_combination: str
    calibration_method: str
    status: AttemptStatus
    result: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.attempt_id.strip() or self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("attempt id and aware timestamp are required")
        if self.status not in ("SUCCEEDED", "FAILED"):
            raise ValueError("attempt status must record success or failure")
        object.__setattr__(self, "result", dict(self.result))


class ExperimentRegistry:
    __slots__ = ("_root", "_definition", "_space")

    def __init__(self, root: Path) -> None:
        self._root = root
        definition_payload = _object(root / "definition.json")
        self._definition = definition_payload
        self._space = _space_from_payload(_mapping(definition_payload["parameter_space"]))
        self._verify()

    @classmethod
    def preregister(cls, root: Path, definition: ExperimentDefinition) -> ExperimentRegistry:
        if root.exists():
            raise FileExistsError(root)
        root.mkdir(parents=True)
        definition_payload = definition.to_dict()
        _write_exclusive(root / "definition.json", _canonical(definition_payload))
        _write_exclusive(root / "attempts.jsonl", b"")
        state = {
            "definition_hash": _hash(definition_payload),
            "search_manifest_hash": definition.parameter_space.canonical_hash,
            "attempt_count": 0,
            "chain_head": "0" * 64,
        }
        _write_exclusive(root / "state.json", _canonical(state))
        return cls(root)

    @property
    def definition_hash(self) -> str:
        return _hash(self._definition)

    @property
    def attempts(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._read_attempts())

    def append_attempt(self, attempt: ExperimentAttempt) -> None:
        self._verify()
        if any(existing["attempt_id"] == attempt.attempt_id for existing in self._read_attempts()):
            raise ValueError("attempt ids are append-only and unique")
        selected = {
            "model_families": attempt.model_family,
            "feature_sets": attempt.feature_set,
            "hyperparameter_combinations": attempt.hyperparameter_combination,
            "barrier_combinations": attempt.barrier_combination,
            "threshold_combinations": attempt.threshold_combination,
            "calibration_methods": attempt.calibration_method,
        }
        for dimension, identifier in selected.items():
            if not self._space.permits(dimension, identifier):
                raise ValueError(f"post-result neighbor or unregistered {dimension} is forbidden")
        state = _object(self._root / "state.json")
        body = {
            "attempt_id": attempt.attempt_id,
            "created_at": attempt.created_at.isoformat(),
            **selected,
            "status": attempt.status,
            "result": dict(attempt.result),
            "previous_hash": state["chain_head"],
        }
        entry = {**body, "entry_hash": _hash(body)}
        with (self._root / "attempts.jsonl").open("ab") as stream:
            stream.write(_canonical(entry))
            stream.flush()
            os.fsync(stream.fileno())
        state["attempt_count"] = _integer(state["attempt_count"]) + 1
        state["chain_head"] = entry["entry_hash"]
        _replace(self._root / "state.json", _canonical(state))
        self._verify()

    def _read_attempts(self) -> list[Mapping[str, object]]:
        values: list[Mapping[str, object]] = []
        for line in (self._root / "attempts.jsonl").read_text(encoding="utf-8").splitlines():
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                raise ValueError("attempt journal entry must be an object")
            values.append(cast(Mapping[str, object], parsed))
        return values

    def _verify(self) -> None:
        state = _object(self._root / "state.json")
        if state["definition_hash"] != _hash(self._definition):
            raise ValueError("preregistered experiment definition was mutated")
        if state["search_manifest_hash"] != self._space.canonical_hash:
            raise ValueError("search space expansion after start is forbidden")
        previous = "0" * 64
        attempts = self._read_attempts()
        for entry in attempts:
            body = {key: value for key, value in entry.items() if key != "entry_hash"}
            if entry.get("previous_hash") != previous or entry.get("entry_hash") != _hash(body):
                raise ValueError("attempt journal is not append-only")
            previous = str(entry["entry_hash"])
        if _integer(state["attempt_count"]) != len(attempts) or state["chain_head"] != previous:
            raise ValueError("attempt deletion/truncation detected")


REGISTRY_FILES = (
    "metadata.json",
    "feature_names.json",
    "feature_manifest.json",
    "scaler.json",
    "imputer.json",
    "trade_model.json",
    "direction_model.json",
    "calibrator.json",
    "fold_metrics.json",
    "stability_report.json",
    "ablation_report.json",
    "overfitting_report.json",
)
REQUIRED_METADATA = (
    "model_id",
    "model_version",
    "created_at",
    "training_start",
    "training_end",
    "instrument",
    "session",
    "horizon",
    "feature_version",
    "label_version",
    "code_commit",
    "random_seed",
    "training_data_hash",
    "experiment_id",
    "outer_fold_count",
    "locked_holdout_status",
    "schema_version",
    "model_status",
    "data_provenance",
)


@dataclass(frozen=True, slots=True)
class RegistryValidation:
    signal: Literal["NO_TRADE"] | None
    reasons: tuple[str, ...]
    checksum: str | None


@dataclass(frozen=True, slots=True)
class RegistryCompatibility:
    feature_version: str
    feature_order: tuple[str, ...]
    instrument: str
    session: str
    horizon: str
    schema_version: str
    scaler_dimension: int
    imputer_dimension: int
    model_checksum: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (
            self.feature_version, self.instrument, self.session, self.horizon, self.schema_version,
        )) or not self.feature_order:
            raise ValueError("complete runtime compatibility contract is required")
        if self.scaler_dimension <= 0 or self.imputer_dimension <= 0:
            raise ValueError("positive preprocessor dimensions are required")
        _sha256(self.model_checksum, "model_checksum")


def publish_model_registry(
    root: Path,
    *,
    metadata: Mapping[str, object],
    artifacts: Mapping[str, object],
) -> str:
    if root.exists():
        raise FileExistsError(root)
    missing_metadata = tuple(name for name in REQUIRED_METADATA if name not in metadata)
    if missing_metadata:
        raise ValueError("missing model provenance: " + ",".join(missing_metadata))
    _validate_metadata(metadata)
    status = str(metadata["model_status"])
    provenance = str(metadata["data_provenance"])
    if status not in MODEL_STATUSES:
        raise ValueError("model status is outside fixed SPEC 42 states")
    if provenance not in ("REAL_READONLY_MARKET_DATA", "SYNTHETIC_TEST_ONLY"):
        raise ValueError("unknown data provenance")
    if provenance == "SYNTHETIC_TEST_ONLY" and status in (
        "LOCKED_TEST_PENDING", "LOCKED_TEST_FAILED", "APPROVED_FOR_PAPER",
    ):
        raise ValueError("synthetic test evidence can never enter the locked production approval path")
    expected_artifacts = set(REGISTRY_FILES) - {"metadata.json"}
    if set(artifacts) != expected_artifacts:
        raise ValueError("all and only SPEC 37 registry artifacts are required")
    for hash_name in ("training_data_hash",):
        _sha256(str(metadata[hash_name]), hash_name)
    if isinstance(metadata["outer_fold_count"], bool) or not isinstance(metadata["outer_fold_count"], int):
        raise ValueError("outer_fold_count must be an integer")
    root.mkdir(parents=True)
    payloads = {"metadata.json": dict(metadata), **dict(artifacts)}
    for name in REGISTRY_FILES:
        _write_exclusive(root / name, _canonical(payloads[name]))
    checksum = _registry_checksum(root)
    _write_exclusive(root / "checksum.sha256", (checksum + "\n").encode("ascii"))
    return checksum


def validate_model_registry(
    root: Path,
    expected_checksum: str | None = None,
    *,
    expected: RegistryCompatibility | None = None,
) -> RegistryValidation:
    try:
        missing = tuple(name for name in (*REGISTRY_FILES, "checksum.sha256") if not (root / name).is_file())
        if missing:
            return RegistryValidation("NO_TRADE", tuple(f"MODEL_FILE_MISSING:{name}" for name in missing), None)
        declared = (root / "checksum.sha256").read_text(encoding="ascii").strip()
        actual = _registry_checksum(root)
        if declared != actual or (expected_checksum is not None and expected_checksum != actual):
            return RegistryValidation("NO_TRADE", ("MODEL_CHECKSUM_MISMATCH",), actual)
        metadata = _object(root / "metadata.json")
        missing_metadata = tuple(name for name in REQUIRED_METADATA if name not in metadata)
        if missing_metadata:
            return RegistryValidation("NO_TRADE", tuple(f"MODEL_PROVENANCE_MISSING:{name}" for name in missing_metadata), actual)
        _validate_metadata(metadata)
        if metadata["model_status"] not in MODEL_STATUSES:
            return RegistryValidation("NO_TRADE", ("MODEL_STATUS_INVALID",), actual)
        if metadata["data_provenance"] == "SYNTHETIC_TEST_ONLY" and metadata["model_status"] in (
            "LOCKED_TEST_PENDING", "LOCKED_TEST_FAILED", "APPROVED_FOR_PAPER",
        ):
            return RegistryValidation("NO_TRADE", ("SYNTHETIC_APPROVAL_FORBIDDEN",), actual)
        if expected is not None:
            feature_names = json.loads((root / "feature_names.json").read_text(encoding="utf-8"))
            scaler = _object(root / "scaler.json")
            imputer = _object(root / "imputer.json")
            checks = (
                (metadata["feature_version"] == expected.feature_version, "FEATURE_VERSION_MISMATCH"),
                (feature_names == list(expected.feature_order), "FEATURE_ORDER_MISMATCH"),
                (metadata["instrument"] == expected.instrument, "INSTRUMENT_MISMATCH"),
                (metadata["session"] == expected.session, "SESSION_MISMATCH"),
                (metadata["horizon"] == expected.horizon, "HORIZON_MISMATCH"),
                (metadata["schema_version"] == expected.schema_version, "SCHEMA_VERSION_MISMATCH"),
                (scaler.get("dimension") == expected.scaler_dimension, "SCALER_DIMENSION_MISMATCH"),
                (imputer.get("output_dimension") == expected.imputer_dimension, "IMPUTER_DIMENSION_MISMATCH"),
                (actual == expected.model_checksum, "EXPECTED_MODEL_CHECKSUM_MISMATCH"),
            )
            reasons = tuple(reason for valid, reason in checks if not valid)
            if reasons:
                return RegistryValidation("NO_TRADE", reasons, actual)
        return RegistryValidation(None, (), actual)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return RegistryValidation("NO_TRADE", ("MODEL_REGISTRY_INVALID",), None)


def validate_registry_for_inference(root: Path, expected: RegistryCompatibility) -> RegistryValidation:
    """Runtime-facing validation always requires a complete pinned contract."""
    return validate_model_registry(root, expected=expected)


def _space_from_payload(payload: Mapping[str, object]) -> SearchSpaceManifest:
    values: dict[str, tuple[str, ...]] = {}
    for name in (
        "model_families",
        "feature_sets",
        "hyperparameter_combinations",
        "barrier_combinations",
        "threshold_combinations",
        "calibration_methods",
    ):
        value = payload[name]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("invalid search space")
        values[name] = tuple(cast(list[str], value))
    return SearchSpaceManifest(
        model_families=values["model_families"],
        feature_sets=values["feature_sets"],
        hyperparameter_combinations=values["hyperparameter_combinations"],
        barrier_combinations=values["barrier_combinations"],
        threshold_combinations=values["threshold_combinations"],
        calibration_methods=values["calibration_methods"],
    )


def _validate_metadata(metadata: Mapping[str, object]) -> None:
    string_fields = (
        "model_id", "model_version", "created_at", "training_start", "training_end",
        "instrument", "session", "horizon", "feature_version", "label_version",
        "code_commit", "experiment_id", "locked_holdout_status", "schema_version",
        "model_status", "data_provenance",
    )
    if any(not isinstance(metadata[name], str) or not str(metadata[name]).strip() for name in string_fields):
        raise ValueError("model metadata strings must be present and non-empty")
    for name in ("created_at", "training_start", "training_end"):
        parsed = datetime.fromisoformat(str(metadata[name]))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")
    _sha256(str(metadata["training_data_hash"]), "training_data_hash")
    for name in ("random_seed", "outer_fold_count"):
        if not isinstance(metadata[name], int) or isinstance(metadata[name], bool):
            raise ValueError(f"{name} must be an integer")
    if cast(int, metadata["outer_fold_count"]) < 0:
        raise ValueError("outer_fold_count cannot be negative")


def _registry_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    for name in REGISTRY_FILES:
        payload = (root / name).read_bytes()
        digest.update(name.encode() + b"\0" + str(len(payload)).encode() + b"\0" + payload)
    return digest.hexdigest()


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return cast(dict[str, object], value)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expected mapping")
    return cast(Mapping[str, object], value)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _replace(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(".tmp")
    _write_exclusive(temporary, payload)
    os.replace(temporary, path)


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected integer")
    return value


def _sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"invalid {name}")
