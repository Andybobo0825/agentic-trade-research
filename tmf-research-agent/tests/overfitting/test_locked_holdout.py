from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tmf_research.validation.locked_holdout import (
    FrozenCandidate,
    HoldoutAccessError,
    HoldoutRow,
    HoldoutCostModel,
    HoldoutPrediction,
    HoldoutTrade,
    LockedHoldoutEvaluation,
    LockedHoldoutApprovalEvidence,
    LockedHoldout,
    select_locked_holdout,
)


def rows(days: int = 100, per_day: int = 10) -> tuple[HoldoutRow, ...]:
    return tuple(
        HoldoutRow(f"{day}-{index}", f"2026-{1 + day // 28:02d}-{1 + day % 28:02d}", {"value": index})
        for day in range(days) for index in range(per_day)
    )


def candidate(suffix: str = "", *, model_hash: str | None = None) -> FrozenCandidate:
    return FrozenCandidate({
        name: model_hash if name == "model" and model_hash is not None else hashlib.sha256((name + suffix).encode()).hexdigest()
        for name in ("model", "features", "labels", "parameters", "thresholds", "rules")
    })


def evaluate(vault: LockedHoldout, frozen: FrozenCandidate, *, losing: bool = False) -> LockedHoldoutEvaluation:
    holdout_rows = vault.read_once(vault.unlock_once(frozen))
    predictions = tuple(
        HoldoutPrediction(
            row.row_id, index % 2, 0.9 if index % 2 else 0.1,
            f"event-{index}", "DAY" if index % 2 else "NIGHT", "TMF202607",
        )
        for index, row in enumerate(holdout_rows)
    )
    cost = HoldoutCostModel(0.1, 0.1, 0.1, 0.1)
    trades = tuple(
        HoldoutTrade(
            row.row_id, "LONG" if index % 2 else "SHORT",
            -1.0 if losing else 2.0, cost.round_trip_cost_points,
            (-1.0 if losing else 2.0) - cost.round_trip_cost_points,
            f"event-{index}", "DAY" if index % 2 else "NIGHT", "TMF202607",
        )
        for index, row in enumerate(holdout_rows[:40])
    )
    return vault.evaluate_once(frozen, predictions, trades, cost)


