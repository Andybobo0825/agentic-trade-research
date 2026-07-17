from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, cast

from tmf_research.models.calibration import TwoStageCalibrationSelection, fit_two_stage_calibrators
from tmf_research.models.provenance import (
    FrozenDecisionPolicy,
    OuterTestPredictions,
    Phase4FoldCapabilities,
    Phase4SourceRow,
    _generated_prediction,
    _generated_predictions,
    canonical_hash,
    freeze_decision_policy,
)
from tmf_research.models.training import (
    Phase4TrainingResult,
    Phase4TrainingSpec,
    _train_phase4_feature_subset,
)
from tmf_research.experiments.registry import (
    ExperimentRegistryEvidence,
    phase4_bundle_evidence_hash,
    phase4_candidate_hashes,
)
from tmf_research.models.serialization import ModelBundle
from tmf_research.features.definitions import default_feature_manifest
from tmf_research.validation.dataset_lineage import DatasetBuildResult, ExecutableOutcome
from tmf_research.validation.ablation import (
    ABLATION_GROUPS,
    AblationComparison,
    AblationFoldResult,
    compare_all_ablations,
)
from tmf_research.validation.metrics import (
    CalibrationRow,
    TradeResult,
    classification_metrics,
    trading_metrics,
)
from tmf_research.validation.report import FoldReport
from tmf_research.validation.stability import (
    CoefficientObservation,
    FeatureCoefficientStability,
    FeatureRemovalEvidence,
    coefficient_stability,
)

if TYPE_CHECKING:
    from tmf_research.validation.approval import CalibrationFoldEvidence, SensitivityEvidence
from tmf_research.validation.overfitting import (
    REQUIRED_REGIMES,
    FoldEvidence,
    GeneralizationGap,
    StabilityDimensions,
    _issue_fold_evidence,
    generalization_gap,
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
    regime_observation_counts: tuple[tuple[str, int], ...]
    calibration_evidence: CalibrationFoldEvidence | None
    ablation_results: tuple[tuple[str, AblationFoldResult], ...]
    coefficient_observations: tuple[CoefficientObservation, ...]
    feature_removal_evidence: tuple[FeatureRemovalEvidence, ...]
    sensitivity_evidence: SensitivityEvidence | None
    sensitivity_results: tuple[tuple[tuple[float, float, float], float], ...]
    training_spec_hash: str | None
    training_feature_order: tuple[str, ...]
    training_l2: float | None
    training_random_seed: int | None
    experiment_checkpoint_hash: str | None
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
            "regime_observations": [list(value) for value in self.regime_observation_counts],
            "calibration": None if self.calibration_evidence is None else self.calibration_evidence.validation_hash,
            "ablations": [[name, value.log_loss, value.brier_score, value.net_ev, value.trade_count, value.maximum_drawdown] for name, value in self.ablation_results],
            "coefficients": [[value.feature, value.coefficient, value.rank] for value in self.coefficient_observations],
            "removals": [[value.feature, value.removed_model_net_ev] for value in self.feature_removal_evidence],
            "sensitivity": None if self.sensitivity_evidence is None else self.sensitivity_evidence.result_hash,
            "sensitivity_results": [[list(key), value] for key, value in self.sensitivity_results],
            "training_spec": self.training_spec_hash,
            "training_contract": [
                list(self.training_feature_order), self.training_l2,
                self.training_random_seed,
            ],
            "experiment": self.experiment_checkpoint_hash,
        })
        if expected != self.content_hash:
            raise ValueError("outer fold evaluation content hash mismatch")


@dataclass(frozen=True, slots=True, init=False)
class ProductionEvaluation:
    folds: tuple[SealedFoldEvaluation, ...]
    reports: tuple[FoldReport, ...]
    gaps: tuple[GeneralizationGap, ...]
    dimensions: StabilityDimensions
    ablations: tuple[AblationComparison, ...]
    coefficients: tuple[FeatureCoefficientStability, ...]
    sensitivities: tuple[SensitivityEvidence, ...]
    calibrations: tuple[CalibrationFoldEvidence, ...]
    experiment: ExperimentRegistryEvidence
    candidate_bundle: ModelBundle
    candidate_bundle_hash: str
    cost_policy_hash: str
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
        self.experiment.assert_current()
        if phase4_bundle_evidence_hash(self.candidate_bundle) != self.candidate_bundle_hash:
            raise ValueError("production evaluation lost exact final candidate bundle")
        if self.dataset_build.content_hash != self.dataset_build_hash:
            raise ValueError("production evaluation lost exact dataset build")
        if {value.cost_policy_hash for value in self.dataset_build.development_outcomes} != {
            self.cost_policy_hash
        }:
            raise ValueError("production evaluation lost exact cost policy")
        if any(
            value.experiment_checkpoint_hash != self.experiment.checkpoint_hash
            for value in self.folds
        ):
            raise ValueError("production folds lost the exact experiment checkpoint")
        expected = canonical_hash({
            "build": self.dataset_build_hash,
            "folds": [value.content_hash for value in self.folds],
            "reports": [_report_payload(value) for value in self.reports],
            "gaps": [_gap_payload(value) for value in self.gaps],
            "dimensions": _dimensions_payload(self.dimensions),
            "ablations": [_ablation_payload(value) for value in self.ablations],
            "coefficients": [_coefficient_payload(value) for value in self.coefficients],
            "sensitivities": [_sensitivity_payload(value) for value in self.sensitivities],
            "calibrations": [_calibration_payload(value) for value in self.calibrations],
            "experiment": self.experiment.checkpoint_hash,
            "cost_policy": self.cost_policy_hash,
            "candidate_bundle": self.candidate_bundle_hash,
        })
        if self.content_hash != expected:
            raise ValueError("production evaluation content hash mismatch")
        policy_contracts = {
            (
                value.policy.trade_threshold, value.policy.direction_threshold,
                value.policy.thresholds_hash, value.policy.rules_hash,
            )
            for value in self.folds
        }
        if len(policy_contracts) != 1:
            raise ValueError("all production folds require one fixed threshold/rule policy")

    @property
    def policy(self) -> FrozenDecisionPolicy:
        return self.folds[0].policy


