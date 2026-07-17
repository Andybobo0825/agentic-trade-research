from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from tmf_research.domain.paper_trades import PaperQuote
from tmf_research.runtime.feature_state import BarSequenceError
from tmf_research.runtime.live_research import LiveResearchRunner
from tmf_research.validation.approval import ApprovalCapability

from tests.phase6_test_support import (
    feature_vector,
    healthy,
    observation,
    runner_for,
    test_only_runtime,
)


class LiveInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runtime, self.checksum = test_only_runtime(Path(self._tmp.name))
        self.runner = runner_for(self.runtime, self.checksum)

    def test_one_inference_per_complete_bar_is_enforced(self) -> None:
        self.runner.process_bar(feature_vector(1), observation(1))

        with self.assertRaises(BarSequenceError):
            self.runner.process_bar(feature_vector(1), observation(1))
        with self.assertRaises(BarSequenceError):
            self.runner.process_bar(feature_vector(0), observation(0))

    def test_every_health_step_fails_closed_in_order(self) -> None:
        cases = (
            (replace(healthy(), connection_ok=False), "CONNECTION_INVALID"),
            (healthy(target_code="TMF202608"), "TARGET_CODE_MISMATCH"),
            (replace(healthy(), rollover_in_progress=True), "ROLLOVER_UNCONFIRMED"),
            (replace(healthy(), tick_age_ms=60_000), "TICK_STALE"),
            (replace(healthy(), bidask_age_ms=60_000), "BIDASK_STALE"),
            (replace(healthy(), data_quality_valid=False), "DATA_QUALITY_INVALID"),
        )

        for minute, (health, expected) in enumerate(cases, start=1):
            with self.subTest(reason=expected):
                record = self.runner.process_bar(
                    feature_vector(minute),
                    observation(minute, health=health),
                )
                self.assertEqual(record.signal, "NO_TRADE")
                self.assertEqual(record.reasons, (expected,))
                self.assertFalse(record.paper_plan.enabled)

    def test_earlier_step_failure_hides_later_checks(self) -> None:
        degraded = replace(
            healthy(),
            connection_ok=False,
            tick_age_ms=60_000,
            data_quality_valid=False,
        )

        record = self.runner.process_bar(
            feature_vector(1), observation(1, health=degraded),
        )

        self.assertEqual(record.reasons, ("CONNECTION_INVALID",))

    def test_missing_required_feature_reports_and_persists_no_trade(self) -> None:
        record = self.runner.process_bar(
            feature_vector(1, return_1m=None),
            observation(1),
        )

        self.assertEqual(record.signal, "NO_TRADE")
        self.assertIn("FEATURES_MISSING", record.reasons)
        self.assertIn("return_1m", record.missing_features)
        self.assertFalse(record.quality.complete_features)

    def test_feature_version_mismatch_forces_no_trade(self) -> None:
        vector = replace(feature_vector(1), feature_version="phase3-features-v2")

        record = self.runner.process_bar(vector, observation(1))

        self.assertEqual(record.signal, "NO_TRADE")
        self.assertEqual(record.reasons, ("FEATURE_VERSION_MISMATCH",))

    def test_model_checksum_mismatch_forces_no_trade(self) -> None:
        runner = runner_for(self.runtime, "b" * 64)

        record = runner.process_bar(feature_vector(1), observation(1))

        self.assertEqual(record.signal, "NO_TRADE")
        self.assertEqual(record.reasons, ("MODEL_CHECKSUM_MISMATCH",))

    def test_prediction_agrees_with_the_frozen_model_and_policy(self) -> None:
        vector = feature_vector(1)
        record = self.runner.process_bar(vector, observation(1))

        transformed = self.runtime.bundle.preprocessor.transform(vector.values)
        self.assertTrue(transformed.is_eligible)
        p_trade, p_long = self.runtime.bundle.calibrator.calibrate(
            self.runtime.bundle.model.trade_model.predict_probability(transformed.values),
            self.runtime.bundle.model.direction_model.predict_probability(transformed.values),
        )
        expected_signal = (
            "NO_TRADE" if p_trade < self.runtime.policy.trade_threshold
            else "LONG" if p_long >= self.runtime.policy.direction_threshold
            else "SHORT"
        )
        self.assertEqual(record.signal, expected_signal)
        self.assertAlmostEqual(
            record.probability.long + record.probability.short
            + record.probability.no_trade,
            1.0,
        )
        if expected_signal != "NO_TRADE":
            self.assertTrue(record.paper_plan.enabled)
            self.assertIsNotNone(self.runner.broker.position)
        self.assertIn("TEST_ONLY_RUNTIME_EVIDENCE", record.warnings)

    def test_entry_rejections_disable_the_plan_but_keep_the_record(self) -> None:
        record = self.runner.process_bar(
            feature_vector(1),
            observation(1, quote=PaperQuote(21500.0, 21504.0, 100)),
        )

        self.assertFalse(record.paper_plan.enabled)
        if record.signal != "NO_TRADE":
            self.assertIn("SPREAD_LIMIT_EXCEEDED", record.reasons)
        self.assertIsNone(self.runner.broker.position)

    def test_open_position_exits_by_priority_before_new_entries(self) -> None:
        first = self.runner.process_bar(feature_vector(1), observation(1))
        if first.signal == "NO_TRADE":
            self.skipTest("fixture model declined the entry; exit flow not reachable")

        position = self.runner.broker.position
        assert position is not None
        if position.direction == "LONG":
            breached = observation(2, bar_low=position.stop_price - 1.0)
        else:
            breached = observation(2, bar_high=position.stop_price + 1.0)
        second = self.runner.process_bar(feature_vector(2), breached)

        rows = self.runner.broker.ledger.rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].exit_reason, "STOP_LOSS")
        self.assertEqual(rows[0].row_id, position.position_id)
        self.assertEqual(second.trace.ledger_row_id, rows[0].row_id)
        reopened = self.runner.broker.position
        if reopened is not None:
            self.assertNotEqual(reopened.position_id, position.position_id)

    def test_every_record_is_persisted_append_only(self) -> None:
        self.runner.process_bar(feature_vector(1), observation(1))
        self.runner.process_bar(
            feature_vector(2),
            observation(2, health=replace(healthy(), connection_ok=False)),
        )

        self.assertEqual(len(self.runner.log.records), 2)
        self.assertFalse(hasattr(self.runner.log, "remove"))
        self.assertFalse(hasattr(self.runner.log, "clear"))

    def test_runtime_configuration_has_no_mutation_surface(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.runtime.stop_points = 5.0  # type: ignore[misc]
        for name in (
            "set_features", "set_coefficients", "set_scaler", "set_threshold",
            "set_stop", "set_target", "set_horizon",
        ):
            self.assertFalse(hasattr(self.runtime, name))
            self.assertFalse(hasattr(self.runner, name))

    def test_approval_capability_cannot_be_forged_for_the_runtime(self) -> None:
        with self.assertRaises(TypeError):
            ApprovalCapability()

    def test_runner_rejects_a_runtime_of_the_wrong_type(self) -> None:
        with self.assertRaises(TypeError):
            LiveResearchRunner(
                runtime=object(),  # type: ignore[arg-type]
                loaded_checksum=self.checksum,
                broker=self.runner.broker,
                gate=self.runner.gate,
                log=self.runner.log,
            )


if __name__ == "__main__":
    unittest.main()
