from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tmf_research.models.provenance import InnerTrainDataset, InnerTrainRow
from tmf_research.models.training import Phase4TrainingSpec, train_phase4_model


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 2, 1, tzinfo=timezone.utc)


def inner_train_dataset() -> InnerTrainDataset:
    rows = (
        InnerTrainRow(START + timedelta(days=1), {"return_1m": -2.0, "basis": None}, "NO_TRADE"),
        InnerTrainRow(START + timedelta(days=2), {"return_1m": -1.0, "basis": 10.0}, "NO_TRADE"),
        InnerTrainRow(START + timedelta(days=3), {"return_1m": 1.0, "basis": 20.0}, "LONG"),
        InnerTrainRow(START + timedelta(days=4), {"return_1m": 2.0, "basis": 30.0}, "SHORT"),
        InnerTrainRow(START + timedelta(days=5), {"return_1m": 9.0, "basis": 40.0}, "AMBIGUOUS"),
        InnerTrainRow(START + timedelta(days=6), {"return_1m": 9.0, "basis": 50.0}, "LONG", is_complete=False),
    )
    return InnerTrainDataset.create(
        fold_id="outer-1/inner-1",
        dataset_hash="d" * 64,
        fit_start=START,
        fit_end=END,
        rows=rows,
    )


def training_spec() -> Phase4TrainingSpec:
    return Phase4TrainingSpec(
        primary_features=("return_1m", "basis"),
        required_features=("return_1m",),
        large_trade_features=(),
        l2=0.5,
        class_weights=((0, 1.0), (1, 2.0)),
        max_iterations=400,
        tolerance=1e-8,
        random_seed=7,
    )


class Phase4TrainingTests(unittest.TestCase):
    def test_one_composition_fits_and_trains_on_the_same_typed_inner_train(self) -> None:
        dataset = inner_train_dataset()
        result = train_phase4_model(dataset, training_spec())

        self.assertEqual(result.preprocessor.provenance.fold_id, dataset.fold_id)
        self.assertEqual(result.preprocessor.provenance.dataset_hash, dataset.dataset_hash)
        self.assertEqual(result.preprocessor.provenance.train_hash, dataset.train_hash)
        self.assertEqual(result.model.record.fold_id, dataset.fold_id)
        self.assertEqual(result.model.record.train_hash, dataset.train_hash)
        self.assertEqual(result.model.record.preprocessor_hash, result.preprocessor.content_hash)
        self.assertEqual(result.model.trade_model.record.preprocessor_hash, result.preprocessor.content_hash)
        self.assertEqual(result.model.direction_model.record.preprocessor_hash, result.preprocessor.content_hash)
        self.assertEqual(result.model.trade_model.record.sample_count, 4)
        self.assertEqual(result.model.direction_model.record.sample_count, 2)

    def test_outer_or_future_rows_cannot_form_an_inner_train_capability(self) -> None:
        with self.assertRaisesRegex(ValueError, "fit interval"):
            InnerTrainDataset.create(
                fold_id="outer-1/inner-1",
                dataset_hash="d" * 64,
                fit_start=START,
                fit_end=END,
                rows=(InnerTrainRow(END + timedelta(microseconds=1), {"return_1m": 1.0}, "LONG"),),
            )

    def test_nonfinite_training_features_are_rejected_before_fit(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                InnerTrainRow(START + timedelta(days=1), {"return_1m": value}, "LONG")

    def test_validation_sentinel_cannot_change_fitted_or_model_hashes(self) -> None:
        result = train_phase4_model(inner_train_dataset(), training_spec())
        before = (result.preprocessor.content_hash, result.model.content_hash)

        transformed = result.preprocessor.transform({"return_1m": 999999999.0, "basis": -999999999.0})

        self.assertTrue(transformed.is_eligible)
        self.assertEqual((result.preprocessor.content_hash, result.model.content_hash), before)

    def test_undeclared_features_cannot_expand_the_formal_model(self) -> None:
        rows = tuple(
            InnerTrainRow(
                row.available_at,
                {**row.features, "undeclared": 1.0},
                row.label,
                row.is_complete,
            )
            for row in inner_train_dataset().rows
        )
        expanded = InnerTrainDataset.create(
            fold_id="outer-1/inner-1",
            dataset_hash="d" * 64,
            fit_start=START,
            fit_end=END,
            rows=rows,
        )

        with self.assertRaisesRegex(ValueError, "feature order"):
            train_phase4_model(expanded, training_spec())


if __name__ == "__main__":
    unittest.main()
