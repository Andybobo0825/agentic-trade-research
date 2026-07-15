from __future__ import annotations

import unittest

from tmf_research.models.inference import combine_probabilities


class ProbabilityTests(unittest.TestCase):
    def test_two_stage_probability_product_is_exact_and_sums_to_one(self) -> None:
        result = combine_probabilities(p_trade=0.6, p_long_given_trade=0.75)

        self.assertAlmostEqual(result.p_long, 0.45)
        self.assertAlmostEqual(result.p_short, 0.15)
        self.assertAlmostEqual(result.p_no_trade, 0.4)
        self.assertAlmostEqual(sum(result.as_tuple()), 1.0)

    def test_out_of_range_probability_is_rejected(self) -> None:
        for value in (1.01, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "probability"):
                combine_probabilities(p_trade=value, p_long_given_trade=0.5)


if __name__ == "__main__":
    unittest.main()
