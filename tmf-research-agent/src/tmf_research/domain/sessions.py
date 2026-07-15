from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo


SessionName = Literal["DAY", "NIGHT", "CLOSED"]


@dataclass(frozen=True, slots=True)
class TradingDay:
    trading_date: date
    day_close: time
    night_open: datetime | None
    night_close: datetime | None
    is_expiry: bool = False
    day_open: time = time(8, 45)

    def __post_init__(self) -> None:
        if (self.night_open is None) != (self.night_close is None):
            raise ValueError("night_open and night_close must both be set or both be absent")
        if self.night_open is not None and self.night_close is not None:
            if self.night_open.tzinfo is None or self.night_close.tzinfo is None:
                raise ValueError("night session boundaries must be timezone-aware")
            if self.night_open >= self.night_close:
                raise ValueError("night_open must precede night_close")
        if self.day_open >= self.day_close:
            raise ValueError("day_open must precede day_close")


@dataclass(frozen=True, slots=True)
class TradingCalendar:
    version: str
    timezone: str
    days: tuple[TradingDay, ...]
    closed_dates: frozenset[date] = frozenset()

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("calendar version is required")
        ZoneInfo(self.timezone)
        ordered = tuple(sorted(self.days, key=lambda item: item.trading_date))
        dates = tuple(item.trading_date for item in ordered)
        if len(dates) != len(set(dates)):
            raise ValueError("trading dates must be unique")
        if self.closed_dates.intersection(dates):
            raise ValueError("closed dates cannot also be trading dates")
        object.__setattr__(self, "days", ordered)
        object.__setattr__(self, "closed_dates", frozenset(self.closed_dates))

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@dataclass(frozen=True, slots=True)
class SessionResolution:
    session: SessionName
    trading_date: date | None
    session_start: datetime | None
    session_end: datetime | None
    calendar_version: str
    is_expiry: bool = False

