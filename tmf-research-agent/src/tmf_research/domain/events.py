from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Literal


SCHEMA_VERSION = "1.1.0"
Session = Literal["DAY", "NIGHT", "CLOSED"]


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class TickEvent:
    event_id: str
    received_at: datetime
    exchange_datetime: datetime
    alias_code: str
    target_code: str
    delivery_month: str
    code: str
    close: float
    volume: int
    simtrade: bool
    raw_payload: Mapping[str, object]
    trading_date: str = ""
    session: Session = "CLOSED"
    open: float | None = None
    high: float | None = None
    low: float | None = None
    avg_price: float | None = None
    underlying_price: float | None = None
    amount: float | None = None
    total_amount: float | None = None
    total_volume: int | None = None
    tick_type: int | None = None
    price_chg: float | None = None
    pct_chg: float | None = None
    bid_side_total_volume: int | None = None
    ask_side_total_volume: int | None = None
    schema_version: str = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _require_aware(self.received_at, "received_at")
        _require_aware(self.exchange_datetime, "exchange_datetime")
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        object.__setattr__(self, "raw_payload", _freeze(dict(self.raw_payload)))

    @property
    def latency_ms(self) -> float:
        return max(
            0.0,
            (self.received_at - self.exchange_datetime).total_seconds() * 1000.0,
        )


@dataclass(frozen=True, slots=True)
class BidAskEvent:
    event_id: str
    received_at: datetime
    exchange_datetime: datetime
    alias_code: str
    target_code: str
    delivery_month: str
    code: str
    bid_prices: tuple[float, ...]
    bid_volumes: tuple[int, ...]
    ask_prices: tuple[float, ...]
    ask_volumes: tuple[int, ...]
    simtrade: bool
    raw_payload: Mapping[str, object]
    trading_date: str = ""
    session: Session = "CLOSED"
    diff_bid_volumes: tuple[int, ...] = ()
    diff_ask_volumes: tuple[int, ...] = ()
    underlying_price: float | None = None
    schema_version: str = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _require_aware(self.received_at, "received_at")
        _require_aware(self.exchange_datetime, "exchange_datetime")
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        object.__setattr__(self, "bid_prices", tuple(self.bid_prices))
        object.__setattr__(self, "bid_volumes", tuple(self.bid_volumes))
        object.__setattr__(self, "ask_prices", tuple(self.ask_prices))
        object.__setattr__(self, "ask_volumes", tuple(self.ask_volumes))
        object.__setattr__(self, "diff_bid_volumes", tuple(self.diff_bid_volumes))
        object.__setattr__(self, "diff_ask_volumes", tuple(self.diff_ask_volumes))
        object.__setattr__(self, "raw_payload", _freeze(dict(self.raw_payload)))

    @property
    def latency_ms(self) -> float:
        return max(
            0.0,
            (self.received_at - self.exchange_datetime).total_seconds() * 1000.0,
        )

    def _level(self, values: tuple[float, ...] | tuple[int, ...], level: int) -> object:
        return values[level - 1] if len(values) >= level else None


def _level_property(attribute: str, level: int) -> property:
    return property(lambda self: self._level(getattr(self, attribute), level))


for _prefix, _attribute in (
    ("bid_price", "bid_prices"),
    ("bid_volume", "bid_volumes"),
    ("ask_price", "ask_prices"),
    ("ask_volume", "ask_volumes"),
    ("diff_bid_volume", "diff_bid_volumes"),
    ("diff_ask_volume", "diff_ask_volumes"),
):
    for _index in range(1, 6):
        setattr(BidAskEvent, f"{_prefix}_{_index}", _level_property(_attribute, _index))


@dataclass(frozen=True, slots=True)
class ConnectionEvent:
    event_id: str
    occurred_at: datetime
    event_type: str
    connection_status: str
    attempt_number: int
    reason: str
    last_tick_at: datetime | None = None
    last_bidask_at: datetime | None = None
    queue_size: int = 0
    dropped_event_count: int = 0

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True, slots=True)
class QueueBackpressureEvent:
    event_id: str
    occurred_at: datetime
    queue_size: int
    dropped_event_count: int
    event_type: str = field(default="QUEUE_BACKPRESSURE", init=False)
    quality_status: str = field(default="INVALID", init=False)
    allow_paper_trade: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True, slots=True)
class RolloverEvent:
    event_id: str
    detected_at: datetime
    effective_from: datetime
    old_target_code: str
    new_target_code: str
    old_delivery_month: str
    new_delivery_month: str
    resolver_version: str
    allow_paper_trade: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_aware(self.detected_at, "detected_at")
        _require_aware(self.effective_from, "effective_from")


@dataclass(frozen=True, slots=True)
class RejectedEvent:
    event_id: str
    rejected_at: datetime
    reasons: tuple[str, ...]
    raw_payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_aware(self.rejected_at, "rejected_at")
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "raw_payload", _freeze(dict(self.raw_payload)))


MarketEvent = TickEvent | BidAskEvent | ConnectionEvent | QueueBackpressureEvent | RolloverEvent
