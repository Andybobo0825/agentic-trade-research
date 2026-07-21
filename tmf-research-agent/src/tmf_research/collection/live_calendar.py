from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tmf_research.domain.sessions import TradingCalendar, TradingDay


_TAIPEI = ZoneInfo("Asia/Taipei")


def synthetic_near_term_calendar(
    anchor_date: date,
    *,
    days_ahead: int = 10,
    days_behind: int = 3,
) -> TradingCalendar:
    """Standard TAIFEX weekday hours for live session tagging, no holiday
    knowledge. Every weekday gets day (08:45-13:45) and night (previous
    weekday 15:00 - this day 05:00) sessions; Sat/Sun are skipped.

    This is deliberately approximate: it exists only to stamp trading_date
    and session onto freshly collected raw ticks so they can be persisted.
    Any mismatch against the true evidence-derived calendar (holidays,
    typhoons) is caught later as a fail-closed rejection at Phase 5 build
    time (RAW_SESSION_OR_EFFECTIVE_DATE_MISMATCH), not silently corrupted.
    """

    if days_ahead < 0 or days_behind < 0:
        raise ValueError("days_ahead and days_behind must be non-negative")
    days: list[TradingDay] = []
    cursor = anchor_date - timedelta(days=days_behind)
    end = anchor_date + timedelta(days=days_ahead)
    while cursor <= end:
        if cursor.weekday() < 5:
            previous_weekday = cursor - timedelta(days=1)
            while previous_weekday.weekday() >= 5:
                previous_weekday -= timedelta(days=1)
            days.append(TradingDay(
                trading_date=cursor,
                day_open=time(8, 45),
                day_close=time(13, 45, 1),
                night_open=datetime.combine(previous_weekday, time(15, 0), tzinfo=_TAIPEI),
                night_close=datetime.combine(cursor, time(5, 0, 1), tzinfo=_TAIPEI),
            ))
        cursor += timedelta(days=1)
    return TradingCalendar(
        version="live-synthetic-v1",
        timezone="Asia/Taipei",
        days=tuple(days),
    )
