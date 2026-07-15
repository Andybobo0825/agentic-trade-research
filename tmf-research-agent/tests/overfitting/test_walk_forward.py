from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from tmf_research.models.provenance import Phase4SourceRow
from tmf_research.validation.folds import Phase5FoldPlanner, TemporalSample
from tmf_research.validation.nested_walk_forward import (
    FrozenSelection,
    OuterEvaluationResult,
    run_nested_walk_forward,
)


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

    def test_input_must_already_be_chronological(self) -> None:
        values = samples()
        with self.assertRaisesRegex(ValueError, "chronological"):
            Phase5FoldPlanner().plan(
                tuple(reversed(values)), outer_test_size=3,
                inner_validation_size=3, minimum_outer_train_size=12,
            )

    def test_runner_gives_selector_no_outer_rows_and_evaluates_frozen_choice(self) -> None:
        planned = Phase5FoldPlanner().plan(
            samples(), outer_test_size=3, inner_validation_size=3,
            minimum_outer_train_size=12, step_size=3,
        )

        def select(selector: object) -> FrozenSelection:
            self.assertFalse(hasattr(selector, "outer_test"))
            return FrozenSelection("candidate", "0" * 64)

        outer_ids = iter(fold.evaluation.outer_fold_id for fold in planned)

        def evaluate(selection: FrozenSelection, outer: tuple[object, ...]) -> OuterEvaluationResult:
            self.assertTrue(outer)
            return OuterEvaluationResult(next(outer_ids), selection.candidate_id, {"net_ev": 0.1})

        self.assertEqual(len(run_nested_walk_forward(planned, select=select, evaluate=evaluate)), len(planned))


if __name__ == "__main__":
    unittest.main()
