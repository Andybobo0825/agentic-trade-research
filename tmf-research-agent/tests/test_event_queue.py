from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tmf_research.collection.event_queue import BoundedEventQueue


NOW = datetime(2026, 7, 15, 8, 45, tzinfo=timezone.utc)


class EventQueueTests(unittest.TestCase):
    def test_offer_never_blocks_and_records_backpressure_evidence(self) -> None:
        queue = BoundedEventQueue[object](
            capacity=1,
            clock=lambda: NOW,
            event_id_factory=lambda: "backpressure-1",
        )

        self.assertTrue(queue.offer(object()))
        self.assertFalse(queue.offer(object()))

        self.assertEqual(queue.size, 1)
        self.assertEqual(queue.dropped_event_count, 1)
        self.assertFalse(queue.quality_valid)
        incident = queue.backpressure_events[0]
        self.assertEqual(incident.event_type, "QUEUE_BACKPRESSURE")
        self.assertEqual(incident.queue_size, 1)
        self.assertEqual(incident.dropped_event_count, 1)

    def test_pop_returns_enqueued_event_without_waiting(self) -> None:
        queue = BoundedEventQueue[str](capacity=2)
        queue.offer("tick")

        self.assertEqual(queue.pop(), "tick")
        self.assertIsNone(queue.pop())


if __name__ == "__main__":
    unittest.main()
