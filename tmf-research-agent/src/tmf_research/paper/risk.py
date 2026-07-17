from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from tmf_research.domain.paper_trades import (
    PaperCostConfig,
    PaperExitReason,
    PaperPosition,
    PaperQuote,
)


ENTRY_REJECTION_REASONS: tuple[str, ...] = (
    "BIDASK_MISSING",
    "BIDASK_STALE",
    "SPREAD_LIMIT_EXCEEDED",
    "DATA_QUALITY_INVALID",
    "MODEL_INCOMPATIBLE",
    "FEATURES_MISSING",
    "POSITION_ALREADY_OPEN",
    "ROLLOVER_IN_PROGRESS",
    "SESSION_ENDED",
    "COST_CONFIG_INCOMPLETE",
)


@dataclass(frozen=True, slots=True)
class EntryConditions:
    """Everything SPEC 34.1 requires a paper entry to verify, as values."""

    quote: PaperQuote | None
    quote_age_limit_ms: int
    spread_limit_points: float
    data_quality_valid: bool
    model_compatible: bool
    features_complete: bool
    position_open: bool
    rollover_in_progress: bool
    session_ending: bool
    cost_config: PaperCostConfig

    def __post_init__(self) -> None:
        if isinstance(self.quote_age_limit_ms, bool) or self.quote_age_limit_ms <= 0:
            raise ValueError("quote age limit must be a positive millisecond count")
        if (
            isinstance(self.spread_limit_points, bool)
            or not isinstance(self.spread_limit_points, (int, float))
            or not math.isfinite(self.spread_limit_points)
            or self.spread_limit_points <= 0.0
        ):
            raise ValueError("spread limit must be finite and positive")


def evaluate_entry(conditions: EntryConditions) -> tuple[str, ...]:
    """Return every SPEC 34.1 rejection reason in fixed order; empty permits."""

    reasons: list[str] = []
    if conditions.quote is None:
        reasons.append("BIDASK_MISSING")
    else:
        if conditions.quote.age_ms > conditions.quote_age_limit_ms:
            reasons.append("BIDASK_STALE")
        if conditions.quote.spread_points > conditions.spread_limit_points:
            reasons.append("SPREAD_LIMIT_EXCEEDED")
    if not conditions.data_quality_valid:
        reasons.append("DATA_QUALITY_INVALID")
    if not conditions.model_compatible:
        reasons.append("MODEL_INCOMPATIBLE")
    if not conditions.features_complete:
        reasons.append("FEATURES_MISSING")
    if conditions.position_open:
        reasons.append("POSITION_ALREADY_OPEN")
    if conditions.rollover_in_progress:
        reasons.append("ROLLOVER_IN_PROGRESS")
    if conditions.session_ending:
        reasons.append("SESSION_ENDED")
    if not conditions.cost_config.complete:
        reasons.append("COST_CONFIG_INCOMPLETE")
    return tuple(reasons)


@dataclass(frozen=True, slots=True)
class ExitObservation:
    """One completed-bar observation used to evaluate SPEC 34.2 exits."""

    observed_at: datetime
    bar_high: float
    bar_low: float
    quote: PaperQuote | None
    quote_age_limit_ms: int
    rollover_in_progress: bool
    tick_prices: tuple[tuple[datetime, float], ...] = ()

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        for name, value in (("bar_high", self.bar_high), ("bar_low", self.bar_low)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite")
        if self.bar_high < self.bar_low:
            raise ValueError("bar range is inverted")
        if isinstance(self.quote_age_limit_ms, bool) or self.quote_age_limit_ms <= 0:
            raise ValueError("quote age limit must be a positive millisecond count")
        previous: datetime | None = None
        for tick_time, tick_price in self.tick_prices:
            if tick_time.tzinfo is None or tick_time.utcoffset() is None:
                raise ValueError("tick times must be timezone-aware")
            if not math.isfinite(tick_price):
                raise ValueError("tick prices must be finite")
            if previous is not None and tick_time < previous:
                raise ValueError("tick prices must be in time order")
            previous = tick_time


def evaluate_exit(
    position: PaperPosition,
    observation: ExitObservation,
) -> PaperExitReason | None:
    """Apply the fixed SPEC 34.2 exit priority to one observation."""

    if position.direction == "LONG":
        stop_touched = observation.bar_low <= position.stop_price
        target_touched = observation.bar_high >= position.target_price
    else:
        stop_touched = observation.bar_high >= position.stop_price
        target_touched = observation.bar_low <= position.target_price
    if stop_touched and target_touched:
        resolved = _first_barrier_touch(position, observation.tick_prices)
        return "STOP_LOSS" if resolved is None else resolved
    if stop_touched:
        return "STOP_LOSS"
    if target_touched:
        return "PROFIT_TARGET"
    if observation.observed_at >= position.vertical_deadline:
        return "VERTICAL_BARRIER"
    if observation.observed_at >= position.session_end:
        return "SESSION_END"
    if (
        observation.quote is None
        or observation.quote.age_ms > observation.quote_age_limit_ms
    ):
        return "DATA_STALE"
    if observation.rollover_in_progress:
        return "ROLLOVER"
    return None


def _first_barrier_touch(
    position: PaperPosition,
    tick_prices: tuple[tuple[datetime, float], ...],
) -> PaperExitReason | None:
    for _tick_time, price in tick_prices:
        if position.direction == "LONG":
            if price <= position.stop_price:
                return "STOP_LOSS"
            if price >= position.target_price:
                return "PROFIT_TARGET"
        else:
            if price >= position.stop_price:
                return "STOP_LOSS"
            if price <= position.target_price:
                return "PROFIT_TARGET"
    return None
