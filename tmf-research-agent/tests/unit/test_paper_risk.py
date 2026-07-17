from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from tmf_research.domain.paper_trades import (
    PaperCostConfig,
    PaperFill,
    PaperIntent,
    PaperPosition,
    PaperQuote,
)
from tmf_research.paper.broker import PaperBroker, PaperPositionError
from tmf_research.paper.risk import (
    ENTRY_REJECTION_REASONS,
    EntryConditions,
    ExitObservation,
    evaluate_entry,
    evaluate_exit,
)


NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
FRESH_QUOTE = PaperQuote(bid_price_1=21500.0, ask_price_1=21501.0, age_ms=100)
COMPLETE_COSTS = PaperCostConfig(
    entry_fee_ntd=20.0, exit_fee_ntd=20.0, tax_ntd=4.0, slippage_cost_ntd=10.0,
)


def clear_entry_conditions() -> EntryConditions:
    return EntryConditions(
        quote=FRESH_QUOTE,
        quote_age_limit_ms=1000,
        spread_limit_points=2.0,
        data_quality_valid=True,
        model_compatible=True,
        features_complete=True,
        position_open=False,
        rollover_in_progress=False,
        session_ending=False,
        cost_config=COMPLETE_COSTS,
    )


def long_position(
    entry_price: float = 21502.0,
    stop_price: float = 21492.0,
    target_price: float = 21522.0,
) -> PaperPosition:
    return PaperPosition(
        position_id="paper-1",
        direction="LONG",
        entry=PaperFill(direction="LONG", price=entry_price, filled_at=NOW),
        stop_price=stop_price,
        target_price=target_price,
        vertical_deadline=NOW + timedelta(minutes=15),
        session_end=NOW + timedelta(hours=4),
    )


def short_position() -> PaperPosition:
    return PaperPosition(
        position_id="paper-2",
        direction="SHORT",
        entry=PaperFill(direction="SHORT", price=21499.0, filled_at=NOW),
        stop_price=21509.0,
        target_price=21479.0,
        vertical_deadline=NOW + timedelta(minutes=15),
        session_end=NOW + timedelta(hours=4),
    )


def observation(
    *,
    high: float = 21505.0,
    low: float = 21500.0,
    observed_at: datetime = NOW + timedelta(minutes=1),
    quote: PaperQuote | None = FRESH_QUOTE,
    rollover_in_progress: bool = False,
    tick_prices: tuple[tuple[datetime, float], ...] = (),
) -> ExitObservation:
    return ExitObservation(
        observed_at=observed_at,
        bar_high=high,
        bar_low=low,
        quote=quote,
        quote_age_limit_ms=1000,
        rollover_in_progress=rollover_in_progress,
        tick_prices=tick_prices,
    )


class EntryRiskTests(unittest.TestCase):
    def test_all_clear_conditions_permit_entry(self) -> None:
        self.assertEqual(evaluate_entry(clear_entry_conditions()), ())

    def test_every_specified_rejection_reason_is_persisted(self) -> None:
        base = clear_entry_conditions()
        cases: tuple[tuple[EntryConditions, str], ...] = (
            (replace(base, quote=None), "BIDASK_MISSING"),
            (
                replace(base, quote=PaperQuote(21500.0, 21501.0, 5000)),
                "BIDASK_STALE",
            ),
            (
                replace(base, quote=PaperQuote(21500.0, 21504.0, 100)),
                "SPREAD_LIMIT_EXCEEDED",
            ),
            (replace(base, data_quality_valid=False), "DATA_QUALITY_INVALID"),
            (replace(base, model_compatible=False), "MODEL_INCOMPATIBLE"),
            (replace(base, features_complete=False), "FEATURES_MISSING"),
            (replace(base, position_open=True), "POSITION_ALREADY_OPEN"),
            (replace(base, rollover_in_progress=True), "ROLLOVER_IN_PROGRESS"),
            (replace(base, session_ending=True), "SESSION_ENDED"),
            (
                replace(
                    base,
                    cost_config=PaperCostConfig(
                        entry_fee_ntd=20.0, exit_fee_ntd=20.0,
                        tax_ntd=None, slippage_cost_ntd=10.0,
                    ),
                ),
                "COST_CONFIG_INCOMPLETE",
            ),
        )

        for conditions, expected in cases:
            with self.subTest(reason=expected):
                self.assertEqual(evaluate_entry(conditions), (expected,))

    def test_multiple_failures_report_every_reason_in_fixed_order(self) -> None:
        conditions = replace(
            clear_entry_conditions(),
            quote=None,
            data_quality_valid=False,
            position_open=True,
            session_ending=True,
        )

        reasons = evaluate_entry(conditions)

        self.assertEqual(
            reasons,
            (
                "BIDASK_MISSING", "DATA_QUALITY_INVALID",
                "POSITION_ALREADY_OPEN", "SESSION_ENDED",
            ),
        )
        self.assertEqual(reasons, tuple(
            reason for reason in ENTRY_REJECTION_REASONS if reason in reasons
        ))


