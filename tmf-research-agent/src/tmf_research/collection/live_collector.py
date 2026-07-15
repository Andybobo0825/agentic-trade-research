from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from tmf_research.collection.event_queue import BoundedEventQueue
from tmf_research.domain.contracts import ContractInfo
from tmf_research.domain.events import BidAskEvent, MarketEvent, TickEvent
from tmf_research.infrastructure.contract_resolver import (
    ContractResolution,
    ContractTracker,
)


MarketCallback = Callable[[Mapping[str, object]], None]


class LiveGateway(Protocol):
    def register_tick_callback(self, callback: MarketCallback) -> None: ...
    def register_bidask_callback(self, callback: MarketCallback) -> None: ...
    def subscribe_tick(self, contract: ContractInfo) -> None: ...
    def subscribe_bidask(self, contract: ContractInfo) -> None: ...


class LiveCollector:
    """Binds callbacks that only normalize, timestamp, enqueue, and return."""

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
        self._gateway.register_tick_callback(self._on_tick)
        self._gateway.register_bidask_callback(self._on_bidask)
        self._gateway.subscribe_tick(resolution.contract)
        self._gateway.subscribe_bidask(resolution.contract)
        return resolution

    def _on_tick(self, payload: Mapping[str, object]) -> None:
        contract = self._required_contract()
        received_at = self._clock()
        event = TickEvent(
            event_id=self._event_id_factory(),
            received_at=received_at,
            exchange_datetime=_datetime(payload, "datetime", received_at),
            alias_code=contract.alias_code,
            target_code=contract.target_code,
            delivery_month=contract.delivery_month,
            code=_text(payload, "code", contract.target_code),
            close=_float(payload, "close"),
            volume=_int(payload, "volume"),
            simtrade=bool(payload.get("simtrade", False)),
            raw_payload=payload,
            open=_optional_float(payload, "open"),
            high=_optional_float(payload, "high"),
            low=_optional_float(payload, "low"),
            avg_price=_optional_float(payload, "avg_price"),
            underlying_price=_optional_float(payload, "underlying_price"),
            total_volume=_optional_int(payload, "total_volume"),
            tick_type=_optional_int(payload, "tick_type"),
        )
        self._queue.offer(event)

    def _on_bidask(self, payload: Mapping[str, object]) -> None:
        contract = self._required_contract()
        received_at = self._clock()
        event = BidAskEvent(
            event_id=self._event_id_factory(),
            received_at=received_at,
            exchange_datetime=_datetime(payload, "datetime", received_at),
            alias_code=contract.alias_code,
            target_code=contract.target_code,
            delivery_month=contract.delivery_month,
            code=_text(payload, "code", contract.target_code),
            bid_prices=_float_tuple(payload.get("bid_price", ())),
            bid_volumes=_int_tuple(payload.get("bid_volume", ())),
            ask_prices=_float_tuple(payload.get("ask_price", ())),
            ask_volumes=_int_tuple(payload.get("ask_volume", ())),
            diff_bid_volumes=_int_tuple(payload.get("diff_bid_vol", ())),
            diff_ask_volumes=_int_tuple(payload.get("diff_ask_vol", ())),
            underlying_price=_optional_float(payload, "underlying_price"),
            simtrade=bool(payload.get("simtrade", False)),
            raw_payload=payload,
        )
        self._queue.offer(event)

    def _required_contract(self) -> ContractInfo:
        if self._contract is None:
            raise RuntimeError("collector has not been started")
        return self._contract


def _text(payload: Mapping[str, object], name: str, default: str = "") -> str:
    value = payload.get(name, default)
    return str(value).strip() if value is not None else default


def _datetime(
    payload: Mapping[str, object],
    name: str,
    default: datetime,
) -> datetime:
    value = payload.get(name, default)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"{name} must be a datetime or ISO-8601 string")


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
