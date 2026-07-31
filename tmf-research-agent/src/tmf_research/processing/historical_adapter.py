from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime

from tmf_research.collection.backfill import SOURCE as HISTORICAL_TICK_SOURCE
from tmf_research.domain.events import BidAskEvent, Session, TickEvent
from tmf_research.domain.sessions import TradingCalendar
from tmf_research.processing.session_resolver import SessionResolver


HISTORICAL_QUOTE_SOURCE = "DERIVED_FROM_HISTORICAL_TICK_L1"


class HistoricalAdapterError(ValueError):
    """Raised when stored historical records cannot become research events."""


def decode_historical_day(
    day: str,
    records: Sequence[Mapping[str, object]],
    *,
    calendar: TradingCalendar | None = None,
) -> tuple[tuple[TickEvent, ...], tuple[BidAskEvent, ...]]:
    """Turn one verified historical-tick day into pipeline-ready events.

    Quote events are derived from the tick-embedded L1 book only when it
    changes, always carry their source tick's timestamps (never earlier),
    and are explicitly marked as derived. Invalid embedded quotes (zero or
    crossed) derive nothing, so downstream staleness rules apply.

    With a calendar, trading date and session come from the resolver, so a
    holiday-eve night belongs to the next trading date instead of the queried
    segment day, and a tick outside every calendar session fails closed.
    Without a calendar, the segment day and an hour heuristic apply.

    Records process in timestamp order regardless of vendor array position
    (real payloads occasionally misplace a night tick after the day close);
    ties keep their stored order, so output stays deterministic. Events do
    not duplicate the raw fields in memory: the append-only segments remain
    the immutable raw evidence.
    """

    resolver = None if calendar is None else SessionResolver(calendar)
    ticks: list[TickEvent] = []
    quotes: list[BidAskEvent] = []
    previous_level: tuple[float, int, float, int] | None = None
    target_code: str | None = None
    ordered = sorted(
        enumerate(records),
        key=lambda item: (_time(item[1], "exchange_datetime", day), item[0]),
    )
    for _original_index, record in ordered:
        source = record.get("source")
        if source != HISTORICAL_TICK_SOURCE:
            raise HistoricalAdapterError(f"{day}: unexpected record source {source!r}")
        event_id = _text(record, "event_id", day)
        if f"-{day}-" not in event_id:
            raise HistoricalAdapterError(
                f"{day}: event {event_id} does not belong to this day"
            )
        derived_target = _text(record, "derived_target_code", day)
        if target_code is None:
            target_code = derived_target
        elif derived_target != target_code:
            raise HistoricalAdapterError(
                f"{day}: mixed derived target codes {target_code} and {derived_target}"
            )
        exchange_datetime = _time(record, "exchange_datetime", day)
        received_at = _time(record, "received_at", day)
        fields = record.get("fields")
        if not isinstance(fields, Mapping):
            raise HistoricalAdapterError(f"{day}: record fields are missing")
        if resolver is None:
            session: Session = _session_for(exchange_datetime, day)
            trading_date = day
        else:
            resolution = resolver.resolve(exchange_datetime)
            if resolution.session == "CLOSED" or resolution.trading_date is None:
                raise HistoricalAdapterError(
                    f"{day}: tick at {exchange_datetime.isoformat()} falls"
                    " outside every calendar session"
                )
            session = resolution.session
            trading_date = resolution.trading_date.isoformat()
        tick = TickEvent(
            event_id=event_id,
            received_at=received_at,
            exchange_datetime=exchange_datetime,
            alias_code=_text(record, "alias_code", day),
            target_code=target_code,
            delivery_month=target_code.removeprefix("TMF"),
            code=target_code,
            close=_number(fields, "close", day),
            volume=_integer(fields, "volume", day),
            simtrade=False,
            raw_payload={},
            trading_date=trading_date,
            session=session,
            tick_type=_optional_integer(fields.get("tick_type")),
        )
        ticks.append(tick)
        level = _embedded_level(fields, day)
        if level is not None and level != previous_level:
            previous_level = level
            bid_price, bid_volume, ask_price, ask_volume = level
            quotes.append(BidAskEvent(
                event_id=f"{event_id}-q",
                received_at=received_at,
                exchange_datetime=exchange_datetime,
                alias_code=tick.alias_code,
                target_code=target_code,
                delivery_month=tick.delivery_month,
                code=target_code,
                bid_prices=(bid_price,),
                bid_volumes=(bid_volume,),
                ask_prices=(ask_price,),
                ask_volumes=(ask_volume,),
                simtrade=False,
                raw_payload={"source": HISTORICAL_QUOTE_SOURCE},
                trading_date=trading_date,
                session=session,
            ))
    return tuple(ticks), tuple(quotes)


def _session_for(moment: datetime, day: str) -> Session:
    hour = moment.hour
    if hour >= 15 or hour < 6:
        return "NIGHT"
    if 8 <= hour < 14:
        return "DAY"
    raise HistoricalAdapterError(
        f"{day}: tick at {moment.isoformat()} falls outside any session"
    )


def _embedded_level(
    fields: Mapping[str, object],
    day: str,
) -> tuple[float, int, float, int] | None:
    bid_price = _number(fields, "bid_price", day)
    ask_price = _number(fields, "ask_price", day)
    bid_volume = _integer(fields, "bid_volume", day)
    ask_volume = _integer(fields, "ask_volume", day)
    if bid_price <= 0.0 or ask_price <= 0.0:
        return None
    if ask_price < bid_price or bid_volume < 0 or ask_volume < 0:
        return None
    return (bid_price, bid_volume, ask_price, ask_volume)


def _text(record: Mapping[str, object], name: str, day: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value.strip():
        raise HistoricalAdapterError(f"{day}: record lacks {name}")
    return value


def _time(record: Mapping[str, object], name: str, day: str) -> datetime:
    raw = _text(record, name, day)
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise HistoricalAdapterError(f"{day}: invalid {name}: {error}") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalAdapterError(f"{day}: {name} must be timezone-aware")
    return value


def _number(fields: Mapping[str, object], name: str, day: str) -> float:
    value = fields.get(name)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise HistoricalAdapterError(f"{day}: field {name} is missing or non-finite")
    return float(value)


def _integer(fields: Mapping[str, object], name: str, day: str) -> int:
    value = fields.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalAdapterError(f"{day}: field {name} is missing or non-integer")
    return value


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
