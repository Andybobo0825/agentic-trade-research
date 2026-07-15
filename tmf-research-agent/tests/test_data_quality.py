from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tmf_research.collection.data_quality import DataQualityMonitor
from tmf_research.domain.events import (
    BidAskEvent,
    ConnectionEvent,
    QueueBackpressureEvent,
    TickEvent,
)


NOW = datetime(2026, 7, 15, 8, 45, tzinfo=timezone.utc)


def tick(
    *,
    event_id: str = "tick-1",
    exchange_datetime: datetime = NOW,
    close: float = 23000.0,
    volume: int = 1,
    simtrade: bool = False,
    target_code: str = "TMF202607",
    trading_date: str = "2026-07-15",
    session: str = "DAY",
) -> TickEvent:
    return TickEvent(
        event_id=event_id,
        received_at=NOW,
        exchange_datetime=exchange_datetime,
        alias_code="TMFR1",
        target_code=target_code,
        delivery_month="202607",
        code="TMF202607",
        close=close,
        volume=volume,
        simtrade=simtrade,
        raw_payload={},
        trading_date=trading_date,
        session=session,  # type: ignore[arg-type]
    )


class DataQualityTests(unittest.TestCase):
    def test_rejects_invalid_duplicate_and_out_of_order_ticks_with_evidence(self) -> None:
        monitor = DataQualityMonitor(clock=lambda: NOW)

        accepted = monitor.evaluate(tick())
        duplicate = monitor.evaluate(tick())
        invalid = monitor.evaluate(
            tick(
                event_id="tick-2",
                exchange_datetime=NOW - timedelta(seconds=1),
                close=0.0,
                volume=-1,
                simtrade=True,
            )
        )

        self.assertTrue(accepted.accepted)
        self.assertEqual(duplicate.reasons, ("DUPLICATE",))
        self.assertEqual(
            invalid.reasons,
            ("INVALID_PRICE", "NEGATIVE_VOLUME", "OUT_OF_ORDER", "SIMTRADE"),
        )
        self.assertEqual(len(monitor.rejections), 2)
        self.assertEqual(monitor.quality_status, "INVALID")

    def test_rejects_crossed_or_invalid_depth_without_silent_drop(self) -> None:
        monitor = DataQualityMonitor(clock=lambda: NOW)
        event = BidAskEvent(
            event_id="quote-1",
            received_at=NOW,
            exchange_datetime=NOW,
            alias_code="TMFR1",
            target_code="TMF202607",
            delivery_month="202607",
            code="TMF202607",
            bid_prices=(23001.0,),
            bid_volumes=(1,),
            ask_prices=(23000.0,),
            ask_volumes=(2,),
            simtrade=False,
            raw_payload={"source": "fixture"},
            trading_date="2026-07-15",
            session="DAY",
        )

        decision = monitor.evaluate(event)

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reasons, ("CROSSED_BOOK", "INVALID_DEPTH"))
        rejection = monitor.rejections[0]
        self.assertEqual(rejection.event_id, "quote-1")
        self.assertEqual(rejection.raw_payload["source"], "fixture")

    def test_retains_all_quality_reasons_and_builds_deterministic_session_report(self) -> None:
        monitor = DataQualityMonitor(
            clock=lambda: NOW,
            stale_after=timedelta(seconds=5),
        )
        monitor.evaluate(tick(event_id="tick-valid", exchange_datetime=NOW))
        monitor.evaluate(tick(event_id="tick-valid", exchange_datetime=NOW))
        monitor.evaluate(
            tick(
                event_id="tick-invalid",
                exchange_datetime=NOW - timedelta(seconds=6),
                close=0.0,
                volume=-1,
                simtrade=True,
            )
        )
        monitor.evaluate(
            BidAskEvent(
                event_id="quote-valid",
                received_at=NOW,
                exchange_datetime=NOW - timedelta(seconds=1),
                alias_code="TMFR1",
                target_code="TMF202607",
                delivery_month="202607",
                code="TMF202607",
                bid_prices=(22999.0,),
                bid_volumes=(1,),
                ask_prices=(23001.0,),
                ask_volumes=(1,),
                simtrade=False,
                raw_payload={},
                trading_date="2026-07-15",
                session="DAY",
            )
        )
        monitor.evaluate(
            BidAskEvent(
                event_id="quote-invalid",
                received_at=NOW,
                exchange_datetime=NOW - timedelta(seconds=7),
                alias_code="TMFR1",
                target_code="TMF202607",
                delivery_month="202607",
                code="TMF202607",
                bid_prices=(23001.0,),
                bid_volumes=(-1,),
                ask_prices=(23000.0,),
                ask_volumes=(1,),
                simtrade=False,
                raw_payload={},
                trading_date="2026-07-15",
                session="DAY",
            )
        )
        monitor.evaluate(
            tick(
                event_id="tick-closed",
                target_code="",
                trading_date="2026-07-15",
                session="CLOSED",
            )
        )
        monitor.record_queue_backpressure(
            QueueBackpressureEvent(
                event_id="queue-1",
                occurred_at=NOW,
                queue_size=100,
                dropped_event_count=3,
            ),
            trading_date="2026-07-15",
            session="DAY",
        )
        monitor.record_connection_drop(
            ConnectionEvent(
                event_id="connection-1",
                occurred_at=NOW,
                event_type="DISCONNECTED",
                connection_status="DISCONNECTED",
                attempt_number=1,
                reason="fixture",
            ),
            trading_date="2026-07-15",
            session="DAY",
        )

        retained_reasons = {
            reason for rejection in monitor.rejections for reason in rejection.reasons
        }
        self.assertTrue(
            {
                "DUPLICATE",
                "OUT_OF_ORDER",
                "INVALID_PRICE",
                "NEGATIVE_VOLUME",
                "INVALID_DEPTH",
                "CROSSED_BOOK",
                "STALE_TICK",
                "STALE_BIDASK",
                "SIMTRADE",
                "OUT_OF_SESSION",
                "UNKNOWN_TARGET",
                "QUEUE_LOSS",
                "CONNECTION_DROP",
            }.issubset(retained_reasons)
        )
        report = monitor.report(
            trading_date="2026-07-15",
            session="DAY",
            expected_seconds=10,
        )
        self.assertEqual((report.tick_count, report.bidask_count), (3, 2))
        self.assertEqual((report.duplicate_count, report.out_of_order_count), (1, 2))
        self.assertEqual((report.invalid_price_count, report.invalid_depth_count), (1, 1))
        self.assertEqual((report.stale_tick_count, report.stale_bidask_count), (1, 1))
        self.assertEqual(report.simtrade_count, 1)
        self.assertEqual(report.queue_drop_count, 3)
        self.assertEqual(report.connection_drop_count, 1)
        self.assertEqual(report.maximum_gap_seconds, 5.0)
        self.assertEqual(report.tick_coverage_ratio, 0.3)
        self.assertEqual(report.bidask_coverage_ratio, 0.2)
        self.assertEqual(report.quality_status, "INVALID")

        repeated = monitor.report(
            trading_date="2026-07-15",
            session="DAY",
            expected_seconds=10,
        )
        self.assertEqual(repeated, report)


if __name__ == "__main__":
    unittest.main()