class ExitPriorityTests(unittest.TestCase):
    def test_stop_touch_alone_exits_at_stop_loss(self) -> None:
        reason = evaluate_exit(long_position(), observation(low=21492.0))

        self.assertEqual(reason, "STOP_LOSS")

    def test_target_touch_alone_exits_at_profit_target(self) -> None:
        reason = evaluate_exit(long_position(), observation(high=21522.0))

        self.assertEqual(reason, "PROFIT_TARGET")

    def test_short_position_touch_sides_are_mirrored(self) -> None:
        stop = evaluate_exit(short_position(), observation(high=21509.0))
        target = evaluate_exit(
            short_position(), observation(high=21505.0, low=21479.0),
        )

        self.assertEqual(stop, "STOP_LOSS")
        self.assertEqual(target, "PROFIT_TARGET")

    def test_ambiguous_same_bar_touch_defaults_to_stop_first(self) -> None:
        reason = evaluate_exit(
            long_position(), observation(high=21522.0, low=21492.0),
        )

        self.assertEqual(reason, "STOP_LOSS")

    def test_tick_sequence_resolves_target_before_stop(self) -> None:
        ticks = (
            (NOW + timedelta(seconds=10), 21522.0),
            (NOW + timedelta(seconds=40), 21492.0),
        )

        reason = evaluate_exit(
            long_position(),
            observation(high=21522.0, low=21492.0, tick_prices=ticks),
        )

        self.assertEqual(reason, "PROFIT_TARGET")

    def test_tick_sequence_confirming_stop_first_keeps_stop(self) -> None:
        ticks = (
            (NOW + timedelta(seconds=10), 21492.0),
            (NOW + timedelta(seconds=40), 21522.0),
        )

        reason = evaluate_exit(
            long_position(),
            observation(high=21522.0, low=21492.0, tick_prices=ticks),
        )

        self.assertEqual(reason, "STOP_LOSS")

    def test_unordered_tick_sequence_is_rejected(self) -> None:
        ticks = (
            (NOW + timedelta(seconds=40), 21522.0),
            (NOW + timedelta(seconds=10), 21492.0),
        )

        with self.assertRaisesRegex(ValueError, "order"):
            evaluate_exit(
                long_position(),
                observation(high=21522.0, low=21492.0, tick_prices=ticks),
            )

    def test_vertical_barrier_fires_after_deadline_without_touch(self) -> None:
        reason = evaluate_exit(
            long_position(),
            observation(observed_at=NOW + timedelta(minutes=15)),
        )

        self.assertEqual(reason, "VERTICAL_BARRIER")

    def test_session_end_fires_before_stale_and_rollover(self) -> None:
        crossing_session = PaperPosition(
            position_id="paper-5",
            direction="LONG",
            entry=PaperFill(direction="LONG", price=21502.0, filled_at=NOW),
            stop_price=21492.0,
            target_price=21522.0,
            vertical_deadline=NOW + timedelta(hours=5),
            session_end=NOW + timedelta(hours=4),
        )

        reason = evaluate_exit(
            crossing_session,
            observation(
                observed_at=NOW + timedelta(hours=4),
                quote=None,
                rollover_in_progress=True,
            ),
        )

        self.assertEqual(reason, "SESSION_END")

    def test_vertical_barrier_outranks_session_end_when_both_passed(self) -> None:
        reason = evaluate_exit(
            long_position(),
            observation(observed_at=NOW + timedelta(hours=4)),
        )

        self.assertEqual(reason, "VERTICAL_BARRIER")

    def test_stale_quote_exits_before_rollover(self) -> None:
        missing = evaluate_exit(long_position(), observation(quote=None))
        stale = evaluate_exit(
            long_position(),
            observation(quote=PaperQuote(21500.0, 21501.0, 5000)),
        )

        self.assertEqual(missing, "DATA_STALE")
        self.assertEqual(stale, "DATA_STALE")

    def test_rollover_exit_and_quiet_bar_hold(self) -> None:
        rollover = evaluate_exit(
            long_position(), observation(rollover_in_progress=True),
        )
        hold = evaluate_exit(long_position(), observation())

        self.assertEqual(rollover, "ROLLOVER")
        self.assertIsNone(hold)

    def test_stop_touch_outranks_every_time_based_exit(self) -> None:
        reason = evaluate_exit(
            long_position(),
            observation(
                low=21492.0,
                observed_at=NOW + timedelta(hours=5),
                quote=None,
                rollover_in_progress=True,
            ),
        )

        self.assertEqual(reason, "STOP_LOSS")


class SinglePositionBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.broker = PaperBroker()
        self.intent = PaperIntent("paper-1", "LONG", 1, NOW)
        self.entry = PaperFill(direction="LONG", price=21502.0, filled_at=NOW)

    def open_default(self) -> PaperPosition:
        return self.broker.open_position(
            self.intent,
            self.entry,
            stop_price=21492.0,
            target_price=21522.0,
            vertical_deadline=NOW + timedelta(minutes=15),
            session_end=NOW + timedelta(hours=4),
        )

    def test_open_position_records_a_single_paper_contract(self) -> None:
        position = self.open_default()

        self.assertEqual(position.direction, "LONG")
        self.assertEqual(position.entry.quantity, 1)
        self.assertIs(self.broker.position, position)

    def test_second_entry_in_same_direction_is_rejected_as_adding(self) -> None:
        self.open_default()

        with self.assertRaisesRegex(PaperPositionError, "position"):
            self.broker.open_position(
                PaperIntent("paper-2", "LONG", 1, NOW),
                PaperFill(direction="LONG", price=21503.0, filled_at=NOW),
                stop_price=21493.0,
                target_price=21523.0,
                vertical_deadline=NOW + timedelta(minutes=15),
                session_end=NOW + timedelta(hours=4),
            )

    def test_opposite_entry_is_rejected_as_reversing(self) -> None:
        self.open_default()

        with self.assertRaisesRegex(PaperPositionError, "position"):
            self.broker.open_position(
                PaperIntent("paper-3", "SHORT", 1, NOW),
                PaperFill(direction="SHORT", price=21499.0, filled_at=NOW),
                stop_price=21509.0,
                target_price=21479.0,
                vertical_deadline=NOW + timedelta(minutes=15),
                session_end=NOW + timedelta(hours=4),
            )

    def test_intent_and_fill_direction_must_match(self) -> None:
        with self.assertRaisesRegex(PaperPositionError, "direction"):
            self.broker.open_position(
                self.intent,
                PaperFill(direction="SHORT", price=21499.0, filled_at=NOW),
                stop_price=21509.0,
                target_price=21479.0,
                vertical_deadline=NOW + timedelta(minutes=15),
                session_end=NOW + timedelta(hours=4),
            )

    def test_position_reopens_only_after_close(self) -> None:
        from tmf_research.domain.paper_trades import PaperExit

        self.open_default()
        self.broker.close_position(
            PaperExit(
                reason="PROFIT_TARGET",
                price=21521.5,
                exited_at=NOW + timedelta(minutes=5),
            ),
            COMPLETE_COSTS,
        )

        self.assertIsNone(self.broker.position)
        reopened = self.broker.open_position(
            PaperIntent("paper-4", "SHORT", 1, NOW + timedelta(minutes=6)),
            PaperFill(
                direction="SHORT", price=21499.0,
                filled_at=NOW + timedelta(minutes=6),
            ),
            stop_price=21509.0,
            target_price=21479.0,
            vertical_deadline=NOW + timedelta(minutes=21),
            session_end=NOW + timedelta(hours=4),
        )

        self.assertEqual(reopened.direction, "SHORT")

    def test_close_without_open_position_is_rejected(self) -> None:
        from tmf_research.domain.paper_trades import PaperExit

        with self.assertRaisesRegex(PaperPositionError, "position"):
            self.broker.close_position(
                PaperExit(reason="STOP_LOSS", price=21492.0, exited_at=NOW),
                COMPLETE_COSTS,
            )


class PaperPositionValidationTests(unittest.TestCase):
    def test_long_protection_prices_must_bracket_entry(self) -> None:
        with self.assertRaisesRegex(ValueError, "stop"):
            long_position(stop_price=21503.0)
        with self.assertRaisesRegex(ValueError, "target"):
            long_position(target_price=21501.0)

    def test_deadlines_must_be_timezone_aware(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone"):
            PaperPosition(
                position_id="paper-1",
                direction="LONG",
                entry=PaperFill(direction="LONG", price=21502.0, filled_at=NOW),
                stop_price=21492.0,
                target_price=21522.0,
                vertical_deadline=datetime(2026, 7, 15, 9, 15),
                session_end=NOW + timedelta(hours=4),
            )


if __name__ == "__main__":
    unittest.main()
