from __future__ import annotations

from tmf_research.processing.one_second import OneSecondState


def book(states: tuple[OneSecondState, ...]) -> dict[str, float | None]:
    if not states:
        return {name: None for name in ("spread_points", "midpoint", "microprice", "microprice_minus_midpoint", "level1_book_imbalance", "quote_update_rate")}
    latest = states[-1]
    valid = latest.bidask_available
    updates = sum(item.last_bidask_at != states[index - 1].last_bidask_at for index, item in enumerate(states[-30:], start=max(0, len(states) - 30)) if index > 0)
    return {
        "spread_points": latest.spread if valid else None,
        "midpoint": latest.midpoint if valid else None,
        "microprice": latest.microprice if valid else None,
        "microprice_minus_midpoint": (
            latest.microprice - latest.midpoint
            if valid and latest.microprice is not None and latest.midpoint is not None
            else None
        ),
        "level1_book_imbalance": latest.level1_imbalance if valid else None,
        "quote_update_rate": float(updates) / min(len(states), 30) if states else None,
    }

