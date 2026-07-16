from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tmf_research.experiments.registry import (
    ExperimentRegistry,
    ModelStatus,
    phase4_candidate_hashes,
    RegistryPublication,
    SourceCommitEvidence,
    build_registry_publication,
    publish_model_registry,
    verified_source_commit,
)
from tmf_research.validation.approval import Phase5DecisionResult, assemble_phase5_evidence, decide_phase5
from tmf_research.validation.locked_holdout import (
    FrozenCandidate, HoldoutAccessError, HoldoutCostModel, LockedHoldout,
    select_locked_holdout,
)
from tmf_research.validation.report import build_phase5_report
from tmf_research.domain.events import TickEvent
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore
from tests.overfitting.test_experiment_registry import attempt, definition
from tests.overfitting.test_locked_holdout import evaluate, rows
from tests.phase5_test_support import (
    aligned_definition,
    complete_fold_evidence,
    subset_fold_evidence,
    synthetic_provenance,
)
from tests.unit.test_model_serialization import bundle


class Phase5EvidencePipelineTests(unittest.TestCase):
    def test_unrelated_real_raw_tick_cannot_promote_synthetic_fold_and_holdout_lineage(self) -> None:
        trained = bundle()
        values = complete_fold_evidence()
        candidate_hashes = phase4_candidate_hashes(trained)
        cost = HoldoutCostModel(0.1, 0.1, 0.1, 0.1)
        now = datetime(2026, 7, 15, tzinfo=UTC)
        with TemporaryDirectory() as directory:
            base = Path(directory)
            raw = AppendOnlyRawStore(base / "raw", writer_version="phase1-v1", dataset_version="dataset-v1")
            manifest = raw.append_segment("tick", [TickEvent(
                event_id="phase5-approved", received_at=now, exchange_datetime=now,
                alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                code="TMF202607", close=23000.0, volume=1, simtrade=False, raw_payload={},
            )], segment_id="phase5-approved", created_at=now)
            provenance = raw.phase5_provenance((manifest,))
            base_definition = aligned_definition(
                definition(candidate_hashes=candidate_hashes), values[0], provenance,
            )
            experiment = ExperimentRegistry.preregister(
                base / "experiment",
                replace(base_definition, comparison=replace(
                    base_definition.comparison, cost_assumption_hash=cost.content_hash,
                )),
            )
            experiment.append_attempt(attempt("approved-real"))
            frozen = FrozenCandidate(candidate_hashes)
            vault = LockedHoldout.create(base / "holdout", select_locked_holdout(rows()))
            vault.freeze(frozen)
            self.assertEqual(evaluate(vault, frozen).status, "PASSED")
            with self.assertRaisesRegex(HoldoutAccessError, "TEST_ONLY"):
                vault.approval_evidence(frozen)

    def test_verified_real_data_with_four_folds_is_rejected_insufficient_data(self) -> None:
        values = subset_fold_evidence(4)
        with TemporaryDirectory() as directory:
            base = Path(directory)
            raw = AppendOnlyRawStore(base / "raw", writer_version="phase1-v1", dataset_version="dataset-v1")
            now = datetime(2026, 7, 15, tzinfo=UTC)
            manifest = raw.append_segment("tick", [TickEvent(
                event_id="phase5-real", received_at=now, exchange_datetime=now,
                alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                code="TMF202607", close=23000.0, volume=1, simtrade=False, raw_payload={},
            )], segment_id="phase5-real", created_at=now)
            provenance = raw.phase5_provenance((manifest,))
            experiment = ExperimentRegistry.preregister(
                base / "experiment", aligned_definition(definition(), values[0], provenance),
            )
            experiment.append_attempt(attempt("real-insufficient"))
            with self.assertRaisesRegex(ValueError, "raw-derived production evaluation"):
                assemble_phase5_evidence(
                    folds=values[0], reports=values[1], gaps=values[2], dimensions=values[3],
                    ablations=values[4], coefficients=values[5], sensitivities=values[6],
                    calibrations=values[7], experiment=experiment.evidence(), holdout=None,
                    data_provenance=provenance,
                )

    def test_synthetic_end_to_end_evidence_publishes_candidate_never_approval(self) -> None:
        trained = bundle()
        values = complete_fold_evidence()
        provenance = synthetic_provenance()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            experiment = ExperimentRegistry.preregister(
                base / "experiment", aligned_definition(
                    definition(candidate_hashes=phase4_candidate_hashes(trained)), values[0], provenance,
                ),
            )
            experiment.append_attempt(attempt("synthetic-mechanics"))
            evidence = assemble_phase5_evidence(
                folds=values[0], reports=values[1], gaps=values[2], dimensions=values[3],
                ablations=values[4], coefficients=values[5], sensitivities=values[6],
                calibrations=values[7], experiment=experiment.evidence(), holdout=None,
                data_provenance=provenance,
            )
            result = decide_phase5(evidence)
            self.assertEqual(result.decision.model_status, ModelStatus.CANDIDATE)
            self.assertIsNone(result.approval)
            report = build_phase5_report(values[1], values[2], values[3], result.decision)
            publication = build_registry_publication(
                bundle=trained, report=report, evidence=evidence,
                decision_result=result, code_commit=verified_source_commit("a" * 40),
            )
            self.assertEqual(
                publication.metadata["candidate_hashes"],
                dict(phase4_candidate_hashes(trained)),
            )
            self.assertEqual(
                publication.metadata["experiment_terminal_anchor_hash"],
                evidence.experiment.terminal_anchor_hash,
            )
            self.assertEqual(
                publication.metadata["data_provenance_hash"],
                evidence.data_provenance.content_hash,
            )
            root = base / "candidate"
            with self.assertRaises(TypeError):
                publication.metadata["model_status"] = ModelStatus.APPROVED_FOR_PAPER.value  # type: ignore[index]
            with self.assertRaises(TypeError):
                RegistryPublication()
            with self.assertRaisesRegex(ValueError, "TEST_ONLY"):
                publish_model_registry(root, publication)
            self.assertFalse(root.exists())
            experiment.append_attempt(attempt("post-build-attempt"))
            with self.assertRaises(ValueError):
                publish_model_registry(base / "stale-candidate", publication)

    def test_publication_rejects_a_nonexistent_commit(self) -> None:
        values = complete_fold_evidence()
        provenance = synthetic_provenance()
        with TemporaryDirectory() as directory:
            experiment = ExperimentRegistry.preregister(
                Path(directory) / "experiment", aligned_definition(
                    definition(candidate_hashes=phase4_candidate_hashes(bundle())), values[0], provenance,
                ),
            )
            experiment.append_attempt(attempt("commit-check"))
            evidence = assemble_phase5_evidence(
                folds=values[0], reports=values[1], gaps=values[2], dimensions=values[3],
                ablations=values[4], coefficients=values[5], sensitivities=values[6],
                calibrations=values[7], experiment=experiment.evidence(), holdout=None,
                data_provenance=provenance,
            )
            result = decide_phase5(evidence)
            report = build_phase5_report(values[1], values[2], values[3], result.decision)
            asserted = Phase5DecisionResult(
                replace(result.decision, model_status=ModelStatus.LOCKED_TEST_PENDING), None,
            )
            with self.assertRaisesRegex(ValueError, "must be derived"):
                build_registry_publication(
                    bundle=bundle(), report=report, evidence=evidence,
                    decision_result=asserted, code_commit=verified_source_commit("a" * 40),
                )
            with self.assertRaises(TypeError):
                build_registry_publication(
                    bundle=bundle(), report=report, evidence=evidence,
                    decision_result=result, code_commit="a" * 40,  # type: ignore[arg-type]
                )
            with self.assertRaises(ValueError):
                verified_source_commit("not-a-full-commit")
            with self.assertRaises(TypeError):
                SourceCommitEvidence()

    def test_publication_rejects_phase4_label_disagreement_before_candidate_promotion(self) -> None:
        trained = bundle()
        values = complete_fold_evidence()
        provenance = synthetic_provenance()
        with TemporaryDirectory() as directory:
            experiment = ExperimentRegistry.preregister(
                Path(directory) / "experiment", aligned_definition(
                    definition(candidate_hashes=phase4_candidate_hashes(trained)), values[0], provenance,
                ),
            )
            experiment.append_attempt(attempt("label-mismatch"))
            evidence = assemble_phase5_evidence(
                folds=values[0], reports=values[1], gaps=values[2], dimensions=values[3],
                ablations=values[4], coefficients=values[5], sensitivities=values[6],
                calibrations=values[7], experiment=experiment.evidence(), holdout=None,
                data_provenance=provenance,
            )
            result = decide_phase5(evidence)
            report = build_phase5_report(values[1], values[2], values[3], result.decision)
            wrong_label = replace(trained, metadata=replace(trained.metadata, label_version="labels-v2"))
            with self.assertRaisesRegex(ValueError, "comparison label"):
                build_registry_publication(
                    bundle=wrong_label, report=report, evidence=evidence,
                    decision_result=result, code_commit=verified_source_commit("a" * 40),
                )


if __name__ == "__main__":
    unittest.main()
