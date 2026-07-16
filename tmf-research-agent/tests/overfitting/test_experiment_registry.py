from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast
import unittest
import shutil

from tmf_research.experiments.comparison import ComparisonContext, require_comparable
from tmf_research.experiments.registry import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentRegistry,
    ModelStatus,
    publish_model_registry,
    transition_model_status,
)
from tests.overfitting.test_search_budget import space
from tests.phase5_test_support import synthetic_provenance
from tests.support.trusted_witness import MemoryTrustedWitness


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def context(**overrides: str) -> ComparisonContext:
    values = {
        "dataset_version": "dataset-v1", "outer_fold_plan_hash": hashlib.sha256(b"wrong-fold-v1").hexdigest(),
        "cost_assumption_hash": hashlib.sha256(b"cost-v1").hexdigest(), "label_version": "labels-v1",
        "evaluation_period": "2025",
    }
    values.update(overrides)
    return ComparisonContext(**values)


def definition(*, candidate_hashes: Mapping[str, str] | None = None) -> ExperimentDefinition:
    return ExperimentDefinition(
        "experiment-1", NOW, "direction hypothesis", "core", "labels-v1", "LOGISTIC",
        space(), "brier", ("log_loss", "ece", "ev"), "2024-2025", "LOCKED", context(),
        candidate_hashes or {name: "0" * 64 for name in ("model", "features", "labels", "parameters", "thresholds", "rules")},
    )


def attempt(
    identifier: str,
    *,
    status: Literal["SUCCEEDED", "FAILED"] = "SUCCEEDED",
    hp: str = "hp-1",
) -> ExperimentAttempt:
    return ExperimentAttempt(
        identifier, NOW, "LOGISTIC", "core", hp, "barrier-1", "threshold-1",
        "PLATT", status, {"reason": "converged" if status == "SUCCEEDED" else "failed"},
    )


