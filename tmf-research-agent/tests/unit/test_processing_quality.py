from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from tmf_research.domain.events import BidAskEvent, TickEvent
from tmf_research.processing.quality_report import QualityReportBuilder


START = datetime(2026, 7, 20, 8, 45, tzinfo=timezone.utc)


def tick(event_id: str, offset: int) -> TickEvent:
    occurred_at = START + timedelta(seconds=offset)
    return TickEvent(
        event_id=event_id,
        received_at=occurred_at,
        exchange_datetime=occurred_at,
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        code="TMF202607",
        close=100.0,
        volume=1,
        simtrade=False,
        raw_payload={},
    )


def quote(offset: int) -> BidAskEvent:
    occurred_at = START + timedelta(seconds=offset)
    return BidAskEvent(
        event_id=f"quote-{offset}",
        received_at=occurred_at,
        exchange_datetime=occurred_at,
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        code="TMF202607",
        bid_prices=(99.0,),
        bid_volumes=(1,),
        ask_prices=(101.0,),
        ask_volumes=(1,),
        simtrade=False,
        raw_payload={},
    )


class QualityReportBuilderTests(unittest.TestCase):
    def test_reports_all_counters_gaps_coverage_and_invalid_status(self) -> None:
        report = QualityReportBuilder().build(
            trading_date=date(2026, 7, 20),
            session="DAY",
            ticks=(tick("tick-0", 0), tick("tick-2", 2)),
            bidasks=(quote(0),),
            rejection_reasons=(
                "DUPLICATE",
                "OUT_OF_ORDER",
                "INVALID_PRICE",
                "INVALID_DEPTH",
                "STALE_TICK",
                "STALE_BIDASK",
                "SIMTRADE",
            ),
            queue_drop_count=1,
            connection_drop_count=2,
            expected_seconds=3,
        )

        self.assertEqual((report.tick_count, report.bidask_count), (2, 1))
        self.assertEqual((report.duplicate_count, report.out_of_order_count), (1, 1))
        self.assertEqual((report.invalid_price_count, report.invalid_depth_count), (1, 1))
        self.assertEqual((report.stale_tick_count, report.stale_bidask_count), (1, 1))
        self.assertEqual((report.simtrade_count, report.queue_drop_count, report.connection_drop_count), (1, 1, 2))
        self.assertEqual(report.maximum_gap_seconds, 2.0)
        self.assertAlmostEqual(report.tick_coverage_ratio, 2.0 / 3.0)
        self.assertAlmostEqual(report.bidask_coverage_ratio, 1.0 / 3.0)
        self.assertEqual(report.quality_status, "INVALID")


if __name__ == "__main__":
    unittest.main()
