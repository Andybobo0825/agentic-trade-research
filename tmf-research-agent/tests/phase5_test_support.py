from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
import hashlib
import json

from tmf_research.models.calibration import fit_two_stage_calibrators
from tmf_research.models.provenance import Phase4SourceRow, TrainingLabel
from tmf_research.models.training import train_phase4_model
from tmf_research.experiments.comparison import ComparisonContext, canonical_fold_periods
from tmf_research.experiments.registry import ExperimentDefinition
from tmf_research.validation.ablation import (
    ABLATION_GROUPS,
    AblationComparison,
    AblationFoldResult,
    compare_all_ablations,
)
from tmf_research.validation.approval import (
    CalibrationFoldEvidence,
    SensitivityEvidence,
    calibration_fold_evidence,
    sensitivity_evidence,
)
from tmf_research.validation.overfitting import (
    FoldEvidence,
    GeneralizationGap,
    REGIME_FAMILIES,
    StabilityDimensions,
    generalization_gap,
    _issue_test_fold_evidence,
)
from tmf_research.validation.metrics import CalibrationRow
from tmf_research.validation.report import FoldReport
from tmf_research.validation.stability import (
    CoefficientObservation,
    FeatureCoefficientStability,
    FeatureRemovalEvidence,
    coefficient_stability,
)
from tmf_research.validation.data_provenance import DataProvenanceEvidence, _issue_synthetic_test_provenance
from tests.phase4_test_support import TestPhase4FoldPlanner
from tests.unit.test_phase4_training import training_spec


def synthetic_provenance() -> DataProvenanceEvidence:
    return _issue_synthetic_test_provenance("dataset-v1")


def regime_contributions(total: float) -> dict[str, float]:
    return {
        name: total / len(family)
        for family in REGIME_FAMILIES for name in family
    }


def replace_test_fold(fold: FoldEvidence, **changes: object) -> FoldEvidence:
    names = (
        "trade_count", "long_count", "short_count", "train_ev", "test_ev",
        "baseline_net_ev", "baseline_brier", "baseline_log_loss", "net_pnl",
        "train_log_loss", "test_log_loss", "train_brier", "test_brier",
        "train_profit_factor", "test_profit_factor", "train_trade_frequency",
        "test_trade_frequency", "train_accuracy", "test_accuracy",
    )
    manifest = changes.pop("manifest", fold.manifest)
    if changes.keys() - set(names):
        raise ValueError("unknown test fold override")
    values = tuple(changes.get(name, getattr(fold, name)) for name in names)
    return _issue_test_fold_evidence(manifest, *values)  # type: ignore[arg-type]


def aligned_definition(
    base: ExperimentDefinition,
    folds: tuple[FoldEvidence, ...],
    provenance: DataProvenanceEvidence,
) -> ExperimentDefinition:
    fold_hash = hashlib.sha256(
        json.dumps([fold.manifest_hash for fold in folds], separators=(",", ":")).encode()
    ).hexdigest()
    train_period, evaluation_period = canonical_fold_periods(tuple(fold.manifest for fold in folds))
    return replace(base, train_period=train_period, comparison=ComparisonContext(
        provenance.dataset_version, fold_hash,
        hashlib.sha256(b"phase5-complete-cost-model-v1").hexdigest(),
        base.label_version, evaluation_period,
    ))


def subset_fold_evidence(count: int) -> tuple[
    tuple[FoldEvidence, ...], tuple[FoldReport, ...], tuple[GeneralizationGap, ...],
    StabilityDimensions, tuple[AblationComparison, ...], tuple[FeatureCoefficientStability, ...],
    tuple[SensitivityEvidence, ...], tuple[CalibrationFoldEvidence, ...],
]:
    values = complete_fold_evidence()
    folds = values[0][:count]
    ablations = compare_all_ablations(
        values[4][0].full_model_folds[:count],
        {value.removed_group: value.removed_model_folds[:count] for value in values[4]},
    )
    coefficient = values[5][0]
    coefficients = coefficient_stability(
        coefficient.observations[:count], coefficient.removal_evidence[:count],
    )
    total = 10.0 * count
    dimensions = StabilityDimensions(
        regime_contributions(total), {f"m{index}": 10.0 for index in range(count)},
        {"LONG": total / 2.0, "SHORT": total / 2.0},
        {"TMF202607": total / 2.0, "TMF202608": total / 2.0}, total,
        {f"event-{index}": 10.0 for index in range(count)}, True,
    )
    reports = tuple(
        replace(report, stability={**report.stability, "fold_profit_concentration": 1.0 / count})
        for report in values[1][:count]
    )
    return (
        folds, reports, values[2][:count], dimensions, ablations,
        coefficients, values[6][:count], values[7][:count],
    )


