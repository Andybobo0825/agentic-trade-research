from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from tmf_research.models.provenance import (
    Phase4FoldCapabilities,
    Phase4SourceRow,
    _issue_phase4_fold,
    _Phase4FoldPlanRegistry,
    _PLANNER_AUTHORITY,
)


class TestPhase4FoldPlanner:
    """Test-only adapter for the private future Phase 5 planner boundary."""

    __test__ = False

    def __init__(self) -> None:
        self._registry = _Phase4FoldPlanRegistry(_PLANNER_AUTHORITY)

    def issue(
        self,
        *,
        source_rows: Sequence[Phase4SourceRow],
        outer_fold_id: str,
        inner_fold_id: str,
        train_start: datetime,
        train_end: datetime,
        validation_start: datetime,
        validation_end: datetime,
        outer_test_start: datetime,
        outer_test_end: datetime,
    ) -> Phase4FoldCapabilities:
        return _issue_phase4_fold(
            registry=self._registry,
            planner_authority=_PLANNER_AUTHORITY,
            source_rows=source_rows,
            outer_fold_id=outer_fold_id,
            inner_fold_id=inner_fold_id,
            train_start=train_start,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            outer_test_start=outer_test_start,
            outer_test_end=outer_test_end,
        )


TEST_PHASE4_FOLD_PLANNER = TestPhase4FoldPlanner()
