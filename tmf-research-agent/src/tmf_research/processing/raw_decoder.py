from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import math
from typing import cast

from tmf_research.domain.events import BidAskEvent, Session, TickEvent


def decode_tick(record: Mapping[str, object]) -> TickEvent:
    return TickEvent(
        event_id=_text(record, "event_id"),
        received_at=_datetime(record, "received_at"),
        exchange_datetime=_datetime(record, "exchange_datetime"),
        alias_code=_text(record, "alias_code"),
        target_code=_text(record, "target_code"),
        delivery_month=_text(record, "delivery_month"),
        code=_text(record, "code"),
        close=_number(record, "close"),
        volume=_integer(record, "volume"),
        simtrade=_boolean(record, "simtrade"),
        raw_payload=_mapping(record.get("raw_payload", {})),
        trading_date=_text(record, "trading_date"),
        session=_session(record),
        underlying_price=_optional_number(record.get("underlying_price")),
        tick_type=_optional_integer(record.get("tick_type")),
    )


def decode_bidask(record: Mapping[str, object]) -> BidAskEvent:
    return BidAskEvent(
        event_id=_text(record, "event_id"),
        received_at=_datetime(record, "received_at"),
        exchange_datetime=_datetime(record, "exchange_datetime"),
        alias_code=_text(record, "alias_code"),
        target_code=_text(record, "target_code"),
        delivery_month=_text(record, "delivery_month"),
        code=_text(record, "code"),
        bid_prices=_numbers(record, "bid_prices"),
        bid_volumes=_integers(record, "bid_volumes"),
        ask_prices=_numbers(record, "ask_prices"),
        ask_volumes=_integers(record, "ask_volumes"),
        simtrade=_boolean(record, "simtrade"),
        raw_payload=_mapping(record.get("raw_payload", {})),
        trading_date=_text(record, "trading_date"),
        session=_session(record),
        underlying_price=_optional_number(record.get("underlying_price")),
    )


def _text(record: Mapping[str, object], name: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"raw {name} is required")
    return value


def _datetime(record: Mapping[str, object], name: str) -> datetime:
    value = datetime.fromisoformat(_text(record, name))
    if value.tzinfo is None:
        raise ValueError(f"raw {name} must be timezone-aware")
    return value


def _number(record: Mapping[str, object], name: str) -> float:
    value = record.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"raw {name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"raw {name} must be finite")
    return numeric


def _integer(record: Mapping[str, object], name: str) -> int:
    value = record.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"raw {name} must be an integer")
    return value


def _boolean(record: Mapping[str, object], name: str) -> bool:
    value = record.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"raw {name} must be boolean")
    return value


def _numbers(record: Mapping[str, object], name: str) -> tuple[float, ...]:
    values = _sequence(record, name)
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool)
        or not math.isfinite(float(value))
        for value in values
    ):
        raise ValueError(f"raw {name} must contain finite numbers")
    return tuple(float(cast(int | float, value)) for value in values)


def _integers(record: Mapping[str, object], name: str) -> tuple[int, ...]:
    values = _sequence(record, name)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise ValueError(f"raw {name} must contain integers")
    return tuple(cast(int, value) for value in values)


def _sequence(record: Mapping[str, object], name: str) -> Sequence[object]:
    value = record.get(name)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"raw {name} must be a sequence")
    return value


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("raw payload must be an object")
    return {str(key): item for key, item in value.items()}


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError("raw optional number is invalid")
    return float(value)


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("raw optional integer is invalid")
    return value


def _session(record: Mapping[str, object]) -> Session:
    value = _text(record, "session")
    if value not in ("DAY", "NIGHT", "CLOSED"):
        raise ValueError("raw session is invalid")
    return cast(Session, value)
