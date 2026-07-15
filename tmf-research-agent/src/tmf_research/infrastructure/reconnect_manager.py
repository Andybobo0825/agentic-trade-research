from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol
from uuid import uuid4

from tmf_research.domain.contracts import ContractInfo
from tmf_research.domain.events import ConnectionEvent, RolloverEvent
from tmf_research.infrastructure.contract_resolver import ContractTracker


class SubscriptionGateway(Protocol):
    def subscribe_tick(self, contract: ContractInfo) -> None: ...
    def subscribe_bidask(self, contract: ContractInfo) -> None: ...


class ConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"


@dataclass(frozen=True, slots=True)
class ReconnectResult:
    connection: ConnectionEvent
    rollover: RolloverEvent | None


class ReconnectManager:
    """Records connection state and re-resolves before every resubscription."""

    def __init__(
        self,
        gateway: SubscriptionGateway,
        tracker: ContractTracker,
        *,
        clock: Callable[[], datetime] | None = None,
        event_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._gateway = gateway
        self._tracker = tracker
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._event_id_factory = event_id_factory or (lambda: str(uuid4()))
        self._state = ConnectionState.CONNECTED
        self._attempt_number = 0
        self._last_reason = ""

    @property
    def state(self) -> ConnectionState:
        return self._state

    def mark_disconnected(self, reason: str) -> ConnectionEvent:
        self._state = ConnectionState.DISCONNECTED
        self._last_reason = reason
        return self._event("CONNECTION_DROPPED", reason)

    def reconnect(self) -> ReconnectResult:
        self._state = ConnectionState.CONNECTING
        self._attempt_number += 1
        resolution = self._tracker.refresh()
        self._gateway.subscribe_tick(resolution.contract)
        self._gateway.subscribe_bidask(resolution.contract)
        self._state = ConnectionState.CONNECTED
        return ReconnectResult(
            connection=self._event("CONNECTION_RESTORED", self._last_reason),
            rollover=resolution.rollover,
        )

    def _event(self, event_type: str, reason: str) -> ConnectionEvent:
        return ConnectionEvent(
            event_id=self._event_id_factory(),
            occurred_at=self._clock(),
            event_type=event_type,
            connection_status=self._state.value,
            attempt_number=self._attempt_number,
            reason=reason,
        )
