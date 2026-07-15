from __future__ import annotations

from tmf_research.processing.bars import Bar


def vwap(bars: tuple[Bar, ...]) -> float | None:
    weighted = sum((bar.vwap or 0.0) * bar.volume for bar in bars if bar.vwap is not None)
    volume = sum(bar.volume for bar in bars if bar.vwap is not None)
    return weighted / volume if volume > 0 else None

