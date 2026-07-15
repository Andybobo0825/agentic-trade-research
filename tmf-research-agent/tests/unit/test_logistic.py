from __future__ import annotations

import unittest

from tmf_research.models.logistic import ModelTrainingSample, fit_two_stage_logistic


class LogisticTests(unittest.TestCase):
    def test_two_stage_training_records_scope_weights_and_exclusions(self) -> None:
        samples = (
            ModelTrainingSample((-2.0,), "NO_TRADE"), ModelTrainingSample((-1.0,), "NO_TRADE"),
            ModelTrainingSample((1.0,), "LONG"), ModelTrainingSample((2.0,), "SHORT"),
            ModelTrainingSample((9.0,), "AMBIGUOUS"), ModelTrainingSample((9.0,), "LONG", is_complete=False),
        )
        model = fit_two_stage_logistic(
            samples, feature_order=("return_1m",), l2=0.5, class_weights={0: 1.0, 1: 2.0},
            max_iterations=400, tolerance=1e-8, random_seed=7,
        )

        self.assertEqual(model.trade_model.record.sample_count, 4)
        self.assertEqual(model.direction_model.record.sample_count, 2)
        self.assertEqual(model.record.excluded_ambiguous, 1)
        self.assertEqual(model.record.excluded_incomplete, 1)
        self.assertEqual(model.trade_model.l2, 0.5)
        self.assertEqual(model.trade_model.max_iterations, 400)
        self.assertEqual(model.trade_model.feature_order, ("return_1m",))
        self.assertEqual(model.direction_model.classes, ("SHORT", "LONG"))
        self.assertAlmostEqual(sum(model.predict((1.5,)).as_tuple()), 1.0)


if __name__ == "__main__":
    unittest.main()
