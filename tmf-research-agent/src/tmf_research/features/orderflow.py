from __future__ import annotations

from tmf_research.processing.one_second import OneSecondState


def flow(states: tuple[OneSecondState, ...], threshold: int) -> dict[str, float | None]:
    window = states[-10:]
    buy = sum(item.buy_volume for item in window)
    sell = sum(item.sell_volume for item in window)
    unknown = sum(item.unknown_volume for item in window)
    total = buy + sell
    all_volume = total + unknown
    large = sum(item.volume for item in window if item.volume >= threshold)
    return {
        "aggressive_buy_volume_10s": float(buy),
        "aggressive_sell_volume_10s": float(sell),
        "trade_imbalance_10s": (buy - sell) / total if total > 0 else None,
        "unknown_trade_ratio": unknown / all_volume if all_volume > 0 else None,
        "large_trade_ratio": large / all_volume if all_volume > 0 else None,
    }

