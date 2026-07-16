from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

from tmf_research.models.calibration import TwoStageCalibrationSelection
from tmf_research.models.provenance import (
    FrozenDecisionPolicy,
    OuterTestPredictions,
    Phase4FoldCapabilities,
    Phase4SourceRow,
    canonical_hash,
)
from tmf_research.models.training import Phase4TrainingResult
from tmf_research.validation.dataset_lineage import DatasetBuildResult, ExecutableOutcome
from tmf_research.validation.overfitting import (
    REQUIRED_REGIMES,
    FoldEvidence,
    StabilityDimensions,
    _issue_fold_evidence,
)


_FOLD_EVALUATION_SEAL = object()
_PRODUCTION_EVALUATION_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class SealedFoldEvaluation:
    evidence: FoldEvidence
    predictions: OuterTestPredictions
    lineage_hash: str
    policy: FrozenDecisionPolicy
    contribution_rows: tuple[tuple[str, str, str, str, str, float], ...]
    content_hash: str
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> SealedFoldEvaluation:
        raise TypeError("outer fold evaluations must be issued from sealed raw/model evidence")

    def __post_init__(self) -> None:
        if self._seal is not _FOLD_EVALUATION_SEAL:
            raise TypeError("invalid outer fold evaluation authority")
        if self.evidence.authority != "RAW_DERIVED":
            raise TypeError("production fold evaluation requires raw-derived metrics")
        expected = canonical_hash({
            "fold": self.evidence.derivation_hash,
            "predictions": self.predictions.content_hash,
            "lineage": self.lineage_hash,
            "policy": self.policy.content_hash,
            "contributions": [list(value) for value in self.contribution_rows],
        })
        if expected != self.content_hash:
            raise ValueError("outer fold evaluation content hash mismatch")


@dataclass(frozen=True, slots=True, init=False)
class ProductionEvaluation:
    folds: tuple[SealedFoldEvaluation, ...]
    dimensions: StabilityDimensions
    dataset_build_hash: str
    dataset_build: DatasetBuildResult
    content_hash: str
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> ProductionEvaluation:
        raise TypeError("production evaluation must aggregate sealed raw-derived folds")

    def __post_init__(self) -> None:
        if self._seal is not _PRODUCTION_EVALUATION_SEAL or not self.folds:
            raise TypeError("invalid production evaluation authority")
        self.dataset_build.assert_current()
        if self.dataset_build.content_hash != self.dataset_build_hash:
            raise ValueError("production evaluation lost exact dataset build")
        expected = canonical_hash({
            "build": self.dataset_build_hash,
            "folds": [value.content_hash for value in self.folds],
            "dimensions": _dimensions_payload(self.dimensions),
        })
        if self.content_hash != expected:
            raise ValueError("production evaluation content hash mismatch")
        if len({value.policy.content_hash for value in self.folds}) != 1:
            raise ValueError("all production folds require one frozen decision policy")

    @property
    def policy(self) -> FrozenDecisionPolicy:
        return self.folds[0].policy


