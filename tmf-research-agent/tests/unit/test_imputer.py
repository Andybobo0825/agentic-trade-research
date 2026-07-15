from __future__ import annotations

import unittest

from tmf_research.models.training import train_phase4_model

from tests.unit.test_phase4_training import inner_train_dataset, training_spec


class ImputerTests(unittest.TestCase):
    def test_required_missing_fails_closed_and_optional_uses_inner_train_median_indicator(self) -> None:
        imputer = train_phase4_model(inner_train_dataset(), training_spec()).preprocessor.imputer

        optional = imputer.transform({"return_1m": 5.0, "basis": None})
        required = imputer.transform({"return_1m": None, "basis": 99.0})

        self.assertEqual(optional.values, (5.0, 30.0, 1.0))
        self.assertEqual(optional.output_feature_order, ("return_1m", "basis", "basis__missing"))
        self.assertTrue(optional.is_eligible)
        self.assertFalse(required.is_eligible)
        self.assertEqual(required.signal, "NO_TRADE")
        self.assertIn("REQUIRED_FEATURE_MISSING:return_1m", required.reasons)


if __name__ == "__main__":
    unittest.main()
