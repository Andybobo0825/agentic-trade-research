from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from tmf_research.experiments.comparison import ComparisonContext, require_canonical_fold_periods
from tmf_research.experiments.search_budget import SearchSpaceManifest
from tmf_research.validation.data_provenance import DataProvenanceEvidence, DataProvenanceKind
from tmf_research.infrastructure.trusted_witness import (
    SqliteTrustedWitness, TrustedWitness, WitnessHead, WitnessMissing, witness_subject,
)


AttemptStatus = Literal["SUCCEEDED", "FAILED"]
_EXPERIMENT_EVIDENCE_SEAL = object()
_COMMIT_SEAL = object()
class ModelStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    REJECTED_LEAKAGE = "REJECTED_LEAKAGE"
    REJECTED_INSUFFICIENT_DATA = "REJECTED_INSUFFICIENT_DATA"
    REJECTED_OVERFIT_RISK = "REJECTED_OVERFIT_RISK"
    REJECTED_UNSTABLE = "REJECTED_UNSTABLE"
    CANDIDATE = "CANDIDATE"
    LOCKED_TEST_PENDING = "LOCKED_TEST_PENDING"
    LOCKED_TEST_FAILED = "LOCKED_TEST_FAILED"
    APPROVED_FOR_PAPER = "APPROVED_FOR_PAPER"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True, init=False)
class SourceCommitEvidence:
    commit: str
    content_hash: str
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> SourceCommitEvidence:
        raise TypeError("source commit evidence must be issued by the commit verifier")

    def __post_init__(self) -> None:
        if self._seal is not _COMMIT_SEAL or not _git_commit(self.commit):
            raise TypeError("invalid source commit evidence")
        _sha256(self.content_hash, "source_commit_evidence")


def verified_source_commit(commit: str) -> SourceCommitEvidence:
    if not _git_commit(commit):
        raise ValueError("source commit must be one full 40-character lowercase hexadecimal id")
    instance = object.__new__(SourceCommitEvidence)
    for name, value in (("commit", commit), ("content_hash", _hash({"commit": commit})), ("_seal", _COMMIT_SEAL)):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


MODEL_STATUSES = tuple(status.value for status in ModelStatus)
_ALLOWED_TRANSITIONS: Mapping[ModelStatus, frozenset[ModelStatus]] = {
    ModelStatus.DRAFT: frozenset({ModelStatus.VALIDATING, ModelStatus.REJECTED_LEAKAGE, ModelStatus.REJECTED_INSUFFICIENT_DATA, ModelStatus.RETIRED}),
    ModelStatus.VALIDATING: frozenset({ModelStatus.REJECTED_LEAKAGE, ModelStatus.REJECTED_INSUFFICIENT_DATA, ModelStatus.REJECTED_OVERFIT_RISK, ModelStatus.REJECTED_UNSTABLE, ModelStatus.CANDIDATE, ModelStatus.RETIRED}),
    ModelStatus.CANDIDATE: frozenset({ModelStatus.LOCKED_TEST_PENDING, ModelStatus.REJECTED_OVERFIT_RISK, ModelStatus.REJECTED_UNSTABLE, ModelStatus.RETIRED}),
    ModelStatus.LOCKED_TEST_PENDING: frozenset({ModelStatus.LOCKED_TEST_FAILED, ModelStatus.APPROVED_FOR_PAPER, ModelStatus.RETIRED}),
    ModelStatus.APPROVED_FOR_PAPER: frozenset({ModelStatus.RETIRED}),
    ModelStatus.REJECTED_LEAKAGE: frozenset({ModelStatus.RETIRED}),
    ModelStatus.REJECTED_INSUFFICIENT_DATA: frozenset({ModelStatus.RETIRED}),
    ModelStatus.REJECTED_OVERFIT_RISK: frozenset({ModelStatus.RETIRED}),
    ModelStatus.REJECTED_UNSTABLE: frozenset({ModelStatus.RETIRED}),
    ModelStatus.LOCKED_TEST_FAILED: frozenset({ModelStatus.RETIRED}),
    ModelStatus.RETIRED: frozenset(),
}


