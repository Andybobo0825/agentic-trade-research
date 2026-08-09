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
        self.subscription_calls: list[tuple[str, object, object, object]] = []
        self.history_calls: list[tuple[object, ...]] = []
        self.quote_callback: Callable[..., None] | None = None
        self.tick_payload: object = {
            "ts": [1, 2],
            "close": [100.0, 101.0],
        }

    def set_on_quote_fop_v1_callback(self, callback: Callable[..., None]) -> None:
        self.quote_callback = callback

    def subscribe(
        self,
        contract: object,
        *,
        quote_type: object,
        version: object,
    ) -> None:
        self.subscription_calls.append(("subscribe", contract, quote_type, version))

    def unsubscribe(
        self,
        contract: object,
        *,
        quote_type: object,
        version: object,
    ) -> None:
        self.subscription_calls.append(("unsubscribe", contract, quote_type, version))

    def ticks(self, contract: object, *, date: str) -> object:
        self.history_calls.append(("ticks", contract, date))
        return self.tick_payload

    def kbars(
        self,
        contract: object,
        *,
        start: str,
        end: str,
        timeout: int,
    ) -> dict[str, object]:
        self.history_calls.append(("kbars", contract, start, end, timeout))
        return {"ts": [1], "Close": [101.0]}


class ReadonlyGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.gateway = ShioajiMarketDataGateway(
            self.api,
            quote_type="quote",
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

    def test_delegates_quote_subscription_inside_adapter(self) -> None:
        contract = self.gateway.resolve_near_contract()

        self.gateway.subscribe_quote(contract)
        self.gateway.unsubscribe_quote(contract)

        self.assertEqual(
            self.api.subscription_calls,
            [
                ("subscribe", self.api.raw_contract, "quote", "v1"),
                ("unsubscribe", self.api.raw_contract, "quote", "v1"),
            ],
        )

    def test_adapts_raw_sdk_callback_to_immutable_mapping(self) -> None:
        received: list[Mapping[str, object]] = []
        self.gateway.register_quote_callback(received.append)

        quote = {"code": "TMF202607", "close": [23000.0], "bid_price": [22999.0]}
        quote_callback = self.api.quote_callback
        self.assertIsNotNone(quote_callback)
        assert quote_callback is not None
        quote_callback("futures", quote)
        quote["code"] = "MUTATED"

        self.assertEqual(received[0]["code"], "TMF202607")
        self.assertEqual(received[0]["close"], (23000.0,))
        self.assertEqual(received[0]["bid_price"], (22999.0,))

    def test_adapts_a_to_dict_only_sdk_object_like_real_quotefopv1(self) -> None:
        class FakeQuoteFOPv1:
            __slots__ = ()

            def to_dict(self) -> dict[str, object]:
                return {"code": "TMF202607", "close": 23000.0, "volume": 1}

        received: list[Mapping[str, object]] = []
        self.gateway.register_quote_callback(received.append)

        quote_callback = self.api.quote_callback
        assert quote_callback is not None
        quote_callback(FakeQuoteFOPv1())

        self.assertEqual(received[0]["code"], "TMF202607")
        self.assertEqual(received[0]["volume"], 1)

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
                    120000,
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
            self.gateway.subscribe_quote(contract)

    def test_fails_closed_when_near_contract_is_missing(self) -> None:
        self.api.Contracts.Futures = {}

        with self.assertRaisesRegex(ContractResolutionError, "TMFR1"):
            self.gateway.resolve_near_contract()

    def test_fails_closed_when_continuous_contract_has_no_target_code(self) -> None:
        del self.api.raw_contract.target_code
        del self.api.raw_contract.code

        with self.assertRaisesRegex(ContractResolutionError, "target code"):
            self.gateway.resolve_near_contract()

    def test_derives_tmf_category_when_registry_entry_lacks_category(self) -> None:
        del self.api.raw_contract.category

        contract = self.gateway.resolve_near_contract()

        self.assertEqual(contract.category, "TMF")

    def test_resolves_verified_txf_continuous_alias_shape(self) -> None:
        raw_contract = SimpleNamespace(
            code="TXFR1",
            name="TX continuous near-month",
            delivery_month="202607",
        )
        self.api.Contracts = SimpleNamespace(
            Futures=SimpleNamespace(TXF={"TXFR1": raw_contract}),
        )
        self.gateway = ShioajiMarketDataGateway(
            self.api,
            quote_type="quote",
            quote_version="v1",
            alias_code="TXFR1",
            clock=lambda: FIXED_NOW,
        )

        contract = self.gateway.resolve_near_contract()

        self.assertEqual(contract.alias_code, "TXFR1")
        self.assertEqual(contract.target_code, "TXFR1")
        self.assertEqual(contract.symbol, "TX continuous near-month")
        self.assertEqual(contract.category, "TXF")
        self.assertEqual(contract.delivery_month, "202607")
        self.assertEqual(contract.delivery_date, "")


if __name__ == "__main__":
    unittest.main()
