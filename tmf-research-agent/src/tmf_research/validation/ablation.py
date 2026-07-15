from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


ABLATION_GROUPS = (
    "PRICE", "VWAP", "ORDER_FLOW", "ORDER_BOOK", "BASIS", "VOLATILITY", "MARKET_STRUCTURE", "TIME",
)
_COMPARISON_SEAL = object()


@dataclass(frozen=True, slots=True)
class AblationFoldResult:
    fold_id: str
    log_loss: float
    brier_score: float
    net_ev: float
    trade_count: int
    maximum_drawdown: float

    def __post_init__(self) -> None:
        if (
            not self.fold_id.strip() or self.trade_count < 0
            or any(not math.isfinite(value) for value in (
                self.log_loss, self.brier_score, self.net_ev, self.maximum_drawdown,
            ))
            or self.log_loss < 0.0 or self.brier_score < 0.0 or self.maximum_drawdown < 0.0
        ):
            raise ValueError("invalid ablation fold result")


@dataclass(frozen=True, slots=True, init=False)
class AblationComparison:
    removed_group: str
    full_model_folds: tuple[AblationFoldResult, ...]
    removed_model_folds: tuple[AblationFoldResult, ...]
    full_model_gain_ratio: float
    fold_stability: float
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> AblationComparison:
        raise TypeError("ablation comparisons must be derived from aligned full/removal folds")

    def __post_init__(self) -> None:
        if self._seal is not _COMPARISON_SEAL or self.removed_group not in ABLATION_GROUPS or not self.full_model_folds:
            raise ValueError("invalid ablation group/evidence")
        full_ids = tuple(value.fold_id for value in self.full_model_folds)
        removed_ids = tuple(value.fold_id for value in self.removed_model_folds)
        if len(set(full_ids)) != len(full_ids) or full_ids != removed_ids:
            raise ValueError("full and removed ablation folds must be unique and aligned")
        if not 0.0 <= self.full_model_gain_ratio <= 1.0 or not 0.0 <= self.fold_stability <= 1.0:
            raise ValueError("ablation ratios must be finite and bounded")

    @property
    def group_supported(self) -> bool:
        return self.full_model_gain_ratio > 0.5


def compare_all_ablations(
    full_model: Sequence[AblationFoldResult],
    removed_by_group: Mapping[str, Sequence[AblationFoldResult]],
) -> tuple[AblationComparison, ...]:
    if tuple(sorted(removed_by_group)) != tuple(sorted(ABLATION_GROUPS)):
        raise ValueError("all eight feature-group ablations are mandatory")
    full = tuple(full_model)
    if not full or len({value.fold_id for value in full}) != len(full):
        raise ValueError("full model requires unique outer fold results")
    comparisons = []
    for group in ABLATION_GROUPS:
        removed = tuple(removed_by_group[group])
        if tuple(value.fold_id for value in removed) != tuple(value.fold_id for value in full):
            raise ValueError("each removal must use the identical full-model outer folds")
        gains = tuple(
            (
                baseline.net_ev >= ablated.net_ev
                and baseline.log_loss <= ablated.log_loss
                and baseline.brier_score <= ablated.brier_score
            )
            for baseline, ablated in zip(full, removed, strict=True)
        )
        ratio = sum(gains) / len(gains)
        stable = 1.0 - (max(baseline.net_ev - ablated.net_ev for baseline, ablated in zip(full, removed, strict=True)) - min(baseline.net_ev - ablated.net_ev for baseline, ablated in zip(full, removed, strict=True))) / (1.0 + max(abs(baseline.net_ev) for baseline in full))
        comparison = object.__new__(AblationComparison)
        for name, value in (
            ("removed_group", group), ("full_model_folds", full),
            ("removed_model_folds", removed), ("full_model_gain_ratio", ratio),
            ("fold_stability", min(1.0, max(0.0, stable))), ("_seal", _COMPARISON_SEAL),
        ):
            object.__setattr__(comparison, name, value)
        comparison.__post_init__()
        comparisons.append(comparison)
    return tuple(comparisons)


def run_all_ablations(
    full_model: Sequence[AblationFoldResult],
    evaluate_without: Callable[[str], Sequence[AblationFoldResult]],
) -> tuple[AblationComparison, ...]:
    return compare_all_ablations(full_model, {group: tuple(evaluate_without(group)) for group in ABLATION_GROUPS})
