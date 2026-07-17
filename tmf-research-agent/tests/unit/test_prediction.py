from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from tmf_research.domain.predictions import (
    InstrumentBlock,
    MarketBlock,
    ModelBlock,
    PaperPlanBlock,
    PredictionRecord,
    ProbabilityBlock,
    QualityBlock,
    SessionBlock,
    TraceBlock,
)


NOW = datetime(2026, 7, 15, 9, 1, tzinfo=timezone.utc)


def instrument() -> InstrumentBlock:
    return InstrumentBlock(
        category="TMF",
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        delivery_date="2026-07-15",
    )


def session() -> SessionBlock:
    return SessionBlock(
        type="DAY", trading_date="2026-07-15",
        minutes_from_open=16, minutes_to_close=284,
    )


def market() -> MarketBlock:
    return MarketBlock(
        last_price=21500.5, bid_price_1=21500.0, ask_price_1=21501.0,
        spread_points=1.0, underlying_price=21510.0, basis_points=-9.5,
        session_vwap=21498.0, atr_15m=12.0,
    )


def probability(long: float = 0.2, short: float = 0.1) -> ProbabilityBlock:
    return ProbabilityBlock(long=long, short=short, no_trade=1.0 - long - short)


def disabled_plan() -> PaperPlanBlock:
    return PaperPlanBlock(
        enabled=False, direction=None, quantity=0,
        entry_price=None, stop_price=None, target_price=None,
        maximum_holding_minutes=0,
    )


def enabled_plan() -> PaperPlanBlock:
    return PaperPlanBlock(
        enabled=True, direction="LONG", quantity=1,
        entry_price=21502.0, stop_price=21492.0, target_price=21522.0,
        maximum_holding_minutes=15,
    )


def quality(*, allow: bool = False, complete: bool = True) -> QualityBlock:
    return QualityBlock(
        tick_age_ms=500, bidask_age_ms=500, data_stale=False,
        rollover=False, complete_features=complete, allow_paper_trade=allow,
    )


def model() -> ModelBlock:
    return ModelBlock(
        model_id="model-1", model_version="v1",
        feature_version="phase3-features-v1", label_version="labels-v1",
        training_end="2026-02-01T00:00:00+00:00", calibration_method="PLATT",
    )


def trace() -> TraceBlock:
    return TraceBlock(
        raw_checksum="a" * 64, dataset_version="dataset-v1",
        experiment_id="experiment-1", code_commit="abc123",
        ledger_row_id=None,
    )


def record(
    *,
    signal: str = "NO_TRADE",
    plan: PaperPlanBlock | None = None,
    quality_block: QualityBlock | None = None,
    probability_block: ProbabilityBlock | None = None,
    evidence_available_at: datetime | None = None,
) -> PredictionRecord:
    return PredictionRecord(
        prediction_id="pred-20260715T090100+0000-TMF202607",
        decision_time=NOW,
        evidence_available_at=(
            evidence_available_at if evidence_available_at is not None else NOW
        ),
        instrument=instrument(),
        session=session(),
        market=market(),
        probability=(
            probability_block if probability_block is not None else probability()
        ),
        signal=signal,  # type: ignore[arg-type]
        paper_plan=plan if plan is not None else disabled_plan(),
        quality=quality_block if quality_block is not None else quality(),
        model=model(),
        reasons=("PHASE6_NOT_APPROVED",),
        missing_features=(),
        warnings=(),
        trace=trace(),
    )


