from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass


ABLATION_GROUPS = (
    "PRICE",
    "VWAP",
    "ORDER_FLOW",
    "ORDER_BOOK",
    "BASIS",
    "VOLATILITY",
    "MARKET_STRUCTURE",
    "TIME",
)


@dataclass(frozen=True, slots=True)
class AblationFoldResult:
    fold_id: str
    log_loss: float
    brier_score: float
    net_ev: float
    trade_count: int
    maximum_drawdown: float

    def __post_init__(self) -> None:
        if not self.fold_id.strip() or any(
            not math.isfinite(value)
            for value in (self.log_loss, self.brier_score, self.net_ev, self.maximum_drawdown)
        ) or self.trade_count < 0:
            raise ValueError("invalid ablation fold result")


@dataclass(frozen=True, slots=True)
class AblationResult:
    removed_group: str
    folds: tuple[AblationFoldResult, ...]
    fold_stability: float

    def __post_init__(self) -> None:
        if self.removed_group not in ABLATION_GROUPS or not self.folds or not 0.0 <= self.fold_stability <= 1.0:
            raise ValueError("invalid ablation result")


def require_complete_ablations(results: Sequence[AblationResult]) -> tuple[AblationResult, ...]:
    if tuple(sorted(result.removed_group for result in results)) != tuple(sorted(ABLATION_GROUPS)):
        raise ValueError("all eight feature-group ablations are mandatory")
    return tuple(sorted(results, key=lambda result: ABLATION_GROUPS.index(result.removed_group)))


def run_all_ablations(evaluate_without: Callable[[str], AblationResult]) -> tuple[AblationResult, ...]:
    results = tuple(evaluate_without(group) for group in ABLATION_GROUPS)
    if any(result.removed_group != group for result, group in zip(results, ABLATION_GROUPS, strict=True)):
        raise ValueError("ablation evaluator must report the exact removed feature group")
    return require_complete_ablations(results)
