from __future__ import annotations

import unittest
from datetime import timedelta

from tmf_research.models.calibration import IsotonicCalibrator, TwoStageCalibrator, fit_two_stage_calibrators
from tmf_research.models.provenance import InnerValidationPrediction, InnerValidationPredictions

from tests.unit.test_phase4_training import END, inner_train_dataset, training_spec
from tmf_research.models.training import train_phase4_model


def validation_predictions(*, sparse: bool = False) -> InnerValidationPredictions:
    training = train_phase4_model(inner_train_dataset(), training_spec())
    count = 4 if sparse else 20
    trade_outcomes: tuple[int, ...]
    direction_outcomes: tuple[int | None, ...]
    if sparse:
        trade_outcomes = (0, 1, 0, 1)
        direction_outcomes = (None, 0, None, 1)
    else:
        trade_outcomes = tuple(0 if index < 10 else 1 for index in range(count))
        direction_outcomes = tuple(None if index < 10 else (0 if index < 15 else 1) for index in range(count))
    rows = tuple(
        InnerValidationPrediction(
            available_at=END + timedelta(minutes=index + 1),
            p_trade=(index + 1) / (count + 1),
            trade_outcome=trade_outcomes[index],
            p_long_given_trade=None if direction_outcomes[index] is None else (index + 1) / (count + 1),
            direction_outcome=direction_outcomes[index],
            net_return=-1.0 if trade_outcomes[index] == 0 else 1.0,
        )
        for index in range(count)
    )
    return InnerValidationPredictions.create(
        provenance=inner_train_dataset().provenance,
        preprocessor_hash=training.preprocessor.content_hash,
        model_hash=training.model.content_hash,
        rows=rows,
    )


class CalibrationTests(unittest.TestCase):
    def test_calibrates_both_stages_and_binds_model_fold_provenance(self) -> None:
        predictions = validation_predictions()
        result = fit_two_stage_calibrators(predictions, bin_count=4, minimum_bin_size=2)

        self.assertTrue(result.candidate_eligible)
        self.assertFalse(result.calibrator.insufficient_evidence)
        self.assertEqual(result.calibrator.provenance, predictions.provenance)
        self.assertEqual(result.calibrator.model_hash, predictions.model_hash)
        self.assertEqual(result.calibrator.preprocessor_hash, predictions.preprocessor_hash)
        self.assertEqual(tuple(item.method for item in result.trade.candidates), ("UNCALIBRATED", "PLATT", "ISOTONIC"))
        self.assertEqual(tuple(item.method for item in result.direction.candidates), ("UNCALIBRATED", "PLATT", "ISOTONIC"))
        self.assertEqual(result.trade.selected.metrics.sort_key, min(item.metrics.sort_key for item in result.trade.candidates))
        self.assertEqual(result.direction.selected.metrics.sort_key, min(item.metrics.sort_key for item in result.direction.candidates))

    def test_isotonic_groups_duplicate_x_with_empirical_weighted_value(self) -> None:
        training = train_phase4_model(inner_train_dataset(), training_spec())
        rows = (
            InnerValidationPrediction(END + timedelta(minutes=1), 0.2, 0, None, None, -1.0),
            InnerValidationPrediction(END + timedelta(minutes=2), 0.2, 1, 0.2, 1, 1.0),
            InnerValidationPrediction(END + timedelta(minutes=3), 0.8, 0, None, None, -1.0),
            InnerValidationPrediction(END + timedelta(minutes=4), 0.8, 1, 0.8, 0, 1.0),
        )
        predictions = InnerValidationPredictions.create(
            provenance=inner_train_dataset().provenance,
            preprocessor_hash=training.preprocessor.content_hash,
            model_hash=training.model.content_hash,
            rows=rows,
        )
        result = fit_two_stage_calibrators(predictions, bin_count=2, minimum_bin_size=1)
        isotonic = next(item.calibrator for item in result.trade.candidates if item.method == "ISOTONIC")

        self.assertIsInstance(isotonic, IsotonicCalibrator)
        self.assertEqual(isotonic.to_dict()["upper_bounds"], [0.2, 0.8])
        self.assertEqual(isotonic.to_dict()["values"], [0.5, 0.5])

    def test_sparse_stage_evidence_cannot_enter_candidate_path(self) -> None:
        result = fit_two_stage_calibrators(validation_predictions(sparse=True), bin_count=5, minimum_bin_size=2)

        self.assertFalse(result.candidate_eligible)
        self.assertTrue(result.calibrator.insufficient_evidence)

    def test_nonfinite_validation_prediction_is_rejected(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                InnerValidationPrediction(END + timedelta(minutes=1), value, 1, 0.5, 1, 0.0)

    def test_calibrator_rejects_unbound_hash_state(self) -> None:
        fitted = fit_two_stage_calibrators(
            validation_predictions(),
            bin_count=4,
            minimum_bin_size=2,
        ).calibrator
        payload = fitted.to_dict()
        payload["validation_hash"] = "not-a-hash"

        with self.assertRaisesRegex(ValueError, "validation hash"):
            TwoStageCalibrator.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
