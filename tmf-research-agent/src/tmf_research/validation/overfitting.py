from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Literal, cast

from tmf_research.experiments.registry import ModelStatus
from tmf_research.models.provenance import NestedFoldManifest


REQUIRED_REGIMES = frozenset({
    "DAY", "NIGHT", "HIGH_VOLATILITY", "MEDIUM_VOLATILITY", "LOW_VOLATILITY",
    "TRENDING", "RANGING", "EXPIRY_WEEK", "NON_EXPIRY_WEEK", "OPENING_30M",
    "INTRADAY", "CLOSING_30M",
})
_FOLD_EVIDENCE_SEAL = object()
FoldEvidenceAuthority = Literal["RAW_DERIVED", "TEST_ONLY"]


class ResearchStatus(str, Enum):
    COMPLETE = "RESEARCH_COMPLETE"
    INSUFFICIENT_DATA = "RESEARCH_INSUFFICIENT_DATA"
    REJECTED = "RESEARCH_REJECTED"


@dataclass(frozen=True, slots=True, init=False)
class FoldEvidence:
    manifest: NestedFoldManifest
    trade_count: int
    long_count: int
    short_count: int
    train_ev: float
    test_ev: float
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
    train_accuracy: float
    test_accuracy: float
    authority: FoldEvidenceAuthority
    derivation_hash: str
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> FoldEvidence:
        raise TypeError("fold evidence must be issued by an authoritative evaluator")

    def __post_init__(self) -> None:
        if self._seal is not _FOLD_EVIDENCE_SEAL or self.authority not in (
            "RAW_DERIVED", "TEST_ONLY",
        ):
            raise TypeError("invalid fold evidence authority")
        if len(self.derivation_hash) != 64 or any(
            value not in "0123456789abcdef" for value in self.derivation_hash
        ):
            raise ValueError("fold derivation hash is required")
        if not isinstance(self.manifest, NestedFoldManifest):
            raise TypeError("fold evidence requires a sealed planner manifest")
        counts = (self.trade_count, self.long_count, self.short_count)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("trade counts must be non-negative integers")
        if self.trade_count != self.long_count + self.short_count:
            raise ValueError("trade count must equal LONG plus SHORT")
        numeric = (
            self.train_ev, self.test_ev, self.baseline_net_ev, self.baseline_brier,
            self.baseline_log_loss, self.net_pnl, self.train_log_loss, self.test_log_loss,
            self.train_brier, self.test_brier, self.train_profit_factor, self.test_profit_factor,
            self.train_trade_frequency, self.test_trade_frequency, self.train_accuracy, self.test_accuracy,
        )
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in numeric):
            raise ValueError("fold metrics must be finite numbers")
        if any(value < 0.0 for value in (
            self.baseline_brier, self.baseline_log_loss, self.train_log_loss, self.test_log_loss,
            self.train_brier, self.test_brier, self.train_profit_factor, self.test_profit_factor,
            self.train_trade_frequency, self.test_trade_frequency,
        )) or any(not 0.0 <= value <= 1.0 for value in (self.train_accuracy, self.test_accuracy)):
            raise ValueError("loss/frequency/accuracy metrics are outside valid ranges")

    @property
    def fold_id(self) -> str:
        return self.manifest.outer_fold_id

    @property
    def manifest_hash(self) -> str:
        return self.manifest.content_hash

    @property
    def train_candidates(self) -> int:
        return self.manifest.inner_train.count + self.manifest.inner_validation.count

    @property
    def test_candidates(self) -> int:
        return self.manifest.outer_test.count

    @property
    def sample_sufficient(self) -> bool:
        return (
            self.train_candidates >= 5_000 and self.test_candidates >= 500
            and self.trade_count >= 30 and self.long_count >= 10 and self.short_count >= 10
        )

    @property
    def fold_status(self) -> str:
        return "VALID" if self.sample_sufficient else "INSUFFICIENT_SAMPLE"


