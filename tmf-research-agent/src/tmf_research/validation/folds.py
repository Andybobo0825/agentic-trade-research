from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from tmf_research.models.provenance import (
    Phase4FoldCapabilities,
    Phase4SourceRow,
    _issue_phase4_fold,
    _Phase4FoldPlanRegistry,
    _PLANNER_AUTHORITY,
)
from tmf_research.validation.purging import purge_and_embargo, validate_embargo


@dataclass(frozen=True, slots=True)
class TemporalSample:
    source: Phase4SourceRow
    decision_time: datetime
    outcome_time: datetime
    trading_date: str

    def __post_init__(self) -> None:
        for name, value in (("decision_time", self.decision_time), ("outcome_time", self.outcome_time)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.source.available_at > self.decision_time:
            raise ValueError("source evidence is not available at decision time")
        if self.outcome_time <= self.decision_time:
            raise ValueError("outcome must follow decision time")
        if not self.trading_date.strip():
            raise ValueError("effective trading date is required")


@dataclass(frozen=True, slots=True)
class SelectorFold:
    outer_fold_id: str
    inner_fold_id: str
    inner_train: tuple[TemporalSample, ...]
    inner_validation: tuple[TemporalSample, ...]

    def __post_init__(self) -> None:
        if not self.inner_train or not self.inner_validation:
            raise ValueError("selector folds require train and validation rows")
        if max(row.decision_time for row in self.inner_train) >= min(
            row.decision_time for row in self.inner_validation
        ):
            raise ValueError("inner folds must be chronological and disjoint")


@dataclass(frozen=True, slots=True)
class EvaluationFold:
    outer_fold_id: str
    outer_test: tuple[TemporalSample, ...]

    def __post_init__(self) -> None:
        if not self.outer_test:
            raise ValueError("outer test rows are required")


@dataclass(frozen=True, slots=True)
class PlannedFold:
    selector: SelectorFold
    evaluation: EvaluationFold
    capabilities: Phase4FoldCapabilities

    def __post_init__(self) -> None:
        if hasattr(self.selector, "outer_test"):
            raise ValueError("outer test capability must not be exposed to selectors")


class Phase5FoldPlanner:
    """Only public fold issuer; Phase 4's materializer remains private and pinned."""

    __slots__ = ("_embargo", "_registry")

    def __init__(
        self,
        *,
        split_strategy: str = "chronological",
        embargo_minutes: int = 60,
        model_horizons_minutes: Sequence[int] = (5, 15, 60),
    ) -> None:
        normalized = split_strategy.strip().lower().replace("-", "_")
        if normalized != "chronological":
            raise ValueError("random, shuffled, stratified, and KFold splits are forbidden")
        self._embargo = validate_embargo(embargo_minutes, model_horizons_minutes)
        self._registry = _Phase4FoldPlanRegistry(_PLANNER_AUTHORITY)

    def plan(
        self,
        rows: Sequence[TemporalSample],
        *,
        outer_test_size: int,
        inner_validation_size: int,
        minimum_outer_train_size: int,
        step_size: int | None = None,
    ) -> tuple[PlannedFold, ...]:
        if any(isinstance(value, bool) or value <= 0 for value in (
            outer_test_size,
            inner_validation_size,
            minimum_outer_train_size,
        )):
            raise ValueError("fold sizes must be positive integers")
        ordered = tuple(sorted(rows, key=lambda row: (row.decision_time, row.source.row_id)))
        if tuple(rows) != ordered:
            raise ValueError("input rows must already be chronological; shuffle is forbidden")
        if len({row.source.row_id for row in ordered}) != len(ordered):
            raise ValueError("fold rows require unique identifiers")
        step = outer_test_size if step_size is None else step_size
        if isinstance(step, bool) or step <= 0:
            raise ValueError("step size must be positive")
        planned: list[PlannedFold] = []
        test_start_index = minimum_outer_train_size
        while test_start_index + outer_test_size <= len(ordered):
            outer_train = ordered[:test_start_index]
            outer_test = ordered[test_start_index : test_start_index + outer_test_size]
            if len(outer_train) <= inner_validation_size:
                test_start_index += step
                continue
            validation_start_index = len(outer_train) - inner_validation_size
            raw_train = outer_train[:validation_start_index]
            raw_validation = outer_train[validation_start_index:]
            validation_start = raw_validation[0].decision_time
            outer_test_start = outer_test[0].decision_time
            inner_train = purge_and_embargo(raw_train, validation_start, self._embargo)
            # Sealed inner-validation datasets only admit complete known
            # outcomes, so ineligible rows leave this role (and only this
            # role) before the fold commitment is issued.
            inner_validation = tuple(
                row
                for row in purge_and_embargo(raw_validation, outer_test_start, self._embargo)
                if row.source.label != "AMBIGUOUS" and row.source.is_complete
            )
            if inner_train and inner_validation:
                number = len(planned) + 1
                outer_id = f"outer-{number:03d}"
                inner_id = f"inner-{number:03d}"
                selector = SelectorFold(outer_id, inner_id, inner_train, inner_validation)
                evaluation = EvaluationFold(outer_id, tuple(outer_test))
                capabilities = self._issue(selector, evaluation)
                planned.append(PlannedFold(selector, evaluation, capabilities))
            test_start_index += step
        return tuple(planned)

    def _issue(self, selector: SelectorFold, evaluation: EvaluationFold) -> Phase4FoldCapabilities:
        train = tuple(row.source for row in selector.inner_train)
        validation = tuple(row.source for row in selector.inner_validation)
        test = tuple(row.source for row in evaluation.outer_test)
        train_start, train_end = _interval(train)
        validation_start, validation_end = _interval(validation)
        test_start, test_end = _interval(test)
        if not (train_end < validation_start and validation_end < test_start):
            raise ValueError("purged fold intervals must be strictly ordered")
        return _issue_phase4_fold(
            registry=self._registry,
            planner_authority=_PLANNER_AUTHORITY,
            source_rows=(*train, *validation, *test),
            outer_fold_id=selector.outer_fold_id,
            inner_fold_id=selector.inner_fold_id,
            train_start=train_start,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            outer_test_start=test_start,
            outer_test_end=test_end,
        )


def _interval(rows: Sequence[Phase4SourceRow]) -> tuple[datetime, datetime]:
    if not rows:
        raise ValueError("fold role cannot be empty")
    ordered = tuple(sorted(row.available_at for row in rows))
    return ordered[0], ordered[-1] + timedelta(microseconds=1)
