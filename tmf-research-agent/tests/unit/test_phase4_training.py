from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast

from tmf_research.models.provenance import (
    InnerTrainDataset,
    Phase4FoldCapabilities,
    Phase4SourceRow,
)
from tmf_research.models.training import Phase4TrainingSpec, train_phase4_model
from tests.phase4_test_support import TEST_PHASE4_FOLD_PLANNER


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 2, 1, tzinfo=timezone.utc)


def default_train_rows() -> tuple[Phase4SourceRow, ...]:
    return (
        Phase4SourceRow("train-1", START + timedelta(days=1), {"return_1m": -2.0, "basis": None}, "NO_TRADE", 0.0),
        Phase4SourceRow("train-2", START + timedelta(days=2), {"return_1m": -1.0, "basis": 10.0}, "NO_TRADE", 0.0),
        Phase4SourceRow("train-3", START + timedelta(days=3), {"return_1m": 1.0, "basis": 20.0}, "LONG", 0.0),
        Phase4SourceRow("train-4", START + timedelta(days=4), {"return_1m": 2.0, "basis": 30.0}, "SHORT", 0.0),
        Phase4SourceRow("train-5", START + timedelta(days=5), {"return_1m": 9.0, "basis": 40.0}, "AMBIGUOUS", 0.0),
        Phase4SourceRow("train-6", START + timedelta(days=6), {"return_1m": 9.0, "basis": 50.0}, "LONG", 0.0, is_complete=False),
    )


def default_validation_rows() -> tuple[Phase4SourceRow, ...]:
    return tuple(
        Phase4SourceRow(
            f"validation-{index}",
            END + timedelta(minutes=index + 1),
            {"return_1m": float(index - 10), "basis": float(index + 10)},
            "NO_TRADE" if index < 10 else ("SHORT" if index < 15 else "LONG"),
            -1.0 if index < 10 else 1.0,
        )
        for index in range(20)
    )


def fold_materialization(
    *,
    train_rows: tuple[Phase4SourceRow, ...] | None = None,
    validation_rows: tuple[Phase4SourceRow, ...] | None = None,
) -> Phase4FoldCapabilities:
    selected_train = default_train_rows() if train_rows is None else train_rows
    if validation_rows is None:
        if train_rows is None:
            selected_validation = default_validation_rows()
        else:
            template = {name: 0.0 for name in selected_train[0].features}
            selected_validation = (
                Phase4SourceRow("validation-auto-1", END + timedelta(minutes=1), template, "NO_TRADE", -1.0),
                Phase4SourceRow("validation-auto-2", END + timedelta(minutes=2), template, "LONG", 1.0),
            )
    else:
        selected_validation = validation_rows
    template = {name: 0.0 for name in selected_train[0].features}
    outer_rows = (
        Phase4SourceRow("outer-1", END + timedelta(hours=2, minutes=1), template, "NO_TRADE", -1.0),
        Phase4SourceRow("outer-2", END + timedelta(hours=2, minutes=2), template, "LONG", 1.0),
    )
    return TEST_PHASE4_FOLD_PLANNER.issue(
        source_rows=selected_train + selected_validation + outer_rows,
        outer_fold_id="outer-1",
        inner_fold_id="inner-1",
        train_start=START,
        train_end=END,
        validation_start=END + timedelta(minutes=1),
        validation_end=END + timedelta(hours=1),
        outer_test_start=END + timedelta(hours=2),
        outer_test_end=END + timedelta(hours=3),
    )


def inner_train_dataset() -> InnerTrainDataset:
    return fold_materialization().inner_train


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

    def test_outer_test_capability_cannot_be_repurposed_as_inner_train(self) -> None:
        materialized = fold_materialization()
        with self.assertRaisesRegex(ValueError, "inner-train capability"):
            train_phase4_model(
                cast(InnerTrainDataset, materialized.outer_test),
                training_spec(),
            )
        with self.assertRaises((TypeError, ValueError)):
            replace(
                materialized.inner_train,
                rows=materialized.outer_test.rows,
            )

    def test_nonfinite_source_features_are_rejected_before_materialization(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                Phase4SourceRow("bad", START + timedelta(days=1), {"return_1m": value}, "LONG", 0.0)

    def test_validation_sentinel_cannot_change_fitted_or_model_hashes(self) -> None:
        result = train_phase4_model(inner_train_dataset(), training_spec())
        before = (result.preprocessor.content_hash, result.model.content_hash)

        transformed = result.preprocessor.transform({"return_1m": 999999999.0, "basis": -999999999.0})

        self.assertTrue(transformed.is_eligible)
        self.assertEqual((result.preprocessor.content_hash, result.model.content_hash), before)

    def test_undeclared_features_cannot_expand_the_formal_model(self) -> None:
        rows = tuple(
            replace(row, features={**row.features, "undeclared": 1.0})
            for row in default_train_rows()
        )
        expanded = fold_materialization(train_rows=rows).inner_train

        with self.assertRaisesRegex(ValueError, "feature order"):
            train_phase4_model(expanded, training_spec())


if __name__ == "__main__":
    unittest.main()
