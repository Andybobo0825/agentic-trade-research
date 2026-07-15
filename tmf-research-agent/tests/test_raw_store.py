from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tmf_research.collection.raw_writer import RawWriter
from tmf_research.domain.events import TickEvent
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore


NOW = datetime(2026, 7, 15, 8, 45, tzinfo=timezone.utc)


class RawStoreTests(unittest.TestCase):
    def test_rejects_path_components_that_escape_the_raw_root(self) -> None:
        event = TickEvent(
            event_id="tick-1",
            received_at=NOW,
            exchange_datetime=NOW,
            alias_code="TMFR1",
            target_code="TMF202607",
            delivery_month="202607",
            code="TMF202607",
            close=23000.0,
            volume=1,
            simtrade=False,
            raw_payload={},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "raw"
            store = AppendOnlyRawStore(root, writer_version="phase1-v1")

            with self.assertRaisesRegex(ValueError, "event_type"):
                store.append_segment(
                    "../../escape",
                    [event],
                    segment_id="segment-1",
                    created_at=NOW,
                )
            with self.assertRaisesRegex(ValueError, "segment_id"):
                store.append_segment(
                    "tick",
                    [event],
                    segment_id="../../escape",
                    created_at=NOW,
                )

            self.assertFalse((Path(directory) / "escape").exists())

    def test_rejects_duplicate_event_ids_across_segments(self) -> None:
        event = TickEvent(
            event_id="tick-1",
            received_at=NOW,
            exchange_datetime=NOW,
            alias_code="TMFR1",
            target_code="TMF202607",
            delivery_month="202607",
            code="TMF202607",
            close=23000.0,
            volume=1,
            simtrade=False,
            raw_payload={},
        )
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyRawStore(Path(directory), writer_version="phase1-v1")
            store.append_segment(
                "tick",
                [event],
                segment_id="segment-1",
                created_at=NOW,
            )

            with self.assertRaisesRegex(FileExistsError, "duplicate event_id"):
                store.append_segment(
                    "tick",
                    [event],
                    segment_id="segment-2",
                    created_at=NOW,
                )

    def test_writes_immutable_ndjson_segment_and_canonical_manifest(self) -> None:
        event = TickEvent(
            event_id="tick-1",
            received_at=NOW,
            exchange_datetime=NOW,
            alias_code="TMFR1",
            target_code="TMF202607",
            delivery_month="202607",
            code="TMF202607",
            close=23000.0,
            volume=1,
            simtrade=False,
            raw_payload={"z": 2, "a": 1},
        )
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyRawStore(Path(directory), writer_version="phase1-v1")

            manifest = store.append_segment(
                "tick",
                [event],
                segment_id="tick-20260715-0001",
                created_at=NOW,
            )

            segment = Path(directory) / manifest.relative_path
            self.assertTrue(segment.is_file())
            record = json.loads(segment.read_text(encoding="utf-8"))
            self.assertEqual(record["target_code"], "TMF202607")
            self.assertEqual(record["raw_payload"], {"a": 1, "z": 2})
            self.assertTrue(store.verify(manifest))
            manifest_line = (Path(directory) / "manifest.ndjson").read_text(
                encoding="utf-8"
            ).strip()
            self.assertEqual(
                manifest_line,
                json.dumps(json.loads(manifest_line), sort_keys=True, separators=(",", ":")),
            )
            with self.assertRaises(FileExistsError):
                store.append_segment(
                    "tick",
                    [event],
                    segment_id="tick-20260715-0001",
                    created_at=NOW,
                )

    def test_raw_writer_delegates_each_batch_to_a_new_segment(self) -> None:
        event = TickEvent(
            event_id="tick-1",
            received_at=NOW,
            exchange_datetime=NOW,
            alias_code="TMFR1",
            target_code="TMF202607",
            delivery_month="202607",
            code="TMF202607",
            close=23000.0,
            volume=1,
            simtrade=False,
            raw_payload={},
        )
        with tempfile.TemporaryDirectory() as directory:
            writer = RawWriter(
                AppendOnlyRawStore(Path(directory), writer_version="phase1-v1")
            )

            manifest = writer.write(
                "tick",
                [event],
                segment_id="writer-0001",
                created_at=NOW,
            )

            self.assertEqual(manifest.record_count, 1)
            self.assertEqual(manifest.event_type, "tick")


if __name__ == "__main__":
    unittest.main()
