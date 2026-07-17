from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime

from tmf_research.domain.paper_trades import (
    EXIT_REASONS,
    ExecutionMode,
    PaperCostConfig,
    PaperDirection,
    PaperExit,
    PaperExitReason,
    PaperPosition,
)


POINT_VALUE_NTD = 10.0


class DuplicateLedgerRowError(ValueError):
    """Raised when a settled trade identity is appended twice."""


@dataclass(frozen=True, slots=True)
class PaperLedgerRow:
    """One immutable, checksummed, PAPER-only settled trade."""

    row_id: str
    direction: PaperDirection
    quantity: int
    entry_price: float
    entry_time: datetime
    exit_price: float
    exit_time: datetime
    exit_reason: PaperExitReason
    gross_pnl_points: float
    gross_pnl_ntd: float
    entry_fee_ntd: float | None
    exit_fee_ntd: float | None
    tax_ntd: float | None
    slippage_cost_ntd: float | None
    cost_complete: bool
    net_pnl_ntd: float | None
    content_hash: str
    execution_mode: ExecutionMode = field(default="PAPER", init=False)

    def __post_init__(self) -> None:
        if _row_hash(self) != self.content_hash:
            raise ValueError("ledger row content hash mismatch")
        if not self.row_id.strip():
            raise ValueError("row_id is required")
        if self.quantity != 1:
            raise ValueError("quantity must be exactly one paper contract")
        if self.exit_reason not in EXIT_REASONS:
            raise ValueError("exit reason is not a specified paper exit")
        for name, value in (
            ("entry_price", self.entry_price),
            ("exit_price", self.exit_price),
            ("gross_pnl_points", self.gross_pnl_points),
            ("gross_pnl_ntd", self.gross_pnl_ntd),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.exit_time < self.entry_time:
            raise ValueError("exit cannot precede entry")
        expected_points = (
            self.exit_price - self.entry_price
            if self.direction == "LONG"
            else self.entry_price - self.exit_price
        )
        if not math.isclose(
            self.gross_pnl_points, expected_points, rel_tol=1e-9, abs_tol=1e-9,
        ):
            raise ValueError("gross points must derive from the recorded fills")
        if not math.isclose(
            self.gross_pnl_ntd,
            self.gross_pnl_points * POINT_VALUE_NTD,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError("gross NTD must be points times the fixed point value")
        components = (
            self.entry_fee_ntd, self.exit_fee_ntd,
            self.tax_ntd, self.slippage_cost_ntd,
        )
        for component in components:
            if component is not None and (
                not math.isfinite(component) or component < 0.0
            ):
                raise ValueError("cost components must be finite and non-negative")
        if self.cost_complete != all(item is not None for item in components):
            raise ValueError("cost completeness must derive from the components")
        if self.cost_complete:
            total = sum(item for item in components if item is not None)
            if self.net_pnl_ntd is None or not math.isclose(
                self.net_pnl_ntd,
                self.gross_pnl_ntd - total,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError("net NTD must subtract each cost exactly once")
        elif self.net_pnl_ntd is not None:
            raise ValueError("net NTD requires complete cost data")

    def claim_profitability(self) -> bool:
        if self.net_pnl_ntd is None:
            raise ValueError("profitability claims require complete cost data")
        return self.net_pnl_ntd > 0.0


def settle_paper_trade(
    position: PaperPosition,
    exit_decision: PaperExit,
    costs: PaperCostConfig,
) -> PaperLedgerRow:
    """Derive the immutable settled row; callers cannot author PnL."""

    if exit_decision.exited_at < position.entry.filled_at:
        raise ValueError("exit cannot precede entry")
    gross_points = (
        exit_decision.price - position.entry.price
        if position.direction == "LONG"
        else position.entry.price - exit_decision.price
    )
    gross_ntd = gross_points * POINT_VALUE_NTD
    net_ntd = gross_ntd - costs.total_ntd if costs.complete else None
    content_hash = _payload_hash({
        "row_id": position.position_id,
        "direction": position.direction,
        "quantity": position.entry.quantity,
        "entry_price": position.entry.price,
        "entry_time": position.entry.filled_at,
        "exit_price": exit_decision.price,
        "exit_time": exit_decision.exited_at,
        "exit_reason": exit_decision.reason,
        "gross_pnl_points": gross_points,
        "gross_pnl_ntd": gross_ntd,
        "entry_fee_ntd": costs.entry_fee_ntd,
        "exit_fee_ntd": costs.exit_fee_ntd,
        "tax_ntd": costs.tax_ntd,
        "slippage_cost_ntd": costs.slippage_cost_ntd,
        "cost_complete": costs.complete,
        "net_pnl_ntd": net_ntd,
    })
    return PaperLedgerRow(
        row_id=position.position_id,
        direction=position.direction,
        quantity=position.entry.quantity,
        entry_price=position.entry.price,
        entry_time=position.entry.filled_at,
        exit_price=exit_decision.price,
        exit_time=exit_decision.exited_at,
        exit_reason=exit_decision.reason,
        gross_pnl_points=gross_points,
        gross_pnl_ntd=gross_ntd,
        entry_fee_ntd=costs.entry_fee_ntd,
        exit_fee_ntd=costs.exit_fee_ntd,
        tax_ntd=costs.tax_ntd,
        slippage_cost_ntd=costs.slippage_cost_ntd,
        cost_complete=costs.complete,
        net_pnl_ntd=net_ntd,
        content_hash=content_hash,
    )


class PaperLedger:
    """Append-only, in-memory record of settled paper trades."""

    __slots__ = ("_rows",)

    def __init__(self) -> None:
        self._rows: dict[str, PaperLedgerRow] = {}

    @property
    def rows(self) -> tuple[PaperLedgerRow, ...]:
        return tuple(self._rows.values())

    def append(self, row: PaperLedgerRow) -> PaperLedgerRow:
        if row.row_id in self._rows:
            raise DuplicateLedgerRowError(
                f"paper ledger row {row.row_id} is already settled"
            )
        self._rows[row.row_id] = row
        return row


def _row_hash(row: PaperLedgerRow) -> str:
    return _payload_hash({
        "row_id": row.row_id,
        "direction": row.direction,
        "quantity": row.quantity,
        "entry_price": row.entry_price,
        "entry_time": row.entry_time,
        "exit_price": row.exit_price,
        "exit_time": row.exit_time,
        "exit_reason": row.exit_reason,
        "gross_pnl_points": row.gross_pnl_points,
        "gross_pnl_ntd": row.gross_pnl_ntd,
        "entry_fee_ntd": row.entry_fee_ntd,
        "exit_fee_ntd": row.exit_fee_ntd,
        "tax_ntd": row.tax_ntd,
        "slippage_cost_ntd": row.slippage_cost_ntd,
        "cost_complete": row.cost_complete,
        "net_pnl_ntd": row.net_pnl_ntd,
    })


def _payload_hash(payload: dict[str, object]) -> str:
    canonical = {
        name: value.isoformat() if isinstance(value, datetime) else value
        for name, value in payload.items()
    }
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
