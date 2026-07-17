from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    name: str
    group: str
    mechanism: str


@dataclass(frozen=True, slots=True)
class MissingIndicatorDefinition:
    name: str
    source_feature: str


@dataclass(frozen=True, slots=True)
class InteractionDefinition:
    name: str
    inputs: tuple[str, str]
    mechanism: str


@dataclass(frozen=True, slots=True)
class RedundancyMetadata:
    scope: str = "TRAIN_ONLY"
    correlation_threshold: float = 0.90
    selection_order: tuple[str, ...] = (
        "COMPLETENESS",
        "SIMPLICITY",
        "CROSS_FOLD_STABILITY",
    )


@dataclass(frozen=True, slots=True)
class FeatureManifest:
    version: str
    primary_features: tuple[FeatureDefinition, ...]
    missing_indicators: tuple[MissingIndicatorDefinition, ...]
    formal_features: tuple[str, ...]
    interactions: tuple[InteractionDefinition, ...]
    redundancy: RedundancyMetadata = RedundancyMetadata()
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("feature manifest version is required")
        if len(self.primary_features) > 40:
            raise ValueError("feature manifest cannot exceed 40 primary features")
        if len(self.missing_indicators) > 10:
            raise ValueError("feature manifest cannot exceed 10 missing indicators")
        if len(self.formal_features) > 30:
            raise ValueError("formal feature set cannot exceed 30 primary features")
        if len(self.interactions) > 5:
            raise ValueError("formal feature set cannot exceed 5 interactions")
        primary_names = tuple(item.name for item in self.primary_features)
        if len(primary_names) != len(set(primary_names)):
            raise ValueError("primary feature names must be unique")
        if not set(self.formal_features).issubset(primary_names):
            raise ValueError("formal features must be primary candidates")
        payload = {
            "version": self.version,
            "primary_features": [
                {"name": item.name, "group": item.group, "mechanism": item.mechanism}
                for item in self.primary_features
            ],
            "missing_indicators": [
                {"name": item.name, "source_feature": item.source_feature}
                for item in self.missing_indicators
            ],
            "formal_features": list(self.formal_features),
            "interactions": [
                {"name": item.name, "inputs": list(item.inputs), "mechanism": item.mechanism}
                for item in self.interactions
            ],
            "redundancy": {
                "scope": self.redundancy.scope,
                "correlation_threshold": self.redundancy.correlation_threshold,
                "selection_order": list(self.redundancy.selection_order),
            },
        }
        object.__setattr__(self, "content_hash", _hash(payload))


@dataclass(frozen=True, slots=True)
class FeatureContext:
    session: str
    session_start: datetime
    session_end: datetime
    trading_date: date
    expiry_date: date
    is_rollover_day: bool
    previous_day_high: float | None
    previous_day_low: float | None
    previous_close: float | None
    night_high: float | None
    night_low: float | None
    opening_range_high: float | None
    opening_range_low: float | None
    large_trade_threshold: int
    large_trade_threshold_fit_end: datetime
    forbidden_transforms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_aware(self.session_start, "session_start")
        _require_aware(self.session_end, "session_end")
        _require_aware(self.large_trade_threshold_fit_end, "large_trade_threshold_fit_end")
        if self.session not in ("DAY", "NIGHT"):
            raise ValueError("feature context requires DAY or NIGHT session")
        if self.large_trade_threshold < 0:
            raise ValueError("large_trade_threshold cannot be negative")


