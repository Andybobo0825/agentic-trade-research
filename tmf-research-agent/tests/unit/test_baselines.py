from __future__ import annotations

import unittest
from datetime import timedelta

from tmf_research.models.baselines import BaselineObservation, ReturnOnlyBaseline, baseline_0, baseline_1, baseline_2, baseline_3, report_outer_fold
from tmf_research.models.provenance import InnerTrainDataset, InnerTrainRow
from tmf_research.models.training import Phase4TrainingSpec, train_phase4_model

from tests.unit.test_phase4_training import END, START


class BaselineTests(unittest.TestCase):
    def test_baselines_zero_through_three_are_exact_and_deterministic(self) -> None:
        observation = BaselineObservation(103.0, 101.0, 102.0, 0.5, (0.02,))

        self.assertEqual(baseline_0(observation), "NO_TRADE")
        self.assertEqual(baseline_1(observation), "LONG")
        self.assertEqual(baseline_2(observation), "LONG")
        self.assertEqual(baseline_3(observation), "LONG")
        self.assertEqual(baseline_1(BaselineObservation(100.0, 100.0, 100.0, 0.0, (0.0,))), "NO_TRADE")
        with self.assertRaisesRegex(ValueError, "finite"):
            BaselineObservation(float("nan"), 100.0, 100.0, 0.0, (0.0,))

    def test_baseline_four_uses_only_price_returns_and_reports_outer_fold(self) -> None:
        rows = (
            InnerTrainRow(START + timedelta(days=1), {"return_1m": -2.0}, "NO_TRADE"),
            InnerTrainRow(START + timedelta(days=2), {"return_1m": -1.0}, "NO_TRADE"),
            InnerTrainRow(START + timedelta(days=3), {"return_1m": 1.0}, "SHORT"),
            InnerTrainRow(START + timedelta(days=4), {"return_1m": 2.0}, "LONG"),
        )
        dataset = InnerTrainDataset.create(
            fold_id="outer-1/inner-1", dataset_hash="b" * 64,
            fit_start=START, fit_end=END, rows=rows,
        )
        direction_model = train_phase4_model(
            dataset,
            Phase4TrainingSpec(primary_features=("return_1m",), required_features=("return_1m",)),
        ).model.direction_model
        baseline = ReturnOnlyBaseline(direction_model)

        report = report_outer_fold(
            outer_fold_id="outer-1",
            observations=(BaselineObservation(1.0, 1.0, 1.0, 0.0, (2.0,)),),
            return_only=baseline,
        )
        self.assertEqual(baseline.predict(BaselineObservation(1.0, 1.0, 1.0, 0.0, (2.0,))), "LONG")
        self.assertEqual(report.outer_fold_id, "outer-1")
        self.assertEqual(tuple(name for name, _ in report.predictions), ("BASELINE_0", "BASELINE_1", "BASELINE_2", "BASELINE_3", "BASELINE_4"))


if __name__ == "__main__":
    unittest.main()
