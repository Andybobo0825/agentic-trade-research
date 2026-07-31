from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from tmf_research.collection.backfill import SOURCE, HistoricalTickRecord
from tmf_research.domain.sessions import TradingCalendar, TradingDay
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore, SegmentManifest
from tmf_research.processing.session_resolver import SessionResolver
from tmf_research.validation.dataset_lineage import _session_batches


TAIPEI = ZoneInfo("Asia/Taipei")
DAYS = ("2025-01-06", "2025-01-07", "2025-01-08")


class RecordingStore(AppendOnlyRawStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root, writer_version="backfill-v1")
        self.read_segments: list[str] = []

    def read_verified(self, manifest: SegmentManifest) -> tuple[dict[str, object], ...]:
        self.read_segments.append(manifest.segment_id)
        return super().read_verified(manifest)


def day_only_calendar() -> TradingCalendar:
    return TradingCalendar(
        version="streaming-fixture-v1",
        timezone="Asia/Taipei",
        days=tuple(
            TradingDay(
                trading_date=date.fromisoformat(day),
                day_close=time(13, 45),
                night_open=None,
                night_close=None,
            )
            for day in DAYS
        ),
    )


def day_records(day: str) -> tuple[HistoricalTickRecord, ...]:
    return tuple(
        HistoricalTickRecord(
            schema_version="1.1.0",
            event_id=f"hist-tick-TMFR1-{day}-{index:06d}",
            exchange_datetime=datetime.fromisoformat(f"{day}T09:0{index}:00+08:00"),
            received_at=datetime(2025, 7, 1, 0, 0, tzinfo=timezone.utc),
            source=SOURCE,
            alias_code="TMFR1",
            derived_target_code="TMF202501",
            derived_delivery_date="2025-01-15",
            target_derivation="taifex-third-wednesday-v1",
            fields={
                "close": 23000.0 + index,
                "volume": 2,
                "bid_price": 22999.0 + index,
                "bid_volume": 5,
                "ask_price": 23001.0 + index,
                "ask_volume": 7,
                "tick_type": 1,
            },
        )
        for index in range(3)
    )


class StreamingSessionBatchesTests(unittest.TestCase):
    def test_historical_days_stream_lazily_in_chronological_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecordingStore(Path(directory))
            manifests = {}
            for day in ("2025-01-08", "2025-01-06", "2025-01-07"):
                manifests[day] = store.append_segment(
                    "historical-tick",
                    day_records(day),
                    segment_id=f"backfill-tick-TMFR1-{day}",
                    created_at=datetime(2025, 7, 1, tzinfo=timezone.utc),
                )
            calendar = day_only_calendar()
            reasons: set[str] = set()
            stream = _session_batches(
                store,
                tuple(manifests.values()),
                calendar,
                SessionResolver(calendar),
                reasons,
            )

            first = next(stream)
            self.assertEqual((first.trading_date, first.session), (DAYS[0], "DAY"))
            self.assertEqual(
                store.read_segments,
                [f"backfill-tick-TMFR1-{day}" for day in DAYS[:2]],
            )

            rest = list(stream)
            self.assertEqual(
                [(batch.trading_date, batch.session) for batch in rest],
                [(DAYS[1], "DAY"), (DAYS[2], "DAY")],
            )
            self.assertEqual(
                store.read_segments,
                [f"backfill-tick-TMFR1-{day}" for day in DAYS],
            )
            self.assertEqual(reasons, set())
            batches = (first, *rest)
            self.assertTrue(all(batch.ticks and batch.quotes for batch in batches))
            self.assertEqual(
                [batch.order_key for batch in batches],
                sorted(batch.order_key for batch in batches),
            )


if __name__ == "__main__":
    unittest.main()
