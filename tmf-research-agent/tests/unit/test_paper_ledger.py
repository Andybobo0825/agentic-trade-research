from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

from tmf_research.domain.paper_trades import (
    PaperCostConfig,
    PaperExit,
    PaperFill,
    PaperPosition,
)
from tmf_research.paper.ledger import (
    DuplicateLedgerRowError,
    PaperLedger,
    settle_paper_trade,
)


NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
COMPLETE_COSTS = PaperCostConfig(
    entry_fee_ntd=20.0, exit_fee_ntd=20.0, tax_ntd=4.0, slippage_cost_ntd=10.0,
)


def position(direction: str = "LONG") -> PaperPosition:
    if direction == "LONG":
        return PaperPosition(
            position_id="paper-1",
            direction="LONG",
            entry=PaperFill(direction="LONG", price=21502.0, filled_at=NOW),
            stop_price=21492.0,
            target_price=21522.0,
            vertical_deadline=NOW + timedelta(minutes=15),
            session_end=NOW + timedelta(hours=4),
        )
    return PaperPosition(
        position_id="paper-2",
        direction="SHORT",
        entry=PaperFill(direction="SHORT", price=21499.0, filled_at=NOW),
        stop_price=21509.0,
        target_price=21479.0,
        vertical_deadline=NOW + timedelta(minutes=15),
        session_end=NOW + timedelta(hours=4),
    )


def target_exit(price: float = 21521.5) -> PaperExit:
    return PaperExit(
        reason="PROFIT_TARGET",
        price=price,
        exited_at=NOW + timedelta(minutes=5),
    )


class SettlementTests(unittest.TestCase):
    def test_long_settlement_records_exact_gross_points(self) -> None:
        row = settle_paper_trade(position(), target_exit(), COMPLETE_COSTS)

        self.assertEqual(row.row_id, "paper-1")
        self.assertEqual(row.direction, "LONG")
        self.assertEqual(row.quantity, 1)
        self.assertEqual(row.entry_price, 21502.0)
        self.assertEqual(row.exit_price, 21521.5)
        self.assertEqual(row.exit_reason, "PROFIT_TARGET")
        self.assertAlmostEqual(row.gross_pnl_points, 19.5)
        self.assertEqual(row.execution_mode, "PAPER")

    def test_short_settlement_reverses_the_point_sign(self) -> None:
        row = settle_paper_trade(
            position("SHORT"),
            PaperExit(
                reason="STOP_LOSS", price=21509.5,
                exited_at=NOW + timedelta(minutes=2),
            ),
            COMPLETE_COSTS,
        )

        self.assertAlmostEqual(row.gross_pnl_points, -10.5)

    def test_exit_before_entry_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exit"):
            settle_paper_trade(
                position(),
                PaperExit(
                    reason="PROFIT_TARGET", price=21521.5,
                    exited_at=NOW - timedelta(minutes=1),
                ),
                COMPLETE_COSTS,
            )

    def test_row_content_hash_detects_tampering(self) -> None:
        row = settle_paper_trade(position(), target_exit(), COMPLETE_COSTS)

        with self.assertRaisesRegex(ValueError, "hash"):
            replace(row, gross_pnl_points=100.0)

    def test_row_is_immutable_and_mode_cannot_be_authored(self) -> None:
        row = settle_paper_trade(position(), target_exit(), COMPLETE_COSTS)

        with self.assertRaises(FrozenInstanceError):
            row.gross_pnl_points = 0.0  # type: ignore[misc]
        with self.assertRaises(TypeError):
            settle_paper_trade(
                position(), target_exit(), COMPLETE_COSTS,
                execution_mode="LIVE",  # type: ignore[call-arg]
            )


class PaperLedgerTests(unittest.TestCase):
    def test_ledger_appends_and_preserves_order(self) -> None:
        ledger = PaperLedger()
        first = settle_paper_trade(position(), target_exit(), COMPLETE_COSTS)
        second = settle_paper_trade(
            position("SHORT"),
            PaperExit(
                reason="VERTICAL_BARRIER", price=21495.0,
                exited_at=NOW + timedelta(minutes=15),
            ),
            COMPLETE_COSTS,
        )

        ledger.append(first)
        ledger.append(second)

        self.assertEqual(ledger.rows, (first, second))

    def test_duplicate_row_ids_are_rejected(self) -> None:
        ledger = PaperLedger()
        row = settle_paper_trade(position(), target_exit(), COMPLETE_COSTS)
        ledger.append(row)

        with self.assertRaisesRegex(DuplicateLedgerRowError, "paper-1"):
            ledger.append(row)

    def test_ledger_exposes_no_mutation_surface(self) -> None:
        ledger = PaperLedger()

        self.assertFalse(hasattr(ledger, "remove"))
        self.assertFalse(hasattr(ledger, "update"))
        self.assertFalse(hasattr(ledger, "clear"))
        self.assertIsInstance(ledger.rows, tuple)


if __name__ == "__main__":
    unittest.main()
