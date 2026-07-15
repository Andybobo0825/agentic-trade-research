from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tmf_research.experiments.registry import (
    REGISTRY_FILES,
    publish_model_registry,
    validate_model_registry,
)
from tmf_research.models.serialization import phase5_registry_artifacts
from tmf_research.validation.overfitting import decide_model_status
from tests.overfitting.test_model_selection import dimensions, fold, gates
from tests.unit.test_model_serialization import bundle


class Phase5EvidencePipelineTests(unittest.TestCase):
    def test_synthetic_end_to_end_evidence_publishes_candidate_never_approval(self) -> None:
        trained = bundle()
        decision = decide_model_status(
            tuple(fold(index) for index in range(5)),
            dimensions(),
            gates(),
            data_provenance="SYNTHETIC_TEST_ONLY",
        )
        self.assertEqual(decision.model_status, "CANDIDATE")
        artifacts = phase5_registry_artifacts(
            trained,
            fold_metrics={"valid_outer_folds": decision.valid_outer_folds},
            stability_report={"decision": decision.model_status},
            ablation_report={"groups": 8},
            overfitting_report={"reasons": list(decision.reasons)},
        )
        self.assertEqual(set(artifacts), set(REGISTRY_FILES) - {"metadata.json"})
        metadata = {
            **trained.metadata.to_dict(),
            "model_status": decision.model_status,
            "outer_fold_count": decision.valid_outer_folds,
            "locked_holdout_status": "SYNTHETIC_NOT_ELIGIBLE",
            "data_provenance": "SYNTHETIC_TEST_ONLY",
        }
        with TemporaryDirectory() as directory:
            root = Path(directory) / "candidate"
            checksum = publish_model_registry(root, metadata=metadata, artifacts=artifacts)
            validation = validate_model_registry(root, checksum)
        self.assertEqual(validation.reasons, ())
        self.assertIsNone(validation.signal)


if __name__ == "__main__":
    unittest.main()
