from __future__ import annotations

import inspect
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

from tmf_research.domain.paper_trades import PaperIntent
from tmf_research.paper.broker import DuplicatePaperIntentError, PaperBroker
from tmf_research.security.readonly_verifier import verify_readonly


NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)


class PaperBoundaryTests(unittest.TestCase):
    def test_records_only_an_immutable_paper_intent(self) -> None:
        broker = PaperBroker()
        intent = PaperIntent(
            intent_id="paper-1",
            direction="LONG",
            quantity=1,
            created_at=NOW,
        )

        record = broker.record_intent(intent)

        self.assertEqual(record.intent_id, "paper-1")
        self.assertEqual(record.direction, "LONG")
        self.assertEqual(record.quantity, 1)
        self.assertEqual(record.recorded_at, NOW)
        self.assertEqual(record.execution_mode, "PAPER")
        self.assertEqual(broker.records, (record,))
        with self.assertRaises(FrozenInstanceError):
            record.quantity = 2  # type: ignore[misc]

    def test_rejects_duplicate_intent_ids(self) -> None:
        broker = PaperBroker()
        intent = PaperIntent("paper-1", "SHORT", 1, NOW)
        broker.record_intent(intent)

        with self.assertRaisesRegex(DuplicatePaperIntentError, "paper-1"):
            broker.record_intent(intent)

    def test_rejects_non_directional_or_non_unit_intents(self) -> None:
        with self.assertRaisesRegex(ValueError, "direction"):
            PaperIntent("paper-1", "NO_TRADE", 1, NOW)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "quantity"):
            PaperIntent("paper-2", "LONG", 2, NOW)
        with self.assertRaisesRegex(ValueError, "intent_id"):
            PaperIntent(" ", "LONG", 1, NOW)

    def test_constructor_cannot_receive_external_capabilities(self) -> None:
        parameters = inspect.signature(PaperBroker.__init__).parameters

        self.assertEqual(tuple(parameters), ("self",))

    def test_paper_source_passes_readonly_network_boundary(self) -> None:
        source_root = Path(inspect.getfile(PaperBroker)).parents[2]

        report = verify_readonly(source_root)

        self.assertTrue(report.ok, report.render())


if __name__ == "__main__":
    unittest.main()
