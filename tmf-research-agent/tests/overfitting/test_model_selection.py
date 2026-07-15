from __future__ import annotations

from dataclasses import replace
import unittest

from tmf_research.models.calibration import CalibrationMetrics
from tmf_research.validation.nested_walk_forward import SelectionCandidate, select_on_inner_validation
from tmf_research.validation.overfitting import (
    ApprovalGates,
    FoldEvidence,
    REQUIRED_REGIMES,
    StabilityDimensions,
    decide_model_status,
)


def fold(index: int, *, sufficient: bool = True, net_pnl: float = 10.0) -> FoldEvidence:
    return FoldEvidence(
        f"fold-{index}", 5000 if sufficient else 4999, 500, 30, 15, 15,
        0.3, 0.2, 0.1, 0.25, 0.6, net_pnl,
        0.5, 0.55, 0.2, 0.22, 1.2, 1.1, 0.05, 0.04,
    )


def dimensions() -> StabilityDimensions:
    return StabilityDimensions(
        {name: 1.0 for name in REQUIRED_REGIMES},
        {f"2026-{index:02d}": 5.0 for index in range(1, 11)},
        {"LONG": 25.0, "SHORT": 25.0},
        {"TMF202607": 25.0, "TMF202608": 25.0},
    )


def gates() -> ApprovalGates:
    return ApprovalGates(
        calibration=True, costs=True, event_independence=True,
        train_test_gap=True, coefficient_stability=True,
        parameter_robustness=True, regime_stability=True,
        target_code_stability=True, ablations_complete=True,
        search_budget_clean=True, all_rules_frozen=True,
        locked_holdout_status="PASSED",
    )


class ModelSelectionTests(unittest.TestCase):
    def test_selection_is_inner_only_and_lexicographic_brier_logloss_ece_ev(self) -> None:
        candidates = (
            SelectionCandidate("higher-ev", "INNER_VALIDATION", {"l2": 1.0}, CalibrationMetrics(0.2, 0.3, 0.1, 99.0)),
            SelectionCandidate("better-brier", "INNER_VALIDATION", {"l2": 2.0}, CalibrationMetrics(0.19, 0.9, 0.9, -1.0)),
        )
        selected = select_on_inner_validation(candidates).candidate
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.candidate_id, "better-brier")
        with self.assertRaisesRegex(ValueError, "Outer Test"):
            select_on_inner_validation((SelectionCandidate("leak", "OUTER_TEST", {}, CalibrationMetrics(0.1, 0.1, 0.1, 1.0)),))

    def test_sparse_bins_are_insufficient_evidence(self) -> None:
        result = select_on_inner_validation((
            SelectionCandidate("sparse", "INNER_VALIDATION", {}, CalibrationMetrics(0.1, 0.1, 0.1, 1.0), True),
        ))
        self.assertEqual(result.status, "INSUFFICIENT_CALIBRATION_EVIDENCE")

    def test_fewer_than_five_valid_folds_rejects_insufficient(self) -> None:
        decision = decide_model_status(tuple(fold(index) for index in range(4)), dimensions(), gates(), data_provenance="REAL_READONLY_MARKET_DATA")
        self.assertEqual(decision.research_status, "RESEARCH_INSUFFICIENT_DATA")
        self.assertEqual(decision.model_status, "REJECTED_INSUFFICIENT_DATA")

    def test_synthetic_mechanics_never_approve(self) -> None:
        decision = decide_model_status(tuple(fold(index) for index in range(5)), dimensions(), gates(), data_provenance="SYNTHETIC_TEST_ONLY")
        self.assertEqual(decision.model_status, "CANDIDATE")
        self.assertIn("SYNTHETIC_TEST_ONLY_CANNOT_APPROVE", decision.reasons)

    def test_nonpositive_total_cannot_bypass_concentration(self) -> None:
        decision = decide_model_status(tuple(fold(index, net_pnl=-1.0) for index in range(5)), dimensions(), gates(), data_provenance="REAL_READONLY_MARKET_DATA")
        self.assertEqual(decision.model_status, "REJECTED_OVERFIT_RISK")
        self.assertIn("NON_POSITIVE_TOTAL_OUTER_NET_PNL", decision.reasons)

    def test_sample_boundaries_are_inclusive_and_each_minimum_is_required(self) -> None:
        exact = fold(1)
        self.assertTrue(exact.sample_sufficient)
        self.assertEqual(exact.fold_status, "VALID")
        cases = (
            replace(exact, train_candidates=4_999),
            replace(exact, test_candidates=499),
            replace(exact, trade_count=29),
            replace(exact, long_count=9),
            replace(exact, short_count=9),
        )
        for insufficient in cases:
            with self.subTest(fold=insufficient):
                self.assertEqual(insufficient.fold_status, "INSUFFICIENT_SAMPLE")

    def test_fold_month_and_direction_concentration_caps_are_derived_not_asserted(self) -> None:
        concentrated_folds = tuple(
            fold(index, net_pnl=30.0 if index == 0 else 5.0) for index in range(5)
        )
        decision = decide_model_status(
            concentrated_folds, dimensions(), gates(), data_provenance="REAL_READONLY_MARKET_DATA",
        )
        self.assertIn("FOLD_CONCENTRATION_ABOVE_40_PERCENT", decision.reasons)
        base = dimensions()
        concentrated_dimensions = StabilityDimensions(
            base.regimes,
            {"2026-01": 20.0, "2026-02": 10.0, "2026-03": 10.0, "2026-04": 10.0},
            {"LONG": 45.0, "SHORT": 5.0},
            base.target_codes,
        )
        decision = decide_model_status(
            tuple(fold(index) for index in range(5)),
            concentrated_dimensions,
            gates(),
            data_provenance="REAL_READONLY_MARKET_DATA",
        )
        self.assertIn("MONTH_CONCENTRATION_ABOVE_30_PERCENT", decision.reasons)
        self.assertIn("DIRECTION_CONCENTRATION_ABOVE_85_PERCENT", decision.reasons)

    def test_majority_brier_and_logloss_noninferiority_are_mandatory(self) -> None:
        folds = tuple(
            replace(fold(index), baseline_brier=0.1, baseline_log_loss=0.4)
            for index in range(5)
        )
        decision = decide_model_status(folds, dimensions(), gates(), data_provenance="REAL_READONLY_MARKET_DATA")
        self.assertIn("BRIER_WORSE_THAN_BASELINE_IN_MAJORITY", decision.reasons)
        self.assertIn("LOG_LOSS_WORSE_THAN_BASELINE_IN_MAJORITY", decision.reasons)


if __name__ == "__main__":
    unittest.main()
