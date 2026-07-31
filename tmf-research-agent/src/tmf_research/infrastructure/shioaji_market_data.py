from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType

from tmf_research.domain.contracts import ContractInfo, KbarBatch, TickBatch


Clock = Callable[[], datetime]
MarketCallback = Callable[[Mapping[str, object]], None]


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
    mapping = _payload_mapping(payload)
    frozen = _freeze_value(mapping)
    if not isinstance(frozen, Mapping):
        raise TypeError("market-data payload did not normalize to a mapping")
    return frozen


def _payload_mapping(payload: object) -> Mapping[object, object]:
    if isinstance(payload, Mapping):
        return payload
    if is_dataclass(payload) and not isinstance(payload, type):
        return {field.name: getattr(payload, field.name) for field in fields(payload)}
    for method_name in ("model_dump", "dict", "_asdict", "to_dict"):
        method = getattr(payload, method_name, None)
        if callable(method):
            candidate = method()
            if isinstance(candidate, Mapping):
                return candidate
    attributes = getattr(payload, "__dict__", None)
    if isinstance(attributes, Mapping):
        return {
            key: value
            for key, value in attributes.items()
            if isinstance(key, str) and not key.startswith("_")
        }
    raise TypeError(
        f"unsupported market-data payload type: {type(payload).__name__}"
    )


def _freeze_value(value: object) -> object:
    if isinstance(value, Enum):
        return _freeze_value(value.value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_value(item) for item in value)
    to_list = getattr(value, "tolist", None)
    if callable(to_list):
        return _freeze_value(to_list())
    raise TypeError(
        f"unsupported market-data payload value: {type(value).__name__}"
    )


class ShioajiMarketDataGateway:
    """Sole owner of raw Shioaji objects in the TMF sidecar."""

    resolver_version = "shioaji-near-v1"

    def __init__(
        self,
        api: object,
        *,
        quote_type: object,
        quote_version: object | None = None,
        alias_code: str = "TMFR1",
        clock: Clock | None = None,
    ) -> None:
        if not alias_code.strip():
            raise ValueError("alias_code is required")
        self._api = api
        self._quote_type = quote_type
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

    def register_quote_callback(self, callback: MarketCallback) -> None:
        def adapt(*args: object) -> None:
            if not args:
                raise TypeError("quote callback payload is required")
            callback(_payload_snapshot(args[-1]))

        getattr(self._api, "set_on_quote_fop_v1_callback")(adapt)

    def subscribe_quote(self, contract: ContractInfo) -> None:
        self._change_subscription("subscribe", contract, self._quote_type)

    def unsubscribe_quote(self, contract: ContractInfo) -> None:
        self._change_subscription("unsubscribe", contract, self._quote_type)

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
        if action == "subscribe":
            direct_method = getattr(self._api, "subscribe", None)
        elif action == "unsubscribe":
            direct_method = getattr(self._api, "unsubscribe", None)
        else:
            raise AssertionError(f"unsupported subscription action: {action}")
        kwargs: dict[str, object] = {"quote_type": quote_type}
        if self._quote_version is not None:
            kwargs["version"] = self._quote_version
        if callable(direct_method):
            direct_method(raw_contract, **kwargs)
            return

        quote_manager = getattr(self._api, "quote")
        method = getattr(quote_manager, action)
        method(raw_contract, **kwargs)


def create_market_data_session(
    *,
    api_key: str,
    secret_key: str,
    simulation: bool,
    alias_code: str = "TMFR1",
    clock: Clock | None = None,
) -> ShioajiMarketDataGateway:
    """Open a market-data-only Shioaji session inside the adapter boundary.

    Accepts API-key credentials only: no certificate, person id, or account
    parameter exists, so brokerage capabilities cannot be activated here.
    """

    if not api_key.strip() or not secret_key.strip():
        raise ValueError("api_key and secret_key are required")
    import shioaji  # type: ignore[import-not-found]

    api = shioaji.Shioaji(simulation=simulation)
    api.login(
        api_key=api_key,
        secret_key=secret_key,
        subscribe_trade=False,
    )
    return ShioajiMarketDataGateway(
        api,
        quote_type=shioaji.constant.QuoteType.Quote,
        quote_version=shioaji.constant.QuoteVersion.v1,
        alias_code=alias_code,
        clock=clock,
    )
