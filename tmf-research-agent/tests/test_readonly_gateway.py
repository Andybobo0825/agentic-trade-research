from __future__ import annotations

import unittest
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from enum import IntEnum
from types import SimpleNamespace

from tmf_research.infrastructure.readonly_gateway import MarketDataGateway
from tmf_research.infrastructure.shioaji_market_data import (
    ContractResolutionError,
    ShioajiMarketDataGateway,
)


FIXED_NOW = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)


class FakeTickKind(IntEnum):
    TRADE = 1


class FakeQuote:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object, object]] = []
        self.tick_callback: Callable[..., None] | None = None
        self.bidask_callback: Callable[..., None] | None = None

    def set_on_tick_fop_v1_callback(
        self,
        callback: Callable[..., None],
    ) -> None:
        self.tick_callback = callback

    def set_on_bidask_fop_v1_callback(
        self,
        callback: Callable[..., None],
    ) -> None:
        self.bidask_callback = callback

    def subscribe(
        self,
        contract: object,
        *,
        quote_type: object,
        version: object,
    ) -> None:
        self.calls.append(("subscribe", contract, quote_type, version))

    def unsubscribe(
        self,
        contract: object,
        *,
        quote_type: object,
        version: object,
    ) -> None:
        self.calls.append(("unsubscribe", contract, quote_type, version))


class FakeApi:
    def __init__(self) -> None:
        self.raw_contract = SimpleNamespace(
            code="TMFR1",
            target_code="TMF202607",
            symbol="TMFR1",
            category="TMF",
            delivery_month="202607",
            delivery_date="2026-07-15",
        )
        self.Contracts = SimpleNamespace(Futures={"TMFR1": self.raw_contract})
        self.quote = FakeQuote()
        self.subscription_calls: list[tuple[str, object, object]] = []
        self.history_calls: list[tuple[object, ...]] = []
        self.tick_payload: object = {
            "ts": [1, 2],
            "close": [100.0, 101.0],
        }

    def subscribe(
        self,
        contract: object,
        *,
        quote_type: object,
    ) -> None:
        self.subscription_calls.append(("subscribe", contract, quote_type))

    def unsubscribe(
        self,
        contract: object,
        *,
        quote_type: object,
    ) -> None:
        self.subscription_calls.append(("unsubscribe", contract, quote_type))

    def ticks(self, contract: object, *, date: str) -> object:
        self.history_calls.append(("ticks", contract, date))
        return self.tick_payload

    def kbars(
        self,
        contract: object,
        *,
        start: str,
        end: str,
    ) -> dict[str, object]:
        self.history_calls.append(("kbars", contract, start, end))
        return {"ts": [1], "Close": [101.0]}


class ReadonlyGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.gateway = ShioajiMarketDataGateway(
            self.api,
            tick_quote_type="tick",
            bidask_quote_type="bidask",
            quote_version="v1",
            clock=lambda: FIXED_NOW,
        )

    def test_resolves_near_contract_without_exposing_raw_contract(self) -> None:
        contract = self.gateway.resolve_near_contract()

        self.assertEqual(contract.alias_code, "TMFR1")
        self.assertEqual(contract.target_code, "TMF202607")
        self.assertEqual(contract.symbol, "TMFR1")
        self.assertEqual(contract.category, "TMF")
        self.assertEqual(contract.delivery_month, "202607")
        self.assertEqual(contract.delivery_date, "2026-07-15")
        self.assertEqual(contract.resolved_at, FIXED_NOW)
        self.assertEqual(contract.resolver_version, "shioaji-near-v1")
        self.assertFalse(hasattr(contract, "raw_contract"))
        self.assertIsInstance(self.gateway, MarketDataGateway)

    def test_delegates_tick_and_bidask_subscriptions_inside_adapter(self) -> None:
        contract = self.gateway.resolve_near_contract()

        self.gateway.subscribe_tick(contract)
        self.gateway.subscribe_bidask(contract)
        self.gateway.unsubscribe_tick(contract)
        self.gateway.unsubscribe_bidask(contract)

        self.assertEqual(
            self.api.subscription_calls,
            [
                ("subscribe", self.api.raw_contract, "tick"),
                ("subscribe", self.api.raw_contract, "bidask"),
                ("unsubscribe", self.api.raw_contract, "tick"),
                ("unsubscribe", self.api.raw_contract, "bidask"),
            ],
        )

    def test_adapts_raw_sdk_callbacks_to_immutable_mappings(self) -> None:
        received: list[Mapping[str, object]] = []
        self.gateway.register_tick_callback(received.append)
        self.gateway.register_bidask_callback(received.append)

        tick = {"code": "TMF202607", "close": [23000.0]}
        quote = SimpleNamespace(code="TMF202607", bid_price=[22999.0])
        tick_callback = self.api.quote.tick_callback
        bidask_callback = self.api.quote.bidask_callback
        self.assertIsNotNone(tick_callback)
        self.assertIsNotNone(bidask_callback)
        assert tick_callback is not None
        assert bidask_callback is not None
        tick_callback("futures", tick)
        bidask_callback("futures", quote)
        tick["code"] = "MUTATED"

        self.assertEqual(received[0]["code"], "TMF202607")
        self.assertEqual(received[0]["close"], (23000.0,))
        self.assertEqual(received[1]["bid_price"], (22999.0,))

    def test_fetches_historical_market_data_as_domain_batches(self) -> None:
        contract = self.gateway.resolve_near_contract()

        ticks = self.gateway.fetch_ticks(contract, "2026-07-14")
        kbars = self.gateway.fetch_kbars(contract, "2026-07-01", "2026-07-14")

        self.assertEqual(ticks.contract, contract)
        self.assertEqual(ticks.date, "2026-07-14")
        self.assertEqual(ticks.fetched_at, FIXED_NOW)
        self.assertEqual(ticks.payload["close"], (100.0, 101.0))
        self.assertEqual(kbars.contract, contract)
        self.assertEqual(kbars.start, "2026-07-01")
        self.assertEqual(kbars.end, "2026-07-14")
        self.assertEqual(kbars.fetched_at, FIXED_NOW)
        self.assertEqual(kbars.payload["Close"], (101.0,))
        self.assertEqual(
            self.api.history_calls,
            [
                ("ticks", self.api.raw_contract, "2026-07-14"),
                (
                    "kbars",
                    self.api.raw_contract,
                    "2026-07-01",
                    "2026-07-14",
                ),
            ],
        )

        close_values = ticks.payload["close"]
        self.assertIsInstance(close_values, tuple)
        with self.assertRaises(AttributeError):
            close_values.append(102.0)  # type: ignore[attr-defined]

    def test_rejects_opaque_historical_payload_instead_of_leaking_it(self) -> None:
        contract = self.gateway.resolve_near_contract()
        self.api.tick_payload = object()

        with self.assertRaisesRegex(TypeError, "unsupported market-data payload"):
            self.gateway.fetch_ticks(contract, "2026-07-14")

    def test_normalizes_enum_subclasses_to_primitive_values(self) -> None:
        contract = self.gateway.resolve_near_contract()
        self.api.tick_payload = {"kind": FakeTickKind.TRADE}

        ticks = self.gateway.fetch_ticks(contract, "2026-07-14")

        self.assertEqual(ticks.payload["kind"], 1)
        self.assertIs(type(ticks.payload["kind"]), int)

    def test_rejects_contract_values_not_resolved_by_this_gateway(self) -> None:
        contract = replace(
            self.gateway.resolve_near_contract(),
            target_code="TMF_UNKNOWN",
        )

        with self.assertRaisesRegex(ContractResolutionError, "TMF_UNKNOWN"):
            self.gateway.subscribe_tick(contract)

    def test_fails_closed_when_near_contract_is_missing(self) -> None:
        self.api.Contracts.Futures = {}

        with self.assertRaisesRegex(ContractResolutionError, "TMFR1"):
            self.gateway.resolve_near_contract()

    def test_fails_closed_when_continuous_contract_has_no_target_code(self) -> None:
        self.api.raw_contract.target_code = ""

        with self.assertRaisesRegex(ContractResolutionError, "target code"):
            self.gateway.resolve_near_contract()


if __name__ == "__main__":
    unittest.main()