class LockedHoldoutContractTests(unittest.TestCase):
    def test_holdout_evaluation_and_approval_capabilities_have_no_public_constructor(self) -> None:
        with self.assertRaises(TypeError):
            LockedHoldoutEvaluation()
        with self.assertRaises(TypeError):
            LockedHoldoutApprovalEvidence()

    def test_final_suffix_uses_larger_of_40_days_and_15_percent(self) -> None:
        selected = select_locked_holdout(rows())
        self.assertEqual((len(selected.development), len(selected.holdout)), (600, 400))
        self.assertEqual(selected.required_rows_by_percent, 150)
        self.assertEqual(selected.status, "READY")
        self.assertEqual(len(select_locked_holdout(rows(days=100, per_day=1), percentage=0.50).holdout), 50)

    def test_empty_and_insufficient_selection_cannot_be_persisted_or_overridden(self) -> None:
        with self.assertRaises(ValueError):
            select_locked_holdout(())
        insufficient = select_locked_holdout(rows(days=20))
        self.assertEqual(insufficient.status, "RESEARCH_INSUFFICIENT_DATA")
        with TemporaryDirectory() as directory, self.assertRaises(ValueError):
            LockedHoldout.create(Path(directory) / "holdout", insufficient)
        with TemporaryDirectory() as directory, self.assertRaises(TypeError):
            LockedHoldout.create(Path(directory) / "holdout", rows())  # type: ignore[arg-type]

    def test_formal_holdout_minima_cannot_be_weakened_or_bool_overridden(self) -> None:
        for overrides in (
            {"percentage": 0.149},
            {"effective_days": 39},
            {"effective_days": True},
            {"percentage": True},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                select_locked_holdout(rows(), **overrides)

    def test_single_use_state_survives_restart_and_rerun_contaminates(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "holdout"
            vault = LockedHoldout.create(root, select_locked_holdout(rows()))
            frozen = candidate()
            vault.freeze(frozen)
            evaluation = evaluate(vault, frozen)
            self.assertEqual(evaluation.status, "PASSED")
            restarted = LockedHoldout(root)
            evidence = restarted.approval_evidence(frozen)
            self.assertEqual(evidence.status, "PASSED")
            self.assertEqual(evaluation.terminal_anchor_hash, evidence.terminal_anchor_hash)
            with self.assertRaises(HoldoutAccessError):
                restarted.mark_rerun_attempt()
            self.assertTrue(restarted.contaminated)
            self.assertFalse(restarted.approval_eligible(frozen))

    def test_post_consumption_data_manifest_or_candidate_mutation_contaminates(self) -> None:
        for target in ("holdout.data.json", "holdout.manifest.json"):
            with self.subTest(target=target), TemporaryDirectory() as directory:
                root = Path(directory) / "holdout"
                vault = LockedHoldout.create(root, select_locked_holdout(rows()))
                frozen = candidate()
                vault.freeze(frozen)
                evaluate(vault, frozen)
                evidence = vault.approval_evidence(frozen)
                (root / target).write_text("{}\n", encoding="utf-8")
                with self.assertRaises(HoldoutAccessError):
                    LockedHoldout(root)
                with self.assertRaises(HoldoutAccessError):
                    evidence.assert_current()
                self.assertFalse(vault.approval_eligible(frozen))
        with TemporaryDirectory() as directory:
            vault = LockedHoldout.create(Path(directory) / "holdout", select_locked_holdout(rows()))
            frozen = candidate()
            vault.freeze(frozen)
            evaluate(vault, frozen)
            with self.assertRaises(HoldoutAccessError):
                vault.assert_candidate_unchanged(candidate("changed"))
            self.assertFalse(vault.approval_eligible(frozen))

    def test_negative_holdout_evaluation_fails_and_stale_evidence_is_revoked(self) -> None:
        with TemporaryDirectory() as directory:
            vault = LockedHoldout.create(Path(directory) / "holdout", select_locked_holdout(rows()))
            frozen = candidate()
            vault.freeze(frozen)
            failed = evaluate(vault, frozen, losing=True)
            self.assertEqual(failed.status, "FAILED")
            with self.assertRaises(HoldoutAccessError):
                vault.approval_evidence(frozen)
        with TemporaryDirectory() as directory:
            vault = LockedHoldout.create(Path(directory) / "holdout", select_locked_holdout(rows()))
            frozen = candidate()
            vault.freeze(frozen)
            self.assertEqual(evaluate(vault, frozen).status, "PASSED")
            evidence = vault.approval_evidence(frozen)
            with self.assertRaises(HoldoutAccessError):
                vault.mark_rerun_attempt()
            with self.assertRaisesRegex(HoldoutAccessError, "stale|current"):
                evidence.assert_current()

    def test_restoring_pre_contamination_state_cannot_revoke_the_rerun_revocation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "holdout"
            vault = LockedHoldout.create(root, select_locked_holdout(rows()))
            frozen = candidate()
            vault.freeze(frozen)
            self.assertEqual(evaluate(vault, frozen).status, "PASSED")
            evidence = vault.approval_evidence(frozen)
            approved_state = (root / "holdout.state.json").read_bytes()
            with self.assertRaises(HoldoutAccessError):
                vault.mark_rerun_attempt()
            audit_files = tuple((root.parent / f".{root.name}.phase5-holdout-audit" / "anchors").glob("*.json"))
            self.assertGreaterEqual(len(audit_files), 6)
            (root / "holdout.state.json").write_bytes(approved_state)
            with self.assertRaises(HoldoutAccessError):
                LockedHoldout(root)
            with self.assertRaises(HoldoutAccessError):
                evidence.assert_current()
            self.assertFalse(vault.approval_eligible(frozen))


if __name__ == "__main__":
    unittest.main()
