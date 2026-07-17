from __future__ import annotations

from pathlib import Path

from tmf_research.paper.replay import ReplayManifest, ReplayRecorder
from tmf_research.runtime.feature_state import RuntimeFeatureVector
from tmf_research.runtime.live_research import LiveResearchRunner, RuntimeObservation

from tests.phase6_test_support import (
    DATASET_VERSION,
    RAW_CHECKSUM,
    feature_vector,
    observation,
    runner_for,
    test_only_runtime,
)


def manifest(*, seed: int = 7, model_version: str = "v1") -> ReplayManifest:
    return ReplayManifest(
        raw_checksum=RAW_CHECKSUM,
        dataset_version=DATASET_VERSION,
        feature_version="phase3-features-v1",
        label_version="labels-v1",
        model_version=model_version,
        experiment_id="experiment-1",
        code_commit="abc123",
        seed=seed,
        calendar_version="calendar-v1",
        cost_policy_version="cost-v1",
    )


def entering_return(runner: LiveResearchRunner) -> float | None:
    """Probe the frozen model for a deterministic entry-producing feature."""

    bundle = runner.runtime.bundle
    policy = runner.runtime.policy
    for step in range(-50, 51):
        value = step / 1000.0
        transformed = bundle.preprocessor.transform(
            {"return_1m": value, "basis": 1.2},
        )
        if not transformed.is_eligible:
            continue
        p_trade, _p_long = bundle.calibrator.calibrate(
            bundle.model.trade_model.predict_probability(transformed.values),
            bundle.model.direction_model.predict_probability(transformed.values),
        )
        if p_trade >= policy.trade_threshold:
            return value
    return None


def fixed_scenario(
    runner: LiveResearchRunner,
) -> tuple[tuple[RuntimeFeatureVector, RuntimeObservation], ...]:
    entry_value = entering_return(runner)
    first = feature_vector(1) if entry_value is None else feature_vector(
        1, return_1m=entry_value,
    )
    return (
        (first, observation(1)),
        (feature_vector(2), observation(2, bar_low=21480.0, bar_high=21515.0)),
        (feature_vector(3), observation(3)),
    )


def run_recorded_scenario(root: Path) -> tuple[str, tuple[str, ...]]:
    runtime, checksum = test_only_runtime(root)
    runner = runner_for(runtime, checksum)
    recorder = ReplayRecorder(manifest())
    for vector, observed in fixed_scenario(runner):
        record = runner.process_bar(vector, observed)
        recorder.record("PREDICTION", record.to_json())
    for row in runner.broker.ledger.rows:
        recorder.record("LEDGER", row.content_hash)
    return recorder.final_checksum(), recorder.lines
