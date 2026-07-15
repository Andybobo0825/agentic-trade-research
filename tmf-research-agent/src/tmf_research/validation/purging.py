from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Protocol, TypeVar


class OutcomeTimed(Protocol):
    @property
    def outcome_time(self) -> datetime: ...

    @property
    def decision_time(self) -> datetime: ...


T = TypeVar("T", bound=OutcomeTimed)


def validate_embargo(embargo_minutes: int, model_horizons_minutes: Sequence[int]) -> timedelta:
    if isinstance(embargo_minutes, bool) or embargo_minutes < 0:
        raise ValueError("embargo must be a non-negative integer number of minutes")
    if not model_horizons_minutes or any(
        isinstance(value, bool) or value <= 0 for value in model_horizons_minutes
    ):
        raise ValueError("positive model horizons are required")
    required = max(model_horizons_minutes)
    if embargo_minutes < required:
        raise ValueError(f"embargo must be at least maximum model horizon ({required} minutes)")
    return timedelta(minutes=embargo_minutes)


def purge_outcomes(rows: Iterable[T], boundary: datetime) -> tuple[T, ...]:
    """Exclude equality as well as outcomes after a validation/test boundary."""
    _aware(boundary, "boundary")
    kept = tuple(row for row in rows if row.outcome_time < boundary)
    return tuple(sorted(kept, key=lambda row: row.decision_time))


def apply_embargo(rows: Iterable[T], boundary: datetime, embargo: timedelta) -> tuple[T, ...]:
    """Remove the interval immediately preceding a validation or test boundary."""
    _aware(boundary, "boundary")
    if embargo < timedelta(0):
        raise ValueError("embargo must not be negative")
    cutoff = boundary - embargo
    return tuple(sorted((row for row in rows if row.decision_time < cutoff), key=lambda row: row.decision_time))


def purge_and_embargo(rows: Iterable[T], boundary: datetime, embargo: timedelta) -> tuple[T, ...]:
    return apply_embargo(purge_outcomes(rows, boundary), boundary, embargo)


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
