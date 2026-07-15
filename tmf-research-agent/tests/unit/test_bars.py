from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tmf_research.domain.events import BidAskEvent, TickEvent
from tmf_research.processing.bars import BarAggregator
from tmf_research.processing.one_second import OneSecondAggregator, OneSecondState


ANCHOR = datetime(2026, 7, 20, 8, 45, tzinfo=timezone.utc)


def tick(second: int, close: float, volume: int) -> TickEvent:
    occurred_at = ANCHOR + timedelta(seconds=second, milliseconds=100)
    return TickEvent(
        event_id=f"tick-{second}",
        received_at=occurred_at,
        exchange_datetime=occurred_at,
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        code="TMF202607",
        close=close,
        volume=volume,
        tick_type=1,
        underlying_price=99.0,
        simtrade=False,
        raw_payload={},
    )


def quote() -> BidAskEvent:
    occurred_at = ANCHOR + timedelta(milliseconds=50)
    return BidAskEvent(
        event_id="quote-0",
        received_at=occurred_at,
        exchange_datetime=occurred_at,
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        code="TMF202607",
        bid_prices=(99.0,),
        bid_volumes=(2,),
        ask_prices=(101.0,),
        ask_volumes=(2,),
        simtrade=False,
        raw_payload={},
    )


def minute_states() -> tuple[OneSecondState, ...]:
    builder = OneSecondAggregator()
    states: list[OneSecondState] = []
    previous: OneSecondState | None = None
    for offset in range(60):
        ticks: tuple[TickEvent, ...] = ()
        if offset == 0:
            ticks = (tick(offset, 100.0, 1),)
        elif offset == 59:
            ticks = (tick(offset, 102.0, 2),)
        quotes: tuple[BidAskEvent, ...] = (quote(),) if offset == 0 else ()
        previous = builder.aggregate(
            ANCHOR + timedelta(seconds=offset),
            ticks,
            quotes,
            previous=previous,
        )
        states.append(previous)
    return tuple(states)


class BarAggregatorTests(unittest.TestCase):
    def test_builds_complete_hand_calculated_minute_bar(self) -> None:
        bar = BarAggregator(interval_minutes=1).aggregate(
            minute_states(),
            session_start=ANCHOR,
        )[0]

        self.assertEqual((bar.bar_start, bar.bar_end), (ANCHOR, ANCHOR + timedelta(minutes=1)))
        self.assertEqual((bar.open, bar.high, bar.low, bar.close), (100.0, 102.0, 100.0, 102.0))
        self.assertEqual((bar.volume, bar.trade_count, bar.buy_volume), (3, 2, 3))
        self.assertAlmostEqual(bar.vwap or 0.0, (100.0 + 204.0) / 3.0)
        self.assertAlmostEqual(bar.tick_coverage_ratio, 2.0 / 60.0)
        self.assertEqual(bar.bidask_coverage_ratio, 1.0)
        self.assertTrue(bar.is_complete)

    def test_marks_missing_seconds_incomplete_and_excludes_research_bar(self) -> None:
        states = minute_states()[1:]
        aggregator = BarAggregator(interval_minutes=1)

        bar = aggregator.aggregate(states, session_start=ANCHOR)[0]

        self.assertFalse(bar.is_complete)
        self.assertEqual(aggregator.research_bars(states, session_start=ANCHOR), ())

    def test_all_timeframes_anchor_to_session_start_not_unix_hour(self) -> None:
        state = minute_states()[2]

        for minutes in (1, 5, 15, 60):
            with self.subTest(minutes=minutes):
                bar = BarAggregator(interval_minutes=minutes).aggregate(
                    (state,),
                    session_start=ANCHOR,
                )[0]
                self.assertEqual(bar.bar_start, ANCHOR)

    def test_session_end_clips_final_bucket_and_marks_it_incomplete(self) -> None:
        state = minute_states()[0]
        session_end = ANCHOR + timedelta(minutes=30)

        bar = BarAggregator(interval_minutes=60).aggregate(
            (state,),
            session_start=ANCHOR,
            session_end=session_end,
        )[0]

        self.assertEqual(bar.bar_end, session_end)
        self.assertFalse(bar.is_complete)


if __name__ == "__main__":
    unittest.main()
