from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tmf_research.experiments.comparison import canonical_fold_periods
from tmf_research.experiments.registry import ExperimentRegistry, ModelStatus
from tmf_research.models.calibration import CalibrationMetrics
from tmf_research.validation.approval import Phase5DecisionResult, assemble_phase5_evidence, decide_phase5
from tmf_research.validation.overfitting import FoldEvidence, ResearchStatus, StabilityDimensions, _core_reasons, generalization_gap
from tmf_research.validation.report import FoldReport
from tests.overfitting.test_experiment_registry import attempt, definition
from tests.phase4_test_support import TestPhase4FoldPlanner
from tests.phase5_test_support import (
    _row, aligned_definition, complete_fold_evidence, regime_contributions,
    replace_test_fold, synthetic_provenance,
)


def evidence_with_candidate_counts(train_candidates: int, test_candidates: int) -> FoldEvidence:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    inner_validation_count = 1
    train_count = train_candidates - inner_validation_count
    train_rows = tuple(
        _row(f"threshold-train-{index}", start + timedelta(minutes=index), index)
        for index in range(train_count)
    )
    train_end = start + timedelta(minutes=train_count)
    validation_start = train_end + timedelta(minutes=2)
    validation_rows = (_row("threshold-validation", validation_start, 0),)
    validation_end = validation_start + timedelta(minutes=2)
    test_start = validation_end + timedelta(minutes=2)
    test_rows = tuple(
        _row(f"threshold-test-{index}", test_start + timedelta(minutes=index), index)
        for index in range(test_candidates)
    )
    materialized = TestPhase4FoldPlanner().issue(
        source_rows=(*train_rows, *validation_rows, *test_rows),
        outer_fold_id=f"threshold-{train_candidates}-{test_candidates}", inner_fold_id="inner-threshold",
        train_start=start, train_end=train_end,
        validation_start=validation_start, validation_end=validation_end,
        outer_test_start=test_start, outer_test_end=test_start + timedelta(minutes=test_candidates + 1),
    )
    return replace_test_fold(complete_fold_evidence()[0][0], manifest=materialized.manifest)


def decision_for(
    *,
    folds: tuple[FoldEvidence, ...] | None = None,
    dimensions: StabilityDimensions | None = None,
) -> Phase5DecisionResult:
    values = complete_fold_evidence()
    actual_folds = values[0] if folds is None else folds
    actual_dimensions = values[3] if dimensions is None else dimensions
    provenance = synthetic_provenance()
    with TemporaryDirectory() as directory:
        registry = ExperimentRegistry.preregister(
            Path(directory) / "registry", aligned_definition(definition(), actual_folds, provenance),
        )
        registry.append_attempt(attempt("a-1"))
        evidence = assemble_phase5_evidence(
            folds=actual_folds,
            reports=values[1], gaps=values[2], dimensions=actual_dimensions,
            ablations=values[4], coefficients=values[5], sensitivities=values[6],
            calibrations=values[7], experiment=registry.evidence(), holdout=None,
            data_provenance=provenance,
        )
        return decide_phase5(evidence)


