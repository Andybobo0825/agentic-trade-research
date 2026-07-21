from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timezone
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from tmf_research.collection.event_queue import BoundedEventQueue
from tmf_research.domain.contracts import ContractInfo
from tmf_research.domain.events import BidAskEvent, MarketEvent, TickEvent
from tmf_research.infrastructure.contract_resolver import (
    ContractResolution,
    ContractTracker,
)


_TAIPEI = ZoneInfo("Asia/Taipei")

MarketCallback = Callable[[Mapping[str, object]], None]


class LiveGateway(Protocol):
    def register_quote_callback(self, callback: MarketCallback) -> None: ...
    def subscribe_quote(self, contract: ContractInfo) -> None: ...


class LiveCollector:
    """Binds one callback that only normalizes, timestamps, enqueues, and
    returns. Shioaji's combined QuoteFOPv1 feed (QuoteType.Quote) carries
    tick fields, L5 bidask fields, and underlying_price in one message, so a
    single subscription yields both a synthetic tick and a synthetic bidask
    per update (tick only when a real trade occurred, i.e. volume > 0)."""

    def __init__(
        self,
        gateway: LiveGateway,
        tracker: ContractTracker,
        event_queue: BoundedEventQueue[MarketEvent],
        *,
        clock: Callable[[], datetime] | None = None,
        event_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._gateway = gateway
        self._tracker = tracker
        self._queue = event_queue
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._event_id_factory = event_id_factory or (lambda: str(uuid4()))
        self._contract: ContractInfo | None = None

    def start(self) -> ContractResolution:
        resolution = self._tracker.refresh()
        self._contract = resolution.contract
        self._gateway.register_quote_callback(self._on_quote)
        self._gateway.subscribe_quote(resolution.contract)
        return resolution

    def _on_quote(self, payload: Mapping[str, object]) -> None:
        contract = self._required_contract()
        received_at = self._clock()
        exchange_datetime = _exchange_datetime(payload, received_at)
        code = _text(payload, "code", contract.target_code)
        underlying_price = _optional_float(payload, "underlying_price")
        simtrade = bool(payload.get("simtrade", False))
        volume = _int(payload, "volume")
        if volume > 0:
            tick = TickEvent(
                event_id=self._event_id_factory(),
                received_at=received_at,
                exchange_datetime=exchange_datetime,
                alias_code=contract.alias_code,
                target_code=contract.target_code,
                delivery_month=contract.delivery_month,
                code=code,
                close=_float(payload, "close"),
                volume=volume,
                simtrade=simtrade,
                raw_payload=payload,
                open=_optional_float(payload, "open"),
                high=_optional_float(payload, "high"),
                low=_optional_float(payload, "low"),
                avg_price=_optional_float(payload, "avg_price"),
                underlying_price=underlying_price,
                total_volume=_optional_int(payload, "total_volume"),
                tick_type=_optional_int(payload, "tick_type"),
            )
            self._queue.offer(tick)
        bidask = BidAskEvent(
            event_id=self._event_id_factory(),
            received_at=received_at,
            exchange_datetime=exchange_datetime,
            alias_code=contract.alias_code,
            target_code=contract.target_code,
            delivery_month=contract.delivery_month,
            code=code,
            bid_prices=_float_tuple(payload.get("bid_price", ())),
            bid_volumes=_int_tuple(payload.get("bid_volume", ())),
            ask_prices=_float_tuple(payload.get("ask_price", ())),
            ask_volumes=_int_tuple(payload.get("ask_volume", ())),
            underlying_price=underlying_price,
            simtrade=simtrade,
            raw_payload=payload,
        )
        self._queue.offer(bidask)

    def _required_contract(self) -> ContractInfo:
        if self._contract is None:
            raise RuntimeError("collector has not been started")
        return self._contract


def _text(payload: Mapping[str, object], name: str, default: str = "") -> str:
    value = payload.get(name, default)
    return str(value).strip() if value is not None else default


def _exchange_datetime(payload: Mapping[str, object], default: datetime) -> datetime:
    """Combined-quote payloads carry a "datetime" field (often naive, needs
    Taipei tzinfo attached); legacy split tick/bidask payloads carry
    separate "date"+"time" fields instead. Both are supported."""

    value = payload.get("datetime")
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=_TAIPEI)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=_TAIPEI)
    raw_date = payload.get("date")
    raw_time = payload.get("time")
    if raw_date is not None and raw_time is not None:
        return _combine_date_time(raw_date, raw_time)
    return default


def _combine_date_time(raw_date: object, raw_time: object) -> datetime:
    day = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date))
    clock = raw_time if isinstance(raw_time, time) else time.fromisoformat(str(raw_time))
    return datetime.combine(day, clock, tzinfo=_TAIPEI)


def _float(payload: Mapping[str, object], name: str) -> float:
    return float(_number(payload.get(name, 0.0), name))


def _int(payload: Mapping[str, object], name: str) -> int:
    return int(_number(payload.get(name, 0), name))


def _optional_float(payload: Mapping[str, object], name: str) -> float | None:
    value = payload.get(name)
    return None if value is None else float(_number(value, name))


def _optional_int(payload: Mapping[str, object], name: str) -> int | None:
    value = payload.get(name)
    return None if value is None else int(_number(value, name))


def _float_tuple(value: object) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(float(_number(item, "depth value")) for item in value)


def _int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(int(_number(item, "depth value")) for item in value)


def _number(value: object, name: str) -> int | float | str:
    if isinstance(value, (int, float, str)) and not isinstance(value, bool):
        return value
    raise TypeError(f"{name} must be numeric")
