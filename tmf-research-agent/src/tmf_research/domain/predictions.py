from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


SCHEMA_VERSION = "1.1.0"
POINT_VALUE_NTD = 10
Signal = Literal["LONG", "SHORT", "NO_TRADE"]
SIGNALS: tuple[Signal, ...] = ("LONG", "SHORT", "NO_TRADE")


def _require_finite(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be finite")


def _require_text(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} is required")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class InstrumentBlock:
    category: str
    alias_code: str
    target_code: str
    delivery_month: str
    delivery_date: str
    point_value_ntd: int = field(default=POINT_VALUE_NTD, init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("category", self.category), ("alias_code", self.alias_code),
            ("target_code", self.target_code),
            ("delivery_month", self.delivery_month),
            ("delivery_date", self.delivery_date),
        ):
            _require_text(value, name)


@dataclass(frozen=True, slots=True)
class SessionBlock:
    type: Literal["DAY", "NIGHT"]
    trading_date: str
    minutes_from_open: int
    minutes_to_close: int

    def __post_init__(self) -> None:
        if self.type not in ("DAY", "NIGHT"):
            raise ValueError("session type must be DAY or NIGHT")
        _require_text(self.trading_date, "trading_date")
        for name, value in (
            ("minutes_from_open", self.minutes_from_open),
            ("minutes_to_close", self.minutes_to_close),
        ):
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class MarketBlock:
    last_price: float
    bid_price_1: float
    ask_price_1: float
    spread_points: float
    underlying_price: float | None
    basis_points: float | None
    session_vwap: float
    atr_15m: float

    def __post_init__(self) -> None:
        for name, value in (
            ("last_price", self.last_price), ("bid_price_1", self.bid_price_1),
            ("ask_price_1", self.ask_price_1),
            ("spread_points", self.spread_points),
            ("session_vwap", self.session_vwap), ("atr_15m", self.atr_15m),
        ):
            _require_finite(value, name)
        for name, optional in (
            ("underlying_price", self.underlying_price),
            ("basis_points", self.basis_points),
        ):
            if optional is not None:
                _require_finite(optional, name)
        if self.spread_points < 0.0:
            raise ValueError("spread_points must be non-negative")


@dataclass(frozen=True, slots=True)
class ProbabilityBlock:
    long: float
    short: float
    no_trade: float

    def __post_init__(self) -> None:
        for value in (self.long, self.short, self.no_trade):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0.0
                or value > 1.0
            ):
                raise ValueError("probability must be between zero and one")
        if abs(self.long + self.short + self.no_trade - 1.0) > 1e-9:
            raise ValueError("class probabilities must sum to one")


@dataclass(frozen=True, slots=True)
class PaperPlanBlock:
    enabled: bool
    direction: Literal["LONG", "SHORT"] | None
    quantity: int
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    maximum_holding_minutes: int

    def __post_init__(self) -> None:
        if isinstance(self.maximum_holding_minutes, bool) or self.maximum_holding_minutes < 0:
            raise ValueError("maximum holding minutes must be non-negative")
        if not self.enabled:
            if (
                self.direction is not None
                or self.quantity != 0
                or self.entry_price is not None
                or self.stop_price is not None
                or self.target_price is not None
            ):
                raise ValueError("disabled plans cannot carry execution values")
            return
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError("enabled plans require a direction")
        if self.quantity != 1:
            raise ValueError("plan quantity must be exactly one paper contract")
        if (
            self.entry_price is None
            or self.stop_price is None
            or self.target_price is None
        ):
            raise ValueError("enabled plans require entry, stop, and target prices")
        for name, value in (
            ("entry_price", self.entry_price), ("stop_price", self.stop_price),
            ("target_price", self.target_price),
        ):
            _require_finite(value, name)
        if self.direction == "LONG":
            if self.stop_price >= self.entry_price:
                raise ValueError("long stop price must fall below entry")
            if self.target_price <= self.entry_price:
                raise ValueError("long target price must rise above entry")
        else:
            if self.stop_price <= self.entry_price:
                raise ValueError("short stop price must rise above entry")
            if self.target_price >= self.entry_price:
                raise ValueError("short target price must fall below entry")
        if self.maximum_holding_minutes <= 0:
            raise ValueError("enabled plans require a positive holding window")


@dataclass(frozen=True, slots=True)
class QualityBlock:
    tick_age_ms: int
    bidask_age_ms: int
    data_stale: bool
    rollover: bool
    complete_features: bool
    allow_paper_trade: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("tick_age_ms", self.tick_age_ms),
            ("bidask_age_ms", self.bidask_age_ms),
        ):
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.allow_paper_trade and (
            self.data_stale or self.rollover or not self.complete_features
        ):
            raise ValueError("allow_paper_trade requires fresh complete evidence")


@dataclass(frozen=True, slots=True)
class ModelBlock:
    model_id: str
    model_version: str
    feature_version: str
    label_version: str
    training_end: str
    calibration_method: str

    def __post_init__(self) -> None:
        for name, value in (
            ("model_id", self.model_id), ("model_version", self.model_version),
            ("feature_version", self.feature_version),
            ("label_version", self.label_version),
            ("training_end", self.training_end),
            ("calibration_method", self.calibration_method),
        ):
            _require_text(value, name)