def evaluate_outer_fold(
    build: DatasetBuildResult,
    capability: Phase4FoldCapabilities,
    training: Phase4TrainingResult,
    calibration: TwoStageCalibrationSelection,
    policy: FrozenDecisionPolicy,
) -> SealedFoldEvaluation:
    if not isinstance(build, DatasetBuildResult) or build.status != "READY":
        raise TypeError("raw-issued READY DatasetBuildResult is required")
    build.assert_current()
    exact = tuple(
        value for value in build.fold_capabilities if value.manifest == capability.manifest
    )
    if len(exact) != 1 or exact[0] is not capability:
        raise ValueError("foreign or reconstructed fold capability")
    predictions = training.predict_outer_test(capability.outer_test, calibration, policy)
    outcome_by_id = {value.row_id: value for value in build.development_outcomes}
    train_values = _score_rows(
        capability.inner_train.rows, training, calibration, policy, outcome_by_id,
    )
    test_values = _join_outer(predictions, capability.outer_test.rows, outcome_by_id)
    train_metrics = _metrics(train_values)
    test_metrics = _metrics(test_values)
    outcomes = tuple(value[3] for value in test_values)
    baseline_rate = sum(
        row.label in ("LONG", "SHORT") for row in capability.outer_test.rows
    ) / len(capability.outer_test.rows)
    epsilon = 1e-15
    baseline_brier = sum(
        (baseline_rate - int(row.label in ("LONG", "SHORT"))) ** 2
        for row in capability.outer_test.rows
    ) / len(capability.outer_test.rows)
    baseline_log_loss = -sum(
        int(row.label in ("LONG", "SHORT")) * math.log(max(epsilon, baseline_rate))
        + int(row.label not in ("LONG", "SHORT"))
        * math.log(max(epsilon, 1.0 - baseline_rate))
        for row in capability.outer_test.rows
    ) / len(capability.outer_test.rows)
    baseline_name = "FIXED_NO_TRADE_V1"
    baseline_net_ev = sum(0.0 for _row in capability.outer_test.rows) / len(
        capability.outer_test.rows
    )
    contribution_rows = tuple(
        (
            outcome.decision_time.strftime("%Y-%m"), signal, outcome.target_code,
            outcome.event_id, outcome.regime, net,
        )
        for _row, _p_trade, signal, outcome, net in test_values
        if signal != "NO_TRADE"
    )
    derivation = {
        "build": build.content_hash,
        "manifest": capability.manifest.content_hash,
        "training_model": training.model.content_hash,
        "calibration": calibration.calibrator.to_dict(),
        "policy": policy.content_hash,
        "predictions": predictions.content_hash,
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "baseline": [baseline_name, baseline_net_ev, baseline_brier, baseline_log_loss],
        "outcomes": [value.content_hash for value in outcomes],
        "contributions": [list(value) for value in contribution_rows],
    }
    derivation_hash = canonical_hash(derivation)
    evidence = _issue_fold_evidence(
        capability.manifest,
        (
            test_metrics[0], test_metrics[1], test_metrics[2],
            train_metrics[3], test_metrics[3], baseline_net_ev,
            baseline_brier, baseline_log_loss, test_metrics[4],
            train_metrics[5], test_metrics[5], train_metrics[6], test_metrics[6],
            train_metrics[7], test_metrics[7], train_metrics[8], test_metrics[8],
            train_metrics[9], test_metrics[9],
        ),
        authority="RAW_DERIVED",
        derivation_hash=derivation_hash,
    )
    payload = {
        "fold": derivation_hash,
        "predictions": predictions.content_hash,
        "lineage": build.lineage.content_hash,
        "policy": policy.content_hash,
        "contributions": [list(value) for value in contribution_rows],
    }
    instance = object.__new__(SealedFoldEvaluation)
    for name, value in (
        ("evidence", evidence), ("predictions", predictions),
        ("lineage_hash", build.lineage.content_hash),
        ("policy", policy),
        ("contribution_rows", contribution_rows),
        ("content_hash", canonical_hash(payload)), ("_seal", _FOLD_EVALUATION_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def aggregate_production_evaluation(
    build: DatasetBuildResult,
    folds: tuple[SealedFoldEvaluation, ...],
) -> ProductionEvaluation:
    if tuple(value.evidence.manifest for value in folds) != tuple(
        value.manifest for value in build.fold_capabilities
    ):
        raise ValueError("production aggregate requires every exact issued fold in order")
    if any(value.lineage_hash != build.lineage.content_hash for value in folds):
        raise ValueError("production folds do not share exact raw lineage")
    contributions = tuple(row for fold in folds for row in fold.contribution_rows)
    total = sum(value[5] for value in contributions)
    months = _sum_by(contributions, 0)
    directions = {name: sum(row[5] for row in contributions if row[1] == name) for name in ("LONG", "SHORT")}
    targets = _sum_by(contributions, 2)
    events = _sum_by(contributions, 3)
    if not months:
        months = {"NONE": 0.0}
    if not targets:
        targets = {"NONE": 0.0}
    if not events:
        events = {"NONE": 0.0}
    regimes = {name: 0.0 for name in REQUIRED_REGIMES}
    for row in contributions:
        regimes[row[4]] = regimes.get(row[4], 0.0) + row[5]
    dimensions = StabilityDimensions(
        regimes, months, directions, targets, total, events, True,
    )
    payload = {
        "build": build.content_hash,
        "folds": [value.content_hash for value in folds],
        "dimensions": _dimensions_payload(dimensions),
    }
    instance = object.__new__(ProductionEvaluation)
    for name, value in (
        ("folds", folds), ("dimensions", dimensions),
        ("dataset_build_hash", build.content_hash),
        ("dataset_build", build),
        ("content_hash", canonical_hash(payload)),
        ("_seal", _PRODUCTION_EVALUATION_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def _score_rows(
    rows: tuple[Phase4SourceRow, ...],
    training: Phase4TrainingResult,
    calibration: TwoStageCalibrationSelection,
    policy: FrozenDecisionPolicy,
    outcomes: dict[str, ExecutableOutcome],
) -> tuple[tuple[Phase4SourceRow, float, str, ExecutableOutcome, float], ...]:
    result = []
    for row in rows:
        transformed = training.preprocessor.transform(row.features)
        if not transformed.is_eligible:
            p_trade, p_long = 0.0, 0.5
        else:
            p_trade, p_long = calibration.calibrator.calibrate(
                training.model.trade_model.predict_probability(transformed.values),
                training.model.direction_model.predict_probability(transformed.values),
            )
        signal = (
            "NO_TRADE" if p_trade < policy.trade_threshold
            else "LONG" if p_long >= policy.direction_threshold else "SHORT"
        )
        outcome = outcomes[row.row_id]
        if outcome.source_row_hash != row.content_hash:
            raise ValueError("executable outcome source hash mismatch")
        net = (
            outcome.long_net_points if signal == "LONG"
            else outcome.short_net_points if signal == "SHORT" else 0.0
        )
        result.append((row, p_trade, signal, outcome, net))
    return tuple(result)


def _join_outer(
    predictions: OuterTestPredictions,
    rows: tuple[Phase4SourceRow, ...],
    outcomes: dict[str, ExecutableOutcome],
) -> tuple[tuple[Phase4SourceRow, float, str, ExecutableOutcome, float], ...]:
    result = []
    for prediction, row in zip(predictions.rows, rows, strict=True):
        outcome = outcomes[row.row_id]
        if prediction.source_row_hash != row.content_hash or outcome.source_row_hash != row.content_hash:
            raise ValueError("outer prediction/outcome source commitment mismatch")
        net = (
            outcome.long_net_points if prediction.signal == "LONG"
            else outcome.short_net_points if prediction.signal == "SHORT" else 0.0
        )
        result.append((row, prediction.p_trade, prediction.signal, outcome, net))
    return tuple(result)


def _metrics(
    rows: tuple[tuple[Phase4SourceRow, float, str, ExecutableOutcome, float], ...],
) -> tuple[int, int, int, float, float, float, float, float, float, float]:
    epsilon = 1e-15
    trades = tuple(value for value in rows if value[2] != "NO_TRADE")
    long_count = sum(value[2] == "LONG" for value in trades)
    short_count = len(trades) - long_count
    net_pnl = sum(value[4] for value in trades)
    net_ev = net_pnl / len(trades) if trades else 0.0
    log_loss = -sum(
        int(row.label in ("LONG", "SHORT")) * math.log(max(epsilon, probability))
        + int(row.label not in ("LONG", "SHORT"))
        * math.log(max(epsilon, 1.0 - probability))
        for row, probability, _signal, _outcome, _net in rows
    ) / len(rows)
    brier = sum(
        (probability - int(row.label in ("LONG", "SHORT"))) ** 2
        for row, probability, _signal, _outcome, _net in rows
    ) / len(rows)
    gains = sum(max(0.0, value[4]) for value in trades)
    losses = -sum(min(0.0, value[4]) for value in trades)
    profit_factor = gains / max(losses, 1e-12)
    frequency = len(trades) / len(rows)
    accuracy = sum(
        (signal == row.label) or (signal == "NO_TRADE" and row.label == "NO_TRADE")
        for row, _probability, signal, _outcome, _net in rows
    ) / len(rows)
    return (
        len(trades), long_count, short_count, net_ev, net_pnl,
        log_loss, brier, profit_factor, frequency, accuracy,
    )


def _sum_by(
    rows: tuple[tuple[str, str, str, str, str, float], ...], index: int,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in rows:
        key = cast(str, row[index])
        values[key] = values.get(key, 0.0) + row[5]
    return values


def _dimensions_payload(value: StabilityDimensions) -> dict[str, object]:
    return {
        "regimes": dict(value.regimes), "months": dict(value.months),
        "directions": dict(value.directions), "target_codes": dict(value.target_codes),
        "events": dict(value.events), "total_net_pnl": value.total_net_pnl,
        "cost_complete": value.cost_complete,
    }
