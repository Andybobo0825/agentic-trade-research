from __future__ import annotations

import unittest
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from tmf_research.domain.sessions import TradingCalendar, TradingDay
from tmf_research.processing.session_resolver import SessionResolver


TAIPEI = ZoneInfo("Asia/Taipei")


def at(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=TAIPEI)


def fixture_calendar() -> TradingCalendar:
    return TradingCalendar(
        version="twse-2026-fixture-v1",
        timezone="Asia/Taipei",
        days=(
            TradingDay(
                trading_date=date(2026, 7, 20),
                day_close=time(13, 45),
                night_open=at(2026, 7, 17, 15, 0),
                night_close=at(2026, 7, 18, 5, 0),
            ),
            TradingDay(
                trading_date=date(2026, 7, 21),
                day_close=time(13, 45),
                night_open=at(2026, 7, 20, 15, 0),
                night_close=at(2026, 7, 21, 5, 0),
            ),
            TradingDay(
                trading_date=date(2026, 7, 23),
                day_close=time(13, 45),
                night_open=None,
                night_close=None,
            ),
            TradingDay(
                trading_date=date(2026, 7, 24),
                day_close=time(13, 30),
                night_open=at(2026, 7, 23, 15, 0),
                night_close=at(2026, 7, 24, 5, 0),
                is_expiry=True,
            ),
            TradingDay(
                trading_date=date(2026, 7, 27),
                day_close=time(13, 45),
                night_open=at(2026, 7, 27, 15, 0),
                night_close=at(2026, 7, 28, 5, 0),
            ),
        ),
        closed_dates=frozenset({date(2026, 7, 22)}),
    )


class SessionResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = SessionResolver(fixture_calendar())

    def test_resolves_literal_day_night_and_closed_boundaries(self) -> None:
        day = self.resolver.resolve(at(2026, 7, 20, 8, 45))
        friday_night = self.resolver.resolve(at(2026, 7, 17, 15, 0))
        saturday_night = self.resolver.resolve(at(2026, 7, 18, 4, 59, 59))

        self.assertEqual((day.session, day.trading_date), ("DAY", date(2026, 7, 20)))
        self.assertEqual(day.session_start, at(2026, 7, 20, 8, 45))
        self.assertEqual(
            (friday_night.session, friday_night.trading_date),
            ("NIGHT", date(2026, 7, 20)),
        )
        self.assertEqual(friday_night.session_start, at(2026, 7, 17, 15, 0))
        self.assertEqual(saturday_night.trading_date, date(2026, 7, 20))
        self.assertEqual(self.resolver.resolve(at(2026, 7, 18, 5, 0)).session, "CLOSED")
        self.assertEqual(self.resolver.resolve(at(2026, 7, 20, 13, 45)).session, "CLOSED")

    def test_uses_explicit_closure_and_never_calendar_plus_one(self) -> None:
        closure = self.resolver.resolve(at(2026, 7, 22, 9, 0))
        before_thursday = self.resolver.resolve(at(2026, 7, 22, 15, 0))

        self.assertEqual(closure.session, "CLOSED")
        self.assertIsNone(closure.trading_date)
        self.assertEqual(before_thursday.session, "CLOSED")
        self.assertEqual(self.resolver.calendar_version, "twse-2026-fixture-v1")

    def test_expiry_day_ends_at_1330_and_has_no_following_night(self) -> None:
        before_close = self.resolver.resolve(at(2026, 7, 24, 13, 29, 59))
        close = self.resolver.resolve(at(2026, 7, 24, 13, 30))
        after_close = self.resolver.resolve(at(2026, 7, 24, 15, 0))

        self.assertEqual(before_close.session, "DAY")
        self.assertTrue(before_close.is_expiry)
        self.assertEqual(close.session, "CLOSED")
        self.assertEqual(after_close.session, "CLOSED")


if __name__ == "__main__":
    unittest.main()
