from __future__ import annotations

from tmf_research.processing.one_second import OneSecondState


def book(states: tuple[OneSecondState, ...]) -> dict[str, float | None]:
    if not states:
        return {name: None for name in ("spread_points", "midpoint", "microprice", "microprice_minus_midpoint", "level1_book_imbalance", "level3_book_imbalance", "level5_book_imbalance")}
    latest = states[-1]
    valid = latest.bidask_available
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
        "level3_book_imbalance": latest.level3_imbalance if valid else None,
        "level5_book_imbalance": latest.level5_imbalance if valid else None,
    }

