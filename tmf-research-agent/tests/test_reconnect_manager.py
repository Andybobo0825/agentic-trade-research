from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from tmf_research.domain.contracts import ContractInfo
from tmf_research.infrastructure.contract_resolver import ContractTracker
from tmf_research.infrastructure.reconnect_manager import (
    ConnectionState,
    ReconnectManager,
)


NOW = datetime(2026, 7, 15, 8, 45, tzinfo=timezone.utc)


class FakeGateway:
    def __init__(self, contracts: list[ContractInfo]) -> None:
        self.contracts = contracts
        self.calls: list[tuple[str, str]] = []

    def resolve_near_contract(self) -> ContractInfo:
        return self.contracts.pop(0)

    def subscribe_tick(self, contract: ContractInfo) -> None:
        self.calls.append(("tick", contract.target_code))

    def subscribe_bidask(self, contract: ContractInfo) -> None:
        self.calls.append(("bidask", contract.target_code))


class ReconnectManagerTests(unittest.TestCase):
    def test_tracks_disconnect_and_resubscribes_resolved_contract(self) -> None:
        first = ContractInfo(
            alias_code="TMFR1",
            target_code="TMF202607",
            symbol="TMFR1",
            category="TMF",
            delivery_month="202607",
            delivery_date="2026-07-15",
            resolved_at=NOW,
            resolver_version="test-v1",
        )
        second = replace(
            first,
            target_code="TMF202608",
            delivery_month="202608",
            delivery_date="2026-08-19",
        )
        gateway = FakeGateway([first, second])
        tracker = ContractTracker(gateway, clock=lambda: NOW)
        tracker.refresh()
        manager = ReconnectManager(gateway, tracker, clock=lambda: NOW)

        disconnected = manager.mark_disconnected("socket closed")
        result = manager.reconnect()

        self.assertEqual(disconnected.connection_status, "DISCONNECTED")
        self.assertEqual(manager.state, ConnectionState.CONNECTED)
        self.assertEqual(result.connection.connection_status, "CONNECTED")
        rollover = result.rollover
        self.assertIsNotNone(rollover)
        assert rollover is not None
        self.assertEqual(rollover.new_target_code, "TMF202608")
        self.assertEqual(
            gateway.calls,
            [("tick", "TMF202608"), ("bidask", "TMF202608")],
        )


if __name__ == "__main__":
    unittest.main()
