from __future__ import annotations

import unittest
from datetime import timedelta

from tmf_research.models.calibration import IsotonicCalibrator, TwoStageCalibrator, fit_two_stage_calibrators
from tmf_research.models.provenance import (
    InnerValidationDataset,
    InnerValidationPredictions,
    InnerValidationRange,
    InnerValidationRow,
    ValidationLabel,
)

from tests.unit.test_phase4_training import END, inner_train_dataset, training_spec
from tmf_research.models.training import train_phase4_model


def validation_predictions(*, sparse: bool = False) -> InnerValidationPredictions:
    training = train_phase4_model(inner_train_dataset(), training_spec())
    count = 4 if sparse else 20
    labels: tuple[ValidationLabel, ...]
    if sparse:
        labels = ("NO_TRADE", "SHORT", "NO_TRADE", "LONG")
    else:
        labels = tuple(
            "NO_TRADE" if index < 10 else ("SHORT" if index < 15 else "LONG")
            for index in range(count)
        )
    rows = tuple(
        InnerValidationRow(
            available_at=END + timedelta(minutes=index + 1),
            features={"return_1m": float(index - count / 2), "basis": float(index + 10)},
            label=labels[index],
            net_return=-1.0 if labels[index] == "NO_TRADE" else 1.0,
        )
        for index in range(count)
    )
    dataset = InnerValidationDataset.create(
        InnerValidationRange.for_parent(training.preprocessor.provenance),
        rows=rows,
    )
    return training.predict_inner_validation(dataset)


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
        training = train_phase4_model(inner_train_dataset(), training_spec())
        rows = (
            InnerValidationRow(END + timedelta(minutes=1), {"return_1m": -1.0, "basis": 10.0}, "NO_TRADE", -1.0),
            InnerValidationRow(END + timedelta(minutes=2), {"return_1m": -1.0, "basis": 10.0}, "LONG", 1.0),
            InnerValidationRow(END + timedelta(minutes=3), {"return_1m": 1.0, "basis": 20.0}, "NO_TRADE", -1.0),
            InnerValidationRow(END + timedelta(minutes=4), {"return_1m": 1.0, "basis": 20.0}, "SHORT", 1.0),
        )
        dataset = InnerValidationDataset.create(
            InnerValidationRange.for_parent(training.preprocessor.provenance),
            rows=rows,
        )
        predictions = training.predict_inner_validation(dataset)
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
                InnerValidationRow(
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
            TwoStageCalibrator.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
