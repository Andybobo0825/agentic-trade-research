from __future__ import annotations

import unittest

from tmf_research.features.definitions import (
    default_feature_manifest,
    historical_l1_feature_manifest,
)


class HistoricalManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.full = default_feature_manifest()
        self.reduced = historical_l1_feature_manifest()

    def test_reduced_manifest_has_its_own_version(self) -> None:
        self.assertEqual(self.reduced.version, "phase3-features-hist-l1-v1")
        self.assertNotEqual(self.reduced.content_hash, self.full.content_hash)

    def test_reduced_manifest_drops_only_the_basis_group(self) -> None:
        full_groups = {item.group for item in self.full.primary_features}
        reduced_groups = {item.group for item in self.reduced.primary_features}

        self.assertEqual(full_groups - reduced_groups, {"basis"})
        self.assertEqual(len(reduced_groups), 7)

    def test_no_basis_feature_or_indicator_survives(self) -> None:
        names = {item.name for item in self.reduced.primary_features}
        self.assertNotIn("basis_points", names)
        self.assertNotIn("basis_change_10s", names)
        self.assertNotIn("basis_change_1m", names)
        self.assertNotIn("basis_pct", names)
        self.assertNotIn("basis_zscore_5m", names)

        indicators = {item.name for item in self.reduced.missing_indicators}
        self.assertNotIn("underlying_missing", indicators)
        self.assertIn("quote_missing", indicators)

        self.assertNotIn("basis_points", self.reduced.formal_features)
        self.assertEqual(len(self.reduced.formal_features), 25)

    def test_interactions_are_preserved_and_basis_independent(self) -> None:
        self.assertEqual(
            tuple(item.name for item in self.reduced.interactions),
            ("return_x_flow", "spread_x_volatility"),
        )

    def test_seven_kept_groups_match_the_full_manifest_exactly(self) -> None:
        full_by_group: dict[str, set[str]] = {}
        for item in self.full.primary_features:
            full_by_group.setdefault(item.group, set()).add(item.name)
        reduced_by_group: dict[str, set[str]] = {}
        for item in self.reduced.primary_features:
            reduced_by_group.setdefault(item.group, set()).add(item.name)

        for group, names in reduced_by_group.items():
            self.assertEqual(names, full_by_group[group])


if __name__ == "__main__":
    unittest.main()
