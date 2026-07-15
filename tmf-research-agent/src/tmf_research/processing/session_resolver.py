from __future__ import annotations

from datetime import datetime

from tmf_research.domain.sessions import SessionResolution, TradingCalendar


class SessionResolver:
    """Resolves exchange sessions from an injected, versioned schedule."""

    def __init__(self, calendar: TradingCalendar) -> None:
        self._calendar = calendar

    @property
    def calendar_version(self) -> str:
        return self._calendar.version

    def resolve(self, value: datetime) -> SessionResolution:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("session timestamp must be timezone-aware")
        local = value.astimezone(self._calendar.zone)
        for day in self._calendar.days:
            day_start = datetime.combine(
                day.trading_date,
                day.day_open,
                tzinfo=self._calendar.zone,
            )
            day_end = datetime.combine(
                day.trading_date,
                day.day_close,
                tzinfo=self._calendar.zone,
            )
            if day_start <= local < day_end:
                return SessionResolution(
                    session="DAY",
                    trading_date=day.trading_date,
                    session_start=day_start,
                    session_end=day_end,
                    calendar_version=self._calendar.version,
                    is_expiry=day.is_expiry,
                )
            if (
                day.night_open is not None
                and day.night_close is not None
                and day.night_open <= local < day.night_close
            ):
                return SessionResolution(
                    session="NIGHT",
                    trading_date=day.trading_date,
                    session_start=day.night_open,
                    session_end=day.night_close,
                    calendar_version=self._calendar.version,
                    is_expiry=day.is_expiry,
                )
        return SessionResolution(
            session="CLOSED",
            trading_date=None,
            session_start=None,
            session_end=None,
            calendar_version=self._calendar.version,
        )