@dataclass(frozen=True, slots=True)
class TraceBlock:
    raw_checksum: str
    dataset_version: str
    experiment_id: str
    code_commit: str
    ledger_row_id: str | None

    def __post_init__(self) -> None:
        if len(self.raw_checksum) != 64 or any(
            character not in "0123456789abcdef" for character in self.raw_checksum
        ):
            raise ValueError("trace raw checksum must be a SHA-256 hex digest")
        for name, value in (
            ("dataset_version", self.dataset_version),
            ("experiment_id", self.experiment_id),
            ("code_commit", self.code_commit),
        ):
            _require_text(value, name)
        if self.ledger_row_id is not None:
            _require_text(self.ledger_row_id, "ledger_row_id")


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    """One immutable SPEC 36 prediction with full traceability."""

    prediction_id: str
    decision_time: datetime
    evidence_available_at: datetime
    instrument: InstrumentBlock
    session: SessionBlock
    market: MarketBlock
    probability: ProbabilityBlock
    signal: Signal
    paper_plan: PaperPlanBlock
    quality: QualityBlock
    model: ModelBlock
    reasons: tuple[str, ...]
    missing_features: tuple[str, ...]
    warnings: tuple[str, ...]
    trace: TraceBlock
    schema_version: str = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _require_text(self.prediction_id, "prediction_id")
        _require_aware(self.decision_time, "decision_time")
        _require_aware(self.evidence_available_at, "evidence_available_at")
        if self.evidence_available_at > self.decision_time:
            raise ValueError("evidence cannot postdate the decision")
        if self.signal not in SIGNALS:
            raise ValueError("signal must be LONG, SHORT, or NO_TRADE")
        if self.signal == "NO_TRADE" and self.paper_plan.enabled:
            raise ValueError("NO_TRADE forbids an enabled paper plan")
        if self.paper_plan.enabled:
            if self.paper_plan.direction != self.signal:
                raise ValueError("enabled plan direction must match the signal")
            if not self.quality.allow_paper_trade:
                raise ValueError("enabled plans require allow_paper_trade quality")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "predictionId": self.prediction_id,
            "decisionTime": self.decision_time.isoformat(),
            "evidenceAvailableAt": self.evidence_available_at.isoformat(),
            "instrument": {
                "category": self.instrument.category,
                "aliasCode": self.instrument.alias_code,
                "targetCode": self.instrument.target_code,
                "deliveryMonth": self.instrument.delivery_month,
                "deliveryDate": self.instrument.delivery_date,
                "pointValueNtd": self.instrument.point_value_ntd,
            },
            "session": {
                "type": self.session.type,
                "tradingDate": self.session.trading_date,
                "minutesFromOpen": self.session.minutes_from_open,
                "minutesToClose": self.session.minutes_to_close,
            },
            "market": {
                "lastPrice": self.market.last_price,
                "bidPrice1": self.market.bid_price_1,
                "askPrice1": self.market.ask_price_1,
                "spreadPoints": self.market.spread_points,
                "underlyingPrice": self.market.underlying_price,
                "basisPoints": self.market.basis_points,
                "sessionVwap": self.market.session_vwap,
                "atr15m": self.market.atr_15m,
            },
            "probability": {
                "long": self.probability.long,
                "short": self.probability.short,
                "noTrade": self.probability.no_trade,
            },
            "signal": self.signal,
            "paperPlan": {
                "enabled": self.paper_plan.enabled,
                "direction": self.paper_plan.direction,
                "quantity": self.paper_plan.quantity,
                "entryPrice": self.paper_plan.entry_price,
                "stopPrice": self.paper_plan.stop_price,
                "targetPrice": self.paper_plan.target_price,
                "maximumHoldingMinutes": self.paper_plan.maximum_holding_minutes,
            },
            "quality": {
                "tickAgeMs": self.quality.tick_age_ms,
                "bidAskAgeMs": self.quality.bidask_age_ms,
                "dataStale": self.quality.data_stale,
                "rollover": self.quality.rollover,
                "completeFeatures": self.quality.complete_features,
                "allowPaperTrade": self.quality.allow_paper_trade,
            },
            "model": {
                "modelId": self.model.model_id,
                "modelVersion": self.model.model_version,
                "featureVersion": self.model.feature_version,
                "labelVersion": self.model.label_version,
                "trainingEnd": self.model.training_end,
                "calibrationMethod": self.model.calibration_method,
            },
            "reasons": list(self.reasons),
            "missingFeatures": list(self.missing_features),
            "warnings": list(self.warnings),
            "trace": {
                "rawChecksum": self.trace.raw_checksum,
                "datasetVersion": self.trace.dataset_version,
                "experimentId": self.trace.experiment_id,
                "codeCommit": self.trace.code_commit,
                "ledgerRowId": self.trace.ledger_row_id,
            },
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_json_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