def evaluate_outer_fold(
    build: DatasetBuildResult,
    capability: Phase4FoldCapabilities,
    training: Phase4TrainingResult,
    calibration: TwoStageCalibrationSelection,
    policy: FrozenDecisionPolicy,
    training_spec: Phase4TrainingSpec | None = None,
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
        row.label in ("LONG", "SHORT") for row in capability.inner_train.rows
    ) / len(capability.inner_train.rows)
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
    baseline_name = "BASELINES_0_TO_4"
    baseline_results: tuple[tuple[str, float, float, float], ...]
    if training_spec is None:
        baseline_net_ev = 0.0
        baseline_results = (("BASELINE_0", 0.0, baseline_brier, baseline_log_loss),)
    else:
        baseline_results = _required_baseline_results(
            capability, training_spec, outcome_by_id,
        )
        baseline_net_ev = max(value[1] for value in baseline_results)
        baseline_brier = min(value[2] for value in baseline_results)
        baseline_log_loss = min(value[3] for value in baseline_results)
    contribution_rows = tuple(
        (
            outcome.decision_time.strftime("%Y-%m"), signal, outcome.target_code,
            outcome.event_id, "|".join(outcome.regime_tags), net,
        )
        for _row, _p_trade, signal, outcome, net in test_values
        if signal != "NO_TRADE"
    )
    regime_observation_counts = tuple(
        (name, sum(name in outcome.regime_tags for outcome in outcomes))
        for name in sorted(REQUIRED_REGIMES)
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
        "baseline_results": [list(value) for value in baseline_results],
        "outcomes": [value.content_hash for value in outcomes],
        "contributions": [list(value) for value in contribution_rows],
        "regime_observations": [list(value) for value in regime_observation_counts],
        "ablations": [], "coefficients": [], "removals": [],
        "sensitivity": None, "sensitivity_results": [], "experiment": None,
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
    payload: dict[str, object] = {
        "fold": derivation_hash,
        "predictions": predictions.content_hash,
        "lineage": build.lineage.content_hash,
        "policy": policy.content_hash,
        "contributions": [list(value) for value in contribution_rows],
        "regime_observations": [list(value) for value in regime_observation_counts],
        "calibration": None,
        "ablations": [],
        "coefficients": [],
        "removals": [],
        "sensitivity": None,
        "sensitivity_results": [],
        "training_spec": None,
        "training_contract": [[], None, None],
        "experiment": None,
    }
    instance = object.__new__(SealedFoldEvaluation)
    for name, value in (
        ("evidence", evidence), ("predictions", predictions),
        ("lineage_hash", build.lineage.content_hash),
        ("policy", policy),
        ("contribution_rows", contribution_rows),
        ("regime_observation_counts", regime_observation_counts),
        ("calibration_evidence", None), ("ablation_results", ()),
        ("coefficient_observations", ()), ("feature_removal_evidence", ()),
        ("sensitivity_evidence", None), ("sensitivity_results", ()),
        ("training_spec_hash", None),
        ("training_feature_order", ()), ("training_l2", None),
        ("training_random_seed", None),
        ("experiment_checkpoint_hash", None),
        ("content_hash", canonical_hash(payload)), ("_seal", _FOLD_EVALUATION_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def evaluate_complete_outer_fold(
    build: DatasetBuildResult,
    capability: Phase4FoldCapabilities,
    training: Phase4TrainingResult,
    training_spec: Phase4TrainingSpec,
    calibration: TwoStageCalibrationSelection,
    policy: FrozenDecisionPolicy,
    experiment: ExperimentRegistryEvidence,
) -> SealedFoldEvaluation:
    """Run the fixed, preregistered Phase 5 diagnostic matrix on one outer fold."""

    from tmf_research.validation.approval import (
        calibration_fold_evidence,
        sensitivity_evidence,
    )

    experiment.assert_current()
    if experiment.attempt_count <= 0 or training.specification_hash != training_spec.content_hash:
        raise ValueError("complete fold evaluation requires an exact preregistered model run")
    if (
        policy.thresholds_hash != experiment.candidate_hashes["thresholds"]
        or policy.rules_hash != experiment.candidate_hashes["rules"]
    ):
        raise ValueError("complete fold policy does not match immutable experiment candidate")
    experiment.assert_successful_result({
        "dataset_build_hash": build.content_hash,
        "fold_manifest_hash": capability.manifest.content_hash,
        "training_spec_hash": training_spec.content_hash,
        "model_hash": training.model.content_hash,
        "calibration_hash": canonical_hash(calibration.calibrator.to_dict()),
        "policy_hash": policy.content_hash,
        "diagnostic_plan_hash": _diagnostic_plan_hash(training_spec, policy),
        "candidate_refit_contract_hash": _candidate_refit_contract_hash(
            build, training_spec, experiment,
        ),
    })
    base = evaluate_outer_fold(
        build, capability, training, calibration, policy, training_spec,
    )
    outcome_by_id = {value.row_id: value for value in build.development_outcomes}
    manifest = default_feature_manifest()
    group_alias = {
        "price": "PRICE", "vwap": "VWAP", "flow": "ORDER_FLOW",
        "orderbook": "ORDER_BOOK", "basis": "BASIS",
        "volatility": "VOLATILITY", "structure": "MARKET_STRUCTURE",
        "time": "TIME",
    }
    feature_groups = {
        value.name: group_alias[value.group] for value in manifest.primary_features
    }
    full_rows = _join_outer(base.predictions, capability.outer_test.rows, outcome_by_id)
    full_metrics = _metrics(full_rows)
    full_ablation = _ablation_result(capability.manifest.outer_fold_id, full_rows)
    ablation_results: list[tuple[str, AblationFoldResult]] = [("FULL", full_ablation)]
    for group in ABLATION_GROUPS:
        removed_features = frozenset(
            name for name, value in feature_groups.items()
            if value == group and name in training_spec.primary_features
        )
        if not removed_features:
            raise ValueError(f"complete diagnostic is missing feature group {group}")
        subset = _subset_spec(
            training_spec,
            removed_features,
        )
        ablated = _train_phase4_feature_subset(capability.inner_train, subset)
        ablated_calibration = _fit_calibration(ablated, capability)
        ablated_policy = freeze_decision_policy(
            ablated_calibration,
            thresholds_hash=policy.thresholds_hash,
            rules_hash=policy.rules_hash,
        )
        scored = _score_rows(
            capability.outer_test.rows, ablated, ablated_calibration,
            ablated_policy, outcome_by_id,
        )
        ablation_results.append((
            group,
            _ablation_result(capability.manifest.outer_fold_id, scored),
        ))
    coefficient_observations_values: list[CoefficientObservation] = []
    for head_name, head in (
        ("TRADE", training.model.trade_model),
        ("DIRECTION", training.model.direction_model),
    ):
        coefficients = dict(zip(head.feature_order, head.coefficients, strict=True))
        ranked = tuple(sorted(
            coefficients, key=lambda name: (-abs(coefficients[name]), name),
        ))
        coefficient_observations_values.extend(
            CoefficientObservation(
                capability.manifest.outer_fold_id, f"{head_name}::{name}",
                coefficients[name], abs(coefficients[name]), index,
                index <= min(10, len(ranked)),
            )
            for index, name in enumerate(ranked, start=1)
        )
    coefficient_observations = tuple(coefficient_observations_values)
    removed_net_ev: dict[str, float] = {}
    for name in training_spec.raw_feature_order:
        subset = _subset_spec(training_spec, frozenset({name}))
        removed = _train_phase4_feature_subset(capability.inner_train, subset)
        removed_calibration = _fit_calibration(removed, capability)
        removed_policy = freeze_decision_policy(
            removed_calibration,
            thresholds_hash=policy.thresholds_hash,
            rules_hash=policy.rules_hash,
        )
        removed_metrics = _metrics(_score_rows(
            capability.outer_test.rows, removed, removed_calibration,
            removed_policy, outcome_by_id,
        ))
        removed_net_ev[name] = removed_metrics[3]
    feature_removals = tuple(
        FeatureRemovalEvidence(
            capability.manifest.outer_fold_id, observation.feature,
            full_metrics[3], removed_net_ev[_coefficient_source(observation.feature)],
        )
        for observation in coefficient_observations
    )
    selected = (training_spec.l2, policy.trade_threshold, 1.0)
    sensitivity: dict[tuple[float, float, float], float] = {selected: full_metrics[3]}
    for l2 in (0.5 * training_spec.l2, 2.0 * training_spec.l2):
        varied = _train_phase4_feature_subset(
            capability.inner_train, replace(training_spec, l2=l2),
        )
        varied_calibration = _fit_calibration(varied, capability)
        varied_policy = freeze_decision_policy(
            varied_calibration,
            thresholds_hash=policy.thresholds_hash,
            rules_hash=policy.rules_hash,
        )
        sensitivity[(l2, policy.trade_threshold, 1.0)] = _metrics(_score_rows(
            capability.outer_test.rows, varied, varied_calibration,
            varied_policy, outcome_by_id,
        ))[3]
    for threshold in (
        round(policy.trade_threshold - 0.05, 12),
        round(policy.trade_threshold + 0.05, 12),
    ):
        sensitivity[(training_spec.l2, threshold, 1.0)] = _metrics(
            _score_rows_thresholds(
                capability.outer_test.rows, training, calibration,
                threshold, policy.direction_threshold, outcome_by_id,
            ),
        )[3]
    primary_scored = _join_outer(
        base.predictions, capability.outer_test.rows, outcome_by_id,
    )
    for multiplier in (0.75, 1.25):
        sensitivity[(training_spec.l2, policy.trade_threshold, multiplier)] = (
            _atr_net_ev(primary_scored, multiplier)
        )
    sensitivity_item = sensitivity_evidence(
        capability.manifest, sensitivity, selected,
    )
    calibration_item = calibration_fold_evidence(capability.manifest, calibration)
    payload = {
        "fold": base.evidence.derivation_hash,
        "predictions": base.predictions.content_hash,
        "lineage": base.lineage_hash,
        "policy": base.policy.content_hash,
        "contributions": [list(value) for value in base.contribution_rows],
        "regime_observations": [list(value) for value in base.regime_observation_counts],
        "calibration": calibration_item.validation_hash,
        "ablations": [[name, value.log_loss, value.brier_score, value.net_ev, value.trade_count, value.maximum_drawdown] for name, value in ablation_results],
        "coefficients": [[value.feature, value.coefficient, value.rank] for value in coefficient_observations],
        "removals": [[value.feature, value.removed_model_net_ev] for value in feature_removals],
        "sensitivity": sensitivity_item.result_hash,
        "sensitivity_results": [[list(key), value] for key, value in sorted(sensitivity.items())],
        "training_spec": training_spec.content_hash,
        "training_contract": [
            list(training_spec.raw_feature_order), training_spec.l2,
            training_spec.random_seed,
        ],
        "experiment": experiment.checkpoint_hash,
    }
    instance = object.__new__(SealedFoldEvaluation)
    for name, value in (
        ("evidence", base.evidence), ("predictions", base.predictions),
        ("lineage_hash", base.lineage_hash), ("policy", base.policy),
        ("contribution_rows", base.contribution_rows),
        ("regime_observation_counts", base.regime_observation_counts),
        ("calibration_evidence", calibration_item),
        ("ablation_results", tuple(ablation_results)),
        ("coefficient_observations", coefficient_observations),
        ("feature_removal_evidence", feature_removals),
        ("sensitivity_evidence", sensitivity_item),
        ("sensitivity_results", tuple(sorted(sensitivity.items()))),
        ("training_spec_hash", training_spec.content_hash),
        ("training_feature_order", training_spec.raw_feature_order),
        ("training_l2", training_spec.l2),
        ("training_random_seed", training_spec.random_seed),
        ("experiment_checkpoint_hash", experiment.checkpoint_hash),
        ("content_hash", canonical_hash(payload)), ("_seal", _FOLD_EVALUATION_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def aggregate_production_evaluation(
    build: DatasetBuildResult,
    folds: tuple[SealedFoldEvaluation, ...],
    experiment: ExperimentRegistryEvidence,
    candidate_bundle: ModelBundle,
) -> ProductionEvaluation:
    build.assert_current()
    experiment.assert_current()
    if tuple(value.evidence.manifest for value in folds) != tuple(
        value.manifest for value in build.fold_capabilities
    ):
        raise ValueError("production aggregate requires every exact issued fold in order")
    if any(value.lineage_hash != build.lineage.content_hash for value in folds):
        raise ValueError("production folds do not share exact raw lineage")
    cost_policy_hashes = {value.cost_policy_hash for value in build.development_outcomes}
    if len(cost_policy_hashes) != 1:
        raise ValueError("production aggregate requires one exact cost policy")
    cost_policy_hash = next(iter(cost_policy_hashes))
    if any(
        value.experiment_checkpoint_hash != experiment.checkpoint_hash
        or value.training_spec_hash is None
        or value.calibration_evidence is None
        or value.sensitivity_evidence is None
        or tuple(name for name, _result in value.ablation_results)
        != ("FULL", *ABLATION_GROUPS)
        or not value.coefficient_observations
        or not value.feature_removal_evidence
        for value in folds
    ):
        raise ValueError("production aggregate requires every complete preregistered fold diagnostic")
    if len({value.training_spec_hash for value in folds}) != 1:
        raise ValueError("production folds require one exact training configuration")
    training_contracts = {
        (value.training_feature_order, value.training_l2, value.training_random_seed)
        for value in folds
    }
    if len(training_contracts) != 1:
        raise ValueError("production folds require one exact feature/parameter contract")
    feature_order, l2, random_seed = next(iter(training_contracts))
    if (
        dict(phase4_candidate_hashes(candidate_bundle))
        != dict(experiment.candidate_hashes)
        or candidate_bundle.metadata.experiment_id != experiment.experiment_id
        or candidate_bundle.metadata.label_version != experiment.comparison.label_version
        or candidate_bundle.feature_names != feature_order
        or candidate_bundle.metadata.random_seed != random_seed
        or candidate_bundle.model.trade_model.l2 != l2
        or candidate_bundle.model.direction_model.l2 != l2
    ):
        raise ValueError("final candidate bundle does not match evaluated fold contract")
    authorized_refits = tuple(
        capability for capability in build.fold_capabilities
        if candidate_bundle.preprocessor.provenance.manifest == capability.manifest
        and candidate_bundle.preprocessor.provenance.train_hash
        == capability.inner_train.train_hash
        and candidate_bundle.calibrator.validation_provenance.validation_dataset_hash
        == capability.inner_validation.validation_dataset_hash
    )
    if len(authorized_refits) != 1:
        raise ValueError(
            "final candidate bundle lacks an exact build-issued development refit capability"
        )
    candidate_bundle_hash = phase4_bundle_evidence_hash(candidate_bundle)
    if any(not value.evidence.sample_sufficient for value in folds):
        raise ValueError("production aggregate requires every outer fold to meet sample minima")
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
    regime_counts = {name: 0 for name in REQUIRED_REGIMES}
    for fold in folds:
        for name, count in fold.regime_observation_counts:
            regime_counts[name] = regime_counts.get(name, 0) + count
    missing_regimes = tuple(name for name, count in regime_counts.items() if count <= 0)
    if missing_regimes:
        raise ValueError(
            "production aggregate lacks observed regime coverage: "
            + ",".join(sorted(missing_regimes))
        )
    for row in contributions:
        for tag in row[4].split("|"):
            regimes[tag] = regimes.get(tag, 0.0) + row[5]
    dimensions = StabilityDimensions(
        regimes, months, directions, targets, total, events,
        all(value.cost_complete for value in build.development_outcomes),
    )
    full_ablations = tuple(dict(value.ablation_results)["FULL"] for value in folds)
    removed_by_group = {
        group: tuple(dict(value.ablation_results)[group] for value in folds)
        for group in ABLATION_GROUPS
    }
    ablations = compare_all_ablations(full_ablations, removed_by_group)
    coefficients = coefficient_stability(
        tuple(item for value in folds for item in value.coefficient_observations),
        tuple(item for value in folds for item in value.feature_removal_evidence),
    )
    sensitivities = tuple(cast("SensitivityEvidence", value.sensitivity_evidence) for value in folds)
    calibrations = tuple(cast("CalibrationFoldEvidence", value.calibration_evidence) for value in folds)
    gaps = tuple(generalization_gap(value.evidence) for value in folds)
    reports = tuple(
        _fold_report(
            value, gap, build, folds, dimensions, coefficients, sensitivities,
        )
        for value, gap in zip(folds, gaps, strict=True)
    )
    payload = {
        "build": build.content_hash,
        "folds": [value.content_hash for value in folds],
        "reports": [_report_payload(value) for value in reports],
        "gaps": [_gap_payload(value) for value in gaps],
        "dimensions": _dimensions_payload(dimensions),
        "ablations": [_ablation_payload(value) for value in ablations],
        "coefficients": [_coefficient_payload(value) for value in coefficients],
        "sensitivities": [_sensitivity_payload(value) for value in sensitivities],
        "calibrations": [_calibration_payload(value) for value in calibrations],
        "experiment": experiment.checkpoint_hash,
        "cost_policy": cost_policy_hash,
        "candidate_bundle": candidate_bundle_hash,
    }
    instance = object.__new__(ProductionEvaluation)
    for name, value in (
        ("folds", folds), ("reports", reports), ("gaps", gaps),
        ("dimensions", dimensions), ("ablations", ablations),
        ("coefficients", coefficients), ("sensitivities", sensitivities),
        ("calibrations", calibrations), ("experiment", experiment),
        ("candidate_bundle", candidate_bundle),
        ("candidate_bundle_hash", candidate_bundle_hash),
        ("cost_policy_hash", cost_policy_hash),
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


def _score_rows_thresholds(
    rows: tuple[Phase4SourceRow, ...],
    training: Phase4TrainingResult,
    calibration: TwoStageCalibrationSelection,
    trade_threshold: float,
    direction_threshold: float,
    outcomes: dict[str, ExecutableOutcome],
) -> tuple[tuple[Phase4SourceRow, float, str, ExecutableOutcome, float], ...]:
    if not 0.0 <= trade_threshold <= 1.0 or not 0.0 <= direction_threshold <= 1.0:
        raise ValueError("sensitivity thresholds must be probabilities")
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
            "NO_TRADE" if p_trade < trade_threshold
            else "LONG" if p_long >= direction_threshold else "SHORT"
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


def _required_baseline_results(
    capability: Phase4FoldCapabilities,
    specification: Phase4TrainingSpec,
    outcomes: dict[str, ExecutableOutcome],
) -> tuple[tuple[str, float, float, float], ...]:
    rows = capability.outer_test.rows
    signals: dict[str, list[str]] = {
        name: [] for name in (
            "BASELINE_0", "BASELINE_1", "BASELINE_2", "BASELINE_3", "BASELINE_4",
        )
    }
    previous_ema: float | None = None
    return_names = tuple(
        name for name in specification.primary_features if name.startswith("return_")
    )
    if not return_names:
        raise ValueError("required return-only baseline lacks return features")
    return_spec = _subset_spec(
        specification,
        frozenset(name for name in specification.raw_feature_order if name not in return_names),
    )
    return_model = _train_phase4_feature_subset(capability.inner_train, return_spec)
    for row in rows:
        signals["BASELINE_0"].append("NO_TRADE")
        signals["BASELINE_1"].append(_signed_signal(row.features.get("return_1m")))
        signals["BASELINE_2"].append(
            _signed_signal(row.features.get("price_to_session_vwap_atr")),
        )
        midpoint = row.features.get("midpoint")
        distance = row.features.get("ema_distance_5")
        ema = (
            float(midpoint) - float(distance)
            if midpoint is not None and distance is not None else None
        )
        signals["BASELINE_3"].append(
            "NO_TRADE" if ema is None or previous_ema is None
            else _signed_signal(ema - previous_ema)
        )
        if ema is not None:
            previous_ema = ema
        transformed = return_model.preprocessor.transform(row.features)
        if not transformed.is_eligible:
            signals["BASELINE_4"].append("NO_TRADE")
        else:
            probability = return_model.model.direction_model.predict_probability(
                transformed.values,
            )
            signals["BASELINE_4"].append(
                "NO_TRADE" if abs(probability - 0.5) <= 1e-15
                else "LONG" if probability > 0.5 else "SHORT"
            )
    results = []
    for name, values in signals.items():
        scored = []
        for row, signal in zip(rows, values, strict=True):
            outcome = outcomes[row.row_id]
            net = (
                outcome.long_net_points if signal == "LONG"
                else outcome.short_net_points if signal == "SHORT" else 0.0
            )
            scored.append((row, float(signal != "NO_TRADE"), signal, outcome, net))
        metrics = _metrics(tuple(scored))
        results.append((name, metrics[3], metrics[6], metrics[5]))
    return tuple(results)


def _signed_signal(value: float | None) -> str:
    if value is None or value == 0.0:
        return "NO_TRADE"
    return "LONG" if value > 0.0 else "SHORT"


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


def _subset_spec(
    specification: Phase4TrainingSpec,
    removed: frozenset[str],
) -> Phase4TrainingSpec:
    primary = tuple(name for name in specification.primary_features if name not in removed)
    if not primary:
        raise ValueError("diagnostic retraining cannot remove every primary feature")
    primary_names = set(primary)
    interactions = tuple(
        value for value in specification.interactions
        if value.name not in removed and set(value.inputs).issubset(primary_names)
    )
    available = primary_names | {value.name for value in interactions}
    return replace(
        specification,
        primary_features=primary,
        required_features=tuple(
            name for name in specification.required_features if name in available
        ),
        interactions=interactions,
        large_trade_features=tuple(
            name for name in specification.large_trade_features if name in available
        ),
    )


def _coefficient_source(feature: str) -> str:
    _head, separator, output = feature.partition("::")
    if not separator or not output:
        raise ValueError("coefficient feature lacks model-head identity")
    return output.removesuffix("__missing")


def _diagnostic_plan_hash(
    specification: Phase4TrainingSpec,
    policy: FrozenDecisionPolicy,
) -> str:
    return canonical_hash({
        "version": "phase5-fixed-diagnostics-v1",
        "ablations": list(ABLATION_GROUPS),
        "feature_removals": list(specification.raw_feature_order),
        "l2": [0.5 * specification.l2, specification.l2, 2.0 * specification.l2],
        "threshold": [
            round(policy.trade_threshold - 0.05, 12), policy.trade_threshold,
            round(policy.trade_threshold + 0.05, 12),
        ],
        "atr": [0.75, 1.0, 1.25],
        "random_seed": specification.random_seed,
        "calibration": {"bin_count": 10, "minimum_bin_size": 20},
        "baselines": [0, 1, 2, 3, 4],
    })


def _candidate_refit_contract_hash(
    build: DatasetBuildResult,
    specification: Phase4TrainingSpec,
    experiment: ExperimentRegistryEvidence,
) -> str:
    return canonical_hash({
        "version": "phase5-candidate-refit-contract-v1",
        "candidate_hashes": dict(experiment.candidate_hashes),
        "dataset_build_hash": build.content_hash,
        "build_spec_hash": build.lineage.build_spec_hash,
        "outer_fold_plan_hash": experiment.comparison.outer_fold_plan_hash,
        "training_spec_hash": specification.content_hash,
        "random_seed": specification.random_seed,
    })


def _fit_calibration(
    training: Phase4TrainingResult,
    capability: Phase4FoldCapabilities,
) -> TwoStageCalibrationSelection:
    generated = []
    for row in capability.inner_validation.rows:
        transformed = training.preprocessor.transform(row.features)
        if not transformed.is_eligible:
            raise ValueError("diagnostic calibration row is ineligible under the retrained subset")
        trade_outcome = int(row.label in ("LONG", "SHORT"))
        generated.append(_generated_prediction(
            source_row=row,
            p_trade=training.model.trade_model.predict_probability(transformed.values),
            trade_outcome=trade_outcome,
            p_long_given_trade=(
                training.model.direction_model.predict_probability(transformed.values)
                if trade_outcome else None
            ),
            direction_outcome=int(row.label == "LONG") if trade_outcome else None,
        ))
    predictions = _generated_predictions(
        provenance=capability.inner_validation.provenance,
        preprocessor_hash=training.preprocessor.content_hash,
        model_hash=training.model.content_hash,
        rows=generated,
    )
    return fit_two_stage_calibrators(predictions)


def _ablation_result(
    fold_id: str,
    rows: tuple[tuple[Phase4SourceRow, float, str, ExecutableOutcome, float], ...],
) -> AblationFoldResult:
    metrics = _metrics(rows)
    equity = 0.0
    peak = 0.0
    maximum_drawdown = 0.0
    for _row, _probability, signal, _outcome, net in rows:
        if signal == "NO_TRADE":
            continue
        equity += net
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    return AblationFoldResult(
        fold_id, metrics[5], metrics[6], metrics[3], metrics[0], maximum_drawdown,
    )


def _atr_net_ev(
    rows: tuple[tuple[Phase4SourceRow, float, str, ExecutableOutcome, float], ...],
    multiplier: float,
) -> float:
    results = []
    for _row, _probability, signal, outcome, _net in rows:
        if signal == "NO_TRADE":
            continue
        matches = tuple(
            value for value in outcome.atr_sensitivity
            if math.isclose(value[0], multiplier, rel_tol=0.0, abs_tol=1e-12)
        )
        if len(matches) != 1:
            raise ValueError("ATR sensitivity result is not exact and unique")
        _value, _label, long_net, short_net = matches[0]
        results.append(long_net if signal == "LONG" else short_net)
    return sum(results) / len(results) if results else 0.0


def _fold_report(
    value: SealedFoldEvaluation,
    gap: GeneralizationGap,
    build: DatasetBuildResult,
    folds: tuple[SealedFoldEvaluation, ...],
    dimensions: StabilityDimensions,
    coefficients: tuple[FeatureCoefficientStability, ...],
    sensitivities: tuple[SensitivityEvidence, ...],
) -> FoldReport:
    outcome_by_id = {
        item.row_id: item for item in build.development_outcomes
    }
    capability = next(
        item for item in build.fold_capabilities
        if item.manifest is value.evidence.manifest
    )
    scored = _join_outer(value.predictions, capability.outer_test.rows, outcome_by_id)
    classification = classification_metrics(
        tuple(int(row.label in ("LONG", "SHORT")) for row, *_rest in scored),
        tuple(probability for _row, probability, *_rest in scored),
        net_returns=tuple(net for *_rest, net in scored),
        threshold=value.policy.trade_threshold,
        bin_count=10,
        minimum_bin_size=20,
    )
    trades = tuple(
        TradeResult(
            signal,
            net,
            (
                outcome.long_gross_points
                if signal == "LONG" else outcome.short_gross_points
            ),
            (outcome.outcome_time - outcome.decision_time).total_seconds() / 60.0,
            outcome.decision_time.date().isoformat(),
        )
        for _row, _probability, signal, outcome, net in scored
        if signal != "NO_TRADE"
    )
    trading = trading_metrics(
        trades,
        candidate_count=len(scored),
        total_available_minutes=max(1.0, float(len(scored))),
    )
    valid_folds = tuple(
        item.evidence for item in folds
        if item.evidence.sample_sufficient
    )
    valid_count = len(valid_folds)
    stability = {
        "positive_fold_ratio": (
            sum(item.test_ev >= 0.0 for item in valid_folds) / valid_count
            if valid_count else 0.0
        ),
        "baseline_outperformance_ratio": (
            sum(item.test_ev > item.baseline_net_ev for item in valid_folds) / valid_count
            if valid_count else 0.0
        ),
        "coefficient_sign_stability": min(
            item.dominant_sign_ratio for item in coefficients
        ),
        "feature_rank_stability": min(
            item.feature_rank_stability for item in coefficients
        ),
        "parameter_sensitivity": (
            sum(not item.parameter_fragility for item in sensitivities) / len(sensitivities)
        ),
        "monthly_contribution_concentration": _concentration(
            dimensions.months.values(), dimensions.total_net_pnl,
        ),
        "directional_contribution_concentration": _concentration(
            dimensions.directions.values(), dimensions.total_net_pnl,
        ),
        "fold_profit_concentration": _concentration(
            (item.net_pnl for item in valid_folds), dimensions.total_net_pnl,
        ),
        "train_test_gap": max(abs(item) for item in (
            gap.log_loss, gap.brier, gap.expected_value, gap.profit_factor,
            gap.trade_frequency, gap.accuracy,
        )),
    }
    manifest = value.evidence.manifest
    return FoldReport(
        value.evidence.fold_id,
        value.evidence.manifest_hash,
        {
            "TRAIN": _region(manifest.inner_train.start, manifest.inner_train.end),
            "INNER_VALIDATION": _region(
                manifest.inner_validation.start, manifest.inner_validation.end,
            ),
            "OUTER_TEST": _region(manifest.outer_test.start, manifest.outer_test.end),
            "LOCKED_HOLDOUT": "SEALED_SUFFIX",
        },
        {
            "log_loss": classification.log_loss,
            "brier_score": classification.brier_score,
            "roc_auc": 0.5 if classification.roc_auc is None else classification.roc_auc,
            "precision": classification.precision,
            "recall": classification.recall,
            "f1": classification.f1,
            "confusion_matrix": classification.confusion_matrix,
            "expected_calibration_error": classification.expected_calibration_error,
            "calibration_table": classification.calibration_table,
        },
        {
            "candidate_count": len(scored),
            "trade_count": trading.trade_count,
            "long_count": trading.long_count,
            "short_count": trading.short_count,
            "win_rate": trading.win_rate,
            "average_win": trading.average_win,
            "average_loss": trading.average_loss,
            "average_net_points": trading.average_net_points,
            "gross_pnl": trading.gross_pnl,
            "net_pnl": trading.net_pnl,
            "profit_factor": trading.profit_factor,
            "maximum_drawdown": trading.maximum_drawdown,
            "longest_losing_streak": trading.longest_losing_streak,
            "expected_value_per_trade": trading.expected_value_per_trade,
            "expected_value_per_day": trading.expected_value_per_day,
            "average_holding_time": trading.average_holding_time,
            "exposure_ratio": trading.exposure_ratio,
            "turnover": trading.turnover,
        },
        stability,
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


def _concentration(values: Iterable[float], total: float) -> float:
    numeric = tuple(values)
    if total <= 0.0 or not numeric:
        return 0.0
    return max(max(0.0, float(value)) / total for value in numeric)


def _region(start: object, end: object) -> str:
    return f"{start!s}/{end!s}"


def _gap_payload(value: GeneralizationGap) -> dict[str, object]:
    return {
        "fold_id": value.fold_id,
        "manifest_hash": value.manifest_hash,
        "log_loss": value.log_loss,
        "brier": value.brier,
        "expected_value": value.expected_value,
        "profit_factor": value.profit_factor,
        "trade_frequency": value.trade_frequency,
        "accuracy": value.accuracy,
        "high_risk_reasons": list(value.high_risk_reasons),
    }


def _report_payload(value: FoldReport) -> dict[str, object]:
    classification = dict(value.classification)
    table = cast(Sequence[CalibrationRow], value.classification["calibration_table"])
    classification["calibration_table"] = [
        asdict(item) for item in table
    ]
    return {
        "fold_id": value.fold_id,
        "manifest_hash": value.manifest_hash,
        "split_regions": dict(value.split_regions),
        "classification": classification,
        "trading": dict(value.trading),
        "stability": dict(value.stability),
    }


def _ablation_fold_payload(value: AblationFoldResult) -> list[object]:
    return [
        value.fold_id, value.log_loss, value.brier_score, value.net_ev,
        value.trade_count, value.maximum_drawdown,
    ]


def _ablation_payload(value: AblationComparison) -> dict[str, object]:
    return {
        "removed_group": value.removed_group,
        "full_model_folds": [_ablation_fold_payload(item) for item in value.full_model_folds],
        "removed_model_folds": [
            _ablation_fold_payload(item) for item in value.removed_model_folds
        ],
        "full_model_gain_ratio": value.full_model_gain_ratio,
        "fold_stability": value.fold_stability,
    }


def _coefficient_payload(value: FeatureCoefficientStability) -> dict[str, object]:
    return {
        "feature": value.feature,
        "observations": [
            [
                item.fold_id, item.feature, item.coefficient,
                item.standardized_magnitude, item.rank, item.important,
            ]
            for item in value.observations
        ],
        "removals": [
            [
                item.fold_id, item.feature, item.full_model_net_ev,
                item.removed_model_net_ev,
            ]
            for item in value.removal_evidence
        ],
        "median_coefficient": value.median_coefficient,
        "dominant_sign_ratio": value.dominant_sign_ratio,
        "feature_rank_stability": value.feature_rank_stability,
        "removal_support_ratio": value.removal_support_ratio,
        "unstable_feature": value.unstable_feature,
    }


def _sensitivity_payload(value: SensitivityEvidence) -> list[object]:
    return [
        value.fold_id, value.manifest_hash, value.result_hash,
        value.parameter_fragility,
    ]


def _calibration_payload(value: CalibrationFoldEvidence) -> list[object]:
    return [
        value.fold_id, value.manifest_hash, value.validation_hash,
        value.candidate_eligible,
    ]
