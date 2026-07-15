from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from tmf_research.features.definitions import default_feature_manifest
from tmf_research.features.pipeline import FeaturePipeline
from tmf_research.labeling.executable_prices import ExecutablePricePolicy
from tmf_research.labeling.pipeline import LabelPipeline
from tmf_research.labeling.triple_barrier import LabelParameters, TripleBarrierLabeler
from tmf_research.processing.bars import Bar

from tests.unit.test_feature_pipeline import START, bar, context, state


def future_bar(decision_time: datetime, index: int, *, high: float, low: float) -> Bar:
    start = decision_time + timedelta(minutes=index)
    return Bar(
        target_code="TMF202607",
        bar_start=start,
        bar_end=start + timedelta(minutes=1),
        open=105.0,
        high=high,
        low=low,
        close=105.0,
        volume=1,
        trade_count=1,
        buy_volume=1,
        sell_volume=0,
        unknown_volume=0,
        vwap=105.0,
        bidask_coverage_ratio=1.0,
        tick_coverage_ratio=1.0,
        is_complete=True,
    )


class Phase3PipelineTests(unittest.TestCase):
    def test_complete_feature_to_label_path_is_deterministic(self) -> None:
        bars = tuple(bar(index, 100.0 + index) for index in range(6))
        states = tuple(state(offset) for offset in range(10))
        original_bars = bars
        decision_time = bars[-1].bar_end
        features = FeaturePipeline(default_feature_manifest()).compute(
            bars=bars,
            states=states,
            decision_time=decision_time,
            context=context(),
        )
        candidate = next(
            item
            for item in LabelPipeline().candidates(bars)
            if item.decision_time == decision_time and item.horizon_minutes == 5
        )
        params = LabelParameters(
            version="integration-label-v1",
            fit_start=START - timedelta(days=30),
            fit_end=START - timedelta(days=1),
            target_atr_multiplier=2.0,
            stop_atr_multiplier=1.0,
            minimum_target_points=3.0,
            minimum_stop_points=3.0,
            horizon_minutes=5,
        )
        labeler = TripleBarrierLabeler(
            price_policy=ExecutablePricePolicy(entry_slippage=0.5, exit_slippage=0.5)
        )
        first = labeler.label(
            candidate_id=candidate.candidate_id,
            decision_time=decision_time,
            entry_state=states[-1],
            future_bars=(future_bar(decision_time, 0, high=112.0, low=104.0),),
            atr=3.0,
            parameters=params,
        )
        second = labeler.label(
            candidate_id=candidate.candidate_id,
            decision_time=decision_time,
            entry_state=states[-1],
            future_bars=(future_bar(decision_time, 0, high=112.0, low=104.0),),
            atr=3.0,
            parameters=params,
        )

        self.assertEqual(first, second)
        self.assertEqual(first.label, "LONG")
        self.assertTrue(first.training_eligible)
        self.assertEqual(len(features.content_hash), 64)
        self.assertEqual(bars, original_bars)


if __name__ == "__main__":
    unittest.main()
