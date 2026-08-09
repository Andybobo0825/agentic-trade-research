from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
import re
from datetime import date, datetime, time, timedelta

from tmf_research.collection.backfill import EVENT_TYPE, third_wednesday


TIMEZONE = "Asia/Taipei"
KBAR_EVENT_TYPE = "historical-kbar-1m"
SUPPORTED_EVENT_TYPES = frozenset({EVENT_TYPE, KBAR_EVENT_TYPE})
_SEGMENT_ID = re.compile(
    r"^backfill-(?P<kind>tick|kbar-1m)-(?P<alias>.+?)-"
    r"(?P<start>\d{4}-\d{2}-\d{2})"
    r"(?:-(?P<end>\d{4}-\d{2}-\d{2}))?$"
)


class CalendarBuilderError(ValueError):
    """Raised when segment evidence cannot form a coherent calendar."""


def build_calendar_payload(
    manifests: Sequence[Mapping[str, object]],
    *,
    version: str,
    dataset_version: str | None = None,
    event_type: str | None = None,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
) -> dict[str, object]:
    """Derive a trading calendar from historical segment evidence.

    Rule (documented approximation of the TAIFEX schedule): a trading date
    is a date with day-session evidence, and every night block attaches to
    the next such trading date. Holiday and typhoon nights therefore roll
    forward instead of forming phantom trading dates. Expiry days close at
    13:30 as observed; everything else closes at 13:45. Closes carry one
    second of tolerance because closing-auction matches print up to ~80ms
    after the nominal close in real payloads.

    Kbar manifests are bucketed by calendar date while a night session is
    bucketed by its 15:00 start. A post-15:00 kbar fragment establishes that
    start; a 00:00-05:00 fragment is joined to that head, using the latest
    earlier head when a weekend or holiday separates the two files. Each
    resolved start is then assigned to the first day-session date strictly
    after it. Thus a Friday head and a Monday tail belong to Monday, never to
    Friday or a weekend date.
    """

    if not version.strip():
        raise CalendarBuilderError("calendar version is required")
    start_bound = _date_bound(start_date, "start_date")
    end_bound = _date_bound(end_date, "end_date")
    if (
        start_bound is not None
        and end_bound is not None
        and end_bound < start_bound
    ):
        raise CalendarBuilderError("calendar end_date precedes start_date")

    selected: list[tuple[Mapping[str, object], date, str]] = []
    event_types: set[str] = set()
    aliases: set[str] = set()
    for manifest in manifests:
        raw_event_type = manifest.get("event_type")
        if not isinstance(raw_event_type, str):
            continue
        if dataset_version is not None and (
            manifest.get("dataset_version") != dataset_version
        ):
            continue
        if event_type is not None and raw_event_type != event_type:
            continue
        if raw_event_type not in SUPPORTED_EVENT_TYPES:
            continue
        segment_day, alias, kind = _segment_evidence(manifest)
        expected_kind = "kbar-1m" if raw_event_type == KBAR_EVENT_TYPE else "tick"
        if kind != expected_kind:
            raise CalendarBuilderError(
                f"segment id kind {kind!r} does not match event type "
                f"{raw_event_type!r}: {manifest.get('segment_id')}"
            )
        selected.append((manifest, segment_day, alias))
        event_types.add(raw_event_type)
        aliases.add(alias)

    if not selected:
        qualifier = (
            f" for dataset {dataset_version!r}"
            if dataset_version is not None
            else ""
        )
        raise CalendarBuilderError(f"no supported segment evidence{qualifier}")
    if len(event_types) > 1:
        raise CalendarBuilderError(
            "multiple event types in calendar evidence; specify event_type"
        )
    if len(aliases) > 1:
        raise CalendarBuilderError(
            "multiple contract aliases in calendar evidence: "
            + ", ".join(sorted(aliases))
        )

    selected_event_type = next(iter(event_types))
    day_evidence: dict[date, datetime] = {}
    night_starts: set[date] = set()
    kbar_night_heads: set[date] = set()
    kbar_night_tails: list[tuple[date, date]] = []
    for manifest, segment_day, _alias in selected:
        minimum = _aware(manifest, "minimum_event_time")
        maximum = _aware(manifest, "maximum_event_time")
        has_day = maximum.date() == segment_day and maximum.hour >= 8
        if selected_event_type == KBAR_EVENT_TYPE:
            # Kbars are filed by calendar date, not trading date.  A file can
            # contain a prior night's 00:00-05:00 tail and the current date's
            # 15:00-23:59 head.  The head is the authoritative session start.
            # A tail normally names that head as the preceding calendar day;
            # over a weekend/holiday, use the latest earlier head instead.
            if minimum.time() < time(8):
                kbar_night_tails.append(
                    (minimum.date() - timedelta(days=1), minimum.date())
                )
            if maximum.date() == segment_day and maximum.time() >= time(15):
                kbar_night_heads.add(segment_day)
        elif minimum.date() < segment_day or minimum.time() < time(8):
            night_starts.add(
                minimum.date()
                if minimum.time() >= time(15)
                else minimum.date() - timedelta(days=1)
            )
        if has_day:
            existing = day_evidence.get(segment_day)
            if existing is None or maximum > existing:
                day_evidence[segment_day] = maximum
    if not day_evidence:
        raise CalendarBuilderError("no day-session evidence in any segment")

    if selected_event_type == KBAR_EVENT_TYPE:
        night_starts.update(kbar_night_heads)
        for candidate, fragment_day in sorted(kbar_night_tails):
            if candidate in kbar_night_heads:
                continue
            earlier_heads = [
                head for head in kbar_night_heads if head < fragment_day
            ]
            night_starts.add(max(earlier_heads) if earlier_heads else candidate)

    trading_dates = sorted(day_evidence)
    nights: dict[date, date] = {}
    for start in sorted(night_starts):
        index = bisect_right(trading_dates, start)
        if index >= len(trading_dates):
            # A night beginning on the requested final trading date belongs
            # after the requested range.  It is safe to omit it when the
            # caller supplied an output end bound; otherwise fail closed.
            if end_bound is not None and start >= end_bound:
                continue
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
        day_close = (
            time(13, 30, 1) if last_day_tick.time() <= time(13, 31) else time(13, 45, 1)
        )
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
            entry["night_close"] = f"{night_close.isoformat()}T05:00:01"
        days.append(entry)
    if start_bound is not None:
        days = [
            entry
            for entry in days
            if str(entry["trading_date"]) >= start_bound.isoformat()
        ]
    if end_bound is not None:
        days = [
            entry
            for entry in days
            if str(entry["trading_date"]) <= end_bound.isoformat()
        ]
    if not days:
        raise CalendarBuilderError("calendar date bounds select no trading days")
    return {"version": version, "timezone": TIMEZONE, "days": days}


def _segment_evidence(
    manifest: Mapping[str, object],
) -> tuple[date, str, str]:
    segment_id = manifest.get("segment_id")
    if not isinstance(segment_id, str) or not segment_id:
        raise CalendarBuilderError("segment evidence lacks segment_id")
    match = _SEGMENT_ID.fullmatch(segment_id)
    if match is None:
        raise CalendarBuilderError(f"unrecognized segment id: {segment_id}")
    try:
        segment_day = date.fromisoformat(match.group("start"))
    except ValueError as error:
        raise CalendarBuilderError(f"unrecognized segment id: {segment_id}") from error
    return segment_day, match.group("alias"), match.group("kind")


def _date_bound(value: str | date | None, name: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise CalendarBuilderError(f"{name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CalendarBuilderError(f"{name} must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise CalendarBuilderError(f"{name} must be canonical YYYY-MM-DD")
    return parsed


def _aware(manifest: Mapping[str, object], name: str) -> datetime:
    raw = manifest.get(name)
    if not isinstance(raw, str) or not raw.strip():
        raise CalendarBuilderError(f"segment manifest lacks {name}")
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None or value.utcoffset() is None:
        raise CalendarBuilderError(f"{name} must be timezone-aware")
    return value
