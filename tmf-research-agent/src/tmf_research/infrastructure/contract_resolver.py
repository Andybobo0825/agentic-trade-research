from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from tmf_research.domain.contracts import ContractInfo
from tmf_research.domain.events import RolloverEvent


class ContractResolver(Protocol):
    def resolve_near_contract(self) -> ContractInfo: ...


@dataclass(frozen=True, slots=True)
class ContractResolution:
    contract: ContractInfo
    rollover: RolloverEvent | None


class ContractTracker:
    """Retains point-in-time target identity and emits explicit rollovers."""

    def __init__(
        self,
        gateway: ContractResolver,
        *,
        clock: Callable[[], datetime] | None = None,
        event_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._gateway = gateway
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._event_id_factory = event_id_factory or (lambda: str(uuid4()))
        self._current: ContractInfo | None = None

    @property
    def current(self) -> ContractInfo | None:
        return self._current

    def refresh(self) -> ContractResolution:
        resolved = self._gateway.resolve_near_contract()
        previous = self._current
        self._current = resolved
        if previous is None or not _changed(previous, resolved):
            return ContractResolution(resolved, None)
        detected_at = self._clock()
        return ContractResolution(
            resolved,
            RolloverEvent(
                event_id=self._event_id_factory(),
                detected_at=detected_at,
                effective_from=resolved.resolved_at,
                old_target_code=previous.target_code,
                new_target_code=resolved.target_code,
                old_delivery_month=previous.delivery_month,
                new_delivery_month=resolved.delivery_month,
                resolver_version=resolved.resolver_version,
            ),
        )


def _changed(previous: ContractInfo, current: ContractInfo) -> bool:
    return (
        previous.target_code != current.target_code
        or previous.delivery_month != current.delivery_month
    )
