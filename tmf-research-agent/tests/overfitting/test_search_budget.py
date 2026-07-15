from __future__ import annotations

import unittest

from tmf_research.experiments.search_budget import SearchBudgetLimits, SearchSpaceManifest


def space(*, feature_sets: tuple[str, ...] = ("core",)) -> SearchSpaceManifest:
    return SearchSpaceManifest(
        model_families=("LOGISTIC",),
        feature_sets=feature_sets,
        hyperparameter_combinations=("hp-1",),
        barrier_combinations=("barrier-1",),
        threshold_combinations=("threshold-1",),
        calibration_methods=("UNCALIBRATED", "PLATT", "ISOTONIC"),
    )


class SearchBudgetTests(unittest.TestCase):
    def test_limits_are_immutable_exact_2_8_30_12_12_3(self) -> None:
        self.assertEqual(tuple(SearchBudgetLimits().as_dict().values()), (2, 8, 30, 12, 12, 3))
        with self.assertRaises(ValueError):
            SearchBudgetLimits(hyperparameter_combinations=31)

    def test_every_dimension_enforces_ceiling_and_manifest_hash_is_canonical(self) -> None:
        first = space()
        second = space()
        self.assertEqual(first.canonical_hash, second.canonical_hash)
        with self.assertRaisesRegex(ValueError, "feature_sets"):
            space(feature_sets=tuple(f"f-{index}" for index in range(9)))
        limits = SearchBudgetLimits().as_dict()
        base = space()
        for field, limit in limits.items():
            values = {
                "model_families": base.model_families,
                "feature_sets": base.feature_sets,
                "hyperparameter_combinations": base.hyperparameter_combinations,
                "barrier_combinations": base.barrier_combinations,
                "threshold_combinations": base.threshold_combinations,
                "calibration_methods": base.calibration_methods,
            }
            values[field] = tuple(f"{field}-{index}" for index in range(limit + 1))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                SearchSpaceManifest(
                    model_families=values["model_families"],
                    feature_sets=values["feature_sets"],
                    hyperparameter_combinations=values["hyperparameter_combinations"],
                    barrier_combinations=values["barrier_combinations"],
                    threshold_combinations=values["threshold_combinations"],
                    calibration_methods=values["calibration_methods"],
                )


if __name__ == "__main__":
    unittest.main()
