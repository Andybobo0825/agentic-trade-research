from __future__ import annotations

import unittest

from tmf_research.models.calibration import CalibrationMetrics
from tmf_research.validation.nested_walk_forward import (
    FrozenSelection,
    SelectionCandidate,
    evaluate_only,
    select_on_inner_validation,
)


class NestedSelectionLeakageTests(unittest.TestCase):
    def test_outer_test_cannot_choose_threshold_calibrator_or_barrier(self) -> None:
        with self.assertRaises(ValueError):
            select_on_inner_validation((
                SelectionCandidate(
                    "outer-leak", "OUTER_TEST",
                    {"trade_threshold": 0.7, "calibration_method": "PLATT", "barrier": "b1"},
                    CalibrationMetrics(0.1, 0.2, 0.03, 1.0),
                ),
            ))

    def test_outer_evaluation_must_match_frozen_inner_selection(self) -> None:
        selection = FrozenSelection("candidate-1", "0" * 64)
        evaluate_only(selection, candidate_id="candidate-1", parameter_hash="0" * 64)
        with self.assertRaises(ValueError):
            evaluate_only(selection, candidate_id="candidate-1", parameter_hash="1" * 64)


if __name__ == "__main__":
    unittest.main()
