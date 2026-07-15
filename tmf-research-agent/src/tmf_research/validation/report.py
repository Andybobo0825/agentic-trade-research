from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from tmf_research.validation.overfitting import GeneralizationGap, ModelDecision, StabilityDimensions


@dataclass(frozen=True, slots=True)
class DistributionSummary:
    all_values: tuple[float, ...]
    mean: float
    median: float
    worst: float
    best: float
    standard_deviation: float
    interquartile_range: float


def summarize(values: Sequence[float], *, higher_is_better: bool = True) -> DistributionSummary:
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("finite fold values are required")
    ordered = tuple(sorted(values))
    quartiles = statistics.quantiles(ordered, n=4, method="inclusive") if len(ordered) > 1 else (ordered[0],) * 3
    return DistributionSummary(
        tuple(values),
        statistics.fmean(values),
        statistics.median(values),
        min(values) if higher_is_better else max(values),
        max(values) if higher_is_better else min(values),
        statistics.pstdev(values),
        quartiles[2] - quartiles[0],
    )


@dataclass(frozen=True, slots=True)
class FoldReport:
    fold_id: str
    split_regions: Mapping[str, str]
    classification: Mapping[str, object]
    trading: Mapping[str, object]
    stability: Mapping[str, object]

    def __post_init__(self) -> None:
        if set(self.split_regions) != {"TRAIN", "INNER_VALIDATION", "OUTER_TEST", "LOCKED_HOLDOUT"}:
            raise ValueError("all report split regions must be visible")
        required_classification = {
            "log_loss", "brier_score", "roc_auc", "precision", "recall", "f1",
            "confusion_matrix", "expected_calibration_error", "calibration_table",
        }
        required_trading = {
            "trade_count", "long_count", "short_count", "win_rate", "average_win", "average_loss",
            "average_net_points", "gross_pnl", "net_pnl", "profit_factor", "maximum_drawdown",
            "longest_losing_streak", "expected_value_per_trade", "expected_value_per_day",
            "average_holding_time", "exposure_ratio", "turnover",
        }
        if not required_classification.issubset(self.classification) or not required_trading.issubset(self.trading):
            raise ValueError("full classification and trading metrics are required")
        required_stability = {
            "positive_fold_ratio", "baseline_outperformance_ratio", "coefficient_sign_stability",
            "feature_rank_stability", "parameter_sensitivity", "monthly_contribution_concentration",
            "directional_contribution_concentration", "fold_profit_concentration", "train_test_gap",
        }
        if not required_stability.issubset(self.stability):
            raise ValueError("full stability metrics are required")


@dataclass(frozen=True, slots=True)
class Phase5Report:
    folds: tuple[FoldReport, ...]
    summaries: Mapping[str, DistributionSummary]
    generalization_gaps: tuple[GeneralizationGap, ...]
    dimensions: StabilityDimensions
    decision: ModelDecision


def build_phase5_report(
    folds: Sequence[FoldReport],
    gaps: Sequence[GeneralizationGap],
    dimensions: StabilityDimensions,
    decision: ModelDecision,
) -> Phase5Report:
    if not folds or len(folds) != len(gaps):
        raise ValueError("every fold requires metrics and a generalization gap")
    common_names = set.intersection(
        *(set(fold.classification) | set(fold.trading) | set(fold.stability) for fold in folds)
    )
    metric_names = tuple(sorted(
        name
        for name in common_names
        if all(
            isinstance(
                (fold.classification if name in fold.classification else fold.trading if name in fold.trading else fold.stability)[name],
                (int, float),
            )
            for fold in folds
        )
    ))
    summaries: dict[str, DistributionSummary] = {}
    lower_is_better = {"log_loss", "brier_score", "expected_calibration_error", "maximum_drawdown"}
    for name in metric_names:
        values = []
        for fold in folds:
            source = fold.classification if name in fold.classification else fold.trading if name in fold.trading else fold.stability
            values.append(float(cast(int | float, source[name])))
        summaries[name] = summarize(values, higher_is_better=name not in lower_is_better)
    return Phase5Report(tuple(folds), summaries, tuple(gaps), dimensions, decision)
