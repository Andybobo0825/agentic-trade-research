from __future__ import annotations

from tmf_research.infrastructure.readonly_gateway import MarketDataGateway
from tmf_research.infrastructure.shioaji_market_data import (
    Clock,
    create_market_data_session,
)


def open_market_data_session(
    *,
    api_key: str,
    secret_key: str,
    simulation: bool,
    alias_code: str = "TMFR1",
    clock: Clock | None = None,
) -> MarketDataGateway:
    """Sole composition point between consumers and the raw adapter.

    Returns the gateway strictly as the MarketDataGateway protocol; no raw
    API state or adapter internals leave this function.
    """

    return create_market_data_session(
        api_key=api_key,
        secret_key=secret_key,
        simulation=simulation,
        alias_code=alias_code,
        clock=clock,
    )