def transition_model_status(
    current: ModelStatus,
    target: ModelStatus,
    *,
    data_provenance: DataProvenanceEvidence,
) -> ModelStatus:
    if not isinstance(current, ModelStatus) or not isinstance(target, ModelStatus):
        raise TypeError("model state must use the exact SPEC 42 enum")
    if not isinstance(data_provenance, DataProvenanceEvidence):
        raise TypeError("model transition requires sealed data provenance evidence")
    data_provenance.assert_current()
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"forbidden model state transition: {current}->{target}")
    if data_provenance.kind is DataProvenanceKind.SYNTHETIC_TEST_ONLY and target in (ModelStatus.LOCKED_TEST_PENDING, ModelStatus.APPROVED_FOR_PAPER):
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
    candidate_hashes: Mapping[str, str]

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
        if self.label_version != self.comparison.label_version:
            raise ValueError("experiment label version and comparison context must match")
        if set(self.candidate_hashes) != {"model", "features", "labels", "parameters", "thresholds", "rules"}:
            raise ValueError("experiment must preregister all frozen candidate component hashes")
        for name, value in self.candidate_hashes.items():
            _sha256(value, name)
        object.__setattr__(self, "candidate_hashes", MappingProxyType(dict(sorted(self.candidate_hashes.items()))))

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
            "candidate_hashes": dict(self.candidate_hashes),
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
        copied = json.loads(json.dumps(dict(self.result), allow_nan=False))
        if not isinstance(copied, dict):
            raise ValueError("attempt result must be a JSON object")
        object.__setattr__(self, "result", MappingProxyType(copied))


@dataclass(frozen=True, slots=True, init=False)
class ExperimentRegistryEvidence:
    experiment_id: str
    definition_hash: str
    search_manifest_hash: str
    attempt_count: int
    chain_head: str
    checkpoint_hash: str
    parameter_space: SearchSpaceManifest
    train_period: str
    comparison: ComparisonContext
    candidate_hashes: Mapping[str, str]
    terminal_anchor_hash: str
    _registry_root: Path
    _audit_root: Path
    _witness: TrustedWitness
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> ExperimentRegistryEvidence:
        raise TypeError("experiment evidence must be issued by a verified immutable registry")

    def __post_init__(self) -> None:
        if self._seal is not _EXPERIMENT_EVIDENCE_SEAL:
            raise TypeError("experiment evidence must be issued by a verified immutable registry")
        if not self.experiment_id.strip() or not self.train_period.strip() or self.attempt_count < 0:
            raise ValueError("invalid experiment evidence")
        for name, value in (
            ("definition", self.definition_hash), ("search", self.search_manifest_hash),
            ("chain", self.chain_head), ("checkpoint", self.checkpoint_hash),
            ("terminal", self.terminal_anchor_hash),
        ):
            _sha256(value, name)
        if self.search_manifest_hash != self.parameter_space.canonical_hash:
            raise ValueError("experiment evidence search manifest mismatch")
        if set(self.candidate_hashes) != {"model", "features", "labels", "parameters", "thresholds", "rules"}:
            raise ValueError("experiment evidence candidate hashes are incomplete")
        for name, value in self.candidate_hashes.items():
            _sha256(value, name)

    def assert_current(self) -> None:
        registry = ExperimentRegistry(self._registry_root, witness=self._witness)
        state = _object(self._registry_root / "state.json")
        terminal = _object(self._audit_root / "terminal.json")
        anchors = _read_external_anchors(self._audit_root)
        latest_anchor = anchors[-1]
        comparison = _mapping(registry._definition["comparison"])
        if (
            registry.definition_hash != self.definition_hash
            or registry._space.canonical_hash != self.search_manifest_hash
            or state.get("attempt_count") != self.attempt_count
            or state.get("chain_head") != self.chain_head
            or state.get("checkpoint_hash") != self.checkpoint_hash
            or dict(_mapping(registry._definition["candidate_hashes"])) != dict(self.candidate_hashes)
            or any(
                comparison.get(name) != getattr(self.comparison, name)
                for name in (
                    "dataset_version", "outer_fold_plan_hash", "cost_assumption_hash",
                    "label_version", "evaluation_period",
                )
            )
            or _hash(latest_anchor) != self.terminal_anchor_hash
            or terminal.get("experiment_id") != self.experiment_id
            or terminal.get("definition_hash") != self.definition_hash
            or terminal.get("attempt_count") != self.attempt_count
            or terminal.get("chain_head") != self.chain_head
            or terminal.get("checkpoint_hash") != self.checkpoint_hash
        ):
            raise ValueError("external terminal anchor is stale or mismatched")


