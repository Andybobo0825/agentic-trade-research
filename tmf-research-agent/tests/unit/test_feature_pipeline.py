from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from tmf_research.features.definitions import (
    FeatureContext,
    default_feature_manifest,
    historical_l1_feature_manifest,
)
from tmf_research.features.pipeline import FeaturePipeline
from tmf_research.processing.bars import Bar
from tmf_research.processing.one_second import OneSecondState


START = datetime(2026, 7, 20, 8, 45, tzinfo=timezone.utc)


def bar(index: int, close: float, *, complete: bool = True) -> Bar:
    start = START + timedelta(minutes=index)
    return Bar(
        target_code="TMF202607",
        bar_start=start,
        bar_end=start + timedelta(minutes=1),
        open=close - 1.0,
        high=close + 1.0,
        low=close - 2.0,
        close=close,
        volume=10 + index,
        trade_count=5,
        buy_volume=7,
        sell_volume=2,
        unknown_volume=1,
        vwap=close - 0.25,
        bidask_coverage_ratio=1.0,
        tick_coverage_ratio=1.0,
        is_complete=complete,
    )


def state(offset: int, *, underlying: float | None = 99.0) -> OneSecondState:
    second = START + timedelta(minutes=5, seconds=offset)
    return OneSecondState(
        second=second,
        target_code="TMF202607",
        open=105.0,
        high=105.0,
        low=105.0,
        close=105.0,
        volume=2,
        trade_count=1,
        buy_volume=2 if offset % 2 == 0 else 0,
        sell_volume=0 if offset % 2 == 0 else 2,
        unknown_volume=0,
        last_bid=104.0,
        last_ask=106.0,
        bidask_available=True,
        spread=2.0,
        midpoint=105.0,
        microprice=105.25,
        level1_imbalance=0.25,
        level3_imbalance=0.20,
        level5_imbalance=0.10,
        underlying_price=underlying,
        basis=None if underlying is None else 105.0 - underlying,
        last_tick_age_ms=100.0,
        last_bidask_age_ms=100.0,
        notional=210.0,
        last_tick_at=second,
        last_bidask_at=second,
        bid_prices=(104.0,),
        bid_volumes=(10,),
        ask_prices=(106.0,),
        ask_volumes=(6,),
    )


def context() -> FeatureContext:
    return FeatureContext(
        session="DAY",
        session_start=START,
        session_end=START + timedelta(hours=5),
        trading_date=date(2026, 7, 20),
        expiry_date=date(2026, 7, 24),
        is_rollover_day=False,
        previous_day_high=110.0,
        previous_day_low=90.0,
        previous_close=100.0,
        night_high=108.0,
        night_low=95.0,
        opening_range_high=107.0,
        opening_range_low=101.0,
        large_trade_threshold=1,
        large_trade_threshold_fit_end=START - timedelta(days=1),
    )


class FeaturePipelineTests(unittest.TestCase):
    def test_computes_all_market_mechanism_groups_with_causal_provenance(self) -> None:
        bars = tuple(bar(index, 100.0 + index) for index in range(6))
        states = tuple(state(offset) for offset in range(10))
        decision_time = bars[-1].bar_end

        row = FeaturePipeline(default_feature_manifest()).compute(
            bars=bars,
            states=states,
            decision_time=decision_time,
            context=context(),
        )

        self.assertAlmostEqual(row.values["return_1m"] or 0.0, 105.0 / 104.0 - 1.0)
        self.assertAlmostEqual(row.values["body_to_range_ratio"] or 0.0, 1.0 / 3.0)
        self.assertIsNotNone(row.values["session_vwap"])
        self.assertAlmostEqual(row.values["trade_imbalance_10s"] or 0.0, 0.0)
        self.assertEqual(row.values["spread_points"], 2.0)
        self.assertEqual(row.values["basis_points"], 6.0)
        self.assertEqual(row.values["true_range_1m"], 3.0)
        self.assertEqual(row.values["distance_previous_close_atr"], 5.0 / 3.0)
        self.assertEqual(row.values["session_day"], 1.0)
        self.assertEqual(row.values["minutes_from_session_open"], 6.0)
        self.assertLessEqual(row.evidence_available_at, row.decision_time)
        self.assertEqual(row.feature_version, default_feature_manifest().version)

    def test_future_sentinel_cannot_change_prior_row_and_missing_basis_stays_missing(self) -> None:
        bars = tuple(bar(index, 100.0 + index) for index in range(6))
        decision_time = bars[-1].bar_end
        pipeline = FeaturePipeline(default_feature_manifest())
        prior = pipeline.compute(
            bars=bars,
            states=(state(0, underlying=None),),
            decision_time=decision_time,
            context=context(),
        )
        future = bar(6, 999999.0)
        mutated = pipeline.compute(
            bars=bars + (future,),
            states=(state(0, underlying=None),),
            decision_time=decision_time,
            context=context(),
        )

        self.assertEqual(prior, mutated)
        self.assertIsNone(prior.values["basis_points"])
        self.assertEqual(prior.missing_indicators["underlying_missing"], 1.0)

    def test_incomplete_decision_bar_is_excluded(self) -> None:
        incomplete = bar(0, 100.0, complete=False)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            FeaturePipeline(default_feature_manifest()).compute(
                bars=(incomplete,),
                states=(),
                decision_time=incomplete.bar_end,
                context=context(),
            )

    def test_forbidden_transform_or_future_fit_scope_fails_closed(self) -> None:
        complete = bar(0, 100.0)
        pipeline = FeaturePipeline(default_feature_manifest())
        with self.assertRaisesRegex(ValueError, "forbidden"):
            pipeline.compute(
                bars=(complete,),
                states=(),
                decision_time=complete.bar_end,
                context=replace(context(), forbidden_transforms=("CENTERED_WINDOW",)),
            )
        with self.assertRaisesRegex(ValueError, "prior train"):
            pipeline.compute(
                bars=(complete,),
                states=(),
                decision_time=complete.bar_end,
                context=replace(
                    context(),
                    large_trade_threshold_fit_end=complete.bar_end + timedelta(seconds=1),
                ),
            )

    def test_historical_l1_manifest_computes_without_basis_group(self) -> None:
        bars = tuple(bar(index, 100.0 + index) for index in range(6))
        states = tuple(state(offset, underlying=None) for offset in range(10))

        row = FeaturePipeline(historical_l1_feature_manifest()).compute(
            bars=bars,
            states=states,
            decision_time=bars[-1].bar_end,
            context=context(),
        )

        self.assertNotIn("basis_points", row.values)
        self.assertNotIn("underlying_missing", row.missing_indicators)
        self.assertEqual(row.feature_version, historical_l1_feature_manifest().version)


if __name__ == "__main__":
    unittest.main()