class PredictionSchemaTests(unittest.TestCase):
    def test_json_matches_spec36_schema_with_fixed_point_value(self) -> None:
        payload = record().to_json_dict()

        self.assertEqual(
            tuple(payload),
            (
                "schemaVersion", "predictionId", "decisionTime",
                "evidenceAvailableAt", "instrument", "session", "market",
                "probability", "signal", "paperPlan", "quality", "model",
                "reasons", "missingFeatures", "warnings", "trace",
            ),
        )
        self.assertEqual(payload["schemaVersion"], "1.1.0")
        instrument_payload = payload["instrument"]
        assert isinstance(instrument_payload, dict)
        self.assertEqual(
            tuple(instrument_payload),
            (
                "category", "aliasCode", "targetCode", "deliveryMonth",
                "deliveryDate", "pointValueNtd",
            ),
        )
        self.assertEqual(instrument_payload["pointValueNtd"], 10)
        session_payload = payload["session"]
        assert isinstance(session_payload, dict)
        self.assertEqual(
            tuple(session_payload),
            ("type", "tradingDate", "minutesFromOpen", "minutesToClose"),
        )
        market_payload = payload["market"]
        assert isinstance(market_payload, dict)
        self.assertEqual(
            tuple(market_payload),
            (
                "lastPrice", "bidPrice1", "askPrice1", "spreadPoints",
                "underlyingPrice", "basisPoints", "sessionVwap", "atr15m",
            ),
        )
        probability_payload = payload["probability"]
        assert isinstance(probability_payload, dict)
        self.assertEqual(tuple(probability_payload), ("long", "short", "noTrade"))
        plan_payload = payload["paperPlan"]
        assert isinstance(plan_payload, dict)
        self.assertEqual(
            tuple(plan_payload),
            (
                "enabled", "direction", "quantity", "entryPrice", "stopPrice",
                "targetPrice", "maximumHoldingMinutes",
            ),
        )
        quality_payload = payload["quality"]
        assert isinstance(quality_payload, dict)
        self.assertEqual(
            tuple(quality_payload),
            (
                "tickAgeMs", "bidAskAgeMs", "dataStale", "rollover",
                "completeFeatures", "allowPaperTrade",
            ),
        )
        model_payload = payload["model"]
        assert isinstance(model_payload, dict)
        self.assertEqual(
            tuple(model_payload),
            (
                "modelId", "modelVersion", "featureVersion", "labelVersion",
                "trainingEnd", "calibrationMethod",
            ),
        )
        trace_payload = payload["trace"]
        assert isinstance(trace_payload, dict)
        self.assertEqual(
            tuple(trace_payload),
            (
                "rawChecksum", "datasetVersion", "experimentId",
                "codeCommit", "ledgerRowId",
            ),
        )

    def test_point_value_cannot_be_authored(self) -> None:
        with self.assertRaises(TypeError):
            InstrumentBlock(
                category="TMF", alias_code="TMFR1", target_code="TMF202607",
                delivery_month="202607", delivery_date="2026-07-15",
                point_value_ntd=50,  # type: ignore[call-arg]
            )

    def test_serialization_is_deterministic(self) -> None:
        first = record().to_json()
        second = record().to_json()

        self.assertEqual(first, second)
        self.assertEqual(record().content_hash, record().content_hash)
        parsed = json.loads(first)
        self.assertEqual(parsed["signal"], "NO_TRADE")

    def test_record_is_immutable(self) -> None:
        value = record()

        with self.assertRaises(FrozenInstanceError):
            value.signal = "LONG"  # type: ignore[misc]


class PredictionConsistencyTests(unittest.TestCase):
    def test_probabilities_must_sum_to_one_within_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "sum"):
            ProbabilityBlock(long=0.5, short=0.5, no_trade=0.5)
        with self.assertRaisesRegex(ValueError, "probability"):
            ProbabilityBlock(long=-0.1, short=0.4, no_trade=0.7)

    def test_evidence_cannot_postdate_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence"):
            record(evidence_available_at=NOW + timedelta(seconds=1))

    def test_no_trade_signal_forbids_an_enabled_plan(self) -> None:
        with self.assertRaisesRegex(ValueError, "plan"):
            record(signal="NO_TRADE", plan=enabled_plan(), quality_block=quality(allow=True))

    def test_enabled_plan_requires_matching_signal_and_permission(self) -> None:
        value = record(
            signal="LONG", plan=enabled_plan(), quality_block=quality(allow=True),
            probability_block=probability(long=0.6, short=0.1),
        )

        self.assertTrue(value.paper_plan.enabled)
        with self.assertRaisesRegex(ValueError, "plan"):
            record(
                signal="SHORT", plan=enabled_plan(),
                quality_block=quality(allow=True),
                probability_block=probability(long=0.1, short=0.6),
            )
        with self.assertRaisesRegex(ValueError, "allow"):
            record(
                signal="LONG", plan=enabled_plan(),
                quality_block=quality(allow=False),
                probability_block=probability(long=0.6, short=0.1),
            )

    def test_enabled_plan_requires_bracketing_prices_and_one_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "quantity"):
            PaperPlanBlock(
                enabled=True, direction="LONG", quantity=2,
                entry_price=21502.0, stop_price=21492.0, target_price=21522.0,
                maximum_holding_minutes=15,
            )
        with self.assertRaisesRegex(ValueError, "stop"):
            PaperPlanBlock(
                enabled=True, direction="LONG", quantity=1,
                entry_price=21502.0, stop_price=21512.0, target_price=21522.0,
                maximum_holding_minutes=15,
            )
        with self.assertRaisesRegex(ValueError, "disabled"):
            PaperPlanBlock(
                enabled=False, direction="LONG", quantity=1,
                entry_price=21502.0, stop_price=21492.0, target_price=21522.0,
                maximum_holding_minutes=15,
            )

    def test_signal_values_are_fixed(self) -> None:
        with self.assertRaisesRegex(ValueError, "signal"):
            record(signal="BUY")


if __name__ == "__main__":
    unittest.main()
