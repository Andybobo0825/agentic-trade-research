from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from tmf_research.models.provenance import Phase4SourceRow
from tmf_research.models.calibration import fit_two_stage_calibrators
from tmf_research.validation.folds import Phase5FoldPlanner, TemporalSample
from tmf_research.validation.nested_walk_forward import (
    freeze_selection,
    inner_selection_candidate,
    run_nested_walk_forward,
    select_on_inner_validation,
)
from tests.unit.test_calibration import validation_predictions


START = datetime(2026, 1, 1, tzinfo=UTC)


def samples(count: int = 24) -> tuple[TemporalSample, ...]:
    values = []
    for index in range(count):
        decision = START + timedelta(hours=2 * index)
        source = Phase4SourceRow(
            f"row-{index:03d}", decision, {"x": float(index)},
            "LONG" if index % 2 else "NO_TRADE", float(index % 3 - 1),
        )
        values.append(TemporalSample(source, decision, decision + timedelta(minutes=15), decision.date().isoformat()))
    return tuple(values)


class WalkForwardContractTests(unittest.TestCase):
    def test_random_shuffle_and_kfold_are_rejected(self) -> None:
        for strategy in ("random", "shuffle", "KFold", "stratified-random"):
            with self.subTest(strategy=strategy), self.assertRaises(ValueError):
                Phase5FoldPlanner(split_strategy=strategy)

    def test_expanding_nested_folds_are_ordered_and_selector_has_no_outer_test(self) -> None:
        planned = Phase5FoldPlanner().plan(
            samples(), outer_test_size=3, inner_validation_size=3,
            minimum_outer_train_size=12, step_size=3,
        )
        self.assertGreaterEqual(len(planned), 3)
        for fold in planned:
            self.assertLess(
                max(row.decision_time for row in fold.selector.inner_train),
                min(row.decision_time for row in fold.selector.inner_validation),
            )
            self.assertLess(
                max(row.decision_time for row in fold.selector.inner_validation),
                min(row.decision_time for row in fold.evaluation.outer_test),
            )
            self.assertFalse(hasattr(fold.selector, "outer_test"))
            self.assertEqual(fold.capabilities.inner_train.rows, tuple(row.source for row in fold.selector.inner_train))

    def test_ambiguous_and_incomplete_rows_leave_only_inner_validation(self) -> None:
        values = list(samples())
        ambiguous = values[14]
        incomplete = values[15]
        values[14] = TemporalSample(
            Phase4SourceRow(
                ambiguous.source.row_id, ambiguous.source.available_at,
                dict(ambiguous.source.features), "AMBIGUOUS", 0.0,
            ),
            ambiguous.decision_time, ambiguous.outcome_time, ambiguous.trading_date,
        )
        values[15] = TemporalSample(
            Phase4SourceRow(
                incomplete.source.row_id, incomplete.source.available_at,
                dict(incomplete.source.features), "LONG", 1.0, is_complete=False,
            ),
            incomplete.decision_time, incomplete.outcome_time, incomplete.trading_date,
        )

        planned = Phase5FoldPlanner().plan(
            tuple(values), outer_test_size=3, inner_validation_size=3,
            minimum_outer_train_size=12, step_size=3,
        )

        self.assertGreaterEqual(len(planned), 3)
        planned_ids = {
            row.source.row_id
            for fold in planned
            for role in (fold.selector.inner_train, fold.evaluation.outer_test)
            for row in role
        }
        self.assertIn("row-014", planned_ids)
        self.assertIn("row-015", planned_ids)
        for fold in planned:
            for row in fold.selector.inner_validation:
                self.assertNotEqual(row.source.label, "AMBIGUOUS")
                self.assertTrue(row.source.is_complete)

    def test_input_must_already_be_chronological(self) -> None:
        values = samples()
        with self.assertRaisesRegex(ValueError, "chronological"):
            Phase5FoldPlanner().plan(
                tuple(reversed(values)), outer_test_size=3,
                inner_validation_size=3, minimum_outer_train_size=12,
            )

    def test_runner_rejects_a_sealed_selection_from_a_different_fold_manifest(self) -> None:
        planned = Phase5FoldPlanner().plan(
            samples(), outer_test_size=3, inner_validation_size=3,
            minimum_outer_train_size=12, step_size=3,
        )
        predictions = validation_predictions()
        calibration = fit_two_stage_calibrators(predictions, bin_count=1, minimum_bin_size=1)
        foreign = freeze_selection(select_on_inner_validation((inner_selection_candidate(
            "foreign", predictions, calibration, parameters={"l2": 1.0},
        ),)))

        with self.assertRaisesRegex(ValueError, "different planner fold manifest"):
            run_nested_walk_forward(
                planned,
                select=lambda selector: foreign,
                evaluate=lambda selection, outer: self.fail("foreign selection reached outer evaluation"),
            )


if __name__ == "__main__":
    unittest.main()
