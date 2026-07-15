from __future__ import annotations

from tmf_research.domain.paper_trades import PaperIntent, PaperRecord


class DuplicatePaperIntentError(ValueError):
    """Raised when replay attempts to record the same intent twice."""


class PaperBroker:
    """In-memory paper evidence boundary with no external capabilities."""

    def __init__(self) -> None:
        self._records: dict[str, PaperRecord] = {}

    @property
    def records(self) -> tuple[PaperRecord, ...]:
        return tuple(self._records.values())

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
