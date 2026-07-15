from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tmf_research.models.scaler import FoldPreprocessor, StandardScaler


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 2, 1, tzinfo=timezone.utc)


class ScalerTests(unittest.TestCase):
    def test_all_transform_state_is_fit_on_train_and_hashed(self) -> None:
        train = ({"return_1m": -1.0, "large_volume": 1.0}, {"return_1m": 0.0, "large_volume": 2.0}, {"return_1m": 1.0, "large_volume": 100.0})
        fitted = FoldPreprocessor.fit(
            train, feature_order=("return_1m", "large_volume"), required_features=("return_1m",),
            fit_start=START, fit_end=END, large_trade_features=("large_volume",),
        )
        repeated = FoldPreprocessor.fit(
            train, feature_order=("return_1m", "large_volume"), required_features=("return_1m",),
            fit_start=START, fit_end=END, large_trade_features=("large_volume",),
        )

        self.assertEqual(fitted.content_hash, repeated.content_hash)
        self.assertEqual(fitted.scaler.fit_scope, "INNER_TRAIN")
        self.assertEqual(fitted.outlier_limits.fit_scope, "INNER_TRAIN")
        self.assertEqual(fitted.large_trade_thresholds.fit_scope, "INNER_TRAIN")
        self.assertEqual(fitted.large_trade_thresholds.thresholds[0][0], "large_volume")
        self.assertEqual(len(fitted.transform({"return_1m": 999999.0, "large_volume": -999999.0}).values), 3)

    def test_rejects_serialized_scaler_dimension_or_nonpositive_deviation(self) -> None:
        with self.assertRaisesRegex(ValueError, "dimension"):
            StandardScaler(("x", "y"), (0.0,), (1.0,))
        with self.assertRaisesRegex(ValueError, "deviation"):
            StandardScaler(("x",), (0.0,), (0.0,))


if __name__ == "__main__":
    unittest.main()
