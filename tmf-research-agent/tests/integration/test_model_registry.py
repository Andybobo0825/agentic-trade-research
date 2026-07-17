from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tmf_research.models.serialization import (
    ExpectedModelContract,
    load_approved_model_bundle,
    load_model_bundle,
    save_model_bundle,
)
from tmf_research.runtime.live_research import freeze_live_runtime

from tests.phase6_test_support import COMPLETE_COSTS, frozen_policy
from tests.unit.test_model_serialization import bundle as build_bundle


class RegistryEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "bundle"
        self.original = build_bundle()
        self.checksum = save_model_bundle(self.original, self.root)
        self.expected = ExpectedModelContract.from_bundle(
            self.original, model_checksum=self.checksum,
        )

    def test_every_spec37_mismatch_forces_no_trade(self) -> None:
        overrides: tuple[tuple[str, object, str], ...] = (
            ("feature_version", "phase3-features-v2", "FEATURE_VERSION_MISMATCH"),
            (
                "feature_order",
                tuple(reversed(self.original.feature_names)),
                "FEATURE_ORDER_MISMATCH",
            ),
            ("instrument", "TXF", "INSTRUMENT_MISMATCH"),
            ("session", "NIGHT", "SESSION_MISMATCH"),
            ("horizon", "60m", "HORIZON_MISMATCH"),
            ("schema_version", "model-bundle-v2", "SCHEMA_VERSION_MISMATCH"),
            ("scaler_dimension", 99, "SCALER_DIMENSION_MISMATCH"),
            ("imputer_dimension", 99, "IMPUTER_DIMENSION_MISMATCH"),
        )

        for name, value, reason in overrides:
            with self.subTest(mismatch=reason):
                expected = ExpectedModelContract.from_bundle(
                    self.original,
                    model_checksum=self.checksum,
                    **{name: value},
                )
                result = load_model_bundle(self.root, expected)
                self.assertIsNone(result.bundle)
                self.assertEqual(result.signal, "NO_TRADE")
                self.assertIn(reason, result.reasons)

    def test_checksum_mismatch_forces_no_trade(self) -> None:
        expected = ExpectedModelContract.from_bundle(
            self.original, model_checksum="c" * 64,
        )

        result = load_model_bundle(self.root, expected)

        self.assertIsNone(result.bundle)
        self.assertEqual(result.signal, "NO_TRADE")
        self.assertIn("EXPECTED_MODEL_CHECKSUM_MISMATCH", result.reasons)

    def test_approved_loader_requires_a_sealed_approval_capability(self) -> None:
        for forged in (None, object(), "APPROVED_FOR_PAPER"):
            with self.subTest(forged=type(forged).__name__):
                result = load_approved_model_bundle(
                    self.root, self.expected, approval=forged,
                )
                self.assertIsNone(result.bundle)
                self.assertEqual(result.signal, "NO_TRADE")
                self.assertIn("MODEL_NOT_APPROVED_FOR_PAPER", result.reasons)

    def test_production_runtime_cannot_freeze_without_approval(self) -> None:
        loaded = load_model_bundle(self.root, self.expected)
        assert loaded.bundle is not None

        with self.assertRaises(TypeError):
            freeze_live_runtime(
                bundle=loaded.bundle,
                contract=self.expected,
                policy=frozen_policy(),
                approval=object(),  # type: ignore[arg-type]
                alias_code="TMFR1",
                target_code="TMF202607",
                delivery_month="202607",
                delivery_date="2026-07-15",
                raw_checksum="a" * 64,
                dataset_version="dataset-v1",
                stop_points=10.0,
                target_points=20.0,
                maximum_holding_minutes=15,
                tick_age_limit_ms=2000,
                bidask_age_limit_ms=2000,
                spread_limit_points=2.0,
                entry_slippage_points=1.0,
                exit_slippage_points=0.5,
                cost_config=COMPLETE_COSTS,
            )


if __name__ == "__main__":
    unittest.main()
