from __future__ import annotations

import statistics

from tmf_research.processing.one_second import OneSecondState

_ZSCORE_WINDOW_SECONDS = 300


def basis_features(states: tuple[OneSecondState, ...]) -> dict[str, float | None]:
    values = tuple(item.basis for item in states if item.basis is not None)
    current = values[-1] if values else None
    latest_underlying = states[-1].underlying_price if states else None
    window = values[-_ZSCORE_WINDOW_SECONDS:]
    zscore = None
    if current is not None and len(window) > 1:
        mean = statistics.fmean(window)
        stdev = statistics.pstdev(window)
        zscore = (current - mean) / stdev if stdev > 0 else None
    return {
        "basis_points": current,
        "basis_change_10s": current - values[-11] if current is not None and len(values) > 10 else None,
        "basis_change_1m": current - values[-61] if current is not None and len(values) > 60 else None,
        "basis_pct": (
            current / latest_underlying
            if current is not None and latest_underlying is not None and latest_underlying != 0.0
            else None
        ),
        "basis_zscore_5m": zscore,
    }

