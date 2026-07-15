from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tmf_research.domain.events import BidAskEvent, TickEvent


NOW = datetime(2026, 7, 15, 8, 45, tzinfo=timezone.utc)


class CollectionEventTests(unittest.TestCase):
    def test_tick_event_is_frozen_timezone_aware_and_preserves_payload(self) -> None:
        payload = {"code": "TMF202607", "depth": [1, 2]}
        event = TickEvent(
            event_id="tick-1",
            received_at=NOW,
            exchange_datetime=NOW,
            alias_code="TMFR1",
            target_code="TMF202607",
            delivery_month="202607",
            code="TMF202607",
            close=23000.0,
            volume=2,
            simtrade=False,
            raw_payload=payload,
        )

        payload["code"] = "MUTATED"
        self.assertEqual(event.raw_payload["code"], "TMF202607")
        self.assertEqual(event.raw_payload["depth"], (1, 2))
        with self.assertRaises(AttributeError):
            event.target_code = "OTHER"  # type: ignore[misc]

    def test_bidask_event_requires_timezone_aware_timestamps(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            BidAskEvent(
                event_id="quote-1",
                received_at=NOW.replace(tzinfo=None),
                exchange_datetime=NOW,
                alias_code="TMFR1",
                target_code="TMF202607",
                delivery_month="202607",
                code="TMF202607",
                bid_prices=(22999.0,),
                bid_volumes=(3,),
                ask_prices=(23001.0,),
                ask_volumes=(4,),
                simtrade=False,
                raw_payload={},
            )


if __name__ == "__main__":
    unittest.main()
