from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from tmf_research.features.definitions import (
    FeatureDefinition,
    FeatureManifest,
    default_feature_manifest,
)


class FeatureManifestTests(unittest.TestCase):
    def test_default_manifest_is_frozen_bounded_and_hash_stable(self) -> None:
        first = default_feature_manifest()
        second = default_feature_manifest()

        self.assertLessEqual(len(first.primary_features), 40)
        self.assertLessEqual(len(first.missing_indicators), 10)
        self.assertLessEqual(len(first.formal_features), 30)
        self.assertLessEqual(len(first.interactions), 5)
        self.assertEqual(
            {definition.group for definition in first.primary_features},
            {"price", "vwap", "flow", "orderbook", "basis", "volatility", "structure", "time"},
        )
        self.assertEqual(first.redundancy.scope, "TRAIN_ONLY")
        self.assertEqual(first.redundancy.correlation_threshold, 0.90)
        self.assertEqual(first.content_hash, second.content_hash)
        with self.assertRaises(FrozenInstanceError):
            first.version = "mutated"  # type: ignore[misc]

    def test_basis_dispersion_is_trained_on_rather_than_only_declared(self) -> None:
        """basis_zscore_5m is what the basis group was added to test.

        The raw spread carries the price level with it; how far the spread has
        strayed from its own recent range is the part with a mechanism behind
        it. Declaring it as a candidate but leaving it out of the formal set
        meant it was never computed into a sample, so every basis reading so
        far measured the level alone.
        """

        manifest = default_feature_manifest()

        self.assertIn("basis_zscore_5m", manifest.formal_features)
        self.assertLessEqual(len(manifest.formal_features), 30)
        # midpoint makes room: microprice is the same quote weighted by the
        # size resting on each side, and the two scored identically on real data.
        self.assertNotIn("midpoint", manifest.formal_features)
        self.assertIn("microprice", manifest.formal_features)
        self.assertIn(
            "basis_zscore_5m",
            {item.source_feature for item in manifest.missing_indicators},
            "a window-based feature is null early in a session and needs its indicator",
        )

    def test_rejects_candidate_budget_overflow(self) -> None:
        definitions = tuple(
            FeatureDefinition(name=f"feature_{index}", group="price", mechanism="fixture")
            for index in range(41)
        )
        with self.assertRaisesRegex(ValueError, "40"):
            FeatureManifest(
                version="overflow",
                primary_features=definitions,
                missing_indicators=(),
                formal_features=tuple(item.name for item in definitions[:30]),
                interactions=(),
            )


if __name__ == "__main__":
    unittest.main()
