from __future__ import annotations

from tmf_research.features.definitions import FeatureContext
from tmf_research.processing.bars import Bar


def structure_features(bars: tuple[Bar, ...], atr: float | None, context: FeatureContext) -> dict[str, float | None]:
    price = bars[-1].close if bars else None
    def distance(level: float | None) -> float | None:
        return (
            (price - level) / atr
            if price is not None and level is not None and atr is not None and atr != 0.0
            else None
        )

    previous_high_distance = distance(context.previous_day_high)
    false_breakout = (
        float(
            price <= context.previous_day_high
            and any(
                item.high is not None and item.high > context.previous_day_high
                for item in bars
            )
        )
        if price is not None and context.previous_day_high is not None
        else None
    )
    return {
        "distance_previous_day_high_atr": previous_high_distance,
        "distance_previous_day_low_atr": distance(context.previous_day_low),
        "distance_previous_close_atr": distance(context.previous_close),
        "distance_night_high_atr": distance(context.night_high),
        "break_previous_high": float(price > context.previous_day_high) if price is not None and context.previous_day_high is not None else None,
        "false_breakout_high": false_breakout,
    }
