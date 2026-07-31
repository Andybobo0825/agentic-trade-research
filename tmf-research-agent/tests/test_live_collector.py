from __future__ import annotations

import ast
import inspect
import textwrap
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
        self.quote_callback: MarketCallback | None = None
        self.subscriptions: list[tuple[str, str]] = []

    def resolve_near_contract(self) -> ContractInfo:
        return self.contract

    def register_quote_callback(self, callback: MarketCallback) -> None:
        self.quote_callback = callback

    def subscribe_quote(self, contract: ContractInfo) -> None:
        self.subscriptions.append(("quote", contract.target_code))


class LiveCollectorTests(unittest.TestCase):
    def test_market_callback_has_executable_minimality_tripwires(self) -> None:
        forbidden_names = {
            "acquire",
            "aggregate",
            "fit",
            "history",
            "infer",
            "join",
            "model",
            "open",
            "paper",
            "predict",
            "sleep",
            "train",
            "wait",
            "write",
        }
        tree = ast.parse(textwrap.dedent(inspect.getsource(LiveCollector._on_quote)))
        self.assertFalse(
            any(isinstance(node, (ast.Await, ast.For, ast.Try, ast.While, ast.With)) for node in ast.walk(tree))
        )
        called_names = {
            node.func.id.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        called_attributes = {
            node.func.attr.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(forbidden_names & (called_names | called_attributes))
        offer_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "offer"
        ]
        self.assertEqual(len(offer_calls), 2)

    def test_subscribes_callback_and_enqueues_tick_and_bidask_events(self) -> None:
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
        quote_callback = gateway.quote_callback
        self.assertIsNotNone(quote_callback)
        assert quote_callback is not None
        quote_callback(
            {
                "datetime": NOW,
                "code": "TMF202607",
                "close": 23000,
                "volume": 2,
                "underlying_price": 23050.5,
                "bid_price": [22999, 22998],
                "bid_volume": [3, 2],
                "ask_price": [23001, 23002],
                "ask_volume": [4, 5],
            }
        )

        self.assertEqual(resolution.contract.target_code, "TMF202607")
        self.assertEqual(gateway.subscriptions, [("quote", "TMF202607")])
        tick = queue.pop()
        bidask = queue.pop()
        self.assertIsInstance(tick, TickEvent)
        self.assertIsInstance(bidask, BidAskEvent)
        assert isinstance(tick, TickEvent)
        assert isinstance(bidask, BidAskEvent)
        self.assertEqual(tick.target_code, "TMF202607")
        self.assertEqual(tick.underlying_price, 23050.5)
        self.assertEqual(bidask.bid_prices, (22999.0, 22998.0))
        self.assertEqual(bidask.underlying_price, 23050.5)

    def test_zero_volume_quote_only_enqueues_bidask(self) -> None:
        gateway = FakeGateway()
        queue = BoundedEventQueue[MarketEvent](capacity=4)
        collector = LiveCollector(
            gateway,
            ContractTracker(gateway),
            queue,
            clock=lambda: NOW,
        )
        collector.start()
        quote_callback = gateway.quote_callback
        assert quote_callback is not None
        quote_callback(
            {
                "datetime": NOW,
                "code": "TMF202607",
                "close": 23000,
                "volume": 0,
                "bid_price": [22999],
                "bid_volume": [3],
                "ask_price": [23001],
                "ask_volume": [4],
            }
        )

        event = queue.pop()
        self.assertIsInstance(event, BidAskEvent)
        self.assertIsNone(queue.pop())

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

        quote_callback = gateway.quote_callback
        self.assertIsNotNone(quote_callback)
        assert quote_callback is not None
        quote_callback(payload)
        quote_callback(payload)

        self.assertEqual(queue.dropped_event_count, 3)
        self.assertFalse(queue.quality_valid)


if __name__ == "__main__":
    unittest.main()
