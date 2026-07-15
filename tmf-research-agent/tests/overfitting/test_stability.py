from __future__ import annotations

import unittest

from tmf_research.validation.ablation import (
    ABLATION_GROUPS,
    AblationComparison,
    AblationFoldResult,
    compare_all_ablations,
)
from tmf_research.validation.stability import (
    CoefficientObservation,
    FeatureCoefficientStability,
    FeatureProfile,
    FeatureRemovalEvidence,
    coefficient_stability,
    parameter_fragility,
    redundancy_groups,
    sensitivity_grid,
)


class StabilityTests(unittest.TestCase):
    def test_train_only_correlation_and_nonfinite_values_fail_closed(self) -> None:
        profiles = (
            FeatureProfile("complete_complex", (1.0, 2.0, 3.0), 5, 0.9),
            FeatureProfile("incomplete_simple", (1.0, None, 3.0), 1, 1.0),
            FeatureProfile("complete_simple", (2.0, 4.0, 6.0), 1, 0.8),
        )
        self.assertEqual(redundancy_groups(profiles)[0].retained, "complete_simple")
        with self.assertRaises(ValueError):
            FeatureProfile("leak", (1.0, 2.0), 1, 1.0, evidence_role="OUTER_TEST")
        with self.assertRaises(ValueError):
            FeatureProfile("nan", (1.0, float("nan")), 1, 1.0)

    def test_coefficients_require_unique_folds_removal_evidence_and_70_percent_sign(self) -> None:
        observations = tuple(
            CoefficientObservation(f"f-{index}", "x", coefficient, abs(coefficient), index + 1, True)
            for index, coefficient in enumerate((1.0, 0.8, 1.2, 0.4, 0.9))
        )
        removals = tuple(FeatureRemovalEvidence(f"f-{index}", "x", 0.2, 0.1) for index in range(5))
        report = coefficient_stability(observations, removals)[0]
        self.assertFalse(report.unstable_feature)
        self.assertEqual(report.removal_support_ratio, 1.0)
        with self.assertRaisesRegex(ValueError, "unique"):
            coefficient_stability((observations[0], observations[0]), (removals[0], removals[0]))
        flipped = (
            *observations[:3],
            CoefficientObservation("f-3", "x", -0.4, 0.4, 4, True),
            CoefficientObservation("f-4", "x", -0.9, 0.9, 5, True),
        )
        self.assertTrue(coefficient_stability(flipped, removals)[0].unstable_feature)
        with self.assertRaises(TypeError):
            FeatureCoefficientStability()

    def test_all_eight_ablations_compare_identical_folds_to_full_model(self) -> None:
        full = tuple(AblationFoldResult(f"f-{index}", 0.5, 0.2, 0.2, 30, 2.0) for index in range(5))
        removed = {
            group: tuple(AblationFoldResult(f"f-{index}", 0.6, 0.3, 0.1, 30, 3.0) for index in range(5))
            for group in ABLATION_GROUPS
        }
        comparisons = compare_all_ablations(full, removed)
        self.assertEqual(len(comparisons), 8)
        self.assertTrue(all(value.group_supported for value in comparisons))
        with self.assertRaises(TypeError):
            AblationComparison()
        with self.assertRaises(ValueError):
            compare_all_ablations(full, {key: value for key, value in removed.items() if key != "TIME"})

    def test_fixed_parameter_neighbors_and_nan_cannot_appear_stable(self) -> None:
        grid = sensitivity_grid(2.0, 0.6, 1.5)
        self.assertEqual(grid.l2, (1.0, 2.0, 4.0))
        selected = (2.0, 0.6, 1.5)
        results = {
            (1.0, 0.6, 1.5): -1.0, selected: 1.0, (4.0, 0.6, 1.5): -1.0,
            (2.0, 0.55, 1.5): -1.0, (2.0, 0.65, 1.5): -1.0,
            (2.0, 0.6, 1.25): -1.0, (2.0, 0.6, 1.75): -1.0,
        }
        self.assertTrue(parameter_fragility(results, selected))
        results[(1.0, 0.6, 1.5)] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            parameter_fragility(results, selected)


if __name__ == "__main__":
    unittest.main()
