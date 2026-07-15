from __future__ import annotations

from tmf_research.processing.one_second import OneSecondState


def basis_features(states: tuple[OneSecondState, ...]) -> dict[str, float | None]:
    values = tuple(item.basis for item in states if item.basis is not None)
    current = values[-1] if values else None
    return {
        "basis_points": current,
        "basis_change_10s": current - values[-11] if current is not None and len(values) > 10 else None,
        "basis_change_1m": current - values[-61] if current is not None and len(values) > 60 else None,
    }