class ModelSelectionTests(unittest.TestCase):
    def test_fold_evidence_public_construction_and_replace_are_closed(self) -> None:
        with self.assertRaises(TypeError):
            FoldEvidence()
        with self.assertRaises(TypeError):
            replace(complete_fold_evidence()[0][0], net_pnl=999.0)

    def test_candidate_order_is_strict_brier_logloss_ece_then_descending_ev(self) -> None:
        priorities = (
            ("best_brier", CalibrationMetrics(0.09, 9.0, 9.0, -9.0)),
            ("best_logloss", CalibrationMetrics(0.10, 0.19, 9.0, -9.0)),
            ("best_ece", CalibrationMetrics(0.10, 0.20, 0.09, -9.0)),
            ("best_ev", CalibrationMetrics(0.10, 0.20, 0.10, 2.0)),
            ("lower_ev", CalibrationMetrics(0.10, 0.20, 0.10, 1.0)),
        )
        self.assertEqual(
            tuple(name for name, _ in sorted(priorities, key=lambda item: item[1].sort_key)),
            ("best_brier", "best_logloss", "best_ece", "best_ev", "lower_ev"),
        )

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
            replace_test_fold(fold, trade_count=31)
        with self.assertRaisesRegex(ValueError, "integer"):
            replace_test_fold(fold, trade_count=30.0, long_count=15.0, short_count=15.0)

    def test_duplicate_outer_fold_id_or_manifest_rejected(self) -> None:
        values = complete_fold_evidence()
        duplicate = (values[0][0], values[0][0], *values[0][2:])
        provenance = synthetic_provenance()
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry.preregister(
                Path(directory) / "registry", aligned_definition(definition(), values[0], provenance),
            )
            registry.append_attempt(attempt("a-1"))
            with self.assertRaisesRegex(ValueError, "unique"):
                assemble_phase5_evidence(
                    folds=duplicate, reports=values[1], gaps=values[2], dimensions=values[3],
                    ablations=values[4], coefficients=values[5], sensitivities=values[6],
                    calibrations=values[7], experiment=registry.evidence(), holdout=None,
                    data_provenance=provenance,
                )

    def test_exactly_half_brier_and_logloss_noninferiority_is_not_majority(self) -> None:
        values = complete_fold_evidence()
        folds = tuple(
            fold if index < 3 else replace_test_fold(fold, baseline_brier=0.1, baseline_log_loss=0.4)
            for index, fold in enumerate(values[0])
        )
        reports = values[1]
        gaps = tuple(generalization_gap(fold) for fold in folds)
        provenance = synthetic_provenance()
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry.preregister(
                Path(directory) / "registry", aligned_definition(definition(), folds, provenance),
            )
            registry.append_attempt(attempt("a-1"))
            evidence = assemble_phase5_evidence(
                folds=folds, reports=reports, gaps=gaps, dimensions=values[3],
                ablations=values[4], coefficients=values[5], sensitivities=values[6],
                calibrations=values[7], experiment=registry.evidence(), holdout=None,
                data_provenance=provenance,
            )
            decision = decide_phase5(evidence).decision
        self.assertEqual(decision.brier_noninferiority_ratio, 0.5)
        self.assertIn("BRIER_NOT_NONINFERIOR_IN_STRICT_MAJORITY", decision.reasons)
        self.assertIn("LOG_LOSS_NOT_NONINFERIOR_IN_STRICT_MAJORITY", decision.reasons)

    def test_fewer_than_five_and_each_trade_threshold_fail_closed(self) -> None:
        values = complete_fold_evidence()
        self.assertIn(
            "FEWER_THAN_FIVE_VALID_OUTER_FOLDS",
            _core_reasons(values[0][:4], StabilityDimensions(
                regime_contributions(40.0), {"m1": 20.0, "m2": 20.0},
                {"LONG": 20.0, "SHORT": 20.0}, {"T1": 20.0, "T2": 20.0},
                40.0, {f"e{i}": 10.0 for i in range(4)}, True,
            ))[2],
        )
        fold = values[0][0]
        for insufficient in (
            replace_test_fold(fold, trade_count=29, long_count=14, short_count=15),
            replace_test_fold(fold, trade_count=30, long_count=9, short_count=21),
            replace_test_fold(fold, trade_count=30, long_count=21, short_count=9),
        ):
            with self.subTest(counts=(insufficient.trade_count, insufficient.long_count, insufficient.short_count)):
                self.assertFalse(insufficient.sample_sufficient)

    def test_each_manifest_derived_candidate_threshold_fails_one_below(self) -> None:
        for train_candidates, test_candidates in ((4_999, 500), (5_000, 499)):
            with self.subTest(train_candidates=train_candidates, test_candidates=test_candidates):
                fold = evidence_with_candidate_counts(train_candidates, test_candidates)
                self.assertEqual((fold.train_candidates, fold.test_candidates), (train_candidates, test_candidates))
                self.assertFalse(fold.sample_sufficient)

    def test_nonpositive_70_percent_and_concentration_caps_fail_closed(self) -> None:
        values = complete_fold_evidence()
        weak = tuple(
            fold if index < 4 else replace_test_fold(fold, test_ev=-0.1)
            for index, fold in enumerate(values[0])
        )
        weak_reasons = _core_reasons(weak, values[3])[2]
        self.assertIn("NON_NEGATIVE_FOLD_RATIO_BELOW_70_PERCENT", weak_reasons)
        self.assertIn("BASELINE_OUTPERFORMANCE_BELOW_70_PERCENT", weak_reasons)
        concentrated = StabilityDimensions(
            values[3].regimes, {"m1": 19.0, "m2": 14.0, "m3": 14.0, "m4": 13.0},
            {"LONG": 52.0, "SHORT": 8.0}, values[3].target_codes, 60.0,
            values[3].events, True,
        )
        concentrated_folds = (
            replace_test_fold(values[0][0], net_pnl=30.0),
            *(replace_test_fold(fold, net_pnl=6.0) for fold in values[0][1:]),
        )
        cap_reasons = _core_reasons(concentrated_folds, concentrated)[2]
        self.assertIn("FOLD_CONCENTRATION_ABOVE_40_PERCENT", cap_reasons)
        self.assertIn("MONTH_CONCENTRATION_ABOVE_30_PERCENT", cap_reasons)
        self.assertIn("DIRECTION_CONCENTRATION_ABOVE_85_PERCENT", cap_reasons)
        negative_folds = tuple(replace_test_fold(fold, net_pnl=-10.0) for fold in values[0])
        negative_dimensions = StabilityDimensions(
            regime_contributions(-60.0), {"m1": -30.0, "m2": -30.0},
            {"LONG": -30.0, "SHORT": -30.0}, {"T1": -30.0, "T2": -30.0},
            -60.0, {f"e{i}": -10.0 for i in range(6)}, True,
        )
        self.assertIn("NON_POSITIVE_TOTAL_OUTER_NET_PNL", _core_reasons(negative_folds, negative_dimensions)[2])

    def test_contribution_maps_must_be_complete_finite_and_reconcile(self) -> None:
        base = complete_fold_evidence()[3]
        with self.assertRaisesRegex(ValueError, "reconcile"):
            StabilityDimensions(base.regimes, {"2026-01": 1.0}, base.directions, base.target_codes, 60.0, base.events, True)
        with self.assertRaises(ValueError):
            StabilityDimensions(base.regimes, base.months, {"LONG": float("nan"), "SHORT": 60.0}, base.target_codes, 60.0, base.events, True)

    def test_cost_event_regime_and_target_gates_are_derived(self) -> None:
        values = complete_fold_evidence()
        base = values[3]
        risky = StabilityDimensions(
            {**base.regimes, "DAY": -1.0, "NIGHT": 61.0},
            base.months, base.directions,
            {"TMF202607": -1.0, "TMF202608": 61.0}, 60.0,
            {"event-1": 30.0, "event-2": 30.0}, False,
        )
        reasons = _core_reasons(values[0], risky)[2]
        self.assertIn("INCOMPLETE_COST_MODEL", reasons)
        self.assertIn("NEGATIVE_REGIME_CONTRIBUTION", reasons)
        self.assertIn("NEGATIVE_TARGET_CODE_CONTRIBUTION", reasons)
        self.assertIn("EVENT_CONCENTRATION_ABOVE_40_PERCENT", reasons)

    def test_report_stability_cannot_disagree_with_authoritative_evidence(self) -> None:
        values = complete_fold_evidence()
        report = values[1][0]
        stability = dict(report.stability)
        stability["fold_profit_concentration"] = 0.4
        altered = FoldReport(
            report.fold_id, report.manifest_hash, report.split_regions,
            report.classification, report.trading, stability,
        )
        provenance = synthetic_provenance()
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry.preregister(
                Path(directory) / "registry", aligned_definition(definition(), values[0], provenance),
            )
            registry.append_attempt(attempt("report-reconcile"))
            with self.assertRaisesRegex(ValueError, "does not reconcile"):
                assemble_phase5_evidence(
                    folds=values[0], reports=(altered, *values[1][1:]), gaps=values[2],
                    dimensions=values[3], ablations=values[4], coefficients=values[5],
                    sensitivities=values[6], calibrations=values[7],
                    experiment=registry.evidence(), holdout=None,
                    data_provenance=provenance,
                )

    def test_experiment_context_must_match_exact_fold_plan(self) -> None:
        values = complete_fold_evidence()
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry.preregister(Path(directory) / "registry", definition())
            registry.append_attempt(attempt("wrong-context"))
            with self.assertRaisesRegex(ValueError, "fold plan|comparison context"):
                assemble_phase5_evidence(
                    folds=values[0], reports=values[1], gaps=values[2], dimensions=values[3],
                    ablations=values[4], coefficients=values[5], sensitivities=values[6],
                    calibrations=values[7], experiment=registry.evidence(), holdout=None,
                    data_provenance=synthetic_provenance(),
                )

    def test_preregistered_periods_must_match_actual_fold_temporal_coverage(self) -> None:
        values = complete_fold_evidence()
        provenance = synthetic_provenance()
        aligned = aligned_definition(definition(), values[0], provenance)
        exact_train, exact_evaluation = canonical_fold_periods(tuple(fold.manifest for fold in values[0]))
        self.assertEqual(aligned.train_period, exact_train)
        self.assertEqual(aligned.comparison.evaluation_period, exact_evaluation)
        self.assertTrue(exact_train.startswith(values[0][0].manifest.inner_train.start.isoformat()))
        self.assertTrue(exact_evaluation.endswith(values[0][-1].manifest.outer_test.end.isoformat()))
        cases = (
            replace(aligned, train_period="1900-01-01/1900-12-31"),
            replace(aligned, comparison=replace(
                aligned.comparison, evaluation_period="1900-01-01/1900-12-31",
            )),
        )
        for index, mismatched in enumerate(cases):
            with self.subTest(index=index), TemporaryDirectory() as directory:
                registry = ExperimentRegistry.preregister(Path(directory) / "registry", mismatched)
                registry.append_attempt(attempt(f"wrong-period-{index}"))
                with self.assertRaisesRegex(ValueError, "temporal|period"):
                    assemble_phase5_evidence(
                        folds=values[0], reports=values[1], gaps=values[2], dimensions=values[3],
                        ablations=values[4], coefficients=values[5], sensitivities=values[6],
                        calibrations=values[7], experiment=registry.evidence(), holdout=None,
                        data_provenance=provenance,
                    )


if __name__ == "__main__":
    unittest.main()
