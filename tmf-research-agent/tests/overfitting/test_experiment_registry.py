from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast
import unittest

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


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def context(**overrides: str) -> ComparisonContext:
    values = {
        "dataset_version": "dataset-v1", "outer_fold_plan_hash": "fold-v1",
        "cost_assumption_hash": "cost-v1", "label_version": "label-v1",
        "evaluation_period": "2025",
    }
    values.update(overrides)
    return ComparisonContext(**values)


def definition() -> ExperimentDefinition:
    return ExperimentDefinition(
        "experiment-1", NOW, "direction hypothesis", "core", "labels-v1", "LOGISTIC",
        space(), "brier", ("log_loss", "ece", "ev"), "2024-2025", "LOCKED", context(),
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

    def test_post_result_neighbor_and_incomparable_context_are_forbidden(self) -> None:
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry.preregister(Path(directory) / "registry", definition())
            registry.append_attempt(attempt("a-1"))
            with self.assertRaisesRegex(ValueError, "neighbor"):
                registry.append_attempt(attempt("a-2", hp="hp-nearby"))
        require_comparable(context(), context())
        with self.assertRaisesRegex(ValueError, "dataset_version"):
            require_comparable(context(), context(dataset_version="dataset-v2"))

    def test_status_enum_rejects_strings_bogus_and_synthetic_approval(self) -> None:
        self.assertEqual(
            transition_model_status(ModelStatus.DRAFT, ModelStatus.VALIDATING, data_provenance="SYNTHETIC_TEST_ONLY"),
            ModelStatus.VALIDATING,
        )
        with self.assertRaises(TypeError):
            transition_model_status(cast(ModelStatus, "BOGUS"), ModelStatus.VALIDATING, data_provenance="REAL_READONLY_MARKET_DATA")
        with self.assertRaises(ValueError):
            transition_model_status(ModelStatus.CANDIDATE, ModelStatus.LOCKED_TEST_PENDING, data_provenance="SYNTHETIC_TEST_ONLY")
        with self.assertRaises(TypeError):
            publish_model_registry(Path("unused"), cast(object, {"metadata": {}}))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
