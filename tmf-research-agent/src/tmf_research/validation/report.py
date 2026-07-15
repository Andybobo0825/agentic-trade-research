from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from tmf_research.validation.overfitting import GeneralizationGap, ModelDecision, StabilityDimensions


CLASSIFICATION_KEYS = frozenset({
    "log_loss", "brier_score", "roc_auc", "precision", "recall", "f1",
    "confusion_matrix", "expected_calibration_error", "calibration_table",
})
TRADING_KEYS = frozenset({
    "trade_count", "long_count", "short_count", "win_rate", "average_win", "average_loss",
    "average_net_points", "gross_pnl", "net_pnl", "profit_factor", "maximum_drawdown",
    "longest_losing_streak", "expected_value_per_trade", "expected_value_per_day",
    "average_holding_time", "exposure_ratio", "turnover",
})
STABILITY_KEYS = frozenset({
    "positive_fold_ratio", "baseline_outperformance_ratio", "coefficient_sign_stability",
    "feature_rank_stability", "parameter_sensitivity", "monthly_contribution_concentration",
    "directional_contribution_concentration", "fold_profit_concentration", "train_test_gap",
})


@dataclass(frozen=True, slots=True)
class DistributionSummary:
    all_values: tuple[float, ...]
    mean: float
    median: float
    worst: float
    best: float
    standard_deviation: float
    interquartile_range: float

    def __post_init__(self) -> None:
        values = (*self.all_values, self.mean, self.median, self.worst, self.best, self.standard_deviation, self.interquartile_range)
        if not self.all_values or any(not math.isfinite(value) for value in values):
            raise ValueError("distribution summaries require complete finite values")
        if self.standard_deviation < 0.0 or self.interquartile_range < 0.0:
            raise ValueError("distribution spread cannot be negative")


def summarize(values: Sequence[float], *, higher_is_better: bool = True) -> DistributionSummary:
    if not values or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in values):
        raise ValueError("finite numeric fold values are required")
    ordered = tuple(sorted(values))
    quartiles = statistics.quantiles(ordered, n=4, method="inclusive") if len(ordered) > 1 else (ordered[0],) * 3
    return DistributionSummary(
        tuple(values), statistics.fmean(values), statistics.median(values),
        min(values) if higher_is_better else max(values),
        max(values) if higher_is_better else min(values),
        statistics.pstdev(values), quartiles[2] - quartiles[0],
    )


@dataclass(frozen=True, slots=True)
class FoldReport:
    fold_id: str
    manifest_hash: str
    split_regions: Mapping[str, str]
    classification: Mapping[str, object]
    trading: Mapping[str, object]
    stability: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.fold_id.strip() or len(self.manifest_hash) != 64:
            raise ValueError("fold report requires fold and manifest identity")
        if set(self.split_regions) != {"TRAIN", "INNER_VALIDATION", "OUTER_TEST", "LOCKED_HOLDOUT"}:
            raise ValueError("all report split regions must be visible")
        if any(not isinstance(value, str) or not value.strip() for value in self.split_regions.values()):
            raise ValueError("split regions must be non-empty strings")
        if not CLASSIFICATION_KEYS.issubset(self.classification) or not TRADING_KEYS.issubset(self.trading) or not STABILITY_KEYS.issubset(self.stability):
            raise ValueError("full classification, trading, and stability metrics are required")
        for mapping, nonnumeric in (
            (self.classification, {"confusion_matrix", "calibration_table"}),
            (self.trading, set()),
            (self.stability, set()),
        ):
            for name, value in mapping.items():
                if name in nonnumeric:
                    continue
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                    raise ValueError(f"report metric {name} must be a finite number")
        confusion = self.classification["confusion_matrix"]
        if (
            not isinstance(confusion, (tuple, list)) or len(confusion) != 2
            or any(not isinstance(row, (tuple, list)) or len(row) != 2 for row in confusion)
        ):
            raise ValueError("confusion matrix must be 2x2")
        if not isinstance(self.classification["calibration_table"], (tuple, list)):
            raise ValueError("calibration table must be a sequence")
        object.__setattr__(self, "split_regions", MappingProxyType(dict(self.split_regions)))
        object.__setattr__(self, "classification", MappingProxyType(dict(self.classification)))
        object.__setattr__(self, "trading", MappingProxyType(dict(self.trading)))
        object.__setattr__(self, "stability", MappingProxyType(dict(self.stability)))


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
    fold_keys = tuple((fold.fold_id, fold.manifest_hash) for fold in folds)
    gap_keys = tuple((gap.fold_id, gap.manifest_hash) for gap in gaps)
    if len(set(fold_keys)) != len(fold_keys) or fold_keys != gap_keys:
        raise ValueError("fold reports and gap evidence must have identical ordered unique IDs/manifests")
    common_names = set.intersection(
        *(set(fold.classification) | set(fold.trading) | set(fold.stability) for fold in folds)
    )
    metric_names = tuple(sorted(
        name for name in common_names
        if all(
            isinstance(
                (fold.classification if name in fold.classification else fold.trading if name in fold.trading else fold.stability)[name],
                (int, float),
            ) and not isinstance(
                (fold.classification if name in fold.classification else fold.trading if name in fold.trading else fold.stability)[name],
                bool,
            )
            for fold in folds
        )
    ))
    summaries: dict[str, DistributionSummary] = {}
    lower_is_better = {"log_loss", "brier_score", "expected_calibration_error", "maximum_drawdown", "train_test_gap"}
    for name in metric_names:
        values = []
        for fold in folds:
            source = fold.classification if name in fold.classification else fold.trading if name in fold.trading else fold.stability
            values.append(float(cast(int | float, source[name])))
        summaries[name] = summarize(values, higher_is_better=name not in lower_is_better)
    expected_numeric_names = {
        name for name in CLASSIFICATION_KEYS | TRADING_KEYS | STABILITY_KEYS
        if name not in {"confusion_matrix", "calibration_table"}
    }
    if not expected_numeric_names.issubset(summaries):
        raise ValueError("report summaries are incomplete")
    if decision.valid_outer_folds > len(folds):
        raise ValueError("decision valid fold count exceeds aligned report evidence")
    return Phase5Report(tuple(folds), MappingProxyType(summaries), tuple(gaps), dimensions, decision)
