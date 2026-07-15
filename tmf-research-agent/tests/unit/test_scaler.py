from __future__ import annotations

import unittest
from datetime import timedelta

from tmf_research.models.provenance import InnerTrainDataset, InnerTrainRow
from tmf_research.models.scaler import FoldPreprocessor, StandardScaler

from tests.unit.test_phase4_training import END, START


def scaler_dataset() -> InnerTrainDataset:
    return InnerTrainDataset.create(
        fold_id="outer-1/inner-1", dataset_hash="c" * 64, fit_start=START, fit_end=END,
        rows=(
            InnerTrainRow(START + timedelta(days=1), {"return_1m": -1.0, "large_volume": 1.0}, "NO_TRADE"),
            InnerTrainRow(START + timedelta(days=2), {"return_1m": 0.0, "large_volume": 2.0}, "SHORT"),
            InnerTrainRow(START + timedelta(days=3), {"return_1m": 1.0, "large_volume": 100.0}, "LONG"),
        ),
    )


class ScalerTests(unittest.TestCase):
    def test_all_transform_state_is_fit_on_typed_inner_train_and_hashed(self) -> None:
        fitted = FoldPreprocessor.fit_inner_train(
            scaler_dataset(), feature_order=("return_1m", "large_volume"), required_features=("return_1m",),
            large_trade_features=("large_volume",),
        )
        repeated = FoldPreprocessor.fit_inner_train(
            scaler_dataset(), feature_order=("return_1m", "large_volume"), required_features=("return_1m",),
            large_trade_features=("large_volume",),
        )

        self.assertEqual(fitted.content_hash, repeated.content_hash)
        self.assertEqual(fitted.provenance, scaler_dataset().provenance)
        self.assertEqual(fitted.large_trade_thresholds.thresholds[0][0], "large_volume")
        self.assertEqual(len(fitted.transform({"return_1m": 999999.0, "large_volume": -999999.0}).values), 3)

    def test_rejects_serialized_scaler_dimension_or_nonpositive_deviation(self) -> None:
        with self.assertRaisesRegex(ValueError, "dimension"):
            StandardScaler(("x", "y"), (0.0,), (1.0,))
        with self.assertRaisesRegex(ValueError, "deviation"):
            StandardScaler(("x",), (0.0,), (0.0,))

    def test_runtime_nonfinite_feature_fails_closed_without_nan(self) -> None:
        fitted = FoldPreprocessor.fit_inner_train(
            scaler_dataset(), feature_order=("return_1m", "large_volume"), required_features=("return_1m",),
        )
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                result = fitted.transform({"return_1m": value, "large_volume": 1.0})
                self.assertFalse(result.is_eligible)
                self.assertEqual(result.signal, "NO_TRADE")
                self.assertEqual(result.reasons, ("NONFINITE_FEATURE:return_1m",))
                self.assertEqual(result.values, ())


if __name__ == "__main__":
    unittest.main()
