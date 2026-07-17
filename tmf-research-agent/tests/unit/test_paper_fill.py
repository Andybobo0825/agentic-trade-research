from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from tmf_research.domain.paper_trades import PaperFill, PaperQuote
from tmf_research.paper.fill_model import PaperFillModel


NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)


class PaperQuoteTests(unittest.TestCase):
    def test_accepts_a_finite_uncrossed_fresh_quote(self) -> None:
        quote = PaperQuote(bid_price_1=21500.0, ask_price_1=21501.0, age_ms=120)

        self.assertEqual(quote.bid_price_1, 21500.0)
        self.assertEqual(quote.ask_price_1, 21501.0)
        self.assertEqual(quote.spread_points, 1.0)

    def test_rejects_crossed_nonpositive_nonfinite_or_stale_negative_age(self) -> None:
        with self.assertRaisesRegex(ValueError, "crossed"):
            PaperQuote(bid_price_1=21502.0, ask_price_1=21501.0, age_ms=0)
        with self.assertRaisesRegex(ValueError, "positive"):
            PaperQuote(bid_price_1=0.0, ask_price_1=21501.0, age_ms=0)
        with self.assertRaisesRegex(ValueError, "finite"):
            PaperQuote(bid_price_1=float("nan"), ask_price_1=21501.0, age_ms=0)
        with self.assertRaisesRegex(ValueError, "age"):
            PaperQuote(bid_price_1=21500.0, ask_price_1=21501.0, age_ms=-1)

    def test_quote_is_immutable(self) -> None:
        quote = PaperQuote(bid_price_1=21500.0, ask_price_1=21501.0, age_ms=0)

        with self.assertRaises(FrozenInstanceError):
            quote.bid_price_1 = 1.0  # type: ignore[misc]


class PaperFillModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = PaperFillModel(
            entry_slippage_points=1.0,
            exit_slippage_points=0.5,
        )
        self.quote = PaperQuote(bid_price_1=21500.0, ask_price_1=21501.0, age_ms=50)

    def test_long_entry_fills_at_ask_plus_entry_slippage(self) -> None:
        fill = self.model.entry_fill("LONG", self.quote, NOW)

        self.assertEqual(fill.price, 21502.0)
        self.assertEqual(fill.direction, "LONG")
        self.assertEqual(fill.filled_at, NOW)

    def test_short_entry_fills_at_bid_minus_entry_slippage(self) -> None:
        fill = self.model.entry_fill("SHORT", self.quote, NOW)

        self.assertEqual(fill.price, 21499.0)
        self.assertEqual(fill.direction, "SHORT")

    def test_long_exit_fills_below_reference_and_short_above(self) -> None:
        long_exit = self.model.exit_fill("LONG", 21520.0, NOW)
        short_exit = self.model.exit_fill("SHORT", 21520.0, NOW)

        self.assertEqual(long_exit.price, 21519.5)
        self.assertEqual(short_exit.price, 21520.5)

    def test_rejects_negative_or_nonfinite_slippage(self) -> None:
        with self.assertRaisesRegex(ValueError, "slippage"):
            PaperFillModel(entry_slippage_points=-0.5, exit_slippage_points=0.0)
        with self.assertRaisesRegex(ValueError, "slippage"):
            PaperFillModel(
                entry_slippage_points=0.0,
                exit_slippage_points=float("inf"),
            )

    def test_rejects_nonfinite_exit_reference_and_naive_times(self) -> None:
        with self.assertRaisesRegex(ValueError, "reference"):
            self.model.exit_fill("LONG", float("nan"), NOW)
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.model.entry_fill("LONG", self.quote, datetime(2026, 7, 15, 9, 0))

    def test_fill_is_immutable_and_single_contract(self) -> None:
        fill = self.model.entry_fill("LONG", self.quote, NOW)

        self.assertEqual(fill.quantity, 1)
        with self.assertRaises(FrozenInstanceError):
            fill.price = 0.0  # type: ignore[misc]
        with self.assertRaisesRegex(ValueError, "quantity"):
            PaperFill(direction="LONG", price=21500.0, filled_at=NOW, quantity=2)


if __name__ == "__main__":
    unittest.main()
