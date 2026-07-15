from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tmf_research.models.imputer import MedianImputer


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 2, 1, tzinfo=timezone.utc)


class ImputerTests(unittest.TestCase):
    def test_required_missing_fails_closed_and_optional_uses_train_median_indicator(self) -> None:
        imputer = MedianImputer.fit(
            ({"required": 1.0, "optional": 10.0}, {"required": 2.0, "optional": None}, {"required": 3.0, "optional": 30.0}),
            feature_order=("required", "optional"), required_features=("required",), fit_start=START, fit_end=END,
        )

        optional = imputer.transform({"required": 5.0, "optional": None})
        required = imputer.transform({"required": None, "optional": 99.0})

        self.assertEqual(optional.values, (5.0, 20.0, 1.0))
        self.assertEqual(optional.output_feature_order, ("required", "optional", "optional__missing"))
        self.assertTrue(optional.is_eligible)
        self.assertFalse(required.is_eligible)
        self.assertEqual(required.signal, "NO_TRADE")
        self.assertIn("REQUIRED_FEATURE_MISSING:required", required.reasons)


if __name__ == "__main__":
    unittest.main()
