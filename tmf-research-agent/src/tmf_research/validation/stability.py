from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureProfile:
    name: str
    train_values: tuple[float | None, ...]
    simplicity_rank: int
    cross_fold_stability: float
    evidence_role: str = "TRAIN"

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.train_values:
            raise ValueError("feature profile requires name and train values")
        if self.evidence_role != "TRAIN":
            raise ValueError("redundancy selection may use Train Fold only")
        if self.simplicity_rank < 0 or not math.isfinite(self.cross_fold_stability):
            raise ValueError("invalid feature priority evidence")

    @property
    def completeness(self) -> float:
        return sum(value is not None for value in self.train_values) / len(self.train_values)


@dataclass(frozen=True, slots=True)
class CorrelationGroup:
    members: tuple[str, ...]
    retained: str
    removed: tuple[str, ...]


def redundancy_groups(
    profiles: Sequence[FeatureProfile],
    *,
    threshold: float = 0.90,
) -> tuple[CorrelationGroup, ...]:
    if not 0.0 < threshold < 1.0 or not profiles:
        raise ValueError("valid train feature profiles and threshold are required")
    if len({profile.name for profile in profiles}) != len(profiles):
        raise ValueError("feature names must be unique")
    parents = {profile.name: profile.name for profile in profiles}

    def root(name: str) -> str:
        while parents[name] != name:
            parents[name] = parents[parents[name]]
            name = parents[name]
        return name

    def union(left: str, right: str) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    for index, left in enumerate(profiles):
        for right in profiles[index + 1 :]:
            if abs(_pearson(left.train_values, right.train_values)) > threshold:
                union(left.name, right.name)
    grouped: dict[str, list[FeatureProfile]] = {}
    for profile in profiles:
        grouped.setdefault(root(profile.name), []).append(profile)
    decisions = []
    for group in grouped.values():
        ordered = sorted(
            group,
            key=lambda profile: (
                -profile.completeness,
                profile.simplicity_rank,
                -profile.cross_fold_stability,
                profile.name,
            ),
        )
        decisions.append(
            CorrelationGroup(
                tuple(sorted(profile.name for profile in group)),
                ordered[0].name,
                tuple(profile.name for profile in ordered[1:]),
            )
        )
    return tuple(sorted(decisions, key=lambda group: group.members))


@dataclass(frozen=True, slots=True)
class CoefficientObservation:
    fold_id: str
    feature: str
    coefficient: float
    standardized_magnitude: float
    rank: int
    important: bool

    @property
    def sign(self) -> int:
        return 1 if self.coefficient > 0 else -1 if self.coefficient < 0 else 0


@dataclass(frozen=True, slots=True)
class FeatureCoefficientStability:
    feature: str
    observations: tuple[CoefficientObservation, ...]
    median_coefficient: float
    dominant_sign_ratio: float
    feature_rank_stability: float
    unstable_feature: bool


def coefficient_stability(
    observations: Sequence[CoefficientObservation],
    *,
    minimum_sign_ratio: float = 0.70,
    near_zero: float = 1e-12,
) -> tuple[FeatureCoefficientStability, ...]:
    grouped: dict[str, list[CoefficientObservation]] = {}
    for observation in observations:
        if not math.isfinite(observation.coefficient) or not math.isfinite(observation.standardized_magnitude):
            raise ValueError("coefficient evidence must be finite")
        grouped.setdefault(observation.feature, []).append(observation)
    reports = []
    for feature, values in sorted(grouped.items()):
        signs = tuple(value.sign for value in values if value.sign != 0)
        positive = sum(sign > 0 for sign in signs)
        negative = sum(sign < 0 for sign in signs)
        dominant = max(positive, negative) / len(values)
        median = statistics.median(value.coefficient for value in values)
        ranks = tuple(value.rank for value in values)
        rank_stability = 1.0 / (1.0 + statistics.pstdev(ranks)) if len(ranks) > 1 else 1.0
        important = any(value.important for value in values)
        unstable = (positive > 0 and negative > 0) or (important and dominant < minimum_sign_ratio) or (important and abs(median) <= near_zero)
        reports.append(FeatureCoefficientStability(feature, tuple(values), median, dominant, rank_stability, unstable))
    return tuple(reports)


@dataclass(frozen=True, slots=True)
class SensitivityGrid:
    l2: tuple[float, float, float]
    threshold: tuple[float, float, float]
    atr_multiplier: tuple[float, float, float]


def sensitivity_grid(l2: float, threshold: float, atr_multiplier: float) -> SensitivityGrid:
    if l2 <= 0.0 or not 0.05 <= threshold <= 0.95 or atr_multiplier <= 0.25:
        raise ValueError("selected parameters cannot support the required fixed neighborhood")
    return SensitivityGrid(
        (0.5 * l2, l2, 2.0 * l2),
        (round(threshold - 0.05, 12), threshold, round(threshold + 0.05, 12)),
        (round(atr_multiplier - 0.25, 12), atr_multiplier, round(atr_multiplier + 0.25, 12)),
    )


def parameter_fragility(
    results: Mapping[tuple[float, float, float], float],
    selected: tuple[float, float, float],
) -> bool:
    grid = sensitivity_grid(*selected)
    expected = {
        (grid.l2[0], selected[1], selected[2]),
        selected,
        (grid.l2[2], selected[1], selected[2]),
        (selected[0], grid.threshold[0], selected[2]),
        (selected[0], grid.threshold[2], selected[2]),
        (selected[0], selected[1], grid.atr_multiplier[0]),
        (selected[0], selected[1], grid.atr_multiplier[2]),
    }
    if not expected.issubset(results):
        raise ValueError("complete fixed L2/threshold/ATR neighboring evidence is required")
    selected_value = results[selected]
    neighbors = tuple(results[key] for key in expected if key != selected)
    return selected_value > 0.0 and all(value <= 0.0 for value in neighbors)


def _pearson(left: Sequence[float | None], right: Sequence[float | None]) -> float:
    if len(left) != len(right):
        raise ValueError("feature vectors must align")
    pairs = tuple((a, b) for a, b in zip(left, right, strict=True) if a is not None and b is not None)
    if len(pairs) < 2:
        return 0.0
    left_mean = sum(pair[0] for pair in pairs) / len(pairs)
    right_mean = sum(pair[1] for pair in pairs) / len(pairs)
    covariance = sum((a - left_mean) * (b - right_mean) for a, b in pairs)
    left_sum = sum((a - left_mean) ** 2 for a, _ in pairs)
    right_sum = sum((b - right_mean) ** 2 for _, b in pairs)
    denominator = math.sqrt(left_sum * right_sum)
    return covariance / denominator if denominator else 0.0
