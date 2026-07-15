from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ContractInfo:
    """Primitive-only identity of the contract resolved from the near alias."""

    alias_code: str
    target_code: str
    symbol: str
    category: str
    delivery_month: str
    delivery_date: str
    resolved_at: datetime
    resolver_version: str

    def __post_init__(self) -> None:
        if self.resolved_at.tzinfo is None:
            raise ValueError("resolved_at must be timezone-aware")
        if not self.alias_code.strip() or not self.target_code.strip():
            raise ValueError("alias_code and target_code are required")


@dataclass(frozen=True, slots=True)
class TickBatch:
    """Historical tick response bound to the resolved real contract."""

    contract: ContractInfo
    date: str
    fetched_at: datetime
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class KbarBatch:
    """Historical minute-bar response bound to the resolved real contract."""

    contract: ContractInfo
    start: str
    end: str
    fetched_at: datetime
    payload: Mapping[str, object]
