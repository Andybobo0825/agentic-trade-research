from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tmf_research.domain.events import BidAskEvent, TickEvent
from tmf_research.processing.quote_joiner import QuoteJoiner


NOW = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


def tick(**overrides: object) -> TickEvent:
    values = {
        "event_id": "tick-1",
        "received_at": NOW,
        "exchange_datetime": NOW,
        "alias_code": "TMFR1",
        "target_code": "TMF202607",
        "delivery_month": "202607",
        "code": "TMF202607",
        "close": 23000.0,
        "volume": 1,
        "simtrade": False,
        "raw_payload": {},
    }
    values.update(overrides)
    return TickEvent(**values)


def quote(event_id: str, occurred_at: datetime, *, bid: float = 22999.0) -> BidAskEvent:
    return BidAskEvent(
        event_id=event_id,
        received_at=occurred_at,
        exchange_datetime=occurred_at,
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        code="TMF202607",
        bid_prices=(bid,),
        bid_volumes=(2,),
        ask_prices=(bid + 2.0,),
        ask_volumes=(3,),
        simtrade=False,
        raw_payload={},
    )


class QuoteJoinerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.joiner = QuoteJoiner(max_quote_age=timedelta(seconds=2))

    def test_uses_strictly_backward_quote_even_when_future_is_closer(self) -> None:
        earlier = quote("quote-before", NOW - timedelta(seconds=1))
        future = quote("quote-after", NOW + timedelta(milliseconds=1))

        joined = self.joiner.join(tick(), (earlier, future))

        self.assertTrue(joined.bidask_available)
        self.assertEqual(joined.matched_bidask_at, earlier.exchange_datetime)
        self.assertEqual(joined.bidask, earlier)
        self.assertEqual(joined.quote_age_ms, 1000.0)
        self.assertIsNone(joined.unavailable_reason)

    def test_equal_time_tie_uses_stable_input_order(self) -> None:
        first = quote("quote-first", NOW, bid=22998.0)
        second = quote("quote-second", NOW, bid=22999.0)

        joined = self.joiner.join(tick(), (first, second))

        self.assertEqual(joined.bidask, second)
        self.assertEqual(joined.quote_age_ms, 0.0)

    def test_stale_or_missing_quote_exposes_no_book(self) -> None:
        stale = quote("quote-stale", NOW - timedelta(seconds=3))

        stale_join = self.joiner.join(tick(), (stale,))
        missing_join = self.joiner.join(tick(), ())

        self.assertFalse(stale_join.bidask_available)
        self.assertIsNone(stale_join.bidask)
        self.assertEqual(stale_join.matched_bidask_at, stale.exchange_datetime)
        self.assertEqual(stale_join.unavailable_reason, "STALE_BIDASK")
        self.assertFalse(missing_join.bidask_available)
        self.assertIsNone(missing_join.matched_bidask_at)
        self.assertEqual(missing_join.unavailable_reason, "MISSING_BIDASK")


if __name__ == "__main__":
    unittest.main()
