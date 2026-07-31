from __future__ import annotations

from tmf_research.processing.bars import Bar


def returns(closes: tuple[float, ...], periods: int) -> float | None:
    if len(closes) <= periods or closes[-periods - 1] == 0:
        return None
    return closes[-1] / closes[-periods - 1] - 1.0


def ema(values: tuple[float, ...], span: int) -> float | None:
    if not values:
        return None
    alpha = 2.0 / (span + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def consecutive_up(bars: tuple[Bar, ...]) -> float:
    count = 0
    for item in reversed(bars):
        if item.open is None or item.close is None or item.close <= item.open:
            break
        count += 1
    return float(count)


def candle_ratios(bar: Bar) -> float | None:
    if None in (bar.open, bar.high, bar.low, bar.close):
        return None
    assert bar.open is not None and bar.high is not None and bar.low is not None and bar.close is not None
    width = bar.high - bar.low
    if width <= 0:
        return 0.0
    return abs(bar.close - bar.open) / width

