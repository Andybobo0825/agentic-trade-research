from __future__ import annotations

import unittest
from datetime import timedelta
from typing import cast

from tmf_research.models.calibration import IsotonicCalibrator, fit_two_stage_calibrators
from tmf_research.models.provenance import (
    InnerValidationPredictions,
    Phase4SourceRow,
    TrainingLabel,
)

from tests.unit.test_phase4_training import END, fold_materialization, training_spec
from tmf_research.models.training import train_phase4_model
from tests.phase4_deserialization_test_support import deserialize_calibrator_for_test


def validation_predictions(*, sparse: bool = False) -> InnerValidationPredictions:
    if sparse:
        count = 4
        labels = ("NO_TRADE", "SHORT", "NO_TRADE", "LONG")
        rows = tuple(
            Phase4SourceRow(
                f"validation-{index}",
                END + timedelta(minutes=index + 1),
                {"return_1m": float(index - count / 2), "basis": float(index + 10)},
                cast(TrainingLabel, labels[index]),
                -1.0 if labels[index] == "NO_TRADE" else 1.0,
            )
            for index in range(count)
        )
        materialized = fold_materialization(
            validation_rows=rows,
        )
    else:
        materialized = fold_materialization()
    training = train_phase4_model(materialized.inner_train, training_spec())
    return training.predict_inner_validation(materialized.inner_validation)


class CalibrationTests(unittest.TestCase):
    def test_calibrates_both_stages_and_binds_model_fold_provenance(self) -> None:
        predictions = validation_predictions()
        result = fit_two_stage_calibrators(predictions, bin_count=4, minimum_bin_size=2)

        self.assertTrue(result.candidate_eligible)
        self.assertFalse(result.calibrator.insufficient_evidence)
        self.assertEqual(result.calibrator.validation_provenance, predictions.provenance)
        self.assertEqual(result.calibrator.provenance, predictions.provenance.parent_provenance)
        self.assertEqual(result.calibrator.model_hash, predictions.model_hash)
        self.assertEqual(result.calibrator.preprocessor_hash, predictions.preprocessor_hash)
        self.assertEqual(tuple(item.method for item in result.trade.candidates), ("UNCALIBRATED", "PLATT", "ISOTONIC"))
        self.assertEqual(tuple(item.method for item in result.direction.candidates), ("UNCALIBRATED", "PLATT", "ISOTONIC"))
        self.assertEqual(result.trade.selected.metrics.sort_key, min(item.metrics.sort_key for item in result.trade.candidates))
        self.assertEqual(result.direction.selected.metrics.sort_key, min(item.metrics.sort_key for item in result.direction.candidates))

    def test_isotonic_groups_duplicate_x_with_empirical_weighted_value(self) -> None:
        rows = (
            Phase4SourceRow("validation-1", END + timedelta(minutes=1), {"return_1m": -1.0, "basis": 10.0}, "NO_TRADE", -1.0),
            Phase4SourceRow("validation-2", END + timedelta(minutes=2), {"return_1m": -1.0, "basis": 10.0}, "LONG", 1.0),
            Phase4SourceRow("validation-3", END + timedelta(minutes=3), {"return_1m": 1.0, "basis": 20.0}, "NO_TRADE", -1.0),
            Phase4SourceRow("validation-4", END + timedelta(minutes=4), {"return_1m": 1.0, "basis": 20.0}, "SHORT", 1.0),
        )
        materialized = fold_materialization(
            validation_rows=rows,
        )
        training = train_phase4_model(materialized.inner_train, training_spec())
        predictions = training.predict_inner_validation(materialized.inner_validation)
        result = fit_two_stage_calibrators(predictions, bin_count=2, minimum_bin_size=1)
        isotonic = next(item.calibrator for item in result.trade.candidates if item.method == "ISOTONIC")
        expected_bounds = sorted({row.p_trade for row in predictions.rows})

        self.assertIsInstance(isotonic, IsotonicCalibrator)
        self.assertEqual(isotonic.to_dict()["upper_bounds"], expected_bounds)
        self.assertEqual(isotonic.to_dict()["values"], [0.5, 0.5])

    def test_sparse_stage_evidence_cannot_enter_candidate_path(self) -> None:
        result = fit_two_stage_calibrators(validation_predictions(sparse=True), bin_count=5, minimum_bin_size=3)

        self.assertFalse(result.candidate_eligible)
        self.assertTrue(result.calibrator.insufficient_evidence)

    def test_nonfinite_validation_prediction_is_rejected(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                Phase4SourceRow(
                    "bad-validation",
                    END + timedelta(minutes=1),
                    {"return_1m": value, "basis": 1.0},
                    "LONG",
                    0.0,
                )

    def test_calibrator_rejects_unbound_hash_state(self) -> None:
        fitted = fit_two_stage_calibrators(
            validation_predictions(),
            bin_count=4,
            minimum_bin_size=2,
        ).calibrator
        payload = fitted.to_dict()
        payload["validation_hash"] = "not-a-hash"

        with self.assertRaisesRegex(ValueError, "validation hash"):
            deserialize_calibrator_for_test(payload)


if __name__ == "__main__":
    unittest.main()
