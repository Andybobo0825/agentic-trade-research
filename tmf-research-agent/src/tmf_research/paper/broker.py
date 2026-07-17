from __future__ import annotations

from datetime import datetime

from tmf_research.domain.paper_trades import (
    PaperCostConfig,
    PaperExit,
    PaperFill,
    PaperIntent,
    PaperPosition,
    PaperRecord,
)
from tmf_research.paper.ledger import PaperLedger, PaperLedgerRow, settle_paper_trade


class DuplicatePaperIntentError(ValueError):
    """Raised when replay attempts to record the same intent twice."""


class PaperPositionError(ValueError):
    """Raised when a paper action violates the single-position contract."""


class PaperBroker:
    """In-memory paper evidence boundary with no external capabilities."""

    def __init__(self) -> None:
        self._records: dict[str, PaperRecord] = {}
        self._ledger = PaperLedger()
        self._position: PaperPosition | None = None

    @property
    def records(self) -> tuple[PaperRecord, ...]:
        return tuple(self._records.values())

    @property
    def ledger(self) -> PaperLedger:
        return self._ledger

    @property
    def position(self) -> PaperPosition | None:
        return self._position

    def record_intent(self, intent: PaperIntent) -> PaperRecord:
        if intent.intent_id in self._records:
            raise DuplicatePaperIntentError(
                f"paper intent {intent.intent_id} is already recorded"
            )
        record = PaperRecord(
            intent_id=intent.intent_id,
            direction=intent.direction,
            quantity=intent.quantity,
            recorded_at=intent.created_at,
        )
        self._records[intent.intent_id] = record
        return record

    def open_position(
        self,
        intent: PaperIntent,
        entry: PaperFill,
        *,
        stop_price: float,
        target_price: float,
        vertical_deadline: datetime,
        session_end: datetime,
    ) -> PaperPosition:
        if self._position is not None:
            raise PaperPositionError(
                "one open paper position is the maximum; adding, averaging,"
                " and reversing are forbidden"
            )
        if intent.direction != entry.direction:
            raise PaperPositionError("intent and fill direction must match")
        self.record_intent(intent)
        position = PaperPosition(
            position_id=intent.intent_id,
            direction=intent.direction,
            entry=entry,
            stop_price=stop_price,
            target_price=target_price,
            vertical_deadline=vertical_deadline,
            session_end=session_end,
        )
        self._position = position
        return position

    def close_position(
        self,
        exit_decision: PaperExit,
        costs: PaperCostConfig,
    ) -> PaperLedgerRow:
        if self._position is None:
            raise PaperPositionError("no open paper position to close")
        row = settle_paper_trade(self._position, exit_decision, costs)
        self._ledger.append(row)
        self._position = None
        return row
