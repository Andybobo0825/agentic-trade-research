from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta

from tmf_research.collection.backfill import EVENT_TYPE, third_wednesday


TIMEZONE = "Asia/Taipei"


class CalendarBuilderError(ValueError):
    """Raised when segment evidence cannot form a coherent calendar."""


def build_calendar_payload(
    manifests: Sequence[Mapping[str, object]],
    *,
    version: str,
) -> dict[str, object]:
    """Derive a trading calendar from historical segment evidence.

    Rule (documented approximation of the TAIFEX schedule): a trading date
    is a date with day-session evidence, and every night block attaches to
    the next such trading date. Holiday and typhoon nights therefore roll
    forward instead of forming phantom trading dates. Expiry days close at
    13:30 as observed; everything else closes at 13:45.
    """

    if not version.strip():
        raise CalendarBuilderError("calendar version is required")
    day_evidence: dict[date, datetime] = {}
    night_starts: list[date] = []
    for manifest in manifests:
        if manifest.get("event_type") != EVENT_TYPE:
            continue
        segment_id = str(manifest.get("segment_id", ""))
        _prefix, separator, suffix = segment_id.rpartition("TMFR1-")
        if not separator:
            raise CalendarBuilderError(f"unrecognized segment id: {segment_id}")
        segment_day = date.fromisoformat(suffix)
        minimum = _aware(manifest, "minimum_event_time")
        maximum = _aware(manifest, "maximum_event_time")
        has_night = minimum.date() < segment_day or minimum.hour < 8
        has_day = maximum.date() == segment_day and maximum.hour >= 8
        if has_night:
            night_starts.append(minimum.date())
        if has_day:
            existing = day_evidence.get(segment_day)
            if existing is None or maximum > existing:
                day_evidence[segment_day] = maximum
    if not day_evidence:
        raise CalendarBuilderError("no day-session evidence in any segment")

    trading_dates = sorted(day_evidence)
    nights: dict[date, date] = {}
    for start in sorted(night_starts):
        index = bisect_right(trading_dates, start)
        if index >= len(trading_dates):
            raise CalendarBuilderError(
                f"night session starting {start.isoformat()} has no following trading date"
            )
        target = trading_dates[index]
        if target in nights:
            raise CalendarBuilderError(
                f"two night sessions both attach to trading date {target.isoformat()}"
            )
        nights[target] = start

    days: list[dict[str, object]] = []
    for trading_date in trading_dates:
        last_day_tick = day_evidence[trading_date]
        day_close = time(13, 30) if last_day_tick.time() <= time(13, 31) else time(13, 45)
        night_start = nights.get(trading_date)
        entry: dict[str, object] = {
            "trading_date": trading_date.isoformat(),
            "day_open": "08:45:00",
            "day_close": day_close.isoformat(),
            "night_open": None,
            "night_close": None,
            "is_expiry": third_wednesday(trading_date.year, trading_date.month)
            == trading_date,
        }
        if night_start is not None:
            entry["night_open"] = f"{night_start.isoformat()}T15:00:00"
            night_close = night_start + timedelta(days=1)
            entry["night_close"] = f"{night_close.isoformat()}T05:00:00"
        days.append(entry)
    return {"version": version, "timezone": TIMEZONE, "days": days}


def _aware(manifest: Mapping[str, object], name: str) -> datetime:
    raw = manifest.get(name)
    if not isinstance(raw, str) or not raw.strip():
        raise CalendarBuilderError(f"segment manifest lacks {name}")
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None or value.utcoffset() is None:
        raise CalendarBuilderError(f"{name} must be timezone-aware")
    return value
