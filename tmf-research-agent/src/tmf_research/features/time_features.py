from __future__ import annotations

from datetime import datetime

from tmf_research.features.definitions import FeatureContext


def time_features(decision_time: datetime, context: FeatureContext) -> dict[str, float]:
    return {
        "session_day": float(context.session == "DAY"),
        "session_night": float(context.session == "NIGHT"),
        "minutes_from_session_open": (decision_time - context.session_start).total_seconds() / 60.0,
        "minutes_to_session_close": (context.session_end - decision_time).total_seconds() / 60.0,
        "days_to_expiry": float((context.expiry_date - context.trading_date).days),
        "is_rollover_day": float(context.is_rollover_day),
    }
