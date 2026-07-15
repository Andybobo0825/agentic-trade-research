from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from tmf_research.domain.contracts import ContractInfo
from tmf_research.infrastructure.contract_resolver import ContractTracker


NOW = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)


class FakeGateway:
    def __init__(self, contracts: list[ContractInfo]) -> None:
        self.contracts = contracts

    def resolve_near_contract(self) -> ContractInfo:
        return self.contracts.pop(0)


class ContractTrackerTests(unittest.TestCase):
    def test_tracks_real_target_code_and_emits_rollover_on_change(self) -> None:
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
            resolved_at=NOW.replace(hour=9),
        )
        tracker = ContractTracker(
            FakeGateway([first, second]),
            clock=lambda: NOW.replace(hour=9),
            event_id_factory=lambda: "rollover-1",
        )

        initial = tracker.refresh()
        rollover = tracker.refresh()

        self.assertEqual(initial.contract.target_code, "TMF202607")
        self.assertIsNone(initial.rollover)
        self.assertEqual(rollover.contract.target_code, "TMF202608")
        rollover_event = rollover.rollover
        self.assertIsNotNone(rollover_event)
        assert rollover_event is not None
        self.assertEqual(rollover_event.old_target_code, "TMF202607")
        self.assertEqual(rollover_event.new_target_code, "TMF202608")
        self.assertFalse(rollover_event.allow_paper_trade)


if __name__ == "__main__":
    unittest.main()
