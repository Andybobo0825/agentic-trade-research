from __future__ import annotations

import unittest

from tmf_research.validation.ablation import (
    ABLATION_GROUPS,
    AblationFoldResult,
    AblationResult,
    require_complete_ablations,
    run_all_ablations,
)
from tmf_research.validation.stability import (
    CoefficientObservation,
    FeatureProfile,
    coefficient_stability,
    parameter_fragility,
    redundancy_groups,
    sensitivity_grid,
)


class StabilityTests(unittest.TestCase):
    def test_train_only_abs_correlation_above_point_nine_groups_and_prioritizes(self) -> None:
        profiles = (
            FeatureProfile("complete_complex", (1.0, 2.0, 3.0), 5, 0.9),
            FeatureProfile("incomplete_simple", (1.0, None, 3.0), 1, 1.0),
            FeatureProfile("complete_simple", (2.0, 4.0, 6.0), 1, 0.8),
        )
        result = redundancy_groups(profiles)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].retained, "complete_simple")
        with self.assertRaisesRegex(ValueError, "Train"):
            FeatureProfile("leak", (1.0, 2.0), 1, 1.0, evidence_role="OUTER_TEST")

    def test_coefficient_value_sign_magnitude_rank_and_flip_are_reported(self) -> None:
        observations = tuple(
            CoefficientObservation(f"f-{index}", "x", coefficient, abs(coefficient), index + 1, True)
            for index, coefficient in enumerate((1.0, 0.8, 1.2, -0.4, 0.9))
        )
        report = coefficient_stability(observations)[0]
        self.assertEqual(report.observations[0].sign, 1)
        self.assertTrue(report.unstable_feature)
        self.assertEqual(report.dominant_sign_ratio, 0.8)

    def test_all_eight_ablations_are_required_with_fold_metrics(self) -> None:
        fold = AblationFoldResult("f1", 0.5, 0.2, 0.1, 30, 2.0)
        results = tuple(AblationResult(group, (fold,), 0.8) for group in ABLATION_GROUPS)
        self.assertEqual(len(require_complete_ablations(results)), 8)
        self.assertEqual(len(run_all_ablations(lambda group: AblationResult(group, (fold,), 0.8))), 8)
        with self.assertRaises(ValueError):
            require_complete_ablations(results[:-1])

    def test_fixed_parameter_neighborhood_and_isolated_peak_fragility(self) -> None:
        grid = sensitivity_grid(2.0, 0.6, 1.5)
        self.assertEqual(grid.l2, (1.0, 2.0, 4.0))
        self.assertEqual(grid.threshold, (0.55, 0.6, 0.65))
        self.assertEqual(grid.atr_multiplier, (1.25, 1.5, 1.75))
        selected = (2.0, 0.6, 1.5)
        results = {
            (1.0, 0.6, 1.5): -1.0, selected: 1.0, (4.0, 0.6, 1.5): -1.0,
            (2.0, 0.55, 1.5): -1.0, (2.0, 0.65, 1.5): -1.0,
            (2.0, 0.6, 1.25): -1.0, (2.0, 0.6, 1.75): -1.0,
        }
        self.assertTrue(parameter_fragility(results, selected))


if __name__ == "__main__":
    unittest.main()
