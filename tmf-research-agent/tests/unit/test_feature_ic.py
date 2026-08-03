from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[2] / "scripts" / "feature_ic.py"
_spec = importlib.util.spec_from_file_location("feature_ic", _MODULE)
assert _spec is not None and _spec.loader is not None
feature_ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(feature_ic)


class SpearmanTests(unittest.TestCase):
    def test_matches_hand_computed_coefficients(self) -> None:
        ordered = (1.0, 2.0, 3.0, 4.0, 5.0)
        self.assertAlmostEqual(feature_ic.spearman(ordered, ordered), 1.0)
        self.assertAlmostEqual(
            feature_ic.spearman(ordered, tuple(reversed(ordered))), -1.0,
        )
        # Two adjacent swaps give sum(d^2) = 4, so 1 - 6*4/(5*24) = 0.8.
        self.assertAlmostEqual(
            feature_ic.spearman(ordered, (2.0, 1.0, 4.0, 3.0, 5.0)), 0.8,
        )

    def test_ties_share_a_rank_instead_of_inventing_an_order(self) -> None:
        self.assertEqual(
            feature_ic.ranks((10.0, 20.0, 20.0, 30.0)), (1.0, 2.5, 2.5, 4.0),
        )
        # Monotonic but tied in the middle: ranking by input order would read as
        # a perfect 1.0 and overstate the relationship.
        value = feature_ic.spearman((1.0, 2.0, 2.0, 3.0), (1.0, 2.0, 3.0, 4.0))
        assert value is not None
        self.assertLess(value, 1.0)
        self.assertGreater(value, 0.9)

    def test_declines_to_score_what_it_cannot(self) -> None:
        self.assertIsNone(feature_ic.spearman((1.0, 2.0), (1.0, 2.0)))
        self.assertIsNone(feature_ic.spearman((5.0, 5.0, 5.0), (1.0, 2.0, 3.0)))
        with self.assertRaises(ValueError):
            feature_ic.spearman((1.0, 2.0, 3.0), (1.0, 2.0))


if __name__ == "__main__":
    unittest.main()
