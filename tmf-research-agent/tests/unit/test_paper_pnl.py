from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tmf_research.domain.paper_trades import (
    PaperCostConfig,
    PaperExit,
    PaperFill,
    PaperPosition,
)
from tmf_research.paper.ledger import settle_paper_trade


NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)


def long_position() -> PaperPosition:
    return PaperPosition(
        position_id="paper-1",
        direction="LONG",
        entry=PaperFill(direction="LONG", price=21502.0, filled_at=NOW),
        stop_price=21492.0,
        target_price=21522.0,
        vertical_deadline=NOW + timedelta(minutes=15),
        session_end=NOW + timedelta(hours=4),
    )


def exit_at(price: float) -> PaperExit:
    return PaperExit(
        reason="PROFIT_TARGET", price=price, exited_at=NOW + timedelta(minutes=5),
    )


class PaperPnlTests(unittest.TestCase):
    def test_gross_ntd_is_points_times_ten(self) -> None:
        row = settle_paper_trade(
            long_position(), exit_at(21521.5),
            PaperCostConfig(
                entry_fee_ntd=0.0, exit_fee_ntd=0.0,
                tax_ntd=0.0, slippage_cost_ntd=0.0,
            ),
        )

        self.assertAlmostEqual(row.gross_pnl_points, 19.5)
        self.assertAlmostEqual(row.gross_pnl_ntd, 195.0)
        self.assertIsNotNone(row.net_pnl_ntd)
        self.assertAlmostEqual(float(row.net_pnl_ntd or 0.0), 195.0)

    def test_net_subtracts_each_cost_component_exactly_once(self) -> None:
        row = settle_paper_trade(
            long_position(), exit_at(21521.5),
            PaperCostConfig(
                entry_fee_ntd=23.0, exit_fee_ntd=29.0,
                tax_ntd=4.0, slippage_cost_ntd=11.0,
            ),
        )

        self.assertAlmostEqual(row.gross_pnl_ntd, 195.0)
        self.assertAlmostEqual(float(row.net_pnl_ntd or 0.0), 195.0 - 23.0 - 29.0 - 4.0 - 11.0)

    def test_incomplete_costs_permit_gross_but_never_net_or_profit_claim(self) -> None:
        row = settle_paper_trade(
            long_position(), exit_at(21521.5),
            PaperCostConfig(
                entry_fee_ntd=23.0, exit_fee_ntd=None,
                tax_ntd=4.0, slippage_cost_ntd=11.0,
            ),
        )

        self.assertFalse(row.cost_complete)
        self.assertAlmostEqual(row.gross_pnl_ntd, 195.0)
        self.assertIsNone(row.net_pnl_ntd)
        with self.assertRaisesRegex(ValueError, "cost"):
            row.claim_profitability()

    def test_complete_costs_permit_a_profitability_claim(self) -> None:
        winning = settle_paper_trade(
            long_position(), exit_at(21521.5),
            PaperCostConfig(
                entry_fee_ntd=20.0, exit_fee_ntd=20.0,
                tax_ntd=4.0, slippage_cost_ntd=10.0,
            ),
        )
        losing = settle_paper_trade(
            long_position(),
            PaperExit(
                reason="STOP_LOSS", price=21492.0,
                exited_at=NOW + timedelta(minutes=3),
            ),
            PaperCostConfig(
                entry_fee_ntd=20.0, exit_fee_ntd=20.0,
                tax_ntd=4.0, slippage_cost_ntd=10.0,
            ),
        )

        self.assertTrue(winning.claim_profitability())
        self.assertFalse(losing.claim_profitability())

    def test_cost_components_must_be_finite_and_non_negative(self) -> None:
        with self.assertRaisesRegex(ValueError, "cost"):
            PaperCostConfig(
                entry_fee_ntd=-1.0, exit_fee_ntd=20.0,
                tax_ntd=4.0, slippage_cost_ntd=10.0,
            )
        with self.assertRaisesRegex(ValueError, "cost"):
            PaperCostConfig(
                entry_fee_ntd=float("nan"), exit_fee_ntd=20.0,
                tax_ntd=4.0, slippage_cost_ntd=10.0,
            )

    def test_cost_completeness_is_derived_not_authored(self) -> None:
        complete = PaperCostConfig(
            entry_fee_ntd=20.0, exit_fee_ntd=20.0,
            tax_ntd=4.0, slippage_cost_ntd=10.0,
        )
        incomplete = PaperCostConfig(
            entry_fee_ntd=None, exit_fee_ntd=20.0,
            tax_ntd=4.0, slippage_cost_ntd=10.0,
        )

        self.assertTrue(complete.complete)
        self.assertFalse(incomplete.complete)
        self.assertAlmostEqual(complete.total_ntd, 54.0)
        with self.assertRaisesRegex(ValueError, "cost"):
            incomplete.total_ntd


if __name__ == "__main__":
    unittest.main()
