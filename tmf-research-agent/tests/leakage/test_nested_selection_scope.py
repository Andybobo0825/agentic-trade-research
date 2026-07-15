from __future__ import annotations

import unittest

from tmf_research.models.calibration import fit_two_stage_calibrators
from tmf_research.validation.nested_walk_forward import (
    SelectionCandidate,
    evaluate_only,
    freeze_selection,
    inner_selection_candidate,
    select_on_inner_validation,
)
from tests.unit.test_calibration import validation_predictions


class NestedSelectionLeakageTests(unittest.TestCase):
    def test_role_string_or_outer_metrics_cannot_mint_selection_candidate(self) -> None:
        with self.assertRaises(TypeError):
            SelectionCandidate()
        predictions = validation_predictions()
        calibration = fit_two_stage_calibrators(predictions, bin_count=1, minimum_bin_size=1)
        candidate = inner_selection_candidate(
            "candidate", predictions, calibration,
            parameters={"l2": 1.0, "trade_threshold": 0.6, "calibration_method": "PLATT"},
        )
        frozen = freeze_selection(select_on_inner_validation((candidate,)))
        evaluate_only(
            frozen,
            candidate_id=frozen.candidate_id,
            parameter_hash=frozen.parameter_hash,
            manifest_hash=frozen.manifest_hash,
        )
        with self.assertRaises(ValueError):
            evaluate_only(
                frozen,
                candidate_id=frozen.candidate_id,
                parameter_hash="1" * 64,
                manifest_hash=frozen.manifest_hash,
            )

    def test_nonfinite_parameter_and_sparse_calibration_fail_closed(self) -> None:
        predictions = validation_predictions()
        calibration = fit_two_stage_calibrators(predictions, bin_count=4, minimum_bin_size=99)
        with self.assertRaises(ValueError):
            inner_selection_candidate("bad", predictions, calibration, parameters={"l2": float("nan")})
        sparse = inner_selection_candidate("sparse", predictions, calibration, parameters={"l2": 1.0})
        result = select_on_inner_validation((sparse,))
        self.assertEqual(result.status, "INSUFFICIENT_CALIBRATION_EVIDENCE")
        with self.assertRaises(ValueError):
            freeze_selection(result)


if __name__ == "__main__":
    unittest.main()