class ExperimentRegistryTests(unittest.TestCase):
    def test_full_registry_restore_missing_wrong_witness_and_receipt_crash_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "registry"
            witness = MemoryTrustedWitness()
            registry = ExperimentRegistry.preregister(root, definition(), witness=witness)
            registry.append_attempt(attempt("success"))
            snapshot = base / "snapshot"
            snapshot_audit = base / "snapshot-audit"
            shutil.copytree(root, snapshot)
            shutil.copytree(base / ".registry.phase5-audit", snapshot_audit)
            old_receipt = (root / "witness.receipt.json").read_bytes()
            registry.append_attempt(attempt("failed", status="FAILED"))
            (root / "witness.receipt.json").write_bytes(old_receipt)
            recovered = ExperimentRegistry(root, witness=witness)
            self.assertEqual(recovered.evidence().attempt_count, 2)
            shutil.rmtree(root)
            shutil.rmtree(base / ".registry.phase5-audit")
            shutil.copytree(snapshot, root)
            shutil.copytree(snapshot_audit, base / ".registry.phase5-audit")
            with self.assertRaises(ValueError):
                ExperimentRegistry(root, witness=witness)
            with self.assertRaises(ValueError):
                ExperimentRegistry(root, witness=MemoryTrustedWitness())
            (root / "witness.receipt.json").unlink()
            with self.assertRaises((OSError, ValueError)):
                ExperimentRegistry(root, witness=witness)

    def test_successes_and_failures_are_append_only_and_evidence_is_sealed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "registry"
            registry = ExperimentRegistry.preregister(root, definition())
            registry.append_attempt(attempt("a-1"))
            registry.append_attempt(attempt("a-2", status="FAILED"))
            self.assertEqual([item["status"] for item in ExperimentRegistry(root).attempts], ["SUCCEEDED", "FAILED"])
            evidence = registry.evidence()
            self.assertEqual((evidence.attempt_count, evidence.experiment_id), (2, "experiment-1"))

    def test_delete_failed_and_recompute_journal_chain_and_mutable_state_still_fails_checkpoint(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "registry"
            registry = ExperimentRegistry.preregister(root, definition())
            registry.append_attempt(attempt("success"))
            registry.append_attempt(attempt("failed", status="FAILED"))
            first = json.loads((root / "attempts.jsonl").read_text().splitlines()[0])
            (root / "attempts.jsonl").write_text(json.dumps(first, sort_keys=True, separators=(",", ":")) + "\n")
            state = json.loads((root / "state.json").read_text())
            state["attempt_count"] = 1
            state["chain_head"] = first["entry_hash"]
            checkpoint = sorted((root / "checkpoints").glob("*.json"))[0]
            state["checkpoint_hash"] = checkpoint.stem.split("-", 1)[1]
            (root / "state.json").write_text(json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n")
            with self.assertRaisesRegex(ValueError, "deletion"):
                ExperimentRegistry(root)

    def test_delete_failed_checkpoint_too_still_fails_external_terminal_anchor(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "registry"
            registry = ExperimentRegistry.preregister(root, definition())
            registry.append_attempt(attempt("success"))
            registry.append_attempt(attempt("failed", status="FAILED"))
            lines = (root / "attempts.jsonl").read_text().splitlines()
            (root / "attempts.jsonl").write_text(lines[0] + "\n")
            sorted((root / "checkpoints").glob("*.json"))[-1].unlink()
            first_checkpoint = sorted((root / "checkpoints").glob("*.json"))[0]
            state = json.loads((root / "state.json").read_text())
            state.update({
                "attempt_count": 1,
                "chain_head": json.loads(lines[0])["entry_hash"],
                "checkpoint_hash": first_checkpoint.stem.split("-", 1)[1],
            })
            (root / "state.json").write_text(json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n")
            with self.assertRaisesRegex(ValueError, "external terminal anchor"):
                ExperimentRegistry(root)

    def test_failed_tail_cannot_be_erased_by_restoring_the_old_mutable_terminal_too(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "registry"
            registry = ExperimentRegistry.preregister(root, definition())
            registry.append_attempt(attempt("success"))
            audit_root = root.parent / f".{root.name}.phase5-audit"
            old_terminal = (audit_root / "terminal.json").read_bytes()
            registry.append_attempt(attempt("failed", status="FAILED"))
            self.assertEqual(len(tuple((audit_root / "anchors").glob("*.json"))), 3)
            lines = (root / "attempts.jsonl").read_text().splitlines()
            (root / "attempts.jsonl").write_text(lines[0] + "\n")
            sorted((root / "checkpoints").glob("*.json"))[-1].unlink()
            first_checkpoint = sorted((root / "checkpoints").glob("*.json"))[0]
            state = json.loads((root / "state.json").read_text())
            state.update({
                "attempt_count": 1,
                "chain_head": json.loads(lines[0])["entry_hash"],
                "checkpoint_hash": first_checkpoint.stem.split("-", 1)[1],
            })
            (root / "state.json").write_text(json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n")
            (audit_root / "terminal.json").write_bytes(old_terminal)
            with self.assertRaises(ValueError):
                ExperimentRegistry(root)

    def test_previously_issued_evidence_rechecks_the_registry_not_only_the_terminal_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "registry"
            registry = ExperimentRegistry.preregister(root, definition())
            registry.append_attempt(attempt("success"))
            evidence = registry.evidence()
            (root / "attempts.jsonl").write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                evidence.assert_current()

    def test_post_result_neighbor_and_incomparable_context_are_forbidden(self) -> None:
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry.preregister(Path(directory) / "registry", definition())
            registry.append_attempt(attempt("a-1"))
            with self.assertRaisesRegex(ValueError, "neighbor"):
                registry.append_attempt(attempt("a-2", hp="hp-nearby"))
        require_comparable(context(), context())
        with self.assertRaisesRegex(ValueError, "dataset_version"):
            require_comparable(context(), context(dataset_version="dataset-v2"))
        with self.assertRaisesRegex(ValueError, "hash"):
            ComparisonContext("dataset-v1", "not-a-hash", "also-not-a-hash", "labels-v1", "2025")

    def test_status_enum_rejects_strings_bogus_and_synthetic_approval(self) -> None:
        self.assertEqual(
            transition_model_status(ModelStatus.DRAFT, ModelStatus.VALIDATING, data_provenance=synthetic_provenance()),
            ModelStatus.VALIDATING,
        )
        with self.assertRaises(TypeError):
            transition_model_status(cast(ModelStatus, "BOGUS"), ModelStatus.VALIDATING, data_provenance=synthetic_provenance())
        with self.assertRaises(ValueError):
            transition_model_status(ModelStatus.CANDIDATE, ModelStatus.LOCKED_TEST_PENDING, data_provenance=synthetic_provenance())
        with self.assertRaises(TypeError):
            publish_model_registry(Path("unused"), cast(object, {"metadata": {}}))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            transition_model_status(
                ModelStatus.DRAFT, ModelStatus.VALIDATING,
                data_provenance=cast(object, "REAL_READONLY_MARKET_DATA"),  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