class ExperimentRegistry:
    __slots__ = ("_root", "_audit_root", "_definition", "_space", "_witness")

    def __init__(self, root: Path, *, witness: TrustedWitness | None = None) -> None:
        self._root = root
        self._witness = SqliteTrustedWitness() if witness is None else witness
        _require_external_witness(self._witness, root)
        self._audit_root = _external_audit_root(root)
        definition_payload = _object(root / "definition.json")
        self._definition = definition_payload
        self._space = _space_from_payload(_mapping(definition_payload["parameter_space"]))
        self._verify_witness()
        self._verify()

    @classmethod
    def preregister(
        cls, root: Path, definition: ExperimentDefinition, *, witness: TrustedWitness | None = None,
    ) -> ExperimentRegistry:
        if root.exists():
            raise FileExistsError(root)
        audit_root = _external_audit_root(root)
        if audit_root.exists():
            raise FileExistsError(audit_root)
        audit_root.mkdir(parents=True)
        (audit_root / "anchors").mkdir()
        root.mkdir(parents=True)
        definition_payload = definition.to_dict()
        _write_exclusive(root / "definition.json", _canonical(definition_payload))
        _write_exclusive(root / "attempts.jsonl", b"")
        checkpoints = root / "checkpoints"
        checkpoints.mkdir()
        genesis = {
            "version": 1,
            "definition_hash": _hash(definition_payload),
            "search_manifest_hash": definition.parameter_space.canonical_hash,
            "journal_root": "0" * 64,
        }
        genesis_hash = _hash(genesis)
        _write_exclusive(root / f"genesis.{genesis_hash}.json", _canonical(genesis))
        state = {
            "definition_hash": _hash(definition_payload),
            "search_manifest_hash": definition.parameter_space.canonical_hash,
            "attempt_count": 0,
            "chain_head": "0" * 64,
            "genesis_hash": genesis_hash,
            "checkpoint_hash": genesis_hash,
        }
        _write_exclusive(root / "state.json", _canonical(state))
        terminal = {
            "experiment_id": definition.experiment_id,
            "definition_hash": _hash(definition_payload),
            "attempt_count": 0,
            "chain_head": "0" * 64,
            "checkpoint_hash": genesis_hash,
        }
        _write_exclusive(audit_root / "terminal.json", _canonical(terminal))
        _append_external_anchor(audit_root, terminal)
        authority = SqliteTrustedWitness() if witness is None else witness
        _require_external_witness(authority, root)
        subject = witness_subject("EXPERIMENT", secrets.token_bytes(32), genesis_hash)
        receipt = authority.register(subject, genesis_hash)
        _write_exclusive(root / "witness.receipt.json", _canonical(_receipt(receipt)))
        return cls(root, witness=authority)

    @property
    def definition_hash(self) -> str:
        return _hash(self._definition)

    @property
    def attempts(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._read_attempts())

    def append_attempt(self, attempt: ExperimentAttempt) -> None:
        self._verify_witness()
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
        checkpoint_body = {
            "sequence": state["attempt_count"],
            "attempt_count": state["attempt_count"],
            "chain_head": state["chain_head"],
            "previous_checkpoint_hash": state["checkpoint_hash"],
            "entry_hash": entry["entry_hash"],
            "entry_status": attempt.status,
        }
        checkpoint_hash = _hash(checkpoint_body)
        checkpoint_name = f"{_integer(state['attempt_count']):08d}-{checkpoint_hash}.json"
        _write_exclusive(self._root / "checkpoints" / checkpoint_name, _canonical(checkpoint_body))
        state["checkpoint_hash"] = checkpoint_hash
        _replace(self._root / "state.json", _canonical(state))
        terminal = {
            "experiment_id": self._definition["experiment_id"],
            "definition_hash": self.definition_hash,
            "attempt_count": state["attempt_count"],
            "chain_head": state["chain_head"],
            "checkpoint_hash": checkpoint_hash,
        }
        _replace(self._audit_root / "terminal.json", _canonical(terminal))
        _append_external_anchor(self._audit_root, terminal)
        self._verify()
        expected = _witness_receipt(self._root)
        advanced = self._witness.compare_and_swap(expected, checkpoint_hash)
        _replace(self._root / "witness.receipt.json", _canonical(_receipt(advanced)))
        self._verify_witness()

    def evidence(self) -> ExperimentRegistryEvidence:
        self._verify_witness()
        self._verify()
        state = _object(self._root / "state.json")
        terminal_anchor = _read_external_anchors(self._audit_root)[-1]
        comparison_payload = _mapping(self._definition["comparison"])
        instance = object.__new__(ExperimentRegistryEvidence)
        values: dict[str, object] = {
            "experiment_id": str(self._definition["experiment_id"]),
            "definition_hash": self.definition_hash,
            "search_manifest_hash": self._space.canonical_hash,
            "attempt_count": _integer(state["attempt_count"]),
            "chain_head": str(state["chain_head"]),
            "checkpoint_hash": str(state["checkpoint_hash"]),
            "parameter_space": self._space,
            "train_period": str(self._definition["train_period"]),
            "comparison": ComparisonContext(
                str(comparison_payload["dataset_version"]),
                str(comparison_payload["outer_fold_plan_hash"]),
                str(comparison_payload["cost_assumption_hash"]),
                str(comparison_payload["label_version"]),
                str(comparison_payload["evaluation_period"]),
            ),
            "candidate_hashes": MappingProxyType({
                str(name): str(value)
                for name, value in sorted(_mapping(self._definition["candidate_hashes"]).items())
            }),
            "terminal_anchor_hash": _hash(terminal_anchor),
            "_registry_root": self._root,
            "_audit_root": self._audit_root,
            "_witness": self._witness,
            "_seal": _EXPERIMENT_EVIDENCE_SEAL,
        }
        for name, value in values.items():
            object.__setattr__(instance, name, value)
        instance.__post_init__()
        return instance

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
        genesis_files = tuple(self._root.glob("genesis.*.json"))
        if len(genesis_files) != 1:
            raise ValueError("exactly one immutable experiment genesis is required")
        genesis_file = genesis_files[0]
        genesis = _object(genesis_file)
        genesis_hash = _hash(genesis)
        if genesis_file.name != f"genesis.{genesis_hash}.json" or state["genesis_hash"] != genesis_hash:
            raise ValueError("experiment genesis anchor mismatch")
        if genesis["definition_hash"] != _hash(self._definition) or state["definition_hash"] != genesis["definition_hash"]:
            raise ValueError("preregistered experiment definition was mutated")
        if genesis["search_manifest_hash"] != self._space.canonical_hash or state["search_manifest_hash"] != genesis["search_manifest_hash"]:
            raise ValueError("search space expansion after start is forbidden")
        previous = "0" * 64
        attempts = self._read_attempts()
        for entry in attempts:
            body = {key: value for key, value in entry.items() if key != "entry_hash"}
            if entry.get("previous_hash") != previous or entry.get("entry_hash") != _hash(body):
                raise ValueError("attempt journal is not append-only")
            previous = str(entry["entry_hash"])
        authoritative_count = 0
        authoritative_head = str(genesis["journal_root"])
        previous_checkpoint = genesis_hash
        expected_terminals: list[dict[str, object]] = [{
            "experiment_id": self._definition["experiment_id"],
            "definition_hash": self.definition_hash,
            "attempt_count": 0,
            "chain_head": authoritative_head,
            "checkpoint_hash": previous_checkpoint,
        }]
        checkpoints = tuple(sorted((self._root / "checkpoints").glob("*.json")))
        for expected_sequence, checkpoint_file in enumerate(checkpoints, start=1):
            checkpoint = _object(checkpoint_file)
            checkpoint_hash = _hash(checkpoint)
            expected_name = f"{expected_sequence:08d}-{checkpoint_hash}.json"
            if checkpoint_file.name != expected_name:
                raise ValueError("experiment checkpoint sequence/content address mismatch")
            if (
                _integer(checkpoint["sequence"]) != expected_sequence
                or _integer(checkpoint["attempt_count"]) != expected_sequence
                or checkpoint["previous_checkpoint_hash"] != previous_checkpoint
            ):
                raise ValueError("experiment checkpoint chain is invalid")
            authoritative_count = expected_sequence
            authoritative_head = str(checkpoint["chain_head"])
            previous_checkpoint = checkpoint_hash
            expected_terminals.append({
                "experiment_id": self._definition["experiment_id"],
                "definition_hash": self.definition_hash,
                "attempt_count": authoritative_count,
                "chain_head": authoritative_head,
                "checkpoint_hash": previous_checkpoint,
            })
        if (
            authoritative_count != len(attempts)
            or authoritative_head != previous
            or _integer(state["attempt_count"]) != authoritative_count
            or state["chain_head"] != authoritative_head
            or state["checkpoint_hash"] != previous_checkpoint
        ):
            raise ValueError("attempt deletion/truncation detected")
        try:
            terminal = _object(self._audit_root / "terminal.json")
            anchors = _read_external_anchors(self._audit_root)
        except (OSError, ValueError) as error:
            raise ValueError("external terminal anchor is missing or invalid") from error
        anchored_terminals = tuple(
            {key: value for key, value in anchor.items() if key not in {"sequence", "previous_anchor_hash"}}
            for anchor in anchors
        )
        if terminal != expected_terminals[-1] or anchored_terminals != tuple(expected_terminals):
            raise ValueError("external terminal anchor rejects registry rollback")

    def _verify_witness(self) -> None:
        receipt = _witness_receipt(self._root)
        try:
            current = self._witness.current(receipt.subject)
        except WitnessMissing as error:
            raise ValueError("trusted experiment witness is missing") from error
        state = _object(self._root / "state.json")
        local_count = _integer(state["attempt_count"])
        local_head = str(state["checkpoint_hash"])
        if current == receipt and (local_count, local_head) == (receipt.count, receipt.head):
            return
        if current.count == receipt.count + 1 and (local_count, local_head) == (current.count, current.head):
            _replace(self._root / "witness.receipt.json", _canonical(_receipt(current)))
            return
        raise ValueError(
            "trusted experiment witness rejects deletion, external terminal anchor rollback, or divergence"
        )


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
    "phase4_bundle_hash",
    "phase5_evidence_hash",
    "data_provenance_hash",
    "experiment_checkpoint_hash",
    "experiment_terminal_anchor_hash",
    "holdout_state_hash",
    "holdout_evaluation_hash",
    "holdout_cost_model_hash",
    "holdout_terminal_anchor_hash",
    "candidate_hashes",
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


