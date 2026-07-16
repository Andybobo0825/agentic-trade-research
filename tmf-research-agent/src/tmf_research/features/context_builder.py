from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from tmf_research.domain.sessions import SessionResolution, TradingCalendar, TradingDay
from tmf_research.features.definitions import FeatureContext
from tmf_research.processing.bars import Bar
from tmf_research.processing.one_second import OneSecondState


@dataclass(frozen=True, slots=True)
class ResearchBuildSpec:
    """Versioned, file-backed inputs used by the authoritative dataset issuer."""

    calendar: Path
    processing_version: str = "processing-v1"
    feature_version: str = "features-v1"
    label_version: str = "labels-v1"
    cost_points: float = 0.0
    requested_outer_folds: int = 5

    def __post_init__(self) -> None:
        calendar = self.calendar.resolve()
        if not calendar.is_file():
            raise FileNotFoundError(calendar)
        if any(not value.strip() for value in (
            self.processing_version, self.feature_version, self.label_version,
        )):
            raise ValueError("all build-stage versions are required")
        if self.cost_points < 0.0:
            raise ValueError("cost_points must be non-negative")
        if isinstance(self.requested_outer_folds, bool) or self.requested_outer_folds < 5:
            raise ValueError("at least five outer folds are required")
        object.__setattr__(self, "calendar", calendar)

    @property
    def calendar_hash(self) -> str:
        return hashlib.sha256(self.calendar.read_bytes()).hexdigest()

    @property
    def content_hash(self) -> str:
        payload = {
            "calendar_hash": self.calendar_hash,
            "processing_version": self.processing_version,
            "feature_version": self.feature_version,
            "label_version": self.label_version,
            "cost_points": self.cost_points,
            "requested_outer_folds": self.requested_outer_folds,
        }
        return hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()

    def trading_calendar(self) -> TradingCalendar:
        payload = json.loads(self.calendar.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("calendar must be a JSON object")
        timezone = str(payload.get("timezone", ""))
        zone = ZoneInfo(timezone)
        raw_days = payload.get("days")
        if not isinstance(raw_days, list) or not raw_days:
            raise ValueError("calendar requires explicit trading days")
        days = []
        for raw in raw_days:
            if not isinstance(raw, dict):
                raise ValueError("calendar day must be an object")
            trading_date = date.fromisoformat(str(raw["trading_date"]))
            night_open = _optional_datetime(raw.get("night_open"), zone)
            night_close = _optional_datetime(raw.get("night_close"), zone)
            days.append(TradingDay(
                trading_date=trading_date,
                day_open=time.fromisoformat(str(raw["day_open"])),
                day_close=time.fromisoformat(str(raw["day_close"])),
                night_open=night_open,
                night_close=night_close,
                is_expiry=bool(raw.get("is_expiry", False)),
            ))
        return TradingCalendar(
            version=str(payload["version"]), timezone=timezone, days=tuple(days),
        )


def build_feature_context(
    resolution: SessionResolution,
    *,
    prior_bars: tuple[Bar, ...],
    prior_states: tuple[OneSecondState, ...],
) -> FeatureContext:
    if (
        resolution.session not in ("DAY", "NIGHT")
        or resolution.trading_date is None
        or resolution.session_start is None
        or resolution.session_end is None
    ):
        raise ValueError("feature context requires an open resolved session")
    closes = tuple(bar.close for bar in prior_bars if bar.close is not None)
    highs = tuple(bar.high for bar in prior_bars if bar.high is not None)
    lows = tuple(bar.low for bar in prior_bars if bar.low is not None)
    volumes = sorted(
        state.volume for state in prior_states if state.volume > 0
    )
    threshold = volumes[max(0, int(len(volumes) * 0.9) - 1)] if volumes else 1
    return FeatureContext(
        session=resolution.session,
        session_start=resolution.session_start,
        session_end=resolution.session_end,
        trading_date=resolution.trading_date,
        expiry_date=resolution.trading_date if resolution.is_expiry else resolution.trading_date + timedelta(days=365),
        is_rollover_day=False,
        previous_day_high=max(highs) if highs else None,
        previous_day_low=min(lows) if lows else None,
        previous_close=closes[-1] if closes else None,
        night_high=None,
        night_low=None,
        opening_range_high=None,
        opening_range_low=None,
        large_trade_threshold=int(threshold),
        large_trade_threshold_fit_end=resolution.session_start - timedelta(microseconds=1),
    )


def _optional_datetime(value: object, zone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)
