from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


PaperDirection = Literal["LONG", "SHORT"]
ExecutionMode = Literal["PAPER"]
PaperExitReason = Literal[
    "STOP_LOSS",
    "PROFIT_TARGET",
    "VERTICAL_BARRIER",
    "SESSION_END",
    "DATA_STALE",
    "ROLLOVER",
]

EXIT_REASONS: tuple[PaperExitReason, ...] = (
    "STOP_LOSS",
    "PROFIT_TARGET",
    "VERTICAL_BARRIER",
    "SESSION_END",
    "DATA_STALE",
    "ROLLOVER",
)


def _require_finite_positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value <= 0.0:
        raise ValueError(f"{name} must be positive")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PaperIntent:
    """A research-only directional intent, not an executable instruction."""

    intent_id: str
    direction: PaperDirection
    quantity: int
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.intent_id.strip():
            raise ValueError("intent_id is required")
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError("direction must be LONG or SHORT")
        if self.quantity != 1:
            raise ValueError("quantity must be exactly one paper contract")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PaperRecord:
    """Immutable evidence that an intent stayed inside the paper boundary."""

    intent_id: str
    direction: PaperDirection
    quantity: int
    recorded_at: datetime
    execution_mode: ExecutionMode = field(default="PAPER", init=False)


@dataclass(frozen=True, slots=True)
class PaperQuote:
    """One immutable best bid/ask observation expressed as primitives."""

    bid_price_1: float
    ask_price_1: float
    age_ms: int

    def __post_init__(self) -> None:
        for name, value in (
            ("bid_price_1", self.bid_price_1),
            ("ask_price_1", self.ask_price_1),
        ):
            _require_finite_positive(value, name)
        if self.ask_price_1 < self.bid_price_1:
            raise ValueError("quote is crossed")
        if isinstance(self.age_ms, bool) or self.age_ms < 0:
            raise ValueError("quote age must be a non-negative millisecond count")

    @property
    def spread_points(self) -> float:
        return self.ask_price_1 - self.bid_price_1


@dataclass(frozen=True, slots=True)
class PaperCostConfig:
    """Declared NTD cost components; missing components stay explicit."""

    entry_fee_ntd: float | None
    exit_fee_ntd: float | None
    tax_ntd: float | None
    slippage_cost_ntd: float | None

    def __post_init__(self) -> None:
        for value in (
            self.entry_fee_ntd, self.exit_fee_ntd,
            self.tax_ntd, self.slippage_cost_ntd,
        ):
            if value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0.0
            ):
                raise ValueError("cost components must be finite and non-negative")

    @property
    def complete(self) -> bool:
        return None not in (
            self.entry_fee_ntd, self.exit_fee_ntd,
            self.tax_ntd, self.slippage_cost_ntd,
        )

    @property
    def total_ntd(self) -> float:
        if (
            self.entry_fee_ntd is None
            or self.exit_fee_ntd is None
            or self.tax_ntd is None
            or self.slippage_cost_ntd is None
        ):
            raise ValueError("cost configuration is incomplete")
        return (
            self.entry_fee_ntd + self.exit_fee_ntd
            + self.tax_ntd + self.slippage_cost_ntd
        )


@dataclass(frozen=True, slots=True)
class PaperFill:
    """One immutable single-contract paper fill."""

    direction: PaperDirection
    price: float
    filled_at: datetime
    quantity: int = 1

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError("direction must be LONG or SHORT")
        _require_finite_positive(self.price, "fill price")
        _require_aware(self.filled_at, "filled_at")
        if self.quantity != 1:
            raise ValueError("quantity must be exactly one paper contract")


@dataclass(frozen=True, slots=True)
class PaperPosition:
    """The single open paper position with its frozen protection prices."""

    position_id: str
    direction: PaperDirection
    entry: PaperFill
    stop_price: float
    target_price: float
    vertical_deadline: datetime
    session_end: datetime

    def __post_init__(self) -> None:
        if not self.position_id.strip():
            raise ValueError("position_id is required")
        if self.direction != self.entry.direction:
            raise ValueError("position and entry fill direction must match")
        _require_finite_positive(self.stop_price, "stop price")
        _require_finite_positive(self.target_price, "target price")
        _require_aware(self.vertical_deadline, "vertical_deadline")
        _require_aware(self.session_end, "session_end")
        if self.direction == "LONG":
            if self.stop_price >= self.entry.price:
                raise ValueError("long stop price must fall below the entry fill")
            if self.target_price <= self.entry.price:
                raise ValueError("long target price must rise above the entry fill")
        else:
            if self.stop_price <= self.entry.price:
                raise ValueError("short stop price must rise above the entry fill")
            if self.target_price >= self.entry.price:
                raise ValueError("short target price must fall below the entry fill")
        if self.vertical_deadline <= self.entry.filled_at:
            raise ValueError("vertical_deadline must follow the entry fill")
        if self.session_end <= self.entry.filled_at:
            raise ValueError("session_end must follow the entry fill")


@dataclass(frozen=True, slots=True)
class PaperExit:
    """One immutable paper exit decision with its persisted reason."""

    reason: PaperExitReason
    price: float
    exited_at: datetime

    def __post_init__(self) -> None:
        if self.reason not in EXIT_REASONS:
            raise ValueError("exit reason is not a specified paper exit")
        _require_finite_positive(self.price, "exit price")
        _require_aware(self.exited_at, "exited_at")
