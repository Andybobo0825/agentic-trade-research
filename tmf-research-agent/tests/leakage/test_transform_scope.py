from __future__ import annotations

import unittest

from tmf_research.models.scaler import FoldPreprocessor

from tests.unit.test_scaler import scaler_dataset


class TransformScopeLeakageTests(unittest.TestCase):
    def test_validation_and_test_sentinels_cannot_change_inner_train_state(self) -> None:
        preprocessor = FoldPreprocessor.fit_inner_train(
            scaler_dataset(), feature_order=("return_1m", "large_volume"), required_features=("return_1m",),
            large_trade_features=("large_volume",),
        )
        before = preprocessor.to_dict()

        preprocessor.transform({"return_1m": 999999999.0, "large_volume": -999999999.0})
        preprocessor.transform({"return_1m": -999999999.0, "large_volume": 999999999.0})

        self.assertEqual(preprocessor.to_dict(), before)
        self.assertEqual(preprocessor.provenance, scaler_dataset().provenance)


if __name__ == "__main__":
    unittest.main()