_PUBLICATION_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class RegistryPublication:
    metadata: Mapping[str, object]
    artifacts: Mapping[str, object]
    phase4_bundle_hash: str
    phase5_evidence_hash: str
    publication_hash: str
    _phase5_evidence: object
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> RegistryPublication:
        raise TypeError("registry publications must be built from authoritative Phase 4/5 evidence")

    def __post_init__(self) -> None:
        if self._seal is not _PUBLICATION_SEAL:
            raise TypeError("registry publication must derive from a Phase 4 bundle and Phase 5 evidence")
        _sha256(self.phase4_bundle_hash, "phase4_bundle_hash")
        _sha256(self.phase5_evidence_hash, "phase5_evidence_hash")
        _sha256(self.publication_hash, "publication_hash")
        if self.publication_hash != _hash({"metadata": dict(self.metadata), "artifacts": dict(self.artifacts)}):
            raise ValueError("registry publication was mutated after provenance binding")


def phase4_bundle_evidence_hash(bundle: object) -> str:
    from tmf_research.models.serialization import ModelBundle, phase5_registry_artifacts

    if not isinstance(bundle, ModelBundle):
        raise TypeError("Phase 4 ModelBundle is required")
    artifacts = phase5_registry_artifacts(
        bundle,
        fold_metrics={}, stability_report={}, ablation_report={}, overfitting_report={},
    )
    core = {
        name: value
        for name, value in artifacts.items()
        if name not in {"fold_metrics.json", "stability_report.json", "ablation_report.json", "overfitting_report.json"}
    }
    return _hash({"metadata": bundle.metadata.to_dict(), "artifacts": core})


