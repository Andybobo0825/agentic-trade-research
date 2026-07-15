from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


PaperDirection = Literal["LONG", "SHORT"]
ExecutionMode = Literal["PAPER"]


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
