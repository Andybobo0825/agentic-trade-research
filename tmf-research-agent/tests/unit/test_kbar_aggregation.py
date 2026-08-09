from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tmf_research.domain.sessions import TradingCalendar, TradingDay
from tmf_research.processing.kbar_aggregation import (
    MinuteKbar,
    aggregate_15m,
    build_pine_bar_sessions,
    minute_kbars_from_records,
)


TAIPEI = ZoneInfo("Asia/Taipei")
SESSION_START = datetime(2020, 3, 16, 8, 45, tzinfo=TAIPEI)


def calendar(*, close: time = time(9, 15)) -> TradingCalendar:
    return TradingCalendar(
        version="kbar-test-v1",
        timezone="Asia/Taipei",
        days=(TradingDay(
            trading_date=date(2020, 3, 16),
            day_close=close,
            night_open=datetime(2020, 3, 15, 15, 0, tzinfo=TAIPEI),
            night_close=datetime(2020, 3, 16, 5, 0, tzinfo=TAIPEI),
        ),),
    )


def bars(
    start: datetime = SESSION_START,
    *,
    count: int = 30,
    missing: set[int] | None = None,
) -> tuple[MinuteKbar, ...]:
    missing = missing or set()
    return tuple(
        MinuteKbar(
            timestamp=start + timedelta(minutes=index),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.5 + index,
            volume=index + 1,
        )
        for index in range(count)
        if index not in missing
    )


class KbarAggregationTests(unittest.TestCase):
    def test_shioaji_end_label_is_normalized_to_minute_start(self) -> None:
        end_label = datetime(2024, 7, 29, 8, 46)
        ts = int((end_label - datetime(1970, 1, 1)).total_seconds()) * 1_000_000_000

        result = minute_kbars_from_records([{
            "fields": {
                "ts": ts,
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.5,
                "Volume": 10,
            },
        }])

        self.assertEqual(result[0].timestamp, datetime(2024, 7, 29, 8, 45, tzinfo=TAIPEI))

    def test_full_session_aggregates_cleanly_into_15_minute_bars(self) -> None:
        result = aggregate_15m(bars(), calendar=calendar())

        self.assertEqual(len(result), 2)
        first, second = result
        self.assertEqual(first.bar_start, SESSION_START)
        self.assertEqual(first.bar_end, SESSION_START + timedelta(minutes=15))
        self.assertEqual((first.open, first.high, first.low, first.close), (100.0, 115.0, 99.0, 114.5))
        self.assertEqual(first.volume, sum(range(1, 16)))
        self.assertEqual((second.open, second.close), (115.0, 129.5))
        self.assertEqual(second.volume, sum(range(16, 31)))

    def test_partial_bar_at_session_boundary_is_dropped(self) -> None:
        result = aggregate_15m(
            bars(count=17),
            calendar=calendar(close=time(9, 2)),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].bar_start, SESSION_START)

    def test_gap_in_one_minute_data_uses_the_minutes_that_are_present(self) -> None:
        result = aggregate_15m(
            bars(missing={7}),
            calendar=calendar(),
        )

        self.assertEqual(len(result), 2)
        first = result[0]
        self.assertEqual(first.bar_start, SESSION_START)
        self.assertEqual(
            (first.open, first.high, first.low, first.close),
            (100.0, 115.0, 99.0, 114.5),
        )
        self.assertEqual(first.volume, sum(range(1, 16)) - 8)
        self.assertEqual(result[1].bar_start, SESSION_START + timedelta(minutes=15))

    def test_empty_15_minute_window_is_not_emitted(self) -> None:
        result = aggregate_15m(
            bars(missing=set(range(15))),
            calendar=calendar(),
        )

        self.assertEqual(
            tuple(bar.bar_start for bar in result),
            (SESSION_START + timedelta(minutes=15),),
        )


class PineBarSessionTests(unittest.TestCase):
    def test_full_session_builds_complete_pine_bars(self) -> None:
        sessions = build_pine_bar_sessions(bars(), calendar=calendar())

        self.assertEqual(len(sessions), 1)
        fifteen = sessions[0].bars_by_interval[15]
        self.assertEqual(len(fifteen), 2)
        first = fifteen[0]
        self.assertEqual(first.bar_start, SESSION_START)
        self.assertEqual(first.bar_end, SESSION_START + timedelta(minutes=15))
        self.assertEqual(
            (first.open, first.high, first.low, first.close, first.volume),
            (100.0, 115.0, 99.0, 114.5, sum(range(1, 16))),
        )
        self.assertTrue(first.is_complete)

    def test_partial_session_bucket_is_dropped(self) -> None:
        sessions = build_pine_bar_sessions(
            bars(count=17), calendar=calendar(close=time(9, 2)),
        )

        self.assertEqual(
            tuple(bar.bar_start for bar in sessions[0].bars_by_interval[15]),
            (SESSION_START,),
        )

    def test_gap_uses_the_minutes_that_are_present_in_a_pine_bar(self) -> None:
        sessions = build_pine_bar_sessions(
            bars(missing={7}), calendar=calendar(),
        )

        fifteen = sessions[0].bars_by_interval[15]
        self.assertEqual(len(fifteen), 2)
        self.assertEqual(
            (fifteen[0].open, fifteen[0].high, fifteen[0].low,
             fifteen[0].close, fifteen[0].volume),
            (100.0, 115.0, 99.0, 114.5, sum(range(1, 16)) - 8),
        )

    def test_identical_duplicate_vendor_rows_are_not_double_counted(self) -> None:
        source = bars()
        sessions = build_pine_bar_sessions(
            source + (source[0],), calendar=calendar(),
        )

        self.assertEqual(len(sessions[0].minute_bars), len(source))
        self.assertEqual(sessions[0].bars_by_interval[15][0].volume, sum(range(1, 16)))


if __name__ == "__main__":
    unittest.main()
