from __future__ import annotations

import unittest
from collections.abc import Mapping
from datetime import datetime, timezone

from tmf_research.collection.event_queue import BoundedEventQueue
from tmf_research.collection.live_collector import LiveCollector, MarketCallback
from tmf_research.domain.contracts import ContractInfo
from tmf_research.domain.events import BidAskEvent, MarketEvent, TickEvent
from tmf_research.infrastructure.contract_resolver import ContractTracker


NOW = datetime(2026, 7, 15, 8, 45, tzinfo=timezone.utc)


class FakeGateway:
    def __init__(self) -> None:
        self.contract = ContractInfo(
            alias_code="TMFR1",
            target_code="TMF202607",
            symbol="TMFR1",
            category="TMF",
            delivery_month="202607",
            delivery_date="2026-07-15",
            resolved_at=NOW,
            resolver_version="test-v1",
        )
        self.tick_callback: MarketCallback | None = None
        self.bidask_callback: MarketCallback | None = None
        self.subscriptions: list[tuple[str, str]] = []

    def resolve_near_contract(self) -> ContractInfo:
        return self.contract

    def register_tick_callback(self, callback: MarketCallback) -> None:
        self.tick_callback = callback

    def register_bidask_callback(self, callback: MarketCallback) -> None:
        self.bidask_callback = callback

    def subscribe_tick(self, contract: ContractInfo) -> None:
        self.subscriptions.append(("tick", contract.target_code))

    def subscribe_bidask(self, contract: ContractInfo) -> None:
        self.subscriptions.append(("bidask", contract.target_code))


class LiveCollectorTests(unittest.TestCase):
    def test_subscribes_callbacks_and_enqueues_tick_and_bidask_events(self) -> None:
        gateway = FakeGateway()
        queue = BoundedEventQueue[MarketEvent](capacity=4)
        tracker = ContractTracker(gateway)
        ids = iter(("tick-1", "bidask-1"))
        collector = LiveCollector(
            gateway,
            tracker,
            queue,
            clock=lambda: NOW,
            event_id_factory=lambda: next(ids),
        )

        resolution = collector.start()
        tick_callback = gateway.tick_callback
        bidask_callback = gateway.bidask_callback
        self.assertIsNotNone(tick_callback)
        self.assertIsNotNone(bidask_callback)
        assert tick_callback is not None
        assert bidask_callback is not None
        tick_callback(
            {"datetime": NOW, "code": "TMF202607", "close": 23000, "volume": 2}
        )
        bidask_callback(
            {
                "datetime": NOW,
                "code": "TMF202607",
                "bid_price": [22999, 22998],
                "bid_volume": [3, 2],
                "ask_price": [23001, 23002],
                "ask_volume": [4, 5],
            }
        )

        self.assertEqual(resolution.contract.target_code, "TMF202607")
        self.assertEqual(
            gateway.subscriptions,
            [("tick", "TMF202607"), ("bidask", "TMF202607")],
        )
        tick = queue.pop()
        bidask = queue.pop()
        self.assertIsInstance(tick, TickEvent)
        self.assertIsInstance(bidask, BidAskEvent)
        assert isinstance(tick, TickEvent)
        assert isinstance(bidask, BidAskEvent)
        self.assertEqual(tick.target_code, "TMF202607")
        self.assertEqual(bidask.bid_prices, (22999.0, 22998.0))

    def test_full_queue_returns_from_callback_with_drop_evidence(self) -> None:
        gateway = FakeGateway()
        queue = BoundedEventQueue[MarketEvent](capacity=1, clock=lambda: NOW)
        collector = LiveCollector(
            gateway,
            ContractTracker(gateway),
            queue,
            clock=lambda: NOW,
        )
        collector.start()
        payload: Mapping[str, object] = {
            "datetime": NOW,
            "code": "TMF202607",
            "close": 23000,
            "volume": 1,
        }

        tick_callback = gateway.tick_callback
        self.assertIsNotNone(tick_callback)
        assert tick_callback is not None
        tick_callback(payload)
        tick_callback(payload)

        self.assertEqual(queue.dropped_event_count, 1)
        self.assertFalse(queue.quality_valid)


if __name__ == "__main__":
    unittest.main()
