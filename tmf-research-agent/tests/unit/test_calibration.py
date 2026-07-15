from __future__ import annotations

import unittest

from tmf_research.models.calibration import CalibrationSample, fit_and_select_calibrator


class CalibrationTests(unittest.TestCase):
    def test_selects_only_from_inner_validation_with_lexicographic_metrics(self) -> None:
        samples = tuple(
            CalibrationSample(index / 20.0, 1 if index >= 10 else 0, 1.0 if index >= 10 else -1.0)
            for index in range(1, 20)
        )
        result = fit_and_select_calibrator(samples, scope="INNER_VALIDATION", bin_count=4, minimum_bin_size=2)

        self.assertFalse(result.insufficient_evidence)
        self.assertIn(result.selected.method, ("UNCALIBRATED", "PLATT", "ISOTONIC"))
        self.assertEqual(tuple(item.method for item in result.candidates), ("UNCALIBRATED", "PLATT", "ISOTONIC"))
        self.assertEqual(result.selected.metrics.sort_key, min(item.metrics.sort_key for item in result.candidates))

    def test_rejects_outer_scope_and_marks_sparse_bins_insufficient(self) -> None:
        samples = (CalibrationSample(0.1, 0, -1.0), CalibrationSample(0.9, 1, 1.0))
        with self.assertRaisesRegex(ValueError, "INNER_VALIDATION"):
            fit_and_select_calibrator(samples, scope="OUTER_TEST")
        sparse = fit_and_select_calibrator(samples, scope="INNER_VALIDATION", bin_count=5, minimum_bin_size=2)
        self.assertTrue(sparse.insufficient_evidence)


if __name__ == "__main__":
    unittest.main()
