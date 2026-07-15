from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
import unittest

from tmf_research.experiments.comparison import ComparisonContext, require_comparable
from tmf_research.experiments.registry import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentRegistry,
    REGISTRY_FILES,
    RegistryCompatibility,
    publish_model_registry,
    transition_model_status,
    validate_model_registry,
)
from tmf_research.models.serialization import phase5_registry_artifacts
from tests.overfitting.test_search_budget import space
from tests.unit.test_model_serialization import bundle


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def context(**overrides: str) -> ComparisonContext:
    values = {
        "dataset_version": "dataset-v1",
        "outer_fold_plan_hash": "fold-v1",
        "cost_assumption_hash": "cost-v1",
        "label_version": "label-v1",
        "evaluation_period": "2025",
    }
    values.update(overrides)
    return ComparisonContext(**values)


def definition() -> ExperimentDefinition:
    return ExperimentDefinition(
        "exp-1", NOW, "direction hypothesis", "core", "label-v1", "LOGISTIC",
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
    def test_successes_and_failures_are_append_only_and_restart_verifies_chain(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "registry"
            registry = ExperimentRegistry.preregister(root, definition())
            registry.append_attempt(attempt("a-1"))
            registry.append_attempt(attempt("a-2", status="FAILED"))
            self.assertEqual([item["status"] for item in ExperimentRegistry(root).attempts], ["SUCCEEDED", "FAILED"])
            lines = (root / "attempts.jsonl").read_text().splitlines()
            (root / "attempts.jsonl").write_text(lines[0] + "\n")
            with self.assertRaisesRegex(ValueError, "deletion"):
                ExperimentRegistry(root)

    def test_post_result_neighbor_is_forbidden(self) -> None:
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry.preregister(Path(directory) / "registry", definition())
            registry.append_attempt(attempt("a-1"))
            with self.assertRaisesRegex(ValueError, "neighbor"):
                registry.append_attempt(attempt("a-2", hp="hp-nearby"))

    def test_comparison_requires_identical_dataset_fold_cost_label_and_period(self) -> None:
        require_comparable(context(), context())
        with self.assertRaisesRegex(ValueError, "dataset_version"):
            require_comparable(context(), context(dataset_version="dataset-v2"))

    def test_spec37_registry_is_complete_and_synthetic_approval_is_forbidden(self) -> None:
        metadata = {
            "model_id": "m1", "model_version": "v1", "created_at": NOW.isoformat(),
            "training_start": NOW.isoformat(), "training_end": NOW.isoformat(),
            "instrument": "TMF", "session": "DAY", "horizon": "15m",
            "feature_version": "fv1", "label_version": "lv1", "code_commit": "abc",
            "random_seed": 7, "training_data_hash": "0" * 64, "experiment_id": "exp-1",
            "outer_fold_count": 5, "locked_holdout_status": "PASSED", "schema_version": "v1",
            "model_status": "CANDIDATE", "data_provenance": "SYNTHETIC_TEST_ONLY",
        }
        artifacts: dict[str, object] = {
            name: {"name": name} for name in REGISTRY_FILES if name != "metadata.json"
        }
        artifacts["feature_names.json"] = ["x"]
        artifacts["scaler.json"] = {"dimension": 1}
        artifacts["imputer.json"] = {"output_dimension": 1}
        with TemporaryDirectory() as directory:
            root = Path(directory) / "model"
            checksum = publish_model_registry(root, metadata=metadata, artifacts=artifacts)
            self.assertEqual(validate_model_registry(root, checksum).reasons, ())
            expected = RegistryCompatibility("fv1", ("x",), "TMF", "DAY", "15m", "v1", 1, 1, checksum)
            self.assertEqual(validate_model_registry(root, expected=expected).reasons, ())
            payload = json.loads((root / "metadata.json").read_text())
            payload.pop("code_commit")
            (root / "metadata.json").write_text(json.dumps(payload))
            self.assertEqual(validate_model_registry(root).signal, "NO_TRADE")
        metadata["model_status"] = "APPROVED_FOR_PAPER"
        with TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "synthetic"):
            publish_model_registry(Path(directory) / "model", metadata=metadata, artifacts=artifacts)

    def test_model_states_are_fixed_and_synthetic_cannot_enter_approval_path(self) -> None:
        self.assertEqual(
            transition_model_status("DRAFT", "VALIDATING", data_provenance="SYNTHETIC_TEST_ONLY"),
            "VALIDATING",
        )
        with self.assertRaisesRegex(ValueError, "synthetic"):
            transition_model_status("CANDIDATE", "LOCKED_TEST_PENDING", data_provenance="SYNTHETIC_TEST_ONLY")
        with self.assertRaisesRegex(ValueError, "forbidden"):
            transition_model_status("DRAFT", "APPROVED_FOR_PAPER", data_provenance="REAL_READONLY_MARKET_DATA")

    def test_final_artifacts_are_derived_from_real_phase4_bundle_components(self) -> None:
        trained = bundle()
        artifacts = phase5_registry_artifacts(
            trained,
            fold_metrics={"folds": 5},
            stability_report={"status": "PASS"},
            ablation_report={"groups": 8},
            overfitting_report={"status": "REJECTED_INSUFFICIENT_DATA"},
        )
        self.assertEqual(set(artifacts), set(REGISTRY_FILES) - {"metadata.json"})
        self.assertEqual(artifacts["feature_names.json"], list(trained.feature_names))


if __name__ == "__main__":
    unittest.main()
