from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tmf_research.labeling.executable_prices import ExecutablePricePolicy
from tmf_research.processing.one_second import OneSecondState


NOW = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


def state(*, available: bool = True) -> OneSecondState:
    return OneSecondState(
        second=NOW,
        target_code="TMF202607",
        open=100.0,
        high=100.0,
        low=100.0,
        close=100.0,
        volume=1,
        trade_count=1,
        buy_volume=1,
        sell_volume=0,
        unknown_volume=0,
        last_bid=99.0,
        last_ask=101.0,
        bidask_available=available,
        spread=2.0 if available else None,
        midpoint=100.0 if available else None,
        microprice=100.0 if available else None,
        level1_imbalance=0.0 if available else None,
        level3_imbalance=0.0 if available else None,
        level5_imbalance=0.0 if available else None,
        underlying_price=98.0,
        basis=2.0,
        last_tick_age_ms=100.0,
        last_bidask_age_ms=100.0,
        notional=100.0,
        last_tick_at=NOW,
        last_bidask_at=NOW,
    )


class ExecutablePriceTests(unittest.TestCase):
    def test_long_and_short_use_executable_sides_with_slippage(self) -> None:
        policy = ExecutablePricePolicy(entry_slippage=0.5, exit_slippage=0.25)

        long_prices = policy.prices("LONG", state())
        short_prices = policy.prices("SHORT", state())

        self.assertEqual((long_prices.entry, long_prices.exit), (101.5, 98.75))
        self.assertEqual((short_prices.entry, short_prices.exit), (98.5, 101.25))

    def test_rejects_close_only_or_stale_quotes(self) -> None:
        with self.assertRaisesRegex(ValueError, "executable"):
            ExecutablePricePolicy(entry_slippage=0.5, exit_slippage=0.25).snapshot(state(available=False))


if __name__ == "__main__":
    unittest.main()