@dataclass(frozen=True, slots=True)
class FeatureRow:
    feature_time: datetime
    decision_time: datetime
    evidence_available_at: datetime
    feature_version: str
    values: Mapping[str, float | None]
    missing_indicators: Mapping[str, float]
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("feature_time", self.feature_time),
            ("decision_time", self.decision_time),
            ("evidence_available_at", self.evidence_available_at),
        ):
            _require_aware(value, name)
        if self.evidence_available_at > self.decision_time:
            raise ValueError("evidence_available_at cannot exceed decision_time")
        if self.feature_time > self.decision_time:
            raise ValueError("feature_time cannot exceed decision_time")
        frozen_values = MappingProxyType(dict(self.values))
        frozen_missing = MappingProxyType(dict(self.missing_indicators))
        object.__setattr__(self, "values", frozen_values)
        object.__setattr__(self, "missing_indicators", frozen_missing)
        object.__setattr__(
            self,
            "content_hash",
            _hash(
                {
                    "feature_time": self.feature_time.isoformat(),
                    "decision_time": self.decision_time.isoformat(),
                    "evidence_available_at": self.evidence_available_at.isoformat(),
                    "feature_version": self.feature_version,
                    "values": dict(sorted(frozen_values.items())),
                    "missing_indicators": dict(sorted(frozen_missing.items())),
                }
            ),
        )


def default_feature_manifest() -> FeatureManifest:
    grouped: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("price", ("return_1m", "return_5m", "ema_distance_5", "consecutive_up_bars", "body_to_range_ratio", "upper_wick_ratio")),
        ("vwap", ("session_vwap", "rolling_vwap_5m", "price_to_session_vwap_atr", "vwap_slope_5m")),
        ("flow", ("aggressive_buy_volume_10s", "aggressive_sell_volume_10s", "trade_imbalance_10s", "unknown_trade_ratio", "large_trade_ratio")),
        ("orderbook", ("spread_points", "midpoint", "microprice", "microprice_minus_midpoint", "level1_book_imbalance", "quote_update_rate")),
        ("basis", ("basis_points", "basis_change_10s", "basis_change_1m")),
        ("volatility", ("true_range_1m", "atr_5m", "realized_vol_5m", "range_expansion_ratio")),
        ("structure", ("distance_previous_day_high_atr", "distance_previous_day_low_atr", "distance_previous_close_atr", "distance_night_high_atr", "break_previous_high", "false_breakout_high")),
        ("time", ("session_day", "session_night", "minutes_from_session_open", "minutes_to_session_close", "days_to_expiry", "is_rollover_day")),
    )
    definitions = tuple(
        FeatureDefinition(name=name, group=group, mechanism=f"{group} market mechanism")
        for group, names in grouped
        for name in names
    )
    missing = (
        MissingIndicatorDefinition("underlying_missing", "basis_points"),
        MissingIndicatorDefinition("quote_missing", "spread_points"),
        MissingIndicatorDefinition("atr_missing", "atr_5m"),
        MissingIndicatorDefinition("previous_day_missing", "distance_previous_close_atr"),
        MissingIndicatorDefinition("night_range_missing", "distance_night_high_atr"),
    )
    return FeatureManifest(
        version="phase3-features-v1",
        primary_features=definitions,
        missing_indicators=missing,
        formal_features=(
            "return_1m", "return_5m", "ema_distance_5", "consecutive_up_bars",
            "body_to_range_ratio", "session_vwap", "rolling_vwap_5m",
            "price_to_session_vwap_atr", "vwap_slope_5m",
            "aggressive_buy_volume_10s", "aggressive_sell_volume_10s",
            "trade_imbalance_10s", "large_trade_ratio", "spread_points",
            "midpoint", "microprice", "microprice_minus_midpoint",
            "basis_points", "basis_change_10s", "basis_change_1m",
            "true_range_1m", "atr_5m", "realized_vol_5m",
            "range_expansion_ratio", "distance_previous_day_high_atr",
            "distance_previous_day_low_atr", "session_day",
            "minutes_from_session_open", "minutes_to_session_close", "days_to_expiry",
        ),
        interactions=(
            InteractionDefinition("return_x_flow", ("return_1m", "trade_imbalance_10s"), "momentum confirmed by aggressive flow"),
            InteractionDefinition("spread_x_volatility", ("spread_points", "atr_5m"), "liquidity under volatility"),
        ),
    )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
