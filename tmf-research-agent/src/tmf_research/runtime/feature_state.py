from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType


class BarSequenceError(ValueError):
    """Raised when more than one inference targets the same completed bar."""


@dataclass(frozen=True, slots=True)
class RuntimeFeatureVector:
    """Point-in-time features for exactly one completed one-minute bar."""

    bar_close_time: datetime
    evidence_available_at: datetime
    feature_version: str
    values: Mapping[str, float | None] = field(hash=False)

    def __post_init__(self) -> None:
        for name in ("bar_close_time", "evidence_available_at"):
            value: datetime = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.evidence_available_at > self.bar_close_time:
            raise ValueError("feature evidence cannot postdate the bar close")
        if not self.feature_version.strip():
            raise ValueError("feature_version is required")
        for name, value_item in self.values.items():
            if not name.strip():
                raise ValueError("feature names are required")
            if value_item is not None and (
                isinstance(value_item, bool) or not math.isfinite(value_item)
            ):
                raise ValueError("feature values must be finite or missing")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


class BarCloseGate:
    """Admits exactly one strictly-later inference per completed bar."""

    __slots__ = ("_last_bar_close",)

    def __init__(self) -> None:
        self._last_bar_close: datetime | None = None

    def admit(self, vector: RuntimeFeatureVector) -> RuntimeFeatureVector:
        if (
            self._last_bar_close is not None
            and vector.bar_close_time <= self._last_bar_close
        ):
            raise BarSequenceError(
                "one inference per completed bar: "
                f"{vector.bar_close_time.isoformat()} is not after "
                f"{self._last_bar_close.isoformat()}"
            )
        self._last_bar_close = vector.bar_close_time
        return vector
