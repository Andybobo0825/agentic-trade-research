from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tmf_research.collection.raw_writer import RawWriter
from tmf_research.domain.events import TickEvent
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore, RawIntegrityError
from tmf_research.validation.data_provenance import DataProvenanceEvidence


NOW = datetime(2026, 7, 15, 8, 45, tzinfo=timezone.utc)


class RawStoreTests(unittest.TestCase):
    def test_reprocessing_creates_new_dataset_version_without_mutating_old_bytes(self) -> None:
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
            raw_payload={"source": "original"},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_store = AppendOnlyRawStore(
                root,
                writer_version="phase1-v1",
                dataset_version="dataset-v1",
            )
            first = first_store.append_segment(
                "tick", [event], segment_id="segment-1", created_at=NOW
            )
            first_path = root / first.relative_path
            first_bytes = first_path.read_bytes()

            second_store = AppendOnlyRawStore(
                root,
                writer_version="phase1-v2",
                dataset_version="dataset-v2",
            )
            second = second_store.append_segment(
                "tick", [event], segment_id="segment-1", created_at=NOW
            )

            self.assertEqual(first.dataset_version, "dataset-v1")
            self.assertEqual(second.dataset_version, "dataset-v2")
            self.assertNotEqual(first.relative_path, second.relative_path)
            self.assertEqual(first_path.read_bytes(), first_bytes)
            self.assertTrue(first_store.verify(first))
            self.assertTrue(second_store.verify(second))

    def test_tamper_and_partial_path_reuse_fail_closed_with_evidence(self) -> None:
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
            root = Path(directory)
            store = AppendOnlyRawStore(
                root,
                writer_version="phase1-v1",
                dataset_version="dataset-v1",
            )
            manifest = store.append_segment(
                "tick", [event], segment_id="complete", created_at=NOW
            )
            segment = root / manifest.relative_path
            segment.chmod(0o644)
            segment.write_bytes(segment.read_bytes() + b"tampered\n")

            self.assertFalse(store.verify(manifest))
            with self.assertRaisesRegex(RawIntegrityError, "checksum"):
                store.read_verified(manifest)

            partial = (
                root
                / "datasets"
                / "dataset-v1"
                / "segments"
                / "tick"
                / "partial.ndjson"
            )
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b'{"event_id":"tick-partial"')
            partial_bytes = partial.read_bytes()

            with self.assertRaises(FileExistsError):
                store.append_segment(
                    "tick", [event], segment_id="partial", created_at=NOW
                )
            self.assertEqual(partial.read_bytes(), partial_bytes)

    def test_phase5_real_provenance_is_issued_only_from_current_catalogued_raw_segments(self) -> None:
        event = TickEvent(
            event_id="tick-provenance", received_at=NOW, exchange_datetime=NOW,
            alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
            code="TMF202607", close=23000.0, volume=1, simtrade=False, raw_payload={},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = AppendOnlyRawStore(root, writer_version="phase1-v1", dataset_version="dataset-v1")
            manifest = store.append_segment("tick", [event], segment_id="phase5", created_at=NOW)
            provenance = store.phase5_provenance((manifest,))
            self.assertEqual(provenance.kind.value, "REAL_READONLY_MARKET_DATA")
            provenance.assert_current()
            with self.assertRaises(TypeError):
                DataProvenanceEvidence()
            with self.assertRaises(TypeError):
                copy.copy(provenance)
            with self.assertRaises(TypeError):
                copy.deepcopy(provenance)
            segment = root / manifest.relative_path
            segment.chmod(0o644)
            segment.write_bytes(segment.read_bytes() + b"tampered\n")
            with self.assertRaisesRegex(RawIntegrityError, "provenance"):
                provenance.assert_current()

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
