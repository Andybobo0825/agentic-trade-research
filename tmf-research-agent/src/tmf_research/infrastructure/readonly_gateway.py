from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

from tmf_research.domain.contracts import ContractInfo, KbarBatch, TickBatch


@runtime_checkable
class MarketDataGateway(Protocol):
    """Only market-data capabilities exposed beyond infrastructure."""

    def resolve_near_contract(self) -> ContractInfo: ...

    def register_tick_callback(
        self,
        callback: Callable[[Mapping[str, object]], None],
    ) -> None: ...

    def register_bidask_callback(
        self,
        callback: Callable[[Mapping[str, object]], None],
    ) -> None: ...

    def subscribe_tick(self, contract: ContractInfo) -> None: ...

    def subscribe_bidask(self, contract: ContractInfo) -> None: ...

    def unsubscribe_tick(self, contract: ContractInfo) -> None: ...

    def unsubscribe_bidask(self, contract: ContractInfo) -> None: ...

    def fetch_ticks(self, contract: ContractInfo, date: str) -> TickBatch: ...

    def fetch_kbars(
        self,
        contract: ContractInfo,
        start: str,
        end: str,
    ) -> KbarBatch: ...
