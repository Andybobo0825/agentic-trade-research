from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from types import MappingProxyType

from tmf_research.experiments.registry import (
    ExperimentRegistryEvidence,
    ModelStatus,
)
from tmf_research.experiments.comparison import require_canonical_fold_periods
from tmf_research.validation.data_provenance import DataProvenanceEvidence, DataProvenanceKind
from tmf_research.validation.dataset_lineage import DatasetBuildResult, DatasetLineageEvidence
from tmf_research.validation.fold_evaluation import ProductionEvaluation
from tmf_research.models.calibration import TwoStageCalibrationSelection
from tmf_research.models.provenance import NestedFoldManifest
from tmf_research.validation.ablation import ABLATION_GROUPS, AblationComparison
from tmf_research.validation.locked_holdout import LockedHoldoutApprovalEvidence
from tmf_research.validation.overfitting import (
    FoldEvidence,
    GeneralizationGap,
    ModelDecision,
    ResearchStatus,
    StabilityDimensions,
    _core_reasons,
    generalization_gap,
)
from tmf_research.validation.report import FoldReport
from tmf_research.validation.stability import FeatureCoefficientStability, parameter_fragility


_CALIBRATION_SEAL = object()
_SENSITIVITY_SEAL = object()
_BUNDLE_SEAL = object()
_APPROVAL_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class CalibrationFoldEvidence:
    fold_id: str
    manifest_hash: str
    validation_hash: str
    candidate_eligible: bool
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> CalibrationFoldEvidence:
        raise TypeError("calibration evidence must be issued from inner-validation calibration")

    def __post_init__(self) -> None:
        if self._seal is not _CALIBRATION_SEAL:
            raise TypeError("calibration evidence must derive from Phase 4 inner-validation selection")
        for value in (self.manifest_hash, self.validation_hash):
            if len(value) != 64:
                raise ValueError("calibration provenance hashes are required")


