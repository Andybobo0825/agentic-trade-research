from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from tmf_research.domain.paper_trades import PaperCostConfig, PaperQuote
from tmf_research.models.provenance import FrozenDecisionPolicy, canonical_hash, freeze_decision_policy
from tmf_research.models.calibration import fit_two_stage_calibrators
from tmf_research.models.serialization import ExpectedModelContract, ModelBundle, load_model_bundle, save_model_bundle
from tmf_research.paper.broker import PaperBroker
from tmf_research.runtime.feature_state import BarCloseGate, RuntimeFeatureVector
from tmf_research.runtime.health import RuntimeHealth
from tmf_research.runtime.live_research import (
    FrozenLiveRuntime,
    LiveResearchRunner,
    PredictionLog,
    RuntimeObservation,
    _issue_test_only_runtime,
)

from tests.unit.test_calibration import validation_predictions
from tests.unit.test_model_serialization import bundle as build_bundle


BAR_START = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
SESSION_END_TIME = datetime(2026, 7, 15, 13, 45, tzinfo=timezone.utc)
RAW_CHECKSUM = "a" * 64
DATASET_VERSION = "dataset-v1"
COMPLETE_COSTS = PaperCostConfig(
    entry_fee_ntd=20.0, exit_fee_ntd=20.0, tax_ntd=4.0, slippage_cost_ntd=10.0,
)


def frozen_policy() -> FrozenDecisionPolicy:
    calibration = fit_two_stage_calibrators(
        validation_predictions(), bin_count=4, minimum_bin_size=2,
    )
    return freeze_decision_policy(
        calibration,
        thresholds_hash=canonical_hash({
            "trade_probability": 0.5, "direction_probability": 0.5,
        }),
        rules_hash=canonical_hash({"rules": "phase5-fixed-risk-rules-v1"}),
    )


def saved_bundle(root: Path) -> tuple[ModelBundle, str]:
    original = build_bundle()
    checksum = save_model_bundle(original, root / "bundle")
    loaded = load_model_bundle(
        root / "bundle",
        ExpectedModelContract.from_bundle(original, model_checksum=checksum),
    )
    assert loaded.bundle is not None, loaded.reasons
    return loaded.bundle, checksum


def test_only_runtime(root: Path) -> tuple[FrozenLiveRuntime, str]:
    bundle, checksum = saved_bundle(root)
    runtime = _issue_test_only_runtime(
        bundle=bundle,
        contract=ExpectedModelContract.from_bundle(bundle, model_checksum=checksum),
        policy=frozen_policy(),
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        delivery_date="2026-07-15",
        raw_checksum=RAW_CHECKSUM,
        dataset_version=DATASET_VERSION,
        stop_points=10.0,
        target_points=20.0,
        maximum_holding_minutes=15,
        tick_age_limit_ms=2000,
        bidask_age_limit_ms=2000,
        spread_limit_points=2.0,
        entry_slippage_points=1.0,
        exit_slippage_points=0.5,
        cost_config=COMPLETE_COSTS,
    )
    return runtime, checksum


# This is a fixture-style helper imported by tests, not a pytest test itself.
test_only_runtime.__test__ = False  # type: ignore[attr-defined]


def runner_for(runtime: FrozenLiveRuntime, checksum: str) -> LiveResearchRunner:
    return LiveResearchRunner(
        runtime=runtime,
        loaded_checksum=checksum,
        broker=PaperBroker(),
        gate=BarCloseGate(),
        log=PredictionLog(),
    )


def healthy(target_code: str = "TMF202607") -> RuntimeHealth:
    return RuntimeHealth(
        connection_ok=True,
        target_code=target_code,
        rollover_in_progress=False,
        tick_age_ms=500,
        bidask_age_ms=500,
        data_quality_valid=True,
    )


def feature_vector(
    minute: int,
    *,
    return_1m: float | None = 0.004,
    basis: float | None = 1.2,
) -> RuntimeFeatureVector:
    close_time = BAR_START + timedelta(minutes=minute)
    return RuntimeFeatureVector(
        bar_close_time=close_time,
        evidence_available_at=close_time,
        feature_version="phase3-features-v1",
        values={"return_1m": return_1m, "basis": basis},
    )


def observation(
    minute: int,
    *,
    health: RuntimeHealth | None = None,
    quote: PaperQuote | None = PaperQuote(21500.0, 21501.0, 100),
    bar_high: float = 21505.0,
    bar_low: float = 21495.0,
) -> RuntimeObservation:
    observed = BAR_START + timedelta(minutes=minute)
    minutes_to_close = max(0, int((SESSION_END_TIME - observed).total_seconds() // 60))
    return RuntimeObservation(
        health=health if health is not None else healthy(),
        quote=quote,
        bar_high=bar_high,
        bar_low=bar_low,
        last_price=21500.5,
        session_type="DAY",
        trading_date="2026-07-15",
        minutes_from_open=minute + 15,
        minutes_to_close=minutes_to_close,
        session_end_time=SESSION_END_TIME,
        underlying_price=21510.0,
        basis_points=-9.5,
        session_vwap=21498.0,
        atr_15m=12.0,
    )