def _issue_fold_evidence(
    manifest: NestedFoldManifest,
    values: tuple[
        int, int, int, float, float, float, float, float, float, float,
        float, float, float, float, float, float, float, float, float,
    ],
    *,
    authority: FoldEvidenceAuthority,
    derivation_hash: str,
) -> FoldEvidence:
    instance = object.__new__(FoldEvidence)
    names = (
        "trade_count", "long_count", "short_count", "train_ev", "test_ev",
        "baseline_net_ev", "baseline_brier", "baseline_log_loss", "net_pnl",
        "train_log_loss", "test_log_loss", "train_brier", "test_brier",
        "train_profit_factor", "test_profit_factor", "train_trade_frequency",
        "test_trade_frequency", "train_accuracy", "test_accuracy",
    )
    entries = tuple(zip(names, values, strict=True))
    for name, value in (
        ("manifest", manifest), *entries,
        ("authority", authority), ("derivation_hash", derivation_hash),
        ("_seal", _FOLD_EVIDENCE_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def _issue_test_fold_evidence(
    manifest: NestedFoldManifest,
    *values: int | float,
) -> FoldEvidence:
    if len(values) != 19:
        raise ValueError("test fold evidence requires the complete metric vector")
    import hashlib
    import json

    derivation_hash = hashlib.sha256(json.dumps(
        [manifest.content_hash, *values], separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()
    return _issue_fold_evidence(
        manifest,
        cast(tuple[
            int, int, int, float, float, float, float, float, float, float,
            float, float, float, float, float, float, float, float, float,
        ], values),
        authority="TEST_ONLY",
        derivation_hash=derivation_hash,
    )


@dataclass(frozen=True, slots=True)
class GeneralizationGap:
    fold_id: str
    manifest_hash: str
    log_loss: float
    brier: float
    expected_value: float
    profit_factor: float
    trade_frequency: float
    accuracy: float
    high_risk_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.fold_id.strip() or len(self.manifest_hash) != 64:
            raise ValueError("gap requires fold/manifest identity")
        if any(not math.isfinite(value) for value in (
            self.log_loss, self.brier, self.expected_value, self.profit_factor,
            self.trade_frequency, self.accuracy,
        )):
            raise ValueError("generalization gap metrics must be finite")


def generalization_gap(fold: FoldEvidence) -> GeneralizationGap:
    reasons = []
    if fold.train_ev > 0.0 and fold.test_ev < 0.0:
        reasons.append("TRAIN_POSITIVE_TEST_NEGATIVE_EV")
    if fold.train_profit_factor > max(1.0, 1.5 * fold.test_profit_factor):
        reasons.append("PROFIT_FACTOR_GAP")
    if fold.train_brier + 0.05 < fold.test_brier:
        reasons.append("CALIBRATION_GAP")
    if fold.train_trade_frequency > max(0.01, 2.0 * fold.test_trade_frequency):
        reasons.append("TRADE_FREQUENCY_GAP")
    if fold.train_accuracy > fold.test_accuracy and fold.test_ev < fold.train_ev:
        reasons.append("ACCURACY_UP_NET_EV_DOWN")
    return GeneralizationGap(
        fold.fold_id, fold.manifest_hash,
        fold.test_log_loss - fold.train_log_loss,
        fold.test_brier - fold.train_brier,
        fold.test_ev - fold.train_ev,
        fold.train_profit_factor - fold.test_profit_factor,
        fold.train_trade_frequency - fold.test_trade_frequency,
        fold.train_accuracy - fold.test_accuracy,
        tuple(reasons),
    )


@dataclass(frozen=True, slots=True)
class StabilityDimensions:
    regimes: Mapping[str, float]
    months: Mapping[str, float]
    directions: Mapping[str, float]
    target_codes: Mapping[str, float]
    total_net_pnl: float
    events: Mapping[str, float]
    cost_complete: bool

    def __post_init__(self) -> None:
        if not REQUIRED_REGIMES.issubset(self.regimes):
            raise ValueError("all specified market regimes must be reported")
        if set(self.directions) != {"LONG", "SHORT"} or not self.months or not self.target_codes or not self.events:
            raise ValueError("month, direction, target-code, and event contribution evidence is required")
        if not isinstance(self.cost_complete, bool):
            raise ValueError("cost completeness must be an exact boolean")
        if not math.isfinite(self.total_net_pnl):
            raise ValueError("total net PnL must be finite")
        for values in (self.regimes, self.months, self.directions, self.target_codes, self.events):
            if any(
                not key.strip() or not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
                for key, value in values.items()
            ):
                raise ValueError("stability dimensions must be finite numeric mappings")
        for name, values in (("months", self.months), ("directions", self.directions), ("target_codes", self.target_codes), ("events", self.events)):
            if not math.isclose(sum(values.values()), self.total_net_pnl, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"{name} contributions must reconcile to total net PnL")
        object.__setattr__(self, "regimes", MappingProxyType(dict(self.regimes)))
        object.__setattr__(self, "months", MappingProxyType(dict(self.months)))
        object.__setattr__(self, "directions", MappingProxyType(dict(self.directions)))
        object.__setattr__(self, "target_codes", MappingProxyType(dict(self.target_codes)))
        object.__setattr__(self, "events", MappingProxyType(dict(self.events)))


@dataclass(frozen=True, slots=True)
class ModelDecision:
    research_status: ResearchStatus
    model_status: ModelStatus
    evidence_hash: str
    valid_outer_folds: int
    positive_fold_ratio: float
    baseline_outperformance_ratio: float
    brier_noninferiority_ratio: float
    log_loss_noninferiority_ratio: float
    fold_concentration: float | None
    month_concentration: float | None
    direction_concentration: float | None
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.research_status, ResearchStatus) or not isinstance(self.model_status, ModelStatus):
            raise TypeError("model decisions require exact status enums")
        if len(self.evidence_hash) != 64:
            raise ValueError("model decision evidence hash is required")
        if isinstance(self.valid_outer_folds, bool) or not isinstance(self.valid_outer_folds, int) or self.valid_outer_folds < 0:
            raise ValueError("valid outer fold count must be a non-negative integer")
        ratios = (
            self.positive_fold_ratio, self.baseline_outperformance_ratio,
            self.brier_noninferiority_ratio, self.log_loss_noninferiority_ratio,
        )
        concentrations = (self.fold_concentration, self.month_concentration, self.direction_concentration)
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in ratios):
            raise ValueError("decision ratios must be finite and bounded")
        if any(value is not None and (not math.isfinite(value) or not 0.0 <= value <= 1.0) for value in concentrations):
            raise ValueError("decision concentrations must be finite and bounded")
        if any(not reason.strip() for reason in self.reasons):
            raise ValueError("decision reasons must be non-empty codes")


def _core_reasons(
    folds: Sequence[FoldEvidence],
    dimensions: StabilityDimensions,
) -> tuple[tuple[FoldEvidence, ...], dict[str, float | None], tuple[str, ...]]:
    manifest_hashes = tuple(fold.manifest_hash for fold in folds)
    fold_ids = tuple(fold.fold_id for fold in folds)
    if len(set(manifest_hashes)) != len(manifest_hashes) or len(set(fold_ids)) != len(fold_ids):
        raise ValueError("outer fold IDs and planner manifests must be unique")
    valid = tuple(fold for fold in folds if fold.sample_sufficient)
    if not math.isclose(dimensions.total_net_pnl, sum(fold.net_pnl for fold in valid), rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("fold PnL must reconcile to stability contribution total")
    if len(valid) < 5:
        return valid, {
            "positive": 0.0, "baseline": 0.0, "brier": 0.0, "log_loss": 0.0,
            "fold": None, "month": None, "direction": None,
        }, ("FEWER_THAN_FIVE_VALID_OUTER_FOLDS",)
    positive = sum(fold.test_ev >= 0.0 for fold in valid) / len(valid)
    baseline = sum(fold.test_ev > fold.baseline_net_ev for fold in valid) / len(valid)
    brier = sum(fold.test_brier <= fold.baseline_brier for fold in valid) / len(valid)
    log_loss = sum(fold.test_log_loss <= fold.baseline_log_loss for fold in valid) / len(valid)
    total = dimensions.total_net_pnl
    fold_concentration = _concentration({fold.fold_id: fold.net_pnl for fold in valid}, total)
    month_concentration = _concentration(dimensions.months, total)
    direction_concentration = _concentration(dimensions.directions, total)
    event_concentration = _concentration(dimensions.events, total)
    reasons: list[str] = []
    if total <= 0.0:
        reasons.append("NON_POSITIVE_TOTAL_OUTER_NET_PNL")
    if positive < 0.70:
        reasons.append("NON_NEGATIVE_FOLD_RATIO_BELOW_70_PERCENT")
    if baseline < 0.70:
        reasons.append("BASELINE_OUTPERFORMANCE_BELOW_70_PERCENT")
    if brier <= 0.50:
        reasons.append("BRIER_NOT_NONINFERIOR_IN_STRICT_MAJORITY")
    if log_loss <= 0.50:
        reasons.append("LOG_LOSS_NOT_NONINFERIOR_IN_STRICT_MAJORITY")
    if fold_concentration is None or fold_concentration > 0.40:
        reasons.append("FOLD_CONCENTRATION_ABOVE_40_PERCENT")
    if month_concentration is None or month_concentration > 0.30:
        reasons.append("MONTH_CONCENTRATION_ABOVE_30_PERCENT")
    if direction_concentration is None or direction_concentration > 0.85:
        reasons.append("DIRECTION_CONCENTRATION_ABOVE_85_PERCENT")
    if event_concentration is None or event_concentration > 0.40:
        reasons.append("EVENT_CONCENTRATION_ABOVE_40_PERCENT")
    if not dimensions.cost_complete:
        reasons.append("INCOMPLETE_COST_MODEL")
    if any(value < 0.0 for value in dimensions.regimes.values()):
        reasons.append("NEGATIVE_REGIME_CONTRIBUTION")
    if any(value < 0.0 for value in dimensions.target_codes.values()):
        reasons.append("NEGATIVE_TARGET_CODE_CONTRIBUTION")
    return valid, {
        "positive": positive, "baseline": baseline, "brier": brier, "log_loss": log_loss,
        "fold": fold_concentration, "month": month_concentration, "direction": direction_concentration,
    }, tuple(reasons)


def _concentration(contributions: Mapping[str, float], total: float) -> float | None:
    if total <= 0.0 or not contributions:
        return None
    return max(max(0.0, value) / total for value in contributions.values())
