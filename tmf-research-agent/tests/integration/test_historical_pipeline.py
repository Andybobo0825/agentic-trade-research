from __future__ import annotations

import unittest
from datetime import timedelta

from tmf_research.processing.historical_adapter import decode_historical_day
from tmf_research.processing.quote_joiner import QuoteJoiner

from tests.unit.test_historical_adapter import DAY, record


class HistoricalPipelineCompositionTests(unittest.TestCase):
    def test_derived_quotes_join_backward_only_onto_ticks(self) -> None:
        rows = [
            record(0, "2026-07-16T09:01:00+08:00"),
            record(1, "2026-07-16T09:01:02+08:00", bid=46700.0),
            record(2, "2026-07-16T09:01:03+08:00", bid=46700.0),
        ]
        ticks, quotes = decode_historical_day(DAY, rows)
        joiner = QuoteJoiner(max_quote_age=timedelta(seconds=30))

        for tick in ticks:
            joined = joiner.join(tick, quotes)
            self.assertTrue(joined.bidask_available)
            assert joined.matched_bidask_at is not None
            self.assertLessEqual(joined.matched_bidask_at, tick.exchange_datetime)

        last = joiner.join(ticks[-1], quotes)
        self.assertEqual(
            last.matched_bidask_at, ticks[1].exchange_datetime,
        )


if __name__ == "__main__":
    unittest.main()
