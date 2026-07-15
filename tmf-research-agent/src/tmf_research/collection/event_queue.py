from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from typing import Generic, TypeVar
from uuid import uuid4

from tmf_research.domain.events import QueueBackpressureEvent


T = TypeVar("T")
Clock = Callable[[], datetime]
EventIdFactory = Callable[[], str]


class BoundedEventQueue(Generic[T]):
    """Thread-safe bounded queue whose producer path never waits."""

    def __init__(
        self,
        capacity: int,
        *,
        clock: Clock | None = None,
        event_id_factory: EventIdFactory | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._queue: Queue[T] = Queue(maxsize=capacity)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._event_id_factory = event_id_factory or (lambda: str(uuid4()))
        self._dropped_event_count = 0
        self._backpressure_events: list[QueueBackpressureEvent] = []

    def offer(self, event: T) -> bool:
        try:
            self._queue.put_nowait(event)
            return True
        except Full:
            self._dropped_event_count += 1
            self._backpressure_events.append(
                QueueBackpressureEvent(
                    event_id=self._event_id_factory(),
                    occurred_at=self._clock(),
                    queue_size=self._queue.qsize(),
                    dropped_event_count=self._dropped_event_count,
                )
            )
            return False

    def pop(self) -> T | None:
        try:
            return self._queue.get_nowait()
        except Empty:
            return None

    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def dropped_event_count(self) -> int:
        return self._dropped_event_count

    @property
    def quality_valid(self) -> bool:
        return self._dropped_event_count == 0

    @property
    def backpressure_events(self) -> tuple[QueueBackpressureEvent, ...]:
        return tuple(self._backpressure_events)
