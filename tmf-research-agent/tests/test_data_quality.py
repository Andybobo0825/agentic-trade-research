from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tmf_research.collection.data_quality import DataQualityMonitor
from tmf_research.domain.events import BidAskEvent, TickEvent


NOW = datetime(2026, 7, 15, 8, 45, tzinfo=timezone.utc)


def tick(**overrides: object) -> TickEvent:
    values = {
        "event_id": "tick-1",
        "received_at": NOW,
        "exchange_datetime": NOW,
        "alias_code": "TMFR1",
        "target_code": "TMF202607",
        "delivery_month": "202607",
        "code": "TMF202607",
        "close": 23000.0,
        "volume": 1,
        "simtrade": False,
        "raw_payload": {},
    }
    values.update(overrides)
    return TickEvent(**values)


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
            bid_volumes=(-1,),
            ask_prices=(23000.0,),
            ask_volumes=(2,),
            simtrade=False,
            raw_payload={"source": "fixture"},
        )

        decision = monitor.evaluate(event)

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reasons, ("CROSSED_BOOK", "INVALID_DEPTH"))
        rejection = monitor.rejections[0]
        self.assertEqual(rejection.event_id, "quote-1")
        self.assertEqual(rejection.raw_payload["source"], "fixture")


if __name__ == "__main__":
    unittest.main()