@lru_cache(maxsize=1)
def complete_fold_evidence() -> tuple[
    tuple[FoldEvidence, ...],
    tuple[FoldReport, ...],
    tuple[GeneralizationGap, ...],
    StabilityDimensions,
    tuple[AblationComparison, ...],
    tuple[FeatureCoefficientStability, ...],
    tuple[SensitivityEvidence, ...],
    tuple[CalibrationFoldEvidence, ...],
]:
    planner = TestPhase4FoldPlanner()
    folds: list[FoldEvidence] = []
    reports: list[FoldReport] = []
    calibrations: list[CalibrationFoldEvidence] = []
    sensitivities: list[SensitivityEvidence] = []
    for fold_index in range(6):
        start = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=fold_index * 20)
        train_rows = tuple(
            _row(f"f{fold_index}-train-{index}", start + timedelta(minutes=index), index)
            for index in range(4_996)
        )
        validation_start = start + timedelta(minutes=5_100)
        validation_rows = tuple(
            _row(f"f{fold_index}-validation-{index}", validation_start + timedelta(minutes=index), index)
            for index in range(4)
        )
        test_start = start + timedelta(minutes=5_200)
        outer_rows = tuple(
            _row(f"f{fold_index}-outer-{index}", test_start + timedelta(minutes=index), index)
            for index in range(500)
        )
        materialized = planner.issue(
            source_rows=(*train_rows, *validation_rows, *outer_rows),
            outer_fold_id=f"outer-{fold_index + 1}", inner_fold_id=f"inner-{fold_index + 1}",
            train_start=start, train_end=start + timedelta(minutes=4_997),
            validation_start=validation_start, validation_end=validation_start + timedelta(minutes=5),
            outer_test_start=test_start, outer_test_end=test_start + timedelta(minutes=501),
        )
        trained = train_phase4_model(
            materialized.inner_train,
            replace(training_spec(), max_iterations=1),
        )
        calibration = fit_two_stage_calibrators(
            trained.predict_inner_validation(materialized.inner_validation),
            bin_count=1,
            minimum_bin_size=1,
        )
        calibrations.append(calibration_fold_evidence(materialized.manifest, calibration))
        sensitivity_results = {
            (0.5, 0.6, 1.5): 0.1, (1.0, 0.6, 1.5): 0.2, (2.0, 0.6, 1.5): 0.1,
            (1.0, 0.55, 1.5): 0.1, (1.0, 0.65, 1.5): 0.1,
            (1.0, 0.6, 1.25): 0.1, (1.0, 0.6, 1.75): 0.1,
        }
        sensitivities.append(sensitivity_evidence(materialized.manifest, sensitivity_results, (1.0, 0.6, 1.5)))
        evidence = _issue_test_fold_evidence(
            materialized.manifest, 30, 15, 15,
            0.15, 0.20, 0.10, 0.25, 0.60, 10.0,
            0.55, 0.55, 0.22, 0.22, 1.10, 1.10, 0.04, 0.04, 0.60, 0.60,
        )
        folds.append(evidence)
        reports.append(_report(evidence))
    fold_values = tuple(folds)
    fold_ids = tuple(value.fold_id for value in fold_values)
    full = tuple(AblationFoldResult(fold_id, 0.55, 0.22, 0.20, 30, 2.0) for fold_id in fold_ids)
    removed = {
        group: tuple(AblationFoldResult(fold_id, 0.60, 0.25, 0.10, 30, 2.5) for fold_id in fold_ids)
        for group in ABLATION_GROUPS
    }
    ablations = compare_all_ablations(full, removed)
    observations = tuple(
        CoefficientObservation(fold_id, "return_1m", 1.0 + index * 0.01, 1.0, 1, True)
        for index, fold_id in enumerate(fold_ids)
    )
    removals = tuple(FeatureRemovalEvidence(fold_id, "return_1m", 0.2, 0.1) for fold_id in fold_ids)
    coefficients = coefficient_stability(observations, removals)
    dimensions = StabilityDimensions(
        regime_contributions(60.0),
        {"2026-01": 15.0, "2026-02": 15.0, "2026-03": 15.0, "2026-04": 15.0},
        {"LONG": 30.0, "SHORT": 30.0},
        {"TMF202607": 30.0, "TMF202608": 30.0},
        60.0,
        {f"event-{index}": 10.0 for index in range(6)},
        True,
    )
    return (
        fold_values, tuple(reports), tuple(generalization_gap(value) for value in fold_values), dimensions,
        tuple(ablations), coefficients, tuple(sensitivities), tuple(calibrations),
    )


def _row(row_id: str, available_at: datetime, index: int) -> Phase4SourceRow:
    labels: tuple[TrainingLabel, ...] = ("NO_TRADE", "LONG", "SHORT")
    return Phase4SourceRow(
        row_id, available_at, {"return_1m": float(index % 7), "basis": float(index % 11)},
        labels[index % 3], float(index % 3 - 1),
    )


def _report(fold: FoldEvidence) -> FoldReport:
    return FoldReport(
        fold.fold_id, fold.manifest_hash,
        {"TRAIN": "train", "INNER_VALIDATION": "validation", "OUTER_TEST": "test", "LOCKED_HOLDOUT": "locked"},
        {
            "log_loss": fold.test_log_loss, "brier_score": fold.test_brier, "roc_auc": 0.6,
            "precision": 0.5, "recall": 0.5, "f1": 0.5,
            "confusion_matrix": ((200, 50), (50, 200)),
            "expected_calibration_error": 0.05,
            "calibration_table": (CalibrationRow(0.0, 1.0, 500, 0.5, 0.5, fold.test_ev, True),),
        },
        {
            "candidate_count": fold.test_candidates,
            "trade_count": fold.trade_count, "long_count": fold.long_count, "short_count": fold.short_count,
            "win_rate": 0.6, "average_win": 2.0, "average_loss": -1.0,
            "average_net_points": fold.test_ev, "gross_pnl": 60.0, "net_pnl": fold.net_pnl,
            "profit_factor": fold.test_profit_factor, "maximum_drawdown": 2.0,
            "longest_losing_streak": 2, "expected_value_per_trade": fold.test_ev,
            "expected_value_per_day": 1.0, "average_holding_time": 5.0,
            "exposure_ratio": 0.1, "turnover": 1.0,
        },
        {
            "positive_fold_ratio": 1.0, "baseline_outperformance_ratio": 1.0,
            "coefficient_sign_stability": 1.0, "feature_rank_stability": 1.0,
            "parameter_sensitivity": 1.0, "monthly_contribution_concentration": 0.25,
            "directional_contribution_concentration": 0.5,
            "fold_profit_concentration": 1.0 / 6.0, "train_test_gap": 0.05,
        },
    )
