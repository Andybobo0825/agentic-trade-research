from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from tmf_research.models.calibration import CalibrationMetrics, TwoStageCalibrationSelection
from tmf_research.models.provenance import InnerValidationPredictions
from tmf_research.validation.folds import PlannedFold, SelectorFold


SELECTABLE_PARAMETERS = frozenset({
    "l2", "max_iterations", "learning_rate", "barrier", "feature_subset",
    "trade_threshold", "direction_threshold", "calibration_method",
})
_CANDIDATE_SEAL = object()
_FROZEN_SELECTION_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class SelectionCandidate:
    candidate_id: str
    manifest_hash: str
    validation_prediction_hash: str
    parameters: Mapping[str, object]
    metrics: CalibrationMetrics
    sparse_calibration_bins: bool
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> SelectionCandidate:
        raise TypeError("selection candidates must be issued from inner-validation evidence")

    def __post_init__(self) -> None:
        if self._seal is not _CANDIDATE_SEAL:
            raise TypeError("selection candidates require sealed InnerValidationPredictions")
        if not self.candidate_id.strip() or set(self.parameters) - SELECTABLE_PARAMETERS:
            raise ValueError("candidate id/parameter scope is invalid")
        _sha256(self.manifest_hash, "manifest")
        _sha256(self.validation_prediction_hash, "validation predictions")
        copied = json.loads(json.dumps(dict(self.parameters), allow_nan=False))
        if not isinstance(copied, dict):
            raise ValueError("selection parameters must be a JSON object")
        object.__setattr__(self, "parameters", MappingProxyType(copied))


def inner_selection_candidate(
    candidate_id: str,
    predictions: InnerValidationPredictions,
    calibration: TwoStageCalibrationSelection,
    *,
    parameters: Mapping[str, object],
) -> SelectionCandidate:
    if not isinstance(predictions, InnerValidationPredictions):
        raise TypeError("selection evidence must be sealed InnerValidationPredictions")
    if calibration.calibrator.validation_hash != predictions.validation_hash:
        raise ValueError("calibration and inner-validation prediction evidence mismatch")
    if calibration.calibrator.validation_provenance != predictions.provenance:
        raise ValueError("calibration provenance does not match inner-validation capability")
    selected = (calibration.trade.selected.metrics, calibration.direction.selected.metrics)
    metrics = CalibrationMetrics(
        brier_score=sum(value.brier_score for value in selected) / 2.0,
        log_loss=sum(value.log_loss for value in selected) / 2.0,
        expected_calibration_error=sum(value.expected_calibration_error for value in selected) / 2.0,
        expected_value=sum(value.expected_value for value in selected) / 2.0,
    )
    instance = object.__new__(SelectionCandidate)
    values: dict[str, object] = {
        "candidate_id": candidate_id,
        "manifest_hash": predictions.provenance.parent_provenance.manifest.content_hash,
        "validation_prediction_hash": predictions.validation_hash,
        "parameters": dict(parameters),
        "metrics": metrics,
        "sparse_calibration_bins": not calibration.candidate_eligible,
        "_seal": _CANDIDATE_SEAL,
    }
    for name, value in values.items():
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


@dataclass(frozen=True, slots=True)
class SelectionResult:
    candidate: SelectionCandidate | None
    status: str
    ordered_candidate_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in ("SELECTED", "INSUFFICIENT_CALIBRATION_EVIDENCE"):
            raise ValueError("selection status is fixed")


def select_on_inner_validation(candidates: Sequence[SelectionCandidate]) -> SelectionResult:
    if not candidates or any(not isinstance(candidate, SelectionCandidate) for candidate in candidates):
        raise ValueError("sealed inner-validation candidates are required")
    manifests = {candidate.manifest_hash for candidate in candidates}
    if len(manifests) != 1:
        raise ValueError("candidate comparison must use one exact inner-validation fold manifest")
    ordered = tuple(sorted(candidates, key=lambda item: (item.metrics.sort_key, item.candidate_id)))
    eligible = tuple(item for item in ordered if not item.sparse_calibration_bins)
    if not eligible:
        return SelectionResult(None, "INSUFFICIENT_CALIBRATION_EVIDENCE", tuple(item.candidate_id for item in ordered))
    return SelectionResult(eligible[0], "SELECTED", tuple(item.candidate_id for item in ordered))


@dataclass(frozen=True, slots=True, init=False)
class FrozenSelection:
    candidate_id: str
    manifest_hash: str
    parameter_hash: str
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> FrozenSelection:
        raise TypeError("frozen selections must be issued from a sealed selection result")

    def __post_init__(self) -> None:
        if self._seal is not _FROZEN_SELECTION_SEAL:
            raise TypeError("frozen selection must derive from a sealed inner-validation result")
        for name, value in (("manifest", self.manifest_hash), ("parameter", self.parameter_hash)):
            _sha256(value, name)


def freeze_selection(result: SelectionResult) -> FrozenSelection:
    if result.status != "SELECTED" or result.candidate is None:
        raise ValueError("only an eligible inner-validation candidate can be frozen")
    candidate = result.candidate
    payload = json.dumps(dict(candidate.parameters), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    instance = object.__new__(FrozenSelection)
    for name, value in (
        ("candidate_id", candidate.candidate_id),
        ("manifest_hash", candidate.manifest_hash),
        ("parameter_hash", hashlib.sha256(payload).hexdigest()),
        ("_seal", _FROZEN_SELECTION_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def evaluate_only(selection: FrozenSelection, *, candidate_id: str, parameter_hash: str, manifest_hash: str) -> None:
    if not isinstance(selection, FrozenSelection):
        raise TypeError("outer evaluation requires a sealed frozen inner selection")
    if (
        selection.candidate_id != candidate_id
        or selection.parameter_hash != parameter_hash
        or selection.manifest_hash != manifest_hash
    ):
        raise ValueError("Outer Test/Holdout cannot relabel or change the frozen inner selection")


@dataclass(frozen=True, slots=True)
class OuterEvaluationResult:
    outer_fold_id: str
    manifest_hash: str
    candidate_id: str
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.outer_fold_id.strip() or not self.candidate_id.strip() or not self.metrics:
            raise ValueError("outer evaluation evidence is required")
        _sha256(self.manifest_hash, "outer manifest")
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in self.metrics.values()):
            raise ValueError("outer metrics must be finite numbers")
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


def run_nested_walk_forward(
    folds: Sequence[PlannedFold],
    *,
    select: Callable[[SelectorFold], FrozenSelection],
    evaluate: Callable[[FrozenSelection, tuple[object, ...]], OuterEvaluationResult],
) -> tuple[OuterEvaluationResult, ...]:
    results = []
    seen: set[str] = set()
    for fold in folds:
        manifest = fold.capabilities.manifest
        if manifest.content_hash in seen:
            raise ValueError("outer fold manifests must be unique")
        seen.add(manifest.content_hash)
        selection = select(fold.selector)
        if selection.manifest_hash != manifest.content_hash:
            raise ValueError("selector returned evidence from a different planner fold manifest")
        result = evaluate(selection, tuple(fold.evaluation.outer_test))
        if (
            result.outer_fold_id != fold.evaluation.outer_fold_id
            or result.candidate_id != selection.candidate_id
            or result.manifest_hash != manifest.content_hash
        ):
            raise ValueError("outer evaluator changed fold, manifest, or frozen candidate identity")
        results.append(result)
    return tuple(results)


def _sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"invalid {name} SHA-256")
