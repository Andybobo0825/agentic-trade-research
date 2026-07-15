from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tmf_research.labeling.executable_prices import ExecutablePricePolicy
from tmf_research.labeling.triple_barrier import LabelParameters, TripleBarrierLabeler
from tmf_research.processing.bars import Bar

from tests.unit.test_executable_prices import state


NOW = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


def parameters(*, fit_end: datetime | None = None, horizon: int = 5) -> LabelParameters:
    return LabelParameters(
        version="barrier-v1",
        fit_start=NOW - timedelta(days=30),
        fit_end=fit_end or NOW - timedelta(days=1),
        target_atr_multiplier=2.0,
        stop_atr_multiplier=1.0,
        minimum_target_points=3.0,
        minimum_stop_points=3.0,
        horizon_minutes=horizon,
    )


def future_bar(index: int, *, high: float, low: float) -> Bar:
    start = NOW + timedelta(minutes=index)
    return Bar(
        target_code="TMF202607",
        bar_start=start,
        bar_end=start + timedelta(minutes=1),
        open=100.0,
        high=high,
        low=low,
        close=100.0,
        volume=1,
        trade_count=1,
        buy_volume=1,
        sell_volume=0,
        unknown_volume=0,
        vwap=100.0,
        bidask_coverage_ratio=1.0,
        tick_coverage_ratio=1.0,
        is_complete=True,
    )


class TripleBarrierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.labeler = TripleBarrierLabeler(
            price_policy=ExecutablePricePolicy(entry_slippage=0.5, exit_slippage=0.5)
        )

    def test_first_upper_lower_vertical_and_ambiguous_map_deterministically(self) -> None:
        long = self.labeler.label(
            candidate_id="long",
            decision_time=NOW,
            entry_state=state(),
            future_bars=(future_bar(0, high=106.0, low=98.0),),
            atr=2.0,
            parameters=parameters(),
        )
        short = self.labeler.label(
            candidate_id="short",
            decision_time=NOW,
            entry_state=state(),
            future_bars=(future_bar(0, high=103.0, low=95.0),),
            atr=2.0,
            parameters=parameters(),
        )
        ambiguous = self.labeler.label(
            candidate_id="ambiguous",
            decision_time=NOW,
            entry_state=state(),
            future_bars=(future_bar(0, high=106.0, low=95.0),),
            atr=2.0,
            parameters=parameters(),
        )
        vertical = self.labeler.label(
            candidate_id="vertical",
            decision_time=NOW,
            entry_state=state(),
            future_bars=(future_bar(0, high=103.0, low=98.0),),
            atr=2.0,
            parameters=parameters(),
        )

        self.assertEqual((long.label, long.first_touch), ("LONG", "UPPER"))
        self.assertEqual((short.label, short.first_touch), ("SHORT", "LOWER"))
        self.assertEqual((ambiguous.label, ambiguous.first_touch), ("AMBIGUOUS", "BOTH"))
        self.assertFalse(ambiguous.training_eligible)
        self.assertTrue(long.training_eligible)
        self.assertEqual((vertical.label, vertical.first_touch), ("NO_TRADE", "VERTICAL"))
        self.assertEqual((long.entry_bid, long.entry_ask, long.entry_spread), (99.0, 101.0, 2.0))
        self.assertEqual((long.upper_barrier, long.lower_barrier), (105.0, 96.0))
        self.assertEqual(long.vertical_barrier, NOW + timedelta(minutes=5))
        self.assertEqual(long.label_version, "barrier-v1")
        self.assertEqual(long.horizon, "5m")

    def test_label_parameters_must_be_fit_before_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "fit interval"):
            self.labeler.label(
                candidate_id="leak",
                decision_time=NOW,
                entry_state=state(),
                future_bars=(),
                atr=2.0,
                parameters=parameters(fit_end=NOW + timedelta(seconds=1)),
            )


if __name__ == "__main__":
    unittest.main()
