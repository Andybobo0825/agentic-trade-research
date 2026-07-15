from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tmf_research.experiments.registry import ExperimentRegistry, ModelStatus
from tmf_research.validation.approval import Phase5DecisionResult, assemble_phase5_evidence, decide_phase5
from tmf_research.validation.overfitting import FoldEvidence, ResearchStatus, StabilityDimensions, generalization_gap
from tmf_research.validation.report import FoldReport
from tests.overfitting.test_experiment_registry import attempt, definition
from tests.phase5_test_support import complete_fold_evidence


def decision_for(
    *,
    folds: tuple[FoldEvidence, ...] | None = None,
    dimensions: StabilityDimensions | None = None,
) -> Phase5DecisionResult:
    values = complete_fold_evidence()
    actual_folds = values[0] if folds is None else folds
    actual_dimensions = values[3] if dimensions is None else dimensions
    with TemporaryDirectory() as directory:
        registry = ExperimentRegistry.preregister(Path(directory) / "registry", definition())
        registry.append_attempt(attempt("a-1"))
        evidence = assemble_phase5_evidence(
            folds=actual_folds,
            reports=values[1], gaps=values[2], dimensions=actual_dimensions,
            ablations=values[4], coefficients=values[5], sensitivities=values[6],
            calibrations=values[7], experiment=registry.evidence(), holdout=None,
            data_provenance="SYNTHETIC_TEST_ONLY",
        )
        return decide_phase5(evidence)


class ModelSelectionTests(unittest.TestCase):
    def test_complete_synthetic_mechanics_can_only_be_candidate(self) -> None:
        result = decision_for()
        self.assertEqual(result.decision.research_status, ResearchStatus.COMPLETE)
        self.assertEqual(result.decision.model_status, ModelStatus.CANDIDATE)
        self.assertIsNone(result.approval)
        self.assertIn("SYNTHETIC_TEST_ONLY_CANNOT_APPROVE", result.decision.reasons)

    def test_fold_counts_are_manifest_derived_and_trades_reconcile(self) -> None:
        fold = complete_fold_evidence()[0][0]
        self.assertEqual((fold.train_candidates, fold.test_candidates), (5_000, 500))
        self.assertEqual(fold.fold_status, "VALID")
        with self.assertRaisesRegex(ValueError, "LONG plus SHORT"):
            replace(fold, trade_count=31)

    def test_duplicate_outer_fold_id_or_manifest_rejected(self) -> None:
        values = complete_fold_evidence()
        duplicate = (values[0][0], values[0][0], *values[0][2:])
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry.preregister(Path(directory) / "registry", definition())
            registry.append_attempt(attempt("a-1"))
            with self.assertRaisesRegex(ValueError, "unique"):
                assemble_phase5_evidence(
                    folds=duplicate, reports=values[1], gaps=values[2], dimensions=values[3],
                    ablations=values[4], coefficients=values[5], sensitivities=values[6],
                    calibrations=values[7], experiment=registry.evidence(), holdout=None,
                    data_provenance="SYNTHETIC_TEST_ONLY",
                )

    def test_exactly_half_brier_and_logloss_noninferiority_is_not_majority(self) -> None:
        values = complete_fold_evidence()
        folds = tuple(
            fold if index < 3 else replace(fold, baseline_brier=0.1, baseline_log_loss=0.4)
            for index, fold in enumerate(values[0])
        )
        reports = values[1]
        gaps = tuple(generalization_gap(fold) for fold in folds)
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry.preregister(Path(directory) / "registry", definition())
            registry.append_attempt(attempt("a-1"))
            evidence = assemble_phase5_evidence(
                folds=folds, reports=reports, gaps=gaps, dimensions=values[3],
                ablations=values[4], coefficients=values[5], sensitivities=values[6],
                calibrations=values[7], experiment=registry.evidence(), holdout=None,
                data_provenance="SYNTHETIC_TEST_ONLY",
            )
            decision = decide_phase5(evidence).decision
        self.assertEqual(decision.brier_noninferiority_ratio, 0.5)
        self.assertIn("BRIER_NOT_NONINFERIOR_IN_STRICT_MAJORITY", decision.reasons)
        self.assertIn("LOG_LOSS_NOT_NONINFERIOR_IN_STRICT_MAJORITY", decision.reasons)

    def test_contribution_maps_must_be_complete_finite_and_reconcile(self) -> None:
        base = complete_fold_evidence()[3]
        with self.assertRaisesRegex(ValueError, "reconcile"):
            StabilityDimensions(base.regimes, {"2026-01": 1.0}, base.directions, base.target_codes, 60.0)
        with self.assertRaises(ValueError):
            StabilityDimensions(base.regimes, base.months, {"LONG": float("nan"), "SHORT": 60.0}, base.target_codes, 60.0)

    def test_report_stability_cannot_disagree_with_authoritative_evidence(self) -> None:
        values = complete_fold_evidence()
        report = values[1][0]
        stability = dict(report.stability)
        stability["fold_profit_concentration"] = 0.4
        altered = FoldReport(
            report.fold_id, report.manifest_hash, report.split_regions,
            report.classification, report.trading, stability,
        )
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry.preregister(Path(directory) / "registry", definition())
            registry.append_attempt(attempt("report-reconcile"))
            with self.assertRaisesRegex(ValueError, "does not reconcile"):
                assemble_phase5_evidence(
                    folds=values[0], reports=(altered, *values[1][1:]), gaps=values[2],
                    dimensions=values[3], ablations=values[4], coefficients=values[5],
                    sensitivities=values[6], calibrations=values[7],
                    experiment=registry.evidence(), holdout=None,
                    data_provenance="SYNTHETIC_TEST_ONLY",
                )


if __name__ == "__main__":
    unittest.main()
