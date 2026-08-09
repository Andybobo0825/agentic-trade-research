from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast
from zoneinfo import ZoneInfo

from tmf_research.domain.sessions import (
    SessionResolution,
    TradingCalendar,
    TradingDay,
)
from tmf_research.processing.bars import Bar
from tmf_research.processing.session_resolver import SessionResolver


SessionName = Literal["DAY", "NIGHT"]
_EPOCH = datetime(1970, 1, 1)
_TAIPEI = ZoneInfo("Asia/Taipei")
_ONE_MINUTE = timedelta(minutes=1)
_FIFTEEN_MINUTES = timedelta(minutes=15)
DERIVED_EVENT_TYPE = "historical-kbar-15m"


@dataclass(frozen=True, slots=True)
class MinuteKbar:
    """One minute interval with ``timestamp`` normalized to its start."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("minute kbar timestamp must be timezone-aware")
        for name in ("open", "high", "low", "close"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
            ):
                raise ValueError(f"minute kbar {name} must be finite")
        if (
            isinstance(self.volume, bool)
            or not isinstance(self.volume, int)
            or self.volume < 0
        ):
            raise ValueError("minute kbar volume must be non-negative")


@dataclass(frozen=True, slots=True)
class FifteenMinuteKbar:
    trading_date: date
    session: SessionName
    bar_start: datetime
    bar_end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True, slots=True)
class StoredFifteenMinuteKbar:
    """Append-only representation for a derived 15-minute segment."""

    schema_version: str
    event_id: str
    exchange_datetime: datetime
    received_at: datetime
    source: str
    alias_code: str
    trading_date: str
    session: SessionName
    fields: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PineBarSession:
    """One resolved session's kbar-derived Pine input bars."""

    trading_date: date
    session: SessionName
    session_start: datetime
    session_end: datetime
    minute_bars: tuple[MinuteKbar, ...]
    bars_by_interval: Mapping[int, tuple[Bar, ...]]

    @property
    def minute_points(self) -> tuple[tuple[datetime, float, int], ...]:
        """Close/volume observations timestamped at each minute's close."""

        return tuple(
            (bar.timestamp + _ONE_MINUTE, bar.close, bar.volume)
            for bar in self.minute_bars
        )


