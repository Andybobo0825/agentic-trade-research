from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from tmf_research.experiments.registry import DataProvenance, ModelStatus


REQUIRED_REGIMES = frozenset({
    "DAY",
    "NIGHT",
    "HIGH_VOLATILITY",
    "MEDIUM_VOLATILITY",
    "LOW_VOLATILITY",
    "TRENDING",
    "RANGING",
    "EXPIRY_WEEK",
    "NON_EXPIRY_WEEK",
    "OPENING_30M",
    "INTRADAY",
    "CLOSING_30M",
})


@dataclass(frozen=True, slots=True)
class FoldEvidence:
    fold_id: str
    train_candidates: int
    test_candidates: int
    trade_count: int
    long_count: int
    short_count: int
    train_ev: float
    net_ev: float
    baseline_net_ev: float
    baseline_brier: float
    baseline_log_loss: float
    net_pnl: float
    train_log_loss: float
    test_log_loss: float
    train_brier: float
    test_brier: float
    train_profit_factor: float
    test_profit_factor: float
    train_trade_frequency: float
    test_trade_frequency: float

    def __post_init__(self) -> None:
        if not self.fold_id.strip() or any(
            isinstance(value, bool) or value < 0
            for value in (
                self.train_candidates,
                self.test_candidates,
                self.trade_count,
                self.long_count,
                self.short_count,
            )
        ):
            raise ValueError("invalid fold sample evidence")
        numeric = (
            self.net_ev,
            self.train_ev,
            self.baseline_net_ev,
            self.baseline_brier,
            self.baseline_log_loss,
            self.net_pnl,
            self.train_log_loss,
            self.test_log_loss,
            self.train_brier,
            self.test_brier,
            self.train_profit_factor,
            self.test_profit_factor,
            self.train_trade_frequency,
            self.test_trade_frequency,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("fold metrics must be finite")

    @property
    def sample_sufficient(self) -> bool:
        return (
            self.train_candidates >= 5_000
            and self.test_candidates >= 500
            and self.trade_count >= 30
            and self.long_count >= 10
            and self.short_count >= 10
        )

    @property
    def fold_status(self) -> Literal["VALID", "INSUFFICIENT_SAMPLE"]:
        return "VALID" if self.sample_sufficient else "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True, slots=True)
class GeneralizationGap:
    fold_id: str
    log_loss: float
    brier: float
    expected_value: float
    profit_factor: float
    trade_frequency: float
    high_risk_reasons: tuple[str, ...]


def generalization_gap(fold: FoldEvidence) -> GeneralizationGap:
    reasons = []
    if fold.train_ev > 0.0 and fold.net_ev < 0.0:
        reasons.append("TRAIN_POSITIVE_TEST_DEGRADATION")
    if fold.train_profit_factor > max(1.0, 1.5 * fold.test_profit_factor):
        reasons.append("PROFIT_FACTOR_GAP")
    if fold.train_brier + 0.05 < fold.test_brier:
        reasons.append("CALIBRATION_GAP")
    if fold.train_trade_frequency > max(0.01, 2.0 * fold.test_trade_frequency):
        reasons.append("TRADE_FREQUENCY_GAP")
    return GeneralizationGap(
        fold.fold_id,
        fold.test_log_loss - fold.train_log_loss,
        fold.test_brier - fold.train_brier,
        fold.net_ev - fold.train_ev,
        fold.train_profit_factor - fold.test_profit_factor,
        fold.train_trade_frequency - fold.test_trade_frequency,
        tuple(reasons),
    )


@dataclass(frozen=True, slots=True)
class StabilityDimensions:
    regimes: Mapping[str, float]
    months: Mapping[str, float]
    directions: Mapping[str, float]
    target_codes: Mapping[str, float]

    def __post_init__(self) -> None:
        if not REQUIRED_REGIMES.issubset(self.regimes):
            raise ValueError("all specified market regimes must be reported")
        if set(self.directions) != {"LONG", "SHORT"} or not self.months or not self.target_codes:
            raise ValueError("month, direction, and target-code stability evidence is required")
        for mapping in (self.regimes, self.months, self.directions, self.target_codes):
            if any(not key.strip() or not math.isfinite(value) for key, value in mapping.items()):
                raise ValueError("stability dimensions must be finite")
        object.__setattr__(self, "regimes", dict(self.regimes))
        object.__setattr__(self, "months", dict(self.months))
        object.__setattr__(self, "directions", dict(self.directions))
        object.__setattr__(self, "target_codes", dict(self.target_codes))


@dataclass(frozen=True, slots=True)
class ApprovalGates:
    calibration: bool
    costs: bool
    event_independence: bool
    train_test_gap: bool
    coefficient_stability: bool
    parameter_robustness: bool
    regime_stability: bool
    target_code_stability: bool
    ablations_complete: bool
    search_budget_clean: bool
    all_rules_frozen: bool
    locked_holdout_status: Literal["NOT_RUN", "PASSED", "FAILED", "CONTAMINATED"]


@dataclass(frozen=True, slots=True)
class ModelDecision:
    research_status: Literal["RESEARCH_COMPLETE", "RESEARCH_INSUFFICIENT_DATA", "RESEARCH_REJECTED"]
    model_status: ModelStatus
    valid_outer_folds: int
    positive_fold_ratio: float
    baseline_outperformance_ratio: float
    brier_noninferiority_ratio: float
    log_loss_noninferiority_ratio: float
    fold_concentration: float | None
    month_concentration: float | None
    direction_concentration: float | None
    reasons: tuple[str, ...]


def decide_model_status(
    folds: Sequence[FoldEvidence],
    dimensions: StabilityDimensions,
    gates: ApprovalGates,
    *,
    data_provenance: DataProvenance,
) -> ModelDecision:
    if data_provenance not in ("REAL_READONLY_MARKET_DATA", "SYNTHETIC_TEST_ONLY"):
        raise ValueError("unknown data provenance")
    valid = tuple(fold for fold in folds if fold.sample_sufficient)
    if len(valid) < 5:
        return ModelDecision(
            "RESEARCH_INSUFFICIENT_DATA",
            "REJECTED_INSUFFICIENT_DATA",
            len(valid),
            0.0,
            0.0,
            0.0,
            0.0,
            None,
            None,
            None,
            ("FEWER_THAN_FIVE_VALID_OUTER_FOLDS",),
        )
    positive_ratio = sum(fold.net_ev >= 0.0 for fold in valid) / len(valid)
    baseline_ratio = sum(fold.net_ev > fold.baseline_net_ev for fold in valid) / len(valid)
    brier_ratio = sum(fold.test_brier <= fold.baseline_brier for fold in valid) / len(valid)
    log_loss_ratio = sum(fold.test_log_loss <= fold.baseline_log_loss for fold in valid) / len(valid)
    total = sum(fold.net_pnl for fold in valid)
    fold_concentration = _concentration({fold.fold_id: fold.net_pnl for fold in valid}, total)
    month_concentration = _concentration(dimensions.months, total)
    direction_concentration = _concentration(dimensions.directions, total)
    reasons: list[str] = []
    if total <= 0.0:
        reasons.append("NON_POSITIVE_TOTAL_OUTER_NET_PNL")
    if positive_ratio < 0.70:
        reasons.append("NON_NEGATIVE_FOLD_RATIO_BELOW_70_PERCENT")
    if baseline_ratio < 0.70:
        reasons.append("BASELINE_OUTPERFORMANCE_BELOW_70_PERCENT")
    if brier_ratio < 0.50:
        reasons.append("BRIER_WORSE_THAN_BASELINE_IN_MAJORITY")
    if log_loss_ratio < 0.50:
        reasons.append("LOG_LOSS_WORSE_THAN_BASELINE_IN_MAJORITY")
    if fold_concentration is None or fold_concentration > 0.40:
        reasons.append("FOLD_CONCENTRATION_ABOVE_40_PERCENT")
    if month_concentration is None or month_concentration > 0.30:
        reasons.append("MONTH_CONCENTRATION_ABOVE_30_PERCENT")
    if direction_concentration is None or direction_concentration > 0.85:
        reasons.append("DIRECTION_CONCENTRATION_ABOVE_85_PERCENT")
    gate_values = {
        "CALIBRATION_GATE_FAILED": gates.calibration,
        "COST_GATE_FAILED": gates.costs,
        "EVENT_CONCENTRATION_GATE_FAILED": gates.event_independence,
        "GENERALIZATION_GAP_GATE_FAILED": gates.train_test_gap,
        "COEFFICIENT_STABILITY_GATE_FAILED": gates.coefficient_stability,
        "PARAMETER_FRAGILITY_GATE_FAILED": gates.parameter_robustness,
        "REGIME_STABILITY_GATE_FAILED": gates.regime_stability,
        "TARGET_CODE_STABILITY_GATE_FAILED": gates.target_code_stability,
        "ABLATION_GATE_FAILED": gates.ablations_complete,
        "SEARCH_BUDGET_GATE_FAILED": gates.search_budget_clean,
        "FROZEN_RULES_GATE_FAILED": gates.all_rules_frozen,
    }
    reasons.extend(name for name, passed in gate_values.items() if not passed)
    if gates.locked_holdout_status == "CONTAMINATED":
        reasons.append("LOCKED_HOLDOUT_CONTAMINATED")
    elif gates.locked_holdout_status == "FAILED":
        reasons.append("LOCKED_HOLDOUT_FAILED")
    if reasons:
        status: ModelStatus = (
            "LOCKED_TEST_FAILED"
            if gates.locked_holdout_status in ("FAILED", "CONTAMINATED")
            else "REJECTED_OVERFIT_RISK"
        )
        return ModelDecision(
            "RESEARCH_REJECTED",
            status,
            len(valid),
            positive_ratio,
            baseline_ratio,
            brier_ratio,
            log_loss_ratio,
            fold_concentration,
            month_concentration,
            direction_concentration,
            tuple(reasons),
        )
    if data_provenance == "SYNTHETIC_TEST_ONLY":
        return ModelDecision(
            "RESEARCH_COMPLETE",
            "CANDIDATE",
            len(valid),
            positive_ratio,
            baseline_ratio,
            brier_ratio,
            log_loss_ratio,
            fold_concentration,
            month_concentration,
            direction_concentration,
            ("SYNTHETIC_TEST_ONLY_CANNOT_APPROVE",),
        )
    if gates.locked_holdout_status == "NOT_RUN":
        final_status: ModelStatus = "LOCKED_TEST_PENDING"
    else:
        final_status = "APPROVED_FOR_PAPER"
    return ModelDecision(
        "RESEARCH_COMPLETE",
        final_status,
        len(valid),
        positive_ratio,
        baseline_ratio,
        brier_ratio,
        log_loss_ratio,
        fold_concentration,
        month_concentration,
        direction_concentration,
        (),
    )


def _concentration(contributions: Mapping[str, float], total: float) -> float | None:
    if total <= 0.0 or not contributions:
        return None
    return max(max(0.0, value) / total for value in contributions.values())
