from __future__ import annotations

import math

from tmf_research.processing.bars import Bar


def true_range(bar: Bar, previous_close: float | None) -> float | None:
    if bar.high is None or bar.low is None:
        return None
    if previous_close is None:
        return bar.high - bar.low
    return max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))


def volatility_features(bars: tuple[Bar, ...]) -> dict[str, float | None]:
    ranges = tuple(true_range(bar, bars[index - 1].close if index else None) for index, bar in enumerate(bars))
    valid_ranges = tuple(value for value in ranges if value is not None)
    atr = sum(valid_ranges[-5:]) / min(len(valid_ranges), 5) if valid_ranges else None
    closes = tuple(bar.close for bar in bars if bar.close is not None)
    rets = tuple(closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes)) if closes[index - 1] != 0)
    recent = rets[-5:]
    realized = math.sqrt(sum(value * value for value in recent)) if recent else None
    current = valid_ranges[-1] if valid_ranges else None
    baseline = sum(valid_ranges[-6:-1]) / len(valid_ranges[-6:-1]) if len(valid_ranges) > 1 else None
    return {
        "true_range_1m": current,
        "atr_5m": atr,
        "realized_vol_5m": realized,
        "range_expansion_ratio": (
            current / baseline
            if current is not None and baseline is not None and baseline != 0.0
            else None
        ),
    }
