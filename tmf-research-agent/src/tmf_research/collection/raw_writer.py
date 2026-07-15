from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from tmf_research.infrastructure.raw_store import AppendOnlyRawStore, SegmentManifest


class RawWriter:
    """Small collection boundary that always creates a new immutable segment."""

    def __init__(self, store: AppendOnlyRawStore) -> None:
        self._store = store

    def write(
        self,
        event_type: str,
        events: Sequence[object],
        *,
        segment_id: str,
        created_at: datetime,
    ) -> SegmentManifest:
        return self._store.append_segment(
            event_type,
            events,
            segment_id=segment_id,
            created_at=created_at,
        )
