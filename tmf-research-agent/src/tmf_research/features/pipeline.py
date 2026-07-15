from __future__ import annotations

from datetime import timedelta

from tmf_research.features.basis import basis_features
from tmf_research.features.definitions import FeatureContext, FeatureManifest, FeatureRow
from tmf_research.features.orderbook import book
from tmf_research.features.orderflow import flow
from tmf_research.features.price import candle_ratios, consecutive_up, ema, returns
from tmf_research.features.structure import structure_features
from tmf_research.features.time_features import time_features
from tmf_research.features.volatility import volatility_features
from tmf_research.features.volume import vwap
from tmf_research.processing.bars import Bar
from tmf_research.processing.one_second import OneSecondState


class FeaturePipeline:
    def __init__(self, manifest: FeatureManifest) -> None:
        self._manifest = manifest

    def compute(
        self,
        *,
        bars: tuple[Bar, ...],
        states: tuple[OneSecondState, ...],
        decision_time: object,
        context: FeatureContext,
    ) -> FeatureRow:
        from datetime import datetime

        if not isinstance(decision_time, datetime):
            raise TypeError("decision_time must be datetime")
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        if context.forbidden_transforms:
            raise ValueError("centered windows, backward fill, and global transforms are forbidden")
        eligible = tuple(sorted((bar for bar in bars if bar.bar_end <= decision_time), key=lambda item: item.bar_end))
        ending = tuple(bar for bar in eligible if bar.bar_end == decision_time)
        if ending and not ending[-1].is_complete:
            raise ValueError("incomplete decision bar cannot produce features")
        complete = tuple(bar for bar in eligible if bar.is_complete)
        if not complete:
            raise ValueError("at least one complete bar is required")
        causal_states = tuple(sorted((state for state in states if state.second + timedelta(seconds=1) <= decision_time), key=lambda item: item.second))
        latest = complete[-1]
        closes = tuple(bar.close for bar in complete if bar.close is not None)
        latest_close = latest.close
        values: dict[str, float | None] = {}
        values["return_1m"] = returns(closes, 1)
        values["return_5m"] = returns(closes, 5)
        ema5 = ema(closes, 5)
        ema20 = ema(closes, 20)
        values["ema_distance_5"] = latest_close - ema5 if latest_close is not None and ema5 is not None else None
        values["ema_distance_20"] = latest_close - ema20 if latest_close is not None and ema20 is not None else None
        values["consecutive_up_bars"] = consecutive_up(complete)
        body, upper = candle_ratios(latest)
        values["body_to_range_ratio"] = body
        values["upper_wick_ratio"] = upper
        session_vwap = vwap(complete)
        rolling_vwap = vwap(complete[-5:])
        values["session_vwap"] = session_vwap
        values["rolling_vwap_5m"] = rolling_vwap
        vol = volatility_features(complete)
        atr = vol["atr_5m"]
        values["price_to_session_vwap_atr"] = (latest_close - session_vwap) / atr if latest_close is not None and session_vwap is not None and atr not in (None, 0.0) else None
        older_vwap = vwap(complete[:-5]) if len(complete) > 5 else None
        values["vwap_slope_5m"] = session_vwap - older_vwap if session_vwap is not None and older_vwap is not None else None
        values.update(flow(causal_states, context.large_trade_threshold))
        values.update(book(causal_states))
        values.update(basis_features(causal_states))
        values.update(vol)
        values.update(structure_features(latest_close, atr, context))
        values.update(time_features(decision_time, context))
        primary_names = {item.name for item in self._manifest.primary_features}
        if set(values) != primary_names:
            raise ValueError("feature implementation does not match manifest")
        missing = {
            "underlying_missing": float(values["basis_points"] is None),
            "quote_missing": float(values["spread_points"] is None),
            "atr_missing": float(values["atr_5m"] is None),
            "previous_day_missing": float(values["distance_previous_close_atr"] is None),
            "night_range_missing": float(values["distance_night_high_atr"] is None),
        }
        evidence = max(
            latest.bar_end,
            causal_states[-1].second + timedelta(seconds=1) if causal_states else latest.bar_end,
        )
        return FeatureRow(
            feature_time=decision_time,
            decision_time=decision_time,
            evidence_available_at=evidence,
            feature_version=self._manifest.version,
            values=values,
            missing_indicators=missing,
        )

