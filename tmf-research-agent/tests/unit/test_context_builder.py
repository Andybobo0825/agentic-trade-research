from __future__ import annotations

import unittest
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tmf_research.domain.sessions import SessionResolution
from tmf_research.features.context_builder import build_feature_context


TAIPEI = ZoneInfo("Asia/Taipei")


def day_resolution() -> SessionResolution:
    start = datetime(2025, 1, 6, 8, 45, tzinfo=TAIPEI)
    return SessionResolution(
        session="DAY",
        trading_date=date(2025, 1, 6),
        session_start=start,
        session_end=start + timedelta(hours=5),
        calendar_version="test-v1",
    )


class LargeTradeThresholdTest(unittest.TestCase):
    def test_histogram_threshold_matches_sorted_percentile_index(self) -> None:
        cases = (
            [1],
            [5, 1, 3, 3, 9],
            list(range(1, 101)),
            [2] * 10 + [7] * 3,
            [4] * 9 + [400],
        )
        for volumes in cases:
            context = build_feature_context(
                day_resolution(),
                prior_bars=(),
                prior_volume_counts=Counter(volumes),
            )
            ordered = sorted(volumes)
            expected = ordered[max(0, int(len(ordered) * 0.9) - 1)]
            self.assertEqual(context.large_trade_threshold, expected)

    def test_no_prior_volumes_defaults_to_one(self) -> None:
        context = build_feature_context(
            day_resolution(), prior_bars=(), prior_volume_counts={},
        )
        self.assertEqual(context.large_trade_threshold, 1)


if __name__ == "__main__":
    unittest.main()
