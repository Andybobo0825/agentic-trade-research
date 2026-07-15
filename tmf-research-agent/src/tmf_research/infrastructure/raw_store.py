from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SegmentManifest:
    segment_id: str
    event_type: str
    relative_path: str
    checksum_sha256: str
    record_count: int
    schema_version: str
    writer_version: str
    created_at: str
    minimum_event_time: str
    maximum_event_time: str


class AppendOnlyRawStore:
    """Writes create-once NDJSON segments plus an append-only canonical catalog."""

    def __init__(self, root: Path, *, writer_version: str) -> None:
        if not writer_version.strip():
            raise ValueError("writer_version is required")
        self._root = root.resolve()
        self._writer_version = writer_version
        self._root.mkdir(parents=True, exist_ok=True)

    def append_segment(
        self,
        event_type: str,
        events: Sequence[object],
        *,
        segment_id: str,
        created_at: datetime,
    ) -> SegmentManifest:
        if not event_type.strip() or not segment_id.strip():
            raise ValueError("event_type and segment_id are required")
        if not events:
            raise ValueError("events cannot be empty")
        if created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")

        records = [_record(event) for event in events]
        encoded = b"".join(
            (_canonical_json(record) + "\n").encode("utf-8")
            for record in records
        )
        directory = self._root / "segments" / event_type
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{segment_id}.ndjson"
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o444)

        event_times = sorted(_event_time(record) for record in records)
        manifest = SegmentManifest(
            segment_id=segment_id,
            event_type=event_type,
            relative_path=path.relative_to(self._root).as_posix(),
            checksum_sha256=hashlib.sha256(encoded).hexdigest(),
            record_count=len(records),
            schema_version=str(records[0].get("schema_version", "1.1.0")),
            writer_version=self._writer_version,
            created_at=created_at.isoformat(),
            minimum_event_time=event_times[0],
            maximum_event_time=event_times[-1],
        )
        manifest_path = self._root / "manifest.ndjson"
        with manifest_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(_canonical_json(_record(manifest)))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return manifest

    def verify(self, manifest: SegmentManifest) -> bool:
        path = self._root / manifest.relative_path
        if not path.is_file():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == manifest.checksum_sha256


def _event_time(record: Mapping[str, object]) -> str:
    for name in ("exchange_datetime", "occurred_at", "detected_at", "received_at"):
        value = record.get(name)
        if isinstance(value, str) and value:
            return value
    raise ValueError("raw event has no timestamp")


def _record(value: object) -> dict[str, object]:
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("raw records must be dataclass instances")
    return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise TypeError(f"unsupported raw value: {type(value).__name__}")


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
