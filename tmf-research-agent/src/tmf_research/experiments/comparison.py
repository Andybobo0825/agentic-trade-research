from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ComparisonContext:
    dataset_version: str
    outer_fold_plan_hash: str
    cost_assumption_hash: str
    label_version: str
    evaluation_period: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (
            self.dataset_version,
            self.outer_fold_plan_hash,
            self.cost_assumption_hash,
            self.label_version,
            self.evaluation_period,
        )):
            raise ValueError("complete comparison context is required")


def require_comparable(left: ComparisonContext, right: ComparisonContext) -> None:
    mismatches = tuple(
        name
        for name in (
            "dataset_version",
            "outer_fold_plan_hash",
            "cost_assumption_hash",
            "label_version",
            "evaluation_period",
        )
        if getattr(left, name) != getattr(right, name)
    )
    if mismatches:
        raise ValueError("experiments are incomparable: " + ",".join(mismatches))
