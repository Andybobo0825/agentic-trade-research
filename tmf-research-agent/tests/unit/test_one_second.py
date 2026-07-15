from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tmf_research.domain.events import BidAskEvent, TickEvent
from tmf_research.processing.one_second import OneSecondAggregator


SECOND = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


def tick(
    event_id: str,
    offset_ms: int,
    close: float,
    volume: int,
    tick_type: int,
    underlying_price: float,
) -> TickEvent:
    occurred_at = SECOND + timedelta(milliseconds=offset_ms)
    return TickEvent(
        event_id=event_id,
        received_at=occurred_at,
        exchange_datetime=occurred_at,
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        code="TMF202607",
        close=close,
        volume=volume,
        tick_type=tick_type,
        underlying_price=underlying_price,
        simtrade=False,
        raw_payload={},
    )


def quote() -> BidAskEvent:
    occurred_at = SECOND + timedelta(milliseconds=500)
    return BidAskEvent(
        event_id="quote-1",
        received_at=occurred_at,
        exchange_datetime=occurred_at,
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        code="TMF202607",
        bid_prices=(99.0, 98.0, 97.0),
        bid_volumes=(10, 5, 5),
        ask_prices=(101.0, 102.0, 103.0),
        ask_volumes=(6, 4, 2),
        underlying_price=99.0,
        simtrade=False,
        raw_payload={},
    )


class OneSecondAggregatorTests(unittest.TestCase):
    def test_calculates_price_flow_book_basis_and_age_fields(self) -> None:
        state = OneSecondAggregator().aggregate(
            SECOND,
            (
                tick("tick-1", 100, 100.0, 2, 1, 98.0),
                tick("tick-2", 700, 102.0, 3, 2, 99.0),
            ),
            (quote(),),
        )

        self.assertEqual((state.open, state.high, state.low, state.close), (100.0, 102.0, 100.0, 102.0))
        self.assertEqual((state.volume, state.trade_count), (5, 2))
        self.assertEqual((state.buy_volume, state.sell_volume, state.unknown_volume), (2, 3, 0))
        self.assertEqual((state.last_bid, state.last_ask, state.spread, state.midpoint), (99.0, 101.0, 2.0, 100.0))
        self.assertAlmostEqual(state.microprice or 0.0, 100.25)
        self.assertAlmostEqual(state.level1_imbalance or 0.0, 0.25)
        self.assertAlmostEqual(state.level3_imbalance or 0.0, 0.25)
        self.assertAlmostEqual(state.level5_imbalance or 0.0, 0.25)
        self.assertEqual((state.underlying_price, state.basis), (99.0, 1.0))
        self.assertAlmostEqual(state.last_tick_age_ms or 0.0, 300.0)
        self.assertAlmostEqual(state.last_bidask_age_ms or 0.0, 500.0)
        self.assertEqual(state.notional, 506.0)

    def test_empty_second_carries_only_book_and_underlying_without_fake_trade(self) -> None:
        aggregator = OneSecondAggregator()
        previous = aggregator.aggregate(
            SECOND,
            (tick("tick-1", 700, 102.0, 3, 2, 99.0),),
            (quote(),),
        )

        empty = aggregator.aggregate(
            SECOND + timedelta(seconds=1),
            (),
            (),
            previous=previous,
        )

        self.assertEqual((empty.open, empty.high, empty.low, empty.close), (None, None, None, None))
        self.assertEqual((empty.volume, empty.trade_count), (0, 0))
        self.assertEqual((empty.buy_volume, empty.sell_volume, empty.unknown_volume), (0, 0, 0))
        self.assertEqual((empty.last_bid, empty.last_ask, empty.midpoint), (99.0, 101.0, 100.0))
        self.assertEqual((empty.underlying_price, empty.basis), (99.0, 1.0))
        self.assertAlmostEqual(empty.last_tick_age_ms or 0.0, 1300.0)
        self.assertAlmostEqual(empty.last_bidask_age_ms or 0.0, 1500.0)
        self.assertEqual(empty.notional, 0.0)


if __name__ == "__main__":
    unittest.main()
