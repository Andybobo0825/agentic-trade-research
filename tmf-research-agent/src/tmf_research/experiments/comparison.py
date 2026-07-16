from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tmf_research.models.provenance import NestedFoldManifest


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
        for name in ("outer_fold_plan_hash", "cost_assumption_hash"):
            value = getattr(self, name)
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a SHA-256 hash")


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


def canonical_fold_periods(manifests: Sequence[NestedFoldManifest]) -> tuple[str, str]:
    values = tuple(manifests)
    if not values or any(not isinstance(value, NestedFoldManifest) for value in values):
        raise ValueError("canonical temporal coverage requires sealed fold manifests")
    train_start = min(value.inner_train.start for value in values)
    train_end = max(value.inner_validation.end for value in values)
    evaluation_start = min(value.outer_test.start for value in values)
    evaluation_end = max(value.outer_test.end for value in values)
    return (
        f"{train_start.isoformat()}/{train_end.isoformat()}",
        f"{evaluation_start.isoformat()}/{evaluation_end.isoformat()}",
    )


def require_canonical_fold_periods(
    train_period: str,
    evaluation_period: str,
    manifests: Sequence[NestedFoldManifest],
) -> None:
    expected_train, expected_evaluation = canonical_fold_periods(manifests)
    if train_period != expected_train or evaluation_period != expected_evaluation:
        raise ValueError("preregistered temporal periods do not match canonical fold coverage")
