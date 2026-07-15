from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from tmf_research.models.calibration import CalibrationMetrics
from tmf_research.validation.folds import PlannedFold, SelectorFold


SELECTABLE_PARAMETERS = frozenset({
    "l2",
    "max_iterations",
    "learning_rate",
    "barrier",
    "feature_subset",
    "trade_threshold",
    "direction_threshold",
    "calibration_method",
})


@dataclass(frozen=True, slots=True)
class SelectionCandidate:
    candidate_id: str
    evidence_role: Literal["INNER_VALIDATION", "OUTER_TEST", "LOCKED_HOLDOUT"]
    parameters: Mapping[str, object]
    metrics: CalibrationMetrics
    sparse_calibration_bins: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate id is required")
        if set(self.parameters) - SELECTABLE_PARAMETERS:
            raise ValueError("candidate includes a parameter outside the preregistered selection scope")
        object.__setattr__(self, "parameters", dict(self.parameters))


@dataclass(frozen=True, slots=True)
class SelectionResult:
    candidate: SelectionCandidate | None
    status: Literal["SELECTED", "INSUFFICIENT_CALIBRATION_EVIDENCE"]
    ordered_candidate_ids: tuple[str, ...]


def select_on_inner_validation(candidates: Sequence[SelectionCandidate]) -> SelectionResult:
    if not candidates:
        raise ValueError("inner validation candidates are required")
    if any(candidate.evidence_role != "INNER_VALIDATION" for candidate in candidates):
        raise ValueError("Outer Test and Locked Holdout may evaluate only and cannot select parameters")
    ordered = tuple(sorted(candidates, key=lambda item: (item.metrics.sort_key, item.candidate_id)))
    eligible = tuple(item for item in ordered if not item.sparse_calibration_bins)
    if not eligible:
        return SelectionResult(None, "INSUFFICIENT_CALIBRATION_EVIDENCE", tuple(item.candidate_id for item in ordered))
    return SelectionResult(eligible[0], "SELECTED", tuple(item.candidate_id for item in ordered))


@dataclass(frozen=True, slots=True)
class FrozenSelection:
    candidate_id: str
    parameter_hash: str

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or len(self.parameter_hash) != 64:
            raise ValueError("frozen selection requires id and SHA-256")


def evaluate_only(selection: FrozenSelection, *, candidate_id: str, parameter_hash: str) -> None:
    if selection.candidate_id != candidate_id or selection.parameter_hash != parameter_hash:
        raise ValueError("Outer Test/Holdout evaluation cannot change the frozen inner selection")


@dataclass(frozen=True, slots=True)
class OuterEvaluationResult:
    outer_fold_id: str
    candidate_id: str
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.outer_fold_id.strip() or not self.candidate_id.strip() or not self.metrics:
            raise ValueError("outer evaluation evidence is required")
        object.__setattr__(self, "metrics", dict(self.metrics))


def run_nested_walk_forward(
    folds: Sequence[PlannedFold],
    *,
    select: Callable[[SelectorFold], FrozenSelection],
    evaluate: Callable[[FrozenSelection, tuple[object, ...]], OuterEvaluationResult],
) -> tuple[OuterEvaluationResult, ...]:
    """Keep selection and outer evaluation capabilities structurally separate."""
    results = []
    for fold in folds:
        selection = select(fold.selector)
        outer_rows: tuple[object, ...] = tuple(fold.evaluation.outer_test)
        result = evaluate(selection, outer_rows)
        if result.outer_fold_id != fold.evaluation.outer_fold_id or result.candidate_id != selection.candidate_id:
            raise ValueError("outer evaluator changed fold or frozen inner candidate identity")
        results.append(result)
    return tuple(results)
