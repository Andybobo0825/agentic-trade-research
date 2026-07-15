from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from types import MappingProxyType

from tmf_research.domain.contracts import ContractInfo, KbarBatch, TickBatch


Clock = Callable[[], datetime]


class ContractResolutionError(LookupError):
    """Raised when a real contract cannot be resolved without guessing."""


def _value(subject: object, name: str, default: object = "") -> object:
    if isinstance(subject, Mapping):
        return subject.get(name, default)
    return getattr(subject, name, default)


def _text(subject: object, name: str, default: str = "") -> str:
    value = _value(subject, name, default)
    return str(value).strip() if value is not None else default


def _payload_snapshot(payload: object) -> Mapping[str, object]:
    if isinstance(payload, Mapping):
        return MappingProxyType(dict(payload))
    return MappingProxyType({"data": payload})


class ShioajiMarketDataGateway:
    """Sole owner of raw Shioaji objects in the TMF sidecar."""

    resolver_version = "shioaji-near-v1"

    def __init__(
        self,
        api: object,
        *,
        tick_quote_type: object,
        bidask_quote_type: object,
        quote_version: object | None = None,
        alias_code: str = "TMFR1",
        clock: Clock | None = None,
    ) -> None:
        if not alias_code.strip():
            raise ValueError("alias_code is required")
        self._api = api
        self._tick_quote_type = tick_quote_type
        self._bidask_quote_type = bidask_quote_type
        self._quote_version = quote_version
        self._alias_code = alias_code.strip()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._raw_contracts: dict[str, object] = {}

    def resolve_near_contract(self) -> ContractInfo:
        raw_contract = self._resolve_alias(self._alias_code)
        target_code = _text(raw_contract, "target_code")
        if not target_code:
            raise ContractResolutionError(
                f"resolved {self._alias_code} contract has no target code"
            )

        contract = ContractInfo(
            alias_code=self._alias_code,
            target_code=target_code,
            symbol=_text(raw_contract, "symbol", self._alias_code),
            category=_text(raw_contract, "category", "TMF"),
            delivery_month=_text(raw_contract, "delivery_month"),
            delivery_date=_text(raw_contract, "delivery_date"),
            resolved_at=self._clock(),
            resolver_version=self.resolver_version,
        )
        self._raw_contracts[target_code] = raw_contract
        return contract

    def subscribe_tick(self, contract: ContractInfo) -> None:
        self._change_subscription("subscribe", contract, self._tick_quote_type)

    def subscribe_bidask(self, contract: ContractInfo) -> None:
        self._change_subscription("subscribe", contract, self._bidask_quote_type)

    def unsubscribe_tick(self, contract: ContractInfo) -> None:
        self._change_subscription("unsubscribe", contract, self._tick_quote_type)

    def unsubscribe_bidask(self, contract: ContractInfo) -> None:
        self._change_subscription("unsubscribe", contract, self._bidask_quote_type)

    def fetch_ticks(self, contract: ContractInfo, date: str) -> TickBatch:
        if not date.strip():
            raise ValueError("date is required")
        raw_contract = self._raw_contract(contract)
        payload = getattr(self._api, "ticks")(raw_contract, date=date)
        return TickBatch(
            contract=contract,
            date=date,
            fetched_at=self._clock(),
            payload=_payload_snapshot(payload),
        )

    def fetch_kbars(
        self,
        contract: ContractInfo,
        start: str,
        end: str,
    ) -> KbarBatch:
        if not start.strip() or not end.strip():
            raise ValueError("start and end are required")
        raw_contract = self._raw_contract(contract)
        payload = getattr(self._api, "kbars")(
            raw_contract,
            start=start,
            end=end,
        )
        return KbarBatch(
            contract=contract,
            start=start,
            end=end,
            fetched_at=self._clock(),
            payload=_payload_snapshot(payload),
        )

    def _resolve_alias(self, alias_code: str) -> object:
        try:
            contracts = getattr(self._api, "Contracts")
            futures = getattr(contracts, "Futures")
        except AttributeError as error:
            raise ContractResolutionError(
                "Shioaji futures contract registry is unavailable"
            ) from error

        raw_contract: object | None = None
        try:
            raw_contract = futures[alias_code]
        except (KeyError, TypeError):
            raw_contract = getattr(futures, alias_code, None)
        if raw_contract is None:
            raise ContractResolutionError(f"near contract {alias_code} is unavailable")
        return raw_contract

    def _raw_contract(self, contract: ContractInfo) -> object:
        raw_contract = self._raw_contracts.get(contract.target_code)
        if raw_contract is None:
            raise ContractResolutionError(
                f"contract {contract.target_code} was not resolved by this gateway"
            )
        return raw_contract

    def _change_subscription(
        self,
        action: str,
        contract: ContractInfo,
        quote_type: object,
    ) -> None:
        raw_contract = self._raw_contract(contract)
        direct_method = getattr(self._api, action, None)
        if callable(direct_method):
            direct_method(raw_contract, quote_type=quote_type)
            return

        quote_manager = getattr(self._api, "quote")
        method = getattr(quote_manager, action)
        kwargs: dict[str, object] = {"quote_type": quote_type}
        if self._quote_version is not None:
            kwargs["version"] = self._quote_version
        method(raw_contract, **kwargs)
