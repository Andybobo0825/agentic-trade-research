from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from tmf_research.experiments.registry import (
    ExperimentRegistry,
    ModelStatus,
    RegistryPublication,
    build_registry_publication,
    publish_model_registry,
    validate_model_registry,
)
from tmf_research.validation.approval import Phase5DecisionResult, assemble_phase5_evidence, decide_phase5
from tmf_research.validation.report import build_phase5_report
from tests.overfitting.test_experiment_registry import attempt, definition
from tests.phase5_test_support import complete_fold_evidence
from tests.unit.test_model_serialization import bundle


class Phase5EvidencePipelineTests(unittest.TestCase):
    def test_synthetic_end_to_end_evidence_publishes_candidate_never_approval(self) -> None:
        trained = bundle()
        values = complete_fold_evidence()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            experiment = ExperimentRegistry.preregister(base / "experiment", definition())
            experiment.append_attempt(attempt("synthetic-mechanics"))
            evidence = assemble_phase5_evidence(
                folds=values[0], reports=values[1], gaps=values[2], dimensions=values[3],
                ablations=values[4], coefficients=values[5], sensitivities=values[6],
                calibrations=values[7], experiment=experiment.evidence(), holdout=None,
                data_provenance="SYNTHETIC_TEST_ONLY",
            )
            result = decide_phase5(evidence)
            self.assertEqual(result.decision.model_status, ModelStatus.CANDIDATE)
            self.assertIsNone(result.approval)
            report = build_phase5_report(values[1], values[2], values[3], result.decision)
            publication = build_registry_publication(
                bundle=trained, report=report, evidence=evidence,
                decision_result=result,
                code_commit=subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip(),
            )
            root = base / "candidate"
            with self.assertRaises(TypeError):
                publication.metadata["model_status"] = ModelStatus.APPROVED_FOR_PAPER.value  # type: ignore[index]
            with self.assertRaises(TypeError):
                RegistryPublication()
            checksum = publish_model_registry(root, publication)
            validation = validate_model_registry(root, checksum)
        self.assertEqual(validation.reasons, ())
        self.assertIsNone(validation.signal)

    def test_publication_rejects_a_nonexistent_commit(self) -> None:
        values = complete_fold_evidence()
        with TemporaryDirectory() as directory:
            experiment = ExperimentRegistry.preregister(Path(directory) / "experiment", definition())
            experiment.append_attempt(attempt("commit-check"))
            evidence = assemble_phase5_evidence(
                folds=values[0], reports=values[1], gaps=values[2], dimensions=values[3],
                ablations=values[4], coefficients=values[5], sensitivities=values[6],
                calibrations=values[7], experiment=experiment.evidence(), holdout=None,
                data_provenance="SYNTHETIC_TEST_ONLY",
            )
            result = decide_phase5(evidence)
            report = build_phase5_report(values[1], values[2], values[3], result.decision)
            asserted = Phase5DecisionResult(
                replace(result.decision, model_status=ModelStatus.LOCKED_TEST_PENDING), None,
            )
            with self.assertRaisesRegex(ValueError, "must be derived"):
                build_registry_publication(
                    bundle=bundle(), report=report, evidence=evidence,
                    decision_result=asserted,
                    code_commit=subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip(),
                )
            with self.assertRaisesRegex(ValueError, "real repository commit"):
                build_registry_publication(
                    bundle=bundle(), report=report, evidence=evidence,
                    decision_result=result, code_commit="a" * 40,
                )


if __name__ == "__main__":
    unittest.main()
