from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tmf_research.validation.locked_holdout import (
    FrozenCandidate,
    HoldoutAccessError,
    HoldoutRow,
    LockedHoldout,
    select_locked_holdout,
)


def rows(days: int = 100, per_day: int = 10) -> tuple[HoldoutRow, ...]:
    return tuple(
        HoldoutRow(f"{day}-{index}", f"2026-{1 + day // 28:02d}-{1 + day % 28:02d}", {"value": index})
        for day in range(days)
        for index in range(per_day)
    )


def candidate(suffix: str = "") -> FrozenCandidate:
    return FrozenCandidate({
        name: hashlib.sha256((name + suffix).encode()).hexdigest()
        for name in ("model", "features", "labels", "parameters", "thresholds", "rules")
    })


class LockedHoldoutContractTests(unittest.TestCase):
    def test_final_suffix_uses_larger_of_40_days_and_15_percent(self) -> None:
        selected = select_locked_holdout(rows())
        self.assertEqual(len(selected.holdout), 400)
        self.assertEqual(len(selected.development), 600)
        self.assertEqual(selected.required_rows_by_percent, 150)
        self.assertEqual(selected.status, "READY")
        percent_larger = select_locked_holdout(rows(days=200, per_day=1))
        self.assertEqual(len(percent_larger.holdout), 40)
        dense_percent_larger = select_locked_holdout(rows(days=100, per_day=1), percentage=0.50)
        self.assertEqual(len(dense_percent_larger.holdout), 50)

    def test_insufficient_effective_days_fails_closed(self) -> None:
        selected = select_locked_holdout(rows(days=20))
        self.assertEqual(selected.status, "RESEARCH_INSUFFICIENT_DATA")
        self.assertFalse(selected.development)

    def test_single_use_state_survives_restart_and_mutation_contaminates(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "holdout"
            vault = LockedHoldout.create(root, rows(days=2))
            with self.assertRaises(HoldoutAccessError):
                vault.read_once(type("Fake", (), {"token": "x", "candidate_hash": "0" * 64})())
            self.assertEqual(vault.status, "CONTAMINATED")

            clean_root = Path(directory) / "clean"
            clean = LockedHoldout.create(clean_root, rows(days=2))
            frozen = candidate()
            clean.freeze(frozen)
            token = clean.unlock_once(frozen)
            self.assertEqual(len(clean.read_once(token)), 20)
            restarted = LockedHoldout(clean_root)
            self.assertTrue(restarted.approval_eligible(frozen))
            with self.assertRaises(HoldoutAccessError):
                restarted.read_once(token)
            self.assertTrue(restarted.contaminated)

    def test_post_test_hash_change_permanently_contaminates(self) -> None:
        with TemporaryDirectory() as directory:
            vault = LockedHoldout.create(Path(directory) / "holdout", rows(days=2))
            original = candidate()
            vault.freeze(original)
            vault.read_once(vault.unlock_once(original))
            with self.assertRaises(HoldoutAccessError):
                vault.assert_candidate_unchanged(candidate("changed"))
            self.assertFalse(vault.approval_eligible(original))


if __name__ == "__main__":
    unittest.main()
