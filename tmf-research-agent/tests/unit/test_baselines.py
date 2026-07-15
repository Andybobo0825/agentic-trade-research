from __future__ import annotations

import unittest

from tmf_research.models.baselines import BaselineObservation, ReturnOnlyBaseline, baseline_0, baseline_1, baseline_2, baseline_3, report_outer_fold
from tmf_research.models.logistic import BinaryTrainingSample, fit_binary_logistic


class BaselineTests(unittest.TestCase):
    def test_baselines_zero_through_three_are_exact_and_deterministic(self) -> None:
        observation = BaselineObservation(103.0, 101.0, 102.0, 0.5, (0.02,))

        self.assertEqual(baseline_0(observation), "NO_TRADE")
        self.assertEqual(baseline_1(observation), "LONG")
        self.assertEqual(baseline_2(observation), "LONG")
        self.assertEqual(baseline_3(observation), "LONG")
        self.assertEqual(baseline_1(BaselineObservation(100.0, 100.0, 100.0, 0.0, (0.0,))), "NO_TRADE")

    def test_baseline_four_uses_only_price_returns(self) -> None:
        model = fit_binary_logistic(
            (BinaryTrainingSample((-2.0,), 0), BinaryTrainingSample((-1.0,), 0), BinaryTrainingSample((1.0,), 1), BinaryTrainingSample((2.0,), 1)),
            feature_order=("return_1m",), l2=0.1, class_weights={0: 1.0, 1: 1.0},
        )
        baseline = ReturnOnlyBaseline(model)

        self.assertEqual(baseline.predict(BaselineObservation(1.0, 1.0, 1.0, 0.0, (2.0,))), "LONG")
        self.assertEqual(baseline.feature_order, ("return_1m",))
        report = report_outer_fold(
            outer_fold_id="outer-1",
            observations=(BaselineObservation(1.0, 1.0, 1.0, 0.0, (2.0,)),),
            return_only=baseline,
        )
        self.assertEqual(report.outer_fold_id, "outer-1")
        self.assertEqual(tuple(name for name, _ in report.predictions), ("BASELINE_0", "BASELINE_1", "BASELINE_2", "BASELINE_3", "BASELINE_4"))


if __name__ == "__main__":
    unittest.main()