def calibration_fold_evidence(
    manifest: NestedFoldManifest,
    selection: TwoStageCalibrationSelection,
) -> CalibrationFoldEvidence:
    if selection.calibrator.provenance.manifest != manifest:
        raise ValueError("calibration selection does not belong to the planner fold manifest")
    instance = object.__new__(CalibrationFoldEvidence)
    for name, value in (
        ("fold_id", manifest.outer_fold_id),
        ("manifest_hash", manifest.content_hash),
        ("validation_hash", selection.calibrator.validation_hash),
        ("candidate_eligible", selection.candidate_eligible),
        ("_seal", _CALIBRATION_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


@dataclass(frozen=True, slots=True, init=False)
class SensitivityEvidence:
    fold_id: str
    manifest_hash: str
    result_hash: str
    parameter_fragility: bool
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> SensitivityEvidence:
        raise TypeError("sensitivity evidence must be issued from the fixed parameter grid")

    def __post_init__(self) -> None:
        if self._seal is not _SENSITIVITY_SEAL:
            raise TypeError("sensitivity evidence must derive from the fixed parameter neighborhood")
        if len(self.manifest_hash) != 64 or len(self.result_hash) != 64:
            raise ValueError("sensitivity provenance hashes are required")


def sensitivity_evidence(
    manifest: NestedFoldManifest,
    results: Mapping[tuple[float, float, float], float],
    selected: tuple[float, float, float],
) -> SensitivityEvidence:
    fragile = parameter_fragility(results, selected)
    payload = {
        "manifest_hash": manifest.content_hash,
        "selected": list(selected),
        "results": [
            {"parameters": list(key), "net_ev": value}
            for key, value in sorted(results.items())
        ],
    }
    instance = object.__new__(SensitivityEvidence)
    for name, value in (
        ("fold_id", manifest.outer_fold_id), ("manifest_hash", manifest.content_hash),
        ("result_hash", _hash(payload)), ("parameter_fragility", fragile),
        ("_seal", _SENSITIVITY_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


@dataclass(frozen=True, slots=True, init=False)
class Phase5EvidenceBundle:
    folds: tuple[FoldEvidence, ...]
    reports: tuple[FoldReport, ...]
    gaps: tuple[GeneralizationGap, ...]
    dimensions: StabilityDimensions
    ablations: tuple[AblationComparison, ...]
    coefficients: tuple[FeatureCoefficientStability, ...]
    sensitivities: tuple[SensitivityEvidence, ...]
    calibrations: tuple[CalibrationFoldEvidence, ...]
    experiment: ExperimentRegistryEvidence
    holdout: LockedHoldoutApprovalEvidence | None
    data_provenance: DataProvenanceEvidence
    dataset_lineage: DatasetLineageEvidence | None
    production_evaluation_hash: str | None
    production_evaluation: ProductionEvaluation | None
    content_hash: str
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> Phase5EvidenceBundle:
        raise TypeError("Phase 5 evidence must be issued by the authoritative assembler")

    def __post_init__(self) -> None:
        if self._seal is not _BUNDLE_SEAL:
            raise TypeError("Phase 5 evidence bundles must be assembled from verified typed evidence")
        if len(self.content_hash) != 64:
            raise ValueError("Phase 5 evidence hash is required")


def assemble_phase5_evidence(
    *,
    folds: Sequence[FoldEvidence],
    reports: Sequence[FoldReport],
    gaps: Sequence[GeneralizationGap],
    dimensions: StabilityDimensions,
    ablations: Sequence[AblationComparison],
    coefficients: Sequence[FeatureCoefficientStability],
    sensitivities: Sequence[SensitivityEvidence],
    calibrations: Sequence[CalibrationFoldEvidence],
    experiment: ExperimentRegistryEvidence,
    holdout: LockedHoldoutApprovalEvidence | None,
    data_provenance: DataProvenanceEvidence,
    dataset_lineage: DatasetLineageEvidence | DatasetBuildResult | None = None,
    production_evaluation: ProductionEvaluation | None = None,
) -> Phase5EvidenceBundle:
    if isinstance(dataset_lineage, DatasetBuildResult):
        dataset_build: DatasetBuildResult | None = dataset_lineage
        authoritative_lineage: DatasetLineageEvidence | None = dataset_lineage.lineage
    elif isinstance(dataset_lineage, DatasetLineageEvidence):
        dataset_build = None
        authoritative_lineage = dataset_lineage
    else:
        dataset_build = None
        authoritative_lineage = None
    fold_values, report_values, gap_values = tuple(folds), tuple(reports), tuple(gaps)
    if data_provenance.kind is DataProvenanceKind.REAL_READONLY_MARKET_DATA:
        if dataset_build is None or not isinstance(production_evaluation, ProductionEvaluation):
            raise ValueError("real Phase 5 evidence requires sealed raw-derived production evaluation")
        if production_evaluation.dataset_build_hash != dataset_build.content_hash:
            raise ValueError("production evaluation does not belong to exact dataset build")
        production_evaluation.__post_init__()
        if (
            production_evaluation.experiment.experiment_id != experiment.experiment_id
            or production_evaluation.experiment.checkpoint_hash != experiment.checkpoint_hash
            or production_evaluation.experiment.terminal_anchor_hash
            != experiment.terminal_anchor_hash
            or dict(production_evaluation.experiment.candidate_hashes)
            != dict(experiment.candidate_hashes)
            or production_evaluation.cost_policy_hash
            != experiment.comparison.cost_assumption_hash
        ):
            raise ValueError("production evaluation does not belong to exact experiment evidence")
        derived_folds = tuple(value.evidence for value in production_evaluation.folds)
        if (
            fold_values != derived_folds
            or report_values != production_evaluation.reports
            or gap_values != production_evaluation.gaps
            or dimensions != production_evaluation.dimensions
            or tuple(ablations) != production_evaluation.ablations
            or tuple(coefficients) != production_evaluation.coefficients
            or tuple(sensitivities) != production_evaluation.sensitivities
            or tuple(calibrations) != production_evaluation.calibrations
        ):
            raise ValueError(
                "caller evidence cannot replace any raw/model-derived production artifact"
            )
        if (
            production_evaluation.policy.thresholds_hash
            != experiment.candidate_hashes["thresholds"]
            or production_evaluation.policy.rules_hash
            != experiment.candidate_hashes["rules"]
        ):
            raise ValueError("production decision policy does not match preregistered candidate")
    else:
        if production_evaluation is not None:
            raise ValueError("synthetic mechanics cannot carry production evaluation authority")
        if any(value.authority != "TEST_ONLY" for value in fold_values):
            raise ValueError("synthetic mechanics require explicit TEST_ONLY fold authority")
    keys = tuple((fold.fold_id, fold.manifest_hash) for fold in fold_values)
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("Phase 5 evidence requires unique planner fold IDs/manifests")
    if tuple((report.fold_id, report.manifest_hash) for report in report_values) != keys:
        raise ValueError("fold report IDs/manifests do not align with planner evidence")
    if tuple((gap.fold_id, gap.manifest_hash) for gap in gap_values) != keys:
        raise ValueError("generalization gap IDs/manifests do not align with planner evidence")
    for fold, report, gap in zip(fold_values, report_values, gap_values, strict=True):
        if gap != generalization_gap(fold):
            raise ValueError("generalization gap is not derived from its fold metrics")
        if (
            report.classification["log_loss"] != fold.test_log_loss
            or report.classification["brier_score"] != fold.test_brier
            or report.trading["trade_count"] != fold.trade_count
            or report.trading["candidate_count"] != fold.test_candidates
            or report.trading["long_count"] != fold.long_count
            or report.trading["short_count"] != fold.short_count
            or report.trading["net_pnl"] != fold.net_pnl
        ):
            raise ValueError("fold report metrics do not reconcile with fold evidence")
    ablation_values = tuple(ablations)
    if tuple(value.removed_group for value in ablation_values) != ABLATION_GROUPS:
        raise ValueError("all eight ordered ablation comparisons are required")
    fold_ids = tuple(fold.fold_id for fold in fold_values)
    if any(tuple(value.fold_id for value in comparison.full_model_folds) != fold_ids for comparison in ablation_values):
        raise ValueError("ablation folds do not align with planner evidence")
    coefficient_values = tuple(coefficients)
    if not coefficient_values:
        raise ValueError("coefficient and removal-performance evidence is required")
    if any({item.fold_id for item in value.observations} != set(fold_ids) for value in coefficient_values):
        raise ValueError("coefficient observations must cover every unique outer fold")
    sensitivity_values = tuple(sensitivities)
    calibration_values = tuple(calibrations)
    expected_keys = set(keys)
    if {(value.fold_id, value.manifest_hash) for value in sensitivity_values} != expected_keys:
        raise ValueError("parameter sensitivity evidence must cover every planner fold")
    if {(value.fold_id, value.manifest_hash) for value in calibration_values} != expected_keys:
        raise ValueError("calibration evidence must cover every planner fold")
    if not isinstance(experiment, ExperimentRegistryEvidence) or experiment.attempt_count <= 0:
        raise ValueError("verified immutable experiment attempts are required")
    if not isinstance(data_provenance, DataProvenanceEvidence):
        raise TypeError("Phase 5 evidence requires sealed data provenance")
    experiment.assert_current()
    expected_fold_plan_hash = _hash([fold.manifest_hash for fold in fold_values])
    if experiment.comparison.outer_fold_plan_hash != expected_fold_plan_hash:
        raise ValueError("experiment comparison context does not match the exact outer fold plan")
    if experiment.comparison.dataset_version != data_provenance.dataset_version:
        raise ValueError("experiment comparison context does not match data provenance")
    require_canonical_fold_periods(
        experiment.train_period,
        experiment.comparison.evaluation_period,
        tuple(fold.manifest for fold in fold_values),
    )
    data_provenance.assert_current()
    if data_provenance.kind is DataProvenanceKind.SYNTHETIC_TEST_ONLY and holdout is not None:
        raise ValueError("synthetic evidence cannot consume a production locked holdout")
    if holdout is not None:
        holdout.assert_current()
        if dict(holdout.candidate_hashes) != dict(experiment.candidate_hashes):
            raise ValueError("holdout freeze and experiment candidate hashes do not match")
        if holdout.cost_model_hash != experiment.comparison.cost_assumption_hash:
            raise ValueError("holdout evaluation cost model does not match experiment context")
        if (
            dataset_build is None
            or holdout.authority != "RAW_DERIVED"
            or authoritative_lineage is None
            or authoritative_lineage.raw_dataset_hash != data_provenance.dataset_hash
            or tuple(value.manifest for value in dataset_build.fold_capabilities)
            != tuple(value.manifest for value in fold_values)
            or not authoritative_lineage.binds(
                fold_values,
                selection_hash=holdout.selection_hash,
                data_hash=holdout.data_hash,
            )
        ):
            raise ValueError("raw, fold, and locked holdout dataset lineage is not authoritatively bound")
    _validate_report_stability(
        fold_values, report_values, gap_values, dimensions,
        coefficient_values, sensitivity_values,
    )
    payload = _phase5_payload(
        fold_values, report_values, gap_values, dimensions, ablation_values,
        coefficient_values, sensitivity_values, calibration_values,
        experiment, holdout, data_provenance, authoritative_lineage,
        None if production_evaluation is None else production_evaluation.content_hash,
    )
    instance = object.__new__(Phase5EvidenceBundle)
    values: dict[str, object] = {
        "folds": fold_values, "reports": report_values, "gaps": gap_values,
        "dimensions": dimensions, "ablations": ablation_values,
        "coefficients": coefficient_values, "sensitivities": sensitivity_values,
        "calibrations": calibration_values, "experiment": experiment,
        "holdout": holdout, "data_provenance": data_provenance,
        "dataset_lineage": authoritative_lineage,
        "production_evaluation_hash": (
            None if production_evaluation is None else production_evaluation.content_hash
        ),
        "production_evaluation": production_evaluation,
        "content_hash": _hash(payload), "_seal": _BUNDLE_SEAL,
    }
    for name, value in values.items():
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


@dataclass(frozen=True, slots=True, init=False)
class ApprovalCapability:
    evidence_hash: str
    data_provenance_hash: str
    dataset_lineage_hash: str
    holdout_state_hash: str
    holdout_evaluation_hash: str
    holdout_cost_model_hash: str
    holdout_terminal_anchor_hash: str
    experiment_checkpoint_hash: str
    experiment_terminal_anchor_hash: str
    candidate_hashes: Mapping[str, str]
    fold_manifest_hashes: tuple[str, ...]
    model_status: ModelStatus
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> ApprovalCapability:
        raise TypeError("approval capability must be issued by the Phase 5 decision gate")

    def __post_init__(self) -> None:
        if self._seal is not _APPROVAL_SEAL or self.model_status is not ModelStatus.APPROVED_FOR_PAPER:
            raise TypeError("approval capability can only be issued by all derived Phase 5 gates")
        for value in (
            self.evidence_hash, self.data_provenance_hash, self.dataset_lineage_hash, self.holdout_state_hash,
            self.holdout_evaluation_hash, self.holdout_cost_model_hash,
            self.holdout_terminal_anchor_hash,
            self.experiment_checkpoint_hash, self.experiment_terminal_anchor_hash,
            *self.candidate_hashes.values(), *self.fold_manifest_hashes,
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("approval capability requires complete provenance hashes")
        if set(self.candidate_hashes) != {"model", "features", "labels", "parameters", "thresholds", "rules"}:
            raise ValueError("approval capability requires every frozen candidate component")
        if len(self.fold_manifest_hashes) < 5 or len(set(self.fold_manifest_hashes)) != len(self.fold_manifest_hashes):
            raise ValueError("approval capability requires at least five unique outer fold manifests")


@dataclass(frozen=True, slots=True)
class Phase5DecisionResult:
    decision: ModelDecision
    approval: ApprovalCapability | None


def decide_phase5(bundle: Phase5EvidenceBundle) -> Phase5DecisionResult:
    if not isinstance(bundle, Phase5EvidenceBundle):
        raise TypeError("decision requires a sealed Phase5EvidenceBundle")
    authoritative_hash = _hash(_phase5_payload(
        bundle.folds, bundle.reports, bundle.gaps, bundle.dimensions, bundle.ablations,
        bundle.coefficients, bundle.sensitivities, bundle.calibrations,
        bundle.experiment, bundle.holdout, bundle.data_provenance, bundle.dataset_lineage,
        bundle.production_evaluation_hash,
    ))
    if authoritative_hash != bundle.content_hash:
        raise ValueError("Phase 5 evidence was mutated after provenance binding")
    bundle.data_provenance.assert_current()
    if bundle.dataset_lineage is not None:
        bundle.dataset_lineage.assert_current()
    if bundle.production_evaluation is not None:
        bundle.production_evaluation.__post_init__()
    bundle.experiment.assert_current()
    if bundle.holdout is not None:
        bundle.holdout.assert_current()
    valid, ratios, core_reasons = _core_reasons(bundle.folds, bundle.dimensions)
    reasons = list(core_reasons)
    reasons.extend(
        f"GENERALIZATION_RISK:{gap.fold_id}:{reason}"
        for gap in bundle.gaps for reason in gap.high_risk_reasons
    )
    if any(not value.candidate_eligible for value in bundle.calibrations):
        reasons.append("CALIBRATION_EVIDENCE_INSUFFICIENT")
    if any(value.parameter_fragility for value in bundle.sensitivities):
        reasons.append("PARAMETER_FRAGILITY")
    if any(value.unstable_feature for value in bundle.coefficients):
        reasons.append("COEFFICIENT_OR_REMOVAL_INSTABILITY")
    if any(not value.group_supported for value in bundle.ablations):
        reasons.append("ABLATION_MAJORITY_SUPPORT_FAILED")
    if len(valid) < 5:
        research = ResearchStatus.INSUFFICIENT_DATA
        status = ModelStatus.REJECTED_INSUFFICIENT_DATA
    elif reasons:
        research = ResearchStatus.REJECTED
        status = ModelStatus.REJECTED_OVERFIT_RISK
    elif bundle.data_provenance.kind is DataProvenanceKind.SYNTHETIC_TEST_ONLY:
        research = ResearchStatus.COMPLETE
        status = ModelStatus.CANDIDATE
        reasons.append("SYNTHETIC_TEST_ONLY_CANNOT_APPROVE")
    elif bundle.holdout is None:
        research = ResearchStatus.COMPLETE
        status = ModelStatus.LOCKED_TEST_PENDING
    else:
        research = ResearchStatus.COMPLETE
        status = ModelStatus.APPROVED_FOR_PAPER
    decision = ModelDecision(
        research, status, bundle.content_hash, len(valid),
        float(ratios["positive"] or 0.0), float(ratios["baseline"] or 0.0),
        float(ratios["brier"] or 0.0), float(ratios["log_loss"] or 0.0),
        _optional_float(ratios["fold"]), _optional_float(ratios["month"]),
        _optional_float(ratios["direction"]), tuple(reasons),
    )
    if status is not ModelStatus.APPROVED_FOR_PAPER:
        return Phase5DecisionResult(decision, None)
    assert bundle.holdout is not None
    assert bundle.dataset_lineage is not None
    approval = object.__new__(ApprovalCapability)
    for name, value in (
        ("evidence_hash", bundle.content_hash),
        ("data_provenance_hash", bundle.data_provenance.content_hash),
        ("dataset_lineage_hash", bundle.dataset_lineage.content_hash),
        ("holdout_state_hash", bundle.holdout.state_hash),
        ("holdout_evaluation_hash", bundle.holdout.evaluation_hash),
        ("holdout_cost_model_hash", bundle.holdout.cost_model_hash),
        ("holdout_terminal_anchor_hash", bundle.holdout.terminal_anchor_hash),
        ("experiment_checkpoint_hash", bundle.experiment.checkpoint_hash),
        ("experiment_terminal_anchor_hash", bundle.experiment.terminal_anchor_hash),
        ("candidate_hashes", MappingProxyType(dict(bundle.experiment.candidate_hashes))),
        ("fold_manifest_hashes", tuple(fold.manifest_hash for fold in bundle.folds)),
        ("model_status", ModelStatus.APPROVED_FOR_PAPER),
        ("_seal", _APPROVAL_SEAL),
    ):
        object.__setattr__(approval, name, value)
    approval.__post_init__()
    return Phase5DecisionResult(decision, approval)


def _optional_float(value: float | None) -> float | None:
    return None if value is None else float(value)


def _validate_report_stability(
    folds: tuple[FoldEvidence, ...],
    reports: tuple[FoldReport, ...],
    gaps: tuple[GeneralizationGap, ...],
    dimensions: StabilityDimensions,
    coefficients: tuple[FeatureCoefficientStability, ...],
    sensitivities: tuple[SensitivityEvidence, ...],
) -> None:
    valid = tuple(fold for fold in folds if fold.sample_sufficient)
    total = dimensions.total_net_pnl
    valid_count = len(valid)
    expected = {
        "positive_fold_ratio": sum(fold.test_ev >= 0.0 for fold in valid) / valid_count if valid_count else 0.0,
        "baseline_outperformance_ratio": sum(fold.test_ev > fold.baseline_net_ev for fold in valid) / valid_count if valid_count else 0.0,
        "coefficient_sign_stability": min(value.dominant_sign_ratio for value in coefficients),
        "feature_rank_stability": min(value.feature_rank_stability for value in coefficients),
        "parameter_sensitivity": sum(not value.parameter_fragility for value in sensitivities) / len(sensitivities),
        "monthly_contribution_concentration": _reported_concentration(dimensions.months.values(), total),
        "directional_contribution_concentration": _reported_concentration(dimensions.directions.values(), total),
        "fold_profit_concentration": _reported_concentration((fold.net_pnl for fold in valid), total),
    }
    for report, gap in zip(reports, gaps, strict=True):
        for name, value in expected.items():
            reported = report.stability[name]
            if not isinstance(reported, (int, float)) or isinstance(reported, bool) or not math.isclose(float(reported), value, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"fold report stability metric {name} does not reconcile with evidence")
        train_test_gap = max(abs(value) for value in (
            gap.log_loss, gap.brier, gap.expected_value, gap.profit_factor,
            gap.trade_frequency, gap.accuracy,
        ))
        reported_gap = report.stability["train_test_gap"]
        if not isinstance(reported_gap, (int, float)) or isinstance(reported_gap, bool) or not math.isclose(float(reported_gap), train_test_gap, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("fold report train_test_gap does not reconcile with derived gap evidence")


def _phase5_payload(
    folds: Sequence[FoldEvidence],
    reports: Sequence[FoldReport],
    gaps: Sequence[GeneralizationGap],
    dimensions: StabilityDimensions,
    ablations: Sequence[AblationComparison],
    coefficients: Sequence[FeatureCoefficientStability],
    sensitivities: Sequence[SensitivityEvidence],
    calibrations: Sequence[CalibrationFoldEvidence],
    experiment: ExperimentRegistryEvidence,
    holdout: LockedHoldoutApprovalEvidence | None,
    data_provenance: DataProvenanceEvidence,
    dataset_lineage: DatasetLineageEvidence | None,
    production_evaluation_hash: str | None,
) -> dict[str, object]:
    return {
        "folds": [{
            "manifest_hash": value.manifest_hash,
            "fold_id": value.fold_id,
            "authority": value.authority,
            "derivation_hash": value.derivation_hash,
            "counts": [value.train_candidates, value.test_candidates, value.trade_count, value.long_count, value.short_count],
            "metrics": [
                value.train_ev, value.test_ev, value.baseline_net_ev, value.baseline_brier,
                value.baseline_log_loss, value.net_pnl, value.train_log_loss, value.test_log_loss,
                value.train_brier, value.test_brier, value.train_profit_factor, value.test_profit_factor,
                value.train_trade_frequency, value.test_trade_frequency, value.train_accuracy, value.test_accuracy,
            ],
        } for value in folds],
        "reports": [{
            "fold_id": value.fold_id, "manifest_hash": value.manifest_hash,
            "split_regions": dict(value.split_regions), "classification": _classification_payload(value.classification),
            "trading": dict(value.trading), "stability": dict(value.stability),
        } for value in reports],
        "gaps": [{
            "fold_id": value.fold_id, "manifest_hash": value.manifest_hash,
            "values": [value.log_loss, value.brier, value.expected_value, value.profit_factor, value.trade_frequency, value.accuracy],
            "reasons": list(value.high_risk_reasons),
        } for value in gaps],
        "dimensions": {
            "regimes": dict(dimensions.regimes), "months": dict(dimensions.months),
            "directions": dict(dimensions.directions), "target_codes": dict(dimensions.target_codes),
            "events": dict(dimensions.events), "total_net_pnl": dimensions.total_net_pnl,
            "cost_complete": dimensions.cost_complete,
        },
        "ablations": [{
            "group": value.removed_group,
            "full": [[fold.fold_id, fold.log_loss, fold.brier_score, fold.net_ev, fold.trade_count, fold.maximum_drawdown] for fold in value.full_model_folds],
            "removed": [[fold.fold_id, fold.log_loss, fold.brier_score, fold.net_ev, fold.trade_count, fold.maximum_drawdown] for fold in value.removed_model_folds],
            "ratio": value.full_model_gain_ratio, "stability": value.fold_stability,
        } for value in ablations],
        "coefficients": [{
            "feature": value.feature,
            "observations": [[item.fold_id, item.coefficient, item.standardized_magnitude, item.rank, item.important] for item in value.observations],
            "removals": [[item.fold_id, item.full_model_net_ev, item.removed_model_net_ev] for item in value.removal_evidence],
            "median": value.median_coefficient, "sign": value.dominant_sign_ratio,
            "rank": value.feature_rank_stability, "removal": value.removal_support_ratio,
            "unstable": value.unstable_feature,
        } for value in coefficients],
        "sensitivities": [[value.fold_id, value.manifest_hash, value.result_hash, value.parameter_fragility] for value in sensitivities],
        "calibrations": [[value.fold_id, value.manifest_hash, value.validation_hash, value.candidate_eligible] for value in calibrations],
        "experiment": [
            experiment.experiment_id, experiment.definition_hash, experiment.search_manifest_hash,
            experiment.attempt_count, experiment.chain_head, experiment.checkpoint_hash,
            experiment.terminal_anchor_hash,
            experiment.train_period,
            experiment.comparison.dataset_version, experiment.comparison.outer_fold_plan_hash,
            experiment.comparison.cost_assumption_hash, experiment.comparison.label_version,
            experiment.comparison.evaluation_period,
            dict(experiment.candidate_hashes),
        ],
        "holdout": None if holdout is None else [
            holdout.selection_hash, holdout.candidate_hash, holdout.model_hash,
            holdout.data_hash, holdout.state_hash, holdout.evaluation_hash,
            holdout.cost_model_hash, holdout.terminal_anchor_hash,
            dict(holdout.candidate_hashes), holdout.epoch, holdout.status,
            holdout.authority,
        ],
        "provenance": data_provenance.content_hash,
        "dataset_lineage": None if dataset_lineage is None else dataset_lineage.content_hash,
        "production_evaluation": production_evaluation_hash,
    }


def _reported_concentration(values: Iterable[float], total: float) -> float:
    numeric = tuple(values)
    if total <= 0.0 or not numeric:
        return 0.0
    return max(max(0.0, value) / total for value in numeric)


def _classification_payload(values: Mapping[str, object]) -> dict[str, object]:
    payload = dict(values)
    table = payload.get("calibration_table")
    if isinstance(table, (tuple, list)):
        payload["calibration_table"] = [asdict(value) for value in table]
    return payload


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
