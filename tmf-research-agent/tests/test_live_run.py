from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from tmf_research.collection.live_collector import MarketCallback
from tmf_research.collection.live_run import run_live_collection
from tmf_research.domain.contracts import ContractInfo
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore


_TAIPEI = ZoneInfo("Asia/Taipei")
DAY_START = datetime(2026, 7, 15, 9, 0, tzinfo=_TAIPEI)


class FakeGateway:
    def __init__(self) -> None:
        self.contract = ContractInfo(
            alias_code="TMFR1",
            target_code="TMF202607",
            symbol="TMFR1",
            category="TMF",
            delivery_month="202607",
            delivery_date="2026-07-15",
            resolved_at=DAY_START,
            resolver_version="test-v1",
        )
        self.quote_callback: MarketCallback | None = None
        self.subscribed: list[str] = []

    def resolve_near_contract(self) -> ContractInfo:
        return self.contract

    def register_quote_callback(self, callback: MarketCallback) -> None:
        self.quote_callback = callback

    def subscribe_quote(self, contract: ContractInfo) -> None:
        self.subscribed.append(contract.target_code)


class VirtualClock:
    def __init__(self, start: datetime) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class RunLiveCollectionTests(unittest.TestCase):
    def test_flushes_tagged_tick_and_bidask_events_into_raw_segments(self) -> None:
        clock = VirtualClock(DAY_START)
        gateway = FakeGateway()
        payloads = [
            {
                "datetime": DAY_START,
                "code": "TMF202607",
                "close": 23000.0,
                "volume": 2,
                "underlying_price": 23050.0,
                "bid_price": [22999.0],
                "bid_volume": [3],
                "ask_price": [23001.0],
                "ask_volume": [4],
            },
            {
                "datetime": DAY_START + timedelta(seconds=1),
                "code": "TMF202607",
                "close": 23001.0,
                "volume": 0,
                "underlying_price": 23051.0,
                "bid_price": [23000.0],
                "bid_volume": [2],
                "ask_price": [23002.0],
                "ask_volume": [5],
            },
        ]

        def sleep(seconds: float) -> None:
            clock.advance(seconds)
            if payloads:
                callback = gateway.quote_callback
                assert callback is not None
                callback(payloads.pop(0))

        with TemporaryDirectory() as directory:
            store = AppendOnlyRawStore(Path(directory), writer_version="live-v1")
            summary = run_live_collection(
                gateway,
                store,
                until=DAY_START + timedelta(seconds=5),
                flush_interval_seconds=1.0,
                poll_interval_seconds=0.5,
                clock=clock,
                sleep=sleep,
            )

            self.assertEqual(summary.alias_code, "TMFR1")
            self.assertEqual(summary.stored_records, 3)
            self.assertGreaterEqual(summary.stored_segments, 1)
            self.assertEqual(summary.dropped_event_count, 0)
            self.assertTrue(
                store.has_segment(
                    "live-tick",
                    "live-tick-TMFR1-2026-07-15-DAY-000000",
                )
            )
            self.assertTrue(
                store.has_segment(
                    "live-bidask",
                    "live-bidask-TMFR1-2026-07-15-DAY-000000",
                )
            )
        self.assertEqual(gateway.subscribed, ["TMF202607"])

    def test_second_run_resumes_sequence_numbering_instead_of_colliding(self) -> None:
        payload = {
            "datetime": DAY_START,
            "code": "TMF202607",
            "close": 23000.0,
            "volume": 1,
            "underlying_price": 23050.0,
            "bid_price": [22999.0],
            "bid_volume": [3],
            "ask_price": [23001.0],
            "ask_volume": [4],
        }

        def make_sleep(clock: VirtualClock, gateway: FakeGateway, payloads: list[object]):
            def sleep(seconds: float) -> None:
                clock.advance(seconds)
                if payloads:
                    callback = gateway.quote_callback
                    assert callback is not None
                    callback(payloads.pop(0))
            return sleep

        with TemporaryDirectory() as directory:
            store = AppendOnlyRawStore(Path(directory), writer_version="live-v1")

            clock1 = VirtualClock(DAY_START)
            gateway1 = FakeGateway()
            run_live_collection(
                gateway1,
                store,
                until=DAY_START + timedelta(seconds=2),
                flush_interval_seconds=1.0,
                poll_interval_seconds=0.5,
                clock=clock1,
                sleep=make_sleep(clock1, gateway1, [dict(payload)]),
            )

            clock2 = VirtualClock(DAY_START + timedelta(seconds=10))
            gateway2 = FakeGateway()
            summary2 = run_live_collection(
                gateway2,
                store,
                until=clock2.value + timedelta(seconds=2),
                flush_interval_seconds=1.0,
                poll_interval_seconds=0.5,
                clock=clock2,
                sleep=make_sleep(clock2, gateway2, [dict(payload)]),
            )

            self.assertEqual(summary2.stored_records, 2)
            self.assertTrue(
                store.has_segment("live-tick", "live-tick-TMFR1-2026-07-15-DAY-000000")
            )
            self.assertTrue(
                store.has_segment("live-tick", "live-tick-TMFR1-2026-07-15-DAY-000001")
            )


if __name__ == "__main__":
    unittest.main()