def phase4_candidate_hashes(bundle: object) -> Mapping[str, str]:
    from tmf_research.models.serialization import ModelBundle, phase5_registry_artifacts

    if not isinstance(bundle, ModelBundle):
        raise TypeError("Phase 4 ModelBundle is required")
    artifacts = phase5_registry_artifacts(
        bundle, fold_metrics={}, stability_report={}, ablation_report={}, overfitting_report={},
    )
    return MappingProxyType({
        "model": phase4_bundle_evidence_hash(bundle),
        "features": _hash({"names": artifacts["feature_names.json"], "manifest": artifacts["feature_manifest.json"]}),
        "labels": _hash({"label_version": bundle.metadata.label_version}),
        "parameters": _hash({
            "scaler": artifacts["scaler.json"], "imputer": artifacts["imputer.json"],
            "trade": artifacts["trade_model.json"], "direction": artifacts["direction_model.json"],
            "calibrator": artifacts["calibrator.json"],
        }),
        "thresholds": _hash({"trade_probability": 0.5, "direction_probability": 0.5}),
        "rules": _hash({
            "instrument": bundle.metadata.instrument, "session": bundle.metadata.session,
            "horizon": bundle.metadata.horizon, "research_signal": "NO_TRADE",
        }),
    })


def build_registry_publication(
    *,
    bundle: object,
    report: object,
    evidence: object,
    decision_result: object,
    code_commit: SourceCommitEvidence,
) -> RegistryPublication:
    from tmf_research.models.serialization import ModelBundle, phase5_registry_artifacts
    from tmf_research.validation.approval import Phase5DecisionResult, Phase5EvidenceBundle, decide_phase5
    from tmf_research.validation.report import Phase5Report, build_phase5_report

    if not isinstance(bundle, ModelBundle) or not isinstance(report, Phase5Report):
        raise TypeError("authoritative Phase 4 bundle and Phase 5 report are required")
    if not isinstance(evidence, Phase5EvidenceBundle) or not isinstance(decision_result, Phase5DecisionResult):
        raise TypeError("sealed Phase 5 evidence and decision result are required")
    derived_result = decide_phase5(evidence)
    if decision_result != derived_result:
        raise ValueError("publication decision must be derived from the authoritative Phase 5 bundle")
    decision = derived_result.decision
    authoritative_report = build_phase5_report(
        evidence.reports, evidence.gaps, evidence.dimensions, decision,
    )
    if report != authoritative_report or report.decision != decision or decision.evidence_hash != evidence.content_hash:
        raise ValueError("report, decision, and Phase 5 evidence hashes do not agree")
    if not isinstance(code_commit, SourceCommitEvidence):
        raise TypeError("publication requires sealed source commit evidence")
    code_commit.__post_init__()
    if bundle.metadata.experiment_id != evidence.experiment.experiment_id:
        raise ValueError("Phase 4 bundle and immutable experiment registry disagree")
    if bundle.metadata.label_version != evidence.experiment.comparison.label_version:
        raise ValueError("Phase 4 bundle and immutable experiment comparison label disagree")
    require_canonical_fold_periods(
        evidence.experiment.train_period,
        evidence.experiment.comparison.evaluation_period,
        tuple(fold.manifest for fold in evidence.folds),
    )
    phase4_hash = phase4_bundle_evidence_hash(bundle)
    candidate_hashes = phase4_candidate_hashes(bundle)
    if dict(evidence.experiment.candidate_hashes) != dict(candidate_hashes):
        raise ValueError("experiment preregistration candidate hashes do not match the Phase 4 bundle")
    approved = decision.model_status is ModelStatus.APPROVED_FOR_PAPER
    if approved:
        if (
            decision_result.approval is None or evidence.holdout is None
            or evidence.data_provenance.kind is not DataProvenanceKind.REAL_READONLY_MARKET_DATA
            or decision.valid_outer_folds < 5
            or evidence.holdout.model_hash != phase4_hash
            or dict(evidence.holdout.candidate_hashes) != dict(candidate_hashes)
            or decision_result.approval.evidence_hash != evidence.content_hash
            or decision_result.approval.data_provenance_hash != evidence.data_provenance.content_hash
            or decision_result.approval.holdout_state_hash != evidence.holdout.state_hash
            or decision_result.approval.holdout_evaluation_hash != evidence.holdout.evaluation_hash
            or decision_result.approval.holdout_cost_model_hash != evidence.holdout.cost_model_hash
            or decision_result.approval.holdout_terminal_anchor_hash != evidence.holdout.terminal_anchor_hash
            or decision_result.approval.experiment_checkpoint_hash != evidence.experiment.checkpoint_hash
            or decision_result.approval.experiment_terminal_anchor_hash != evidence.experiment.terminal_anchor_hash
            or dict(decision_result.approval.candidate_hashes) != dict(candidate_hashes)
        ):
            raise ValueError("APPROVED_FOR_PAPER requires the derived approval capability and bound holdout/model evidence")
    elif decision_result.approval is not None:
        raise ValueError("non-approved publication cannot carry an approval capability")
    artifacts = phase5_registry_artifacts(
        bundle,
        fold_metrics={
            "folds": [_fold_report_payload(value) for value in report.folds],
            "summaries": {name: asdict(value) for name, value in report.summaries.items()},
        },
        stability_report={"dimensions": _dimensions_payload(report.dimensions)},
        ablation_report={"comparisons": [_ablation_payload(value) for value in evidence.ablations]},
        overfitting_report={"gaps": [asdict(value) for value in report.generalization_gaps], "decision": asdict(decision)},
    )
    metadata = {
        **bundle.metadata.to_dict(),
        "code_commit": code_commit.commit,
        "outer_fold_count": decision.valid_outer_folds,
        "locked_holdout_status": (
            "PASSED" if approved
            else "PENDING" if decision.model_status is ModelStatus.LOCKED_TEST_PENDING
            else "NOT_RUN"
        ),
        "model_status": decision.model_status.value,
        "data_provenance": evidence.data_provenance.kind.value,
        "phase4_bundle_hash": phase4_hash,
        "phase5_evidence_hash": evidence.content_hash,
        "data_provenance_hash": evidence.data_provenance.content_hash,
        "experiment_checkpoint_hash": evidence.experiment.checkpoint_hash,
        "experiment_terminal_anchor_hash": evidence.experiment.terminal_anchor_hash,
        "holdout_state_hash": None if evidence.holdout is None else evidence.holdout.state_hash,
        "holdout_evaluation_hash": None if evidence.holdout is None else evidence.holdout.evaluation_hash,
        "holdout_cost_model_hash": None if evidence.holdout is None else evidence.holdout.cost_model_hash,
        "holdout_terminal_anchor_hash": None if evidence.holdout is None else evidence.holdout.terminal_anchor_hash,
        "candidate_hashes": dict(candidate_hashes),
    }
    instance = object.__new__(RegistryPublication)
    for name, value in (
        ("metadata", MappingProxyType(metadata)), ("artifacts", MappingProxyType(artifacts)),
        ("phase4_bundle_hash", phase4_hash), ("phase5_evidence_hash", evidence.content_hash),
        ("publication_hash", _hash({"metadata": metadata, "artifacts": artifacts})),
        ("_phase5_evidence", evidence),
        ("_seal", _PUBLICATION_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def publish_model_registry(root: Path, publication: RegistryPublication) -> str:
    if not isinstance(publication, RegistryPublication):
        raise TypeError("publish_model_registry requires a sealed RegistryPublication")
    publication.__post_init__()
    from tmf_research.validation.approval import Phase5EvidenceBundle, decide_phase5

    if not isinstance(publication._phase5_evidence, Phase5EvidenceBundle):
        raise TypeError("registry publication lost its authoritative Phase 5 evidence")
    current_decision = decide_phase5(publication._phase5_evidence).decision
    if (
        current_decision.evidence_hash != publication.phase5_evidence_hash
        or current_decision.model_status.value != publication.metadata["model_status"]
    ):
        raise ValueError("registry publication evidence is stale or no longer current")
    metadata = publication.metadata
    artifacts = publication.artifacts
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
    if status == ModelStatus.APPROVED_FOR_PAPER.value and (
        metadata["outer_fold_count"] < 5
        or metadata["locked_holdout_status"] != "PASSED"
        or provenance != "REAL_READONLY_MARKET_DATA"
        or metadata["holdout_state_hash"] is None
        or metadata["holdout_evaluation_hash"] is None
        or metadata["holdout_cost_model_hash"] is None
        or metadata["holdout_terminal_anchor_hash"] is None
    ):
        raise ValueError("approved publication metadata does not satisfy the derived production gates")
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
        if metadata["model_status"] == ModelStatus.APPROVED_FOR_PAPER.value and (
            _integer(metadata["outer_fold_count"]) < 5
            or metadata["locked_holdout_status"] != "PASSED"
            or metadata["data_provenance"] != "REAL_READONLY_MARKET_DATA"
            or metadata["holdout_state_hash"] is None
            or metadata["holdout_evaluation_hash"] is None
            or metadata["holdout_cost_model_hash"] is None
            or metadata["holdout_terminal_anchor_hash"] is None
        ):
            return RegistryValidation("NO_TRADE", ("APPROVAL_PROVENANCE_INVALID",), actual)
        fold_metrics = _object(root / "fold_metrics.json")
        folds = fold_metrics.get("folds")
        overfitting = _object(root / "overfitting_report.json")
        decision = overfitting.get("decision")
        fold_keys = tuple(
            (item.get("fold_id"), item.get("manifest_hash"))
            for item in folds if isinstance(item, dict)
        ) if isinstance(folds, list) else ()
        if (
            not isinstance(folds, list) or not isinstance(decision, dict)
            or len(fold_keys) != len(folds) or len(set(fold_keys)) != len(fold_keys)
            or any(
                not isinstance(fold_id, str) or not fold_id.strip()
                or not isinstance(manifest_hash, str) or not _valid_sha256(manifest_hash)
                for fold_id, manifest_hash in fold_keys
            )
            or len(folds) < _integer(metadata["outer_fold_count"])
            or decision.get("model_status") != metadata["model_status"]
            or decision.get("evidence_hash") != metadata["phase5_evidence_hash"]
            or decision.get("valid_outer_folds") != metadata["outer_fold_count"]
        ):
            return RegistryValidation("NO_TRADE", ("MODEL_REPORT_PROVENANCE_MISMATCH",), actual)
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
        "model_status", "data_provenance", "phase4_bundle_hash", "phase5_evidence_hash",
        "data_provenance_hash", "experiment_checkpoint_hash", "experiment_terminal_anchor_hash",
    )
    if any(not isinstance(metadata[name], str) or not str(metadata[name]).strip() for name in string_fields):
        raise ValueError("model metadata strings must be present and non-empty")
    for name in ("created_at", "training_start", "training_end"):
        parsed = datetime.fromisoformat(str(metadata[name]))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")
    _sha256(str(metadata["training_data_hash"]), "training_data_hash")
    for name in (
        "phase4_bundle_hash", "phase5_evidence_hash", "data_provenance_hash",
        "experiment_checkpoint_hash", "experiment_terminal_anchor_hash",
    ):
        _sha256(str(metadata[name]), name)
    for name in (
        "holdout_state_hash", "holdout_evaluation_hash", "holdout_cost_model_hash",
        "holdout_terminal_anchor_hash",
    ):
        if metadata[name] is not None:
            _sha256(str(metadata[name]), name)
    candidate_hashes = metadata["candidate_hashes"]
    if not isinstance(candidate_hashes, Mapping) or set(candidate_hashes) != {"model", "features", "labels", "parameters", "thresholds", "rules"}:
        raise ValueError("candidate_hashes must bind every frozen candidate component")
    for name, value in candidate_hashes.items():
        _sha256(str(value), str(name))
    if not _git_commit(str(metadata["code_commit"])):
        raise ValueError("code_commit must be a full hexadecimal commit id")
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
    if not _valid_sha256(value):
        raise ValueError(f"invalid {name}")


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _git_commit(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)


def _external_audit_root(root: Path) -> Path:
    return root.parent / f".{root.name}.phase5-audit"


def _require_external_witness(witness: TrustedWitness, artifact_root: Path) -> None:
    location = witness.location
    if location is not None and location.resolve().is_relative_to(artifact_root.resolve()):
        raise ValueError("trusted witness must live outside the registry artifact root")


def _receipt(head: WitnessHead) -> dict[str, object]:
    return {"subject": head.subject, "count": head.count, "head": head.head}


def _witness_receipt(root: Path) -> WitnessHead:
    value = _object(root / "witness.receipt.json")
    if set(value) != {"subject", "count", "head"}:
        raise ValueError("experiment witness receipt is invalid")
    return WitnessHead(str(value["subject"]), _integer(value["count"]), str(value["head"]))


def _append_external_anchor(audit_root: Path, terminal: Mapping[str, object]) -> str:
    existing = _read_external_anchors(audit_root) if tuple((audit_root / "anchors").glob("*.json")) else ()
    sequence = len(existing)
    previous = "0" * 64 if not existing else _hash(existing[-1])
    anchor = {"sequence": sequence, "previous_anchor_hash": previous, **dict(terminal)}
    anchor_hash = _hash(anchor)
    _write_exclusive(audit_root / "anchors" / f"{sequence:08d}-{anchor_hash}.json", _canonical(anchor))
    return anchor_hash


def _read_external_anchors(audit_root: Path) -> tuple[dict[str, object], ...]:
    files = tuple(sorted((audit_root / "anchors").glob("*.json")))
    if not files:
        raise ValueError("external append-only audit is empty")
    previous = "0" * 64
    anchors: list[dict[str, object]] = []
    for sequence, path in enumerate(files):
        anchor = _object(path)
        anchor_hash = _hash(anchor)
        if (
            path.name != f"{sequence:08d}-{anchor_hash}.json"
            or _integer(anchor.get("sequence")) != sequence
            or anchor.get("previous_anchor_hash") != previous
            or _integer(anchor.get("attempt_count")) != sequence
        ):
            raise ValueError("external append-only terminal audit is invalid")
        previous = anchor_hash
        anchors.append(anchor)
    return tuple(anchors)


def _fold_report_payload(value: object) -> dict[str, object]:
    from tmf_research.validation.report import FoldReport

    if not isinstance(value, FoldReport):
        raise TypeError("fold report evidence is required")
    classification = dict(value.classification)
    table = classification.get("calibration_table")
    if isinstance(table, (tuple, list)):
        classification["calibration_table"] = [asdict(item) for item in table]
    return {
        "fold_id": value.fold_id, "manifest_hash": value.manifest_hash,
        "split_regions": dict(value.split_regions), "classification": classification,
        "trading": dict(value.trading), "stability": dict(value.stability),
    }


def _dimensions_payload(value: object) -> dict[str, object]:
    from tmf_research.validation.overfitting import StabilityDimensions

    if not isinstance(value, StabilityDimensions):
        raise TypeError("stability dimension evidence is required")
    return {
        "regimes": dict(value.regimes), "months": dict(value.months),
        "directions": dict(value.directions), "target_codes": dict(value.target_codes),
        "events": dict(value.events), "total_net_pnl": value.total_net_pnl,
        "cost_complete": value.cost_complete,
    }


def _ablation_payload(value: object) -> dict[str, object]:
    from tmf_research.validation.ablation import AblationComparison

    if not isinstance(value, AblationComparison):
        raise TypeError("ablation comparison evidence is required")
    return {
        "removed_group": value.removed_group,
        "full_model_folds": [asdict(item) for item in value.full_model_folds],
        "removed_model_folds": [asdict(item) for item in value.removed_model_folds],
        "full_model_gain_ratio": value.full_model_gain_ratio,
        "fold_stability": value.fold_stability,
    }
