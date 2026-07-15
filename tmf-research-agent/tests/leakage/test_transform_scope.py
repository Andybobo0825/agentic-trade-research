from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tmf_research.models.scaler import FoldPreprocessor


class TransformScopeLeakageTests(unittest.TestCase):
    def test_validation_and_test_sentinels_cannot_change_train_fitted_state(self) -> None:
        preprocessor = FoldPreprocessor.fit(
            ({"x": 1.0}, {"x": 2.0}, {"x": 3.0}), feature_order=("x",), required_features=("x",),
            fit_start=datetime(2026, 1, 1, tzinfo=timezone.utc), fit_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        before = preprocessor.content_hash

        preprocessor.transform({"x": 999999999.0})
        preprocessor.transform({"x": -999999999.0})

        self.assertEqual(preprocessor.content_hash, before)
        self.assertEqual(preprocessor.fit_scope, "INNER_TRAIN")


if __name__ == "__main__":
    unittest.main()
