from __future__ import annotations

from bisect import bisect_right
from datetime import datetime

from tmf_research.domain.sessions import (
    SessionName,
    SessionResolution,
    TradingCalendar,
    TradingDay,
)


class SessionResolver:
    """Resolves exchange sessions from an injected, versioned schedule."""

    def __init__(self, calendar: TradingCalendar) -> None:
        self._calendar = calendar
        windows: list[tuple[datetime, datetime, SessionResolution]] = []
        for day in calendar.days:
            day_start = datetime.combine(
                day.trading_date,
                day.day_open,
                tzinfo=calendar.zone,
            )
            day_end = datetime.combine(
                day.trading_date,
                day.day_close,
                tzinfo=calendar.zone,
            )
            windows.append((
                day_start,
                day_end,
                _resolution(day, "DAY", day_start, day_end, calendar.version),
            ))
            if day.night_open is not None and day.night_close is not None:
                night_start = day.night_open.astimezone(calendar.zone)
                night_end = day.night_close.astimezone(calendar.zone)
                windows.append((
                    night_start,
                    night_end,
                    _resolution(
                        day, "NIGHT", night_start, night_end, calendar.version,
                    ),
                ))
        windows.sort(key=lambda item: item[0])
        self._windows = tuple(windows)
        self._window_starts = tuple(window[0] for window in windows)

    @property
    def calendar_version(self) -> str:
        return self._calendar.version

    def resolve(self, value: datetime) -> SessionResolution:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("session timestamp must be timezone-aware")
        local = value.astimezone(self._calendar.zone)
        index = bisect_right(self._window_starts, local) - 1
        if index >= 0:
            start, end, resolution = self._windows[index]
            if start <= local < end:
                return resolution
        return SessionResolution(
            session="CLOSED",
            trading_date=None,
            session_start=None,
            session_end=None,
            calendar_version=self._calendar.version,
        )


def _resolution(
    day: TradingDay,
    session: SessionName,
    start: datetime,
    end: datetime,
    calendar_version: str,
) -> SessionResolution:
    if session not in ("DAY", "NIGHT"):
        raise ValueError("session must be DAY or NIGHT")
    return SessionResolution(
        session=session,
        trading_date=day.trading_date,
        session_start=start,
        session_end=end,
        calendar_version=calendar_version,
        is_expiry=day.is_expiry,
    )
