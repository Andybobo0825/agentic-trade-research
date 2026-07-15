from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from tmf_research.labeling.executable_prices import ExecutablePricePolicy
from tmf_research.processing.bars import Bar
from tmf_research.processing.one_second import OneSecondState


Label = Literal["LONG", "SHORT", "NO_TRADE", "AMBIGUOUS"]


@dataclass(frozen=True, slots=True)
class LabelParameters:
    version: str
    fit_start: datetime
    fit_end: datetime
    target_atr_multiplier: float
    stop_atr_multiplier: float
    minimum_target_points: float
    minimum_stop_points: float
    horizon_minutes: int
    selected_scope: str = "TRAIN_INNER"

    def __post_init__(self) -> None:
        _require_aware(self.fit_start, "fit_start")
        _require_aware(self.fit_end, "fit_end")
        if self.fit_end <= self.fit_start:
            raise ValueError("fit interval must be positive")
        if self.selected_scope != "TRAIN_INNER":
            raise ValueError("label parameters must be selected in TRAIN_INNER")
        if self.horizon_minutes not in (5, 15, 60):
            raise ValueError("horizon must be 5, 15, or 60 minutes")
        if min(
            self.target_atr_multiplier,
            self.stop_atr_multiplier,
            self.minimum_target_points,
            self.minimum_stop_points,
        ) < 0:
            raise ValueError("barrier values cannot be negative")


@dataclass(frozen=True, slots=True)
class LabelRecord:
    candidate_id: str
    decision_time: datetime
    evidence_available_at: datetime
    outcome_time: datetime
    horizon: str
    entry_bid: float
    entry_ask: float
    entry_spread: float
    atr_at_entry: float
    upper_barrier: float
    lower_barrier: float
    vertical_barrier: datetime
    label: Label
    first_touch: str
    maximum_favorable_excursion: float
    maximum_adverse_excursion: float
    estimated_cost: float
    label_version: str
    parameter_fit_start: datetime
    parameter_fit_end: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.evidence_available_at < self.decision_time:
            raise ValueError("label evidence cannot precede decision")
        payload = {
            name: getattr(self, name).isoformat() if isinstance(getattr(self, name), datetime) else getattr(self, name)
            for name in (
                "candidate_id", "decision_time", "evidence_available_at", "outcome_time", "horizon",
                "entry_bid", "entry_ask", "entry_spread", "atr_at_entry", "upper_barrier", "lower_barrier",
                "vertical_barrier", "label", "first_touch", "maximum_favorable_excursion",
                "maximum_adverse_excursion", "estimated_cost", "label_version", "parameter_fit_start",
                "parameter_fit_end",
            )
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        object.__setattr__(self, "content_hash", hashlib.sha256(encoded).hexdigest())

    @property
    def training_eligible(self) -> bool:
        return self.label != "AMBIGUOUS"


class TripleBarrierLabeler:
    def __init__(self, *, price_policy: ExecutablePricePolicy) -> None:
        self._price_policy = price_policy

    def label(
        self,
        *,
        candidate_id: str,
        decision_time: datetime,
        entry_state: OneSecondState,
        future_bars: tuple[Bar, ...],
        atr: float,
        parameters: LabelParameters,
    ) -> LabelRecord:
        _require_aware(decision_time, "decision_time")
        if parameters.fit_end > decision_time:
            raise ValueError("label parameter fit interval must end before decision")
        if atr <= 0:
            raise ValueError("atr must be positive")
        quote = self._price_policy.snapshot(entry_state)
        target = max(parameters.target_atr_multiplier * atr, parameters.minimum_target_points)
        stop = max(parameters.stop_atr_multiplier * atr, parameters.minimum_stop_points)
        upper = quote.ask + target
        lower = quote.bid - stop
        vertical = decision_time + timedelta(minutes=parameters.horizon_minutes)
        eligible = tuple(
            sorted(
                (
                    bar
                    for bar in future_bars
                    if bar.is_complete
                    and bar.bar_start >= decision_time
                    and bar.bar_end <= vertical
                ),
                key=lambda item: (item.bar_end, item.bar_start),
            )
        )
        label: Label = "NO_TRADE"
        first_touch = "VERTICAL"
        outcome_time = vertical
        inspected: list[Bar] = []
        for bar in eligible:
            expected_start = decision_time + timedelta(minutes=len(inspected))
            if bar.bar_start != expected_start:
                raise ValueError("label horizon has incomplete bars")
            inspected.append(bar)
            touches_upper = bar.high is not None and bar.high >= upper
            touches_lower = bar.low is not None and bar.low <= lower
            if touches_upper and touches_lower:
                label, first_touch, outcome_time = "AMBIGUOUS", "BOTH", bar.bar_end
                break
            if touches_upper:
                label, first_touch, outcome_time = "LONG", "UPPER", bar.bar_end
                break
            if touches_lower:
                label, first_touch, outcome_time = "SHORT", "LOWER", bar.bar_end
                break
        if first_touch == "VERTICAL" and len(inspected) != parameters.horizon_minutes:
            raise ValueError("label horizon has incomplete bars")
        highs = tuple(bar.high for bar in inspected if bar.high is not None)
        lows = tuple(bar.low for bar in inspected if bar.low is not None)
        mfe = max((value - quote.ask for value in highs), default=0.0)
        mae = max((quote.bid - value for value in lows), default=0.0)
        return LabelRecord(
            candidate_id=candidate_id,
            decision_time=decision_time,
            evidence_available_at=outcome_time,
            outcome_time=outcome_time,
            horizon=f"{parameters.horizon_minutes}m",
            entry_bid=quote.bid,
            entry_ask=quote.ask,
            entry_spread=quote.spread,
            atr_at_entry=atr,
            upper_barrier=upper,
            lower_barrier=lower,
            vertical_barrier=vertical,
            label=label,
            first_touch=first_touch,
            maximum_favorable_excursion=max(0.0, mfe),
            maximum_adverse_excursion=max(0.0, mae),
            estimated_cost=quote.spread + self._price_policy.estimated_round_trip_cost,
            label_version=parameters.version,
            parameter_fit_start=parameters.fit_start,
            parameter_fit_end=parameters.fit_end,
        )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