def aggregate_15m(
    bars: Sequence[MinuteKbar],
    *,
    calendar: TradingCalendar,
) -> tuple[FifteenMinuteKbar, ...]:
    """Aggregate present 1-minute bars inside explicit sessions.

    A bucket is returned when its full fifteen-minute window ends no later than
    the resolved session end and at least one expected minute is present.
    Missing minutes are omitted from the OHLCV calculation; clipped buckets
    and session crossings are omitted rather than filled.
    """

    resolver = SessionResolver(calendar)
    buckets: dict[
        tuple[date, SessionName, datetime, datetime],
        dict[datetime, MinuteKbar],
    ] = {}
    for bar in bars:
        resolution = resolver.resolve(bar.timestamp)
        if (
            resolution.session not in ("DAY", "NIGHT")
            or resolution.trading_date is None
            or resolution.session_start is None
            or resolution.session_end is None
        ):
            continue
        session_start = resolution.session_start
        session_end = resolution.session_end
        if bar.timestamp + _ONE_MINUTE > session_end:
            continue
        offset_seconds = int((bar.timestamp - session_start).total_seconds())
        if offset_seconds < 0 or offset_seconds % 60 != 0:
            continue
        bucket_start = session_start + timedelta(
            minutes=(offset_seconds // 60 // 15) * 15,
        )
        bucket_end = bucket_start + _FIFTEEN_MINUTES
        if bucket_end > session_end:
            continue
        key = (
            resolution.trading_date,
            cast(SessionName, resolution.session),
            bucket_start,
            session_end,
        )
        bucket = buckets.setdefault(key, {})
        if bar.timestamp in bucket:
            if bucket[bar.timestamp] != bar:
                raise ValueError(
                    f"conflicting minute kbar timestamp: {bar.timestamp}"
                )
            continue
        bucket[bar.timestamp] = bar

    output: list[FifteenMinuteKbar] = []
    for (trading_date, session, bucket_start, _session_end), bucket in sorted(
        buckets.items(),
        key=lambda item: item[0][2],
    ):
        expected = tuple(
            bucket_start + timedelta(minutes=offset)
            for offset in range(15)
        )
        present = tuple(
            bucket[timestamp]
            for timestamp in expected
            if timestamp in bucket
        )
        if not present:
            continue
        output.append(FifteenMinuteKbar(
            trading_date=trading_date,
            session=session,
            bar_start=bucket_start,
            bar_end=bucket_start + _FIFTEEN_MINUTES,
            open=present[0].open,
            high=max(bar.high for bar in present),
            low=min(bar.low for bar in present),
            close=present[-1].close,
            volume=sum(bar.volume for bar in present),
        ))
    return tuple(output)


def build_pine_bar_sessions(
    bars: Sequence[MinuteKbar],
    *,
    calendar: TradingCalendar,
    target_code: str = "TXFR1",
    intervals: Sequence[int] = (1, 5, 15, 60),
) -> tuple[PineBarSession, ...]:
    """Build :class:`Bar` inputs from stored one-minute kbars.

    The kbar timestamp is treated as the start of its one-minute interval;
    its close and volume become observable at ``timestamp + 1 minute``.  Each
    output interval is anchored to its resolved session start.  A timeframe
    bucket is emitted when its full window ends inside that same session and
    at least one constituent one-minute kbar exists.  Missing constituent
    minutes are omitted from its OHLCV values.

    This is deliberately a kbar adapter, not another signal implementation:
    callers pass the resulting ``Bar`` objects to the existing ``PineState``.
    """

    requested = tuple(intervals)
    if not requested or any(interval not in (1, 5, 15, 60) for interval in requested):
        raise ValueError("intervals must contain only 1, 5, 15, or 60")
    if len(set(requested)) != len(requested):
        raise ValueError("intervals must be unique")
    if not target_code.strip():
        raise ValueError("target_code is required")

    resolver = SessionResolver(calendar)
    grouped: dict[
        tuple[date, SessionName],
        tuple[SessionResolution, dict[datetime, MinuteKbar]],
    ] = {}
    for minute in sorted(bars, key=lambda item: item.timestamp):
        resolution = resolver.resolve(minute.timestamp)
        if (
            resolution.session not in ("DAY", "NIGHT")
            or resolution.trading_date is None
            or resolution.session_start is None
            or resolution.session_end is None
        ):
            continue
        if (
            minute.timestamp.second != 0
            or minute.timestamp.microsecond != 0
            or minute.timestamp < resolution.session_start
            or minute.timestamp + _ONE_MINUTE > resolution.session_end
        ):
            continue
        offset_seconds = int(
            (minute.timestamp - resolution.session_start).total_seconds()
        )
        if offset_seconds < 0 or offset_seconds % 60 != 0:
            continue
        session = cast(SessionName, resolution.session)
        key = (resolution.trading_date, session)
        current = grouped.get(key)
        if current is None:
            minute_map: dict[datetime, MinuteKbar] = {}
            grouped[key] = (resolution, minute_map)
        else:
            minute_map = current[1]
        if minute.timestamp in minute_map:
            if minute_map[minute.timestamp] != minute:
                raise ValueError(
                    f"conflicting minute kbar timestamp: {minute.timestamp}"
                )
            continue
        minute_map[minute.timestamp] = minute

    output: list[PineBarSession] = []
    for _key, (resolution, minute_map) in sorted(
        grouped.items(),
        key=lambda item: item[1][0].session_start or datetime.min,
    ):
        if (
            resolution.trading_date is None
            or resolution.session not in ("DAY", "NIGHT")
            or resolution.session_start is None
            or resolution.session_end is None
        ):
            continue
        minute_bars = tuple(sorted(minute_map.values(), key=lambda item: item.timestamp))
        bars_by_interval = MappingProxyType({
            interval: _build_pine_bars(
                minute_map,
                resolution=resolution,
                interval=interval,
                target_code=target_code,
            )
            for interval in requested
        })
        output.append(PineBarSession(
            trading_date=resolution.trading_date,
            session=cast(SessionName, resolution.session),
            session_start=resolution.session_start,
            session_end=resolution.session_end,
            minute_bars=minute_bars,
            bars_by_interval=bars_by_interval,
        ))
    return tuple(output)


def _build_pine_bars(
    minute_map: Mapping[datetime, MinuteKbar],
    *,
    resolution: SessionResolution,
    interval: int,
    target_code: str,
) -> tuple[Bar, ...]:
    assert resolution.session_start is not None
    assert resolution.session_end is not None
    output: list[Bar] = []
    start = resolution.session_start
    delta = timedelta(minutes=interval)
    while start + delta <= resolution.session_end:
        expected = tuple(
            start + timedelta(minutes=offset)
            for offset in range(0, interval, 1)
        )
        present = tuple(
            minute_map[timestamp]
            for timestamp in expected
            if timestamp in minute_map
        )
        if present:
            volume = sum(minute.volume for minute in present)
            output.append(Bar(
                target_code=target_code,
                bar_start=start,
                bar_end=start + delta,
                open=present[0].open,
                high=max(minute.high for minute in present),
                low=min(minute.low for minute in present),
                close=present[-1].close,
                volume=volume,
                # Kbars do not carry tick count, side volume, quote coverage,
                # or a true VWAP.  Keep those fields explicitly unknown rather
                # than manufacturing tick-derived metadata.
                trade_count=0,
                buy_volume=0,
                sell_volume=0,
                unknown_volume=volume,
                vwap=None,
                bidask_coverage_ratio=0.0,
                tick_coverage_ratio=0.0,
                is_complete=True,
            ))
        start += delta
    return tuple(output)


def encode_15m_bars(
    bars: Sequence[FifteenMinuteKbar],
    *,
    alias_code: str,
    created_at: datetime,
) -> tuple[StoredFifteenMinuteKbar, ...]:
    """Encode derived bars for a separate append-only output segment."""

    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    return tuple(
        StoredFifteenMinuteKbar(
            schema_version="1.0.0",
            event_id=(
                f"derived-kbar-15m-{alias_code}-{bar.trading_date}"
                f"-{bar.session}-{bar.bar_start.isoformat()}"
            ),
            exchange_datetime=bar.bar_start,
            received_at=created_at,
            source="DERIVED_FROM_SHIOAJI_KBARS_1M",
            alias_code=alias_code,
            trading_date=bar.trading_date.isoformat(),
            session=bar.session,
            fields={
                "bar_start": bar.bar_start.isoformat(),
                "bar_end": bar.bar_end.isoformat(),
                "Open": bar.open,
                "High": bar.high,
                "Low": bar.low,
                "Close": bar.close,
                "Volume": bar.volume,
            },
        )
        for bar in bars
    )


def minute_kbars_from_records(
    records: Sequence[Mapping[str, object]],
) -> tuple[MinuteKbar, ...]:
    """Decode the raw-store representation without changing its OHLCV values."""

    output: list[MinuteKbar] = []
    for record in records:
        fields = record.get("fields")
        if not isinstance(fields, Mapping):
            raise ValueError("stored kbar record lacks fields")
        ts = fields.get("ts")
        if isinstance(ts, bool) or not isinstance(ts, int):
            raise ValueError("stored kbar ts must be an integer")
        # Shioaji's one-minute ``ts`` labels the minute's closing boundary:
        # the first day-session row is 08:46 for the 08:45-08:46 minute.
        # Normalize that vendor label to the interval start for session
        # anchoring; the raw ``ts`` remains untouched in ``fields``.
        output.append(MinuteKbar(
            timestamp=_kbar_time(ts) - _ONE_MINUTE,
            open=_number(fields, "Open"),
            high=_number(fields, "High"),
            low=_number(fields, "Low"),
            close=_number(fields, "Close"),
            volume=_volume(fields.get("Volume")),
        ))
    return tuple(output)


def load_trading_calendar(path: Path) -> TradingCalendar:
    """Load the repository's explicit calendar JSON for session resolution."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("calendar must be a JSON object")
    timezone_name = str(payload.get("timezone", ""))
    zone = ZoneInfo(timezone_name)
    raw_days = payload.get("days")
    if not isinstance(raw_days, list) or not raw_days:
        raise ValueError("calendar requires explicit trading days")
    days: list[TradingDay] = []
    for raw_day in raw_days:
        if not isinstance(raw_day, Mapping):
            raise ValueError("calendar day must be an object")
        days.append(TradingDay(
            trading_date=date.fromisoformat(str(raw_day["trading_date"])),
            day_open=time.fromisoformat(str(raw_day["day_open"])),
            day_close=time.fromisoformat(str(raw_day["day_close"])),
            night_open=_optional_datetime(raw_day.get("night_open"), zone),
            night_close=_optional_datetime(raw_day.get("night_close"), zone),
            is_expiry=bool(raw_day.get("is_expiry", False)),
        ))
    return TradingCalendar(
        version=str(payload["version"]),
        timezone=timezone_name,
        days=tuple(days),
    )


def _number(fields: Mapping[str, object], name: str) -> float:
    value = fields.get(name)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(float(value))
    ):
        raise ValueError(f"stored kbar {name} must be finite numeric")
    return float(value)


def _volume(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("stored kbar Volume must be a non-negative integer")
    return value


def _kbar_time(value: int) -> datetime:
    if value < 0:
        raise ValueError("stored kbar ts must be non-negative")
    wall = _EPOCH + timedelta(microseconds=value // 1_000)
    return wall.replace(tzinfo=_TAIPEI)


def _optional_datetime(value: object, zone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("calendar session boundary must be timezone-aware")
    return parsed.astimezone(zone)
