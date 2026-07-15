from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tmf_research.labeling.pipeline import LabelManifest, LabelPipeline
from tmf_research.processing.bars import Bar

from tests.unit.test_triple_barrier import parameters


START = datetime(2026, 7, 20, 8, 45, tzinfo=timezone.utc)


def bar(index: int, *, complete: bool = True) -> Bar:
    start = START + timedelta(minutes=index)
    return Bar(
        target_code="TMF202607",
        bar_start=start,
        bar_end=start + timedelta(minutes=1),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=1,
        trade_count=1,
        buy_volume=1,
        sell_volume=0,
        unknown_volume=0,
        vwap=100.0,
        bidask_coverage_ratio=1.0,
        tick_coverage_ratio=1.0,
        is_complete=complete,
    )


class LabelPipelineTests(unittest.TestCase):
    def test_creates_one_unique_candidate_per_complete_close_and_horizon(self) -> None:
        candidates = LabelPipeline().candidates(
            (bar(0), bar(1), bar(2, complete=False)),
            horizons=(5, 15, 60),
        )

        self.assertEqual(len(candidates), 6)
        self.assertEqual({candidate.horizon_minutes for candidate in candidates}, {5, 15, 60})
        self.assertEqual(len({candidate.candidate_id for candidate in candidates}), 6)
        self.assertTrue(all(candidate.decision_time in (bar(0).bar_end, bar(1).bar_end) for candidate in candidates))

    def test_label_manifest_hash_is_stable_and_primary_horizon_is_15m(self) -> None:
        params = tuple(parameters(horizon=horizon) for horizon in (5, 15, 60))
        first = LabelManifest.from_parameters("labels-v1", params)
        second = LabelManifest.from_parameters("labels-v1", params)

        self.assertEqual(first.primary_horizon_minutes, 15)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.horizons_minutes, (5, 15, 60))


if __name__ == "__main__":
    unittest.main()
