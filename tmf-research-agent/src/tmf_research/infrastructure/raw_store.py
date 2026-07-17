from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tmf_research.validation.data_provenance import DataProvenanceEvidence


_SAFE_PATH_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


@dataclass(frozen=True, slots=True)
class SegmentManifest:
    segment_id: str
    event_type: str
    dataset_version: str
    relative_path: str
    checksum_sha256: str
    record_count: int
    schema_version: str
    writer_version: str
    created_at: str
    minimum_event_time: str
    maximum_event_time: str


class RawIntegrityError(RuntimeError):
    """Raised when immutable raw bytes do not match their manifest."""


class AppendOnlyRawStore:
    """Writes create-once NDJSON segments plus an append-only canonical catalog."""

    def __init__(
        self,
        root: Path,
        *,
        writer_version: str,
        dataset_version: str = "dataset-v1",
    ) -> None:
        if not writer_version.strip():
            raise ValueError("writer_version is required")
        _validate_path_component(dataset_version, "dataset_version")
        self._root = root.resolve()
        self._writer_version = writer_version
        self._dataset_version = dataset_version
        self._dataset_root = self._root / "datasets" / dataset_version
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def dataset_version(self) -> str:
        return self._dataset_version

    def has_segment(self, event_type: str, segment_id: str) -> bool:
        _validate_path_component(event_type, "event_type")
        _validate_path_component(segment_id, "segment_id")
        path = self._dataset_root / "segments" / event_type / f"{segment_id}.ndjson"
        return path.is_file()

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
        _validate_path_component(event_type, "event_type")
        _validate_path_component(segment_id, "segment_id")
        if not events:
            raise ValueError("events cannot be empty")
        if created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")

        records = [_record(event) for event in events]
        encoded = b"".join(
            (_canonical_json(record) + "\n").encode("utf-8")
            for record in records
        )
        directory = self._dataset_root / "segments" / event_type
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{segment_id}.ndjson"
        if path.exists():
            raise FileExistsError(path)
        self._reserve_event_ids(records)
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o444)

        event_times = sorted(_event_time(record) for record in records)
        manifest = SegmentManifest(
            segment_id=segment_id,
            event_type=event_type,
            dataset_version=self._dataset_version,
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

    def _reserve_event_ids(self, records: Sequence[Mapping[str, object]]) -> None:
        event_ids = [_event_id(record) for record in records]
        if len(event_ids) != len(set(event_ids)):
            raise FileExistsError("duplicate event_id within segment")

        directory = self._dataset_root / "event_ids"
        directory.mkdir(parents=True, exist_ok=True)
        markers = {
            event_id: directory / f"{hashlib.sha256(event_id.encode()).hexdigest()}.id"
            for event_id in event_ids
        }
        for event_id, marker in markers.items():
            if marker.exists():
                raise FileExistsError(f"duplicate event_id: {event_id}")
        for event_id, marker in markers.items():
            with marker.open("xb") as stream:
                stream.write(event_id.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            marker.chmod(0o444)

    def verify(self, manifest: SegmentManifest) -> bool:
        try:
            path = self._verified_manifest_path(manifest)
        except RawIntegrityError:
            return False
        if not path.is_file():
            return False
        try:
            encoded = path.read_bytes()
        except OSError:
            return False
        return hashlib.sha256(encoded).hexdigest() == manifest.checksum_sha256

    def phase5_provenance(self, manifests: Sequence[SegmentManifest]) -> DataProvenanceEvidence:
        from tmf_research.validation.data_provenance import _issue_real_data_provenance

        if not manifests or any(not self.verify(manifest) for manifest in manifests):
            raise RawIntegrityError("verified non-empty raw manifests are required for Phase 5 provenance")
        catalog = tuple(
            json.loads(line)
            for line in (self._root / "manifest.ndjson").read_text(encoding="utf-8").splitlines()
        )
        payloads = tuple(_record(manifest) for manifest in manifests)
        if any(payload not in catalog for payload in payloads):
            raise RawIntegrityError("Phase 5 provenance requires catalogued raw manifests")
        return _issue_real_data_provenance(self._root, self._dataset_version, payloads)

    def read_verified(self, manifest: SegmentManifest) -> tuple[dict[str, object], ...]:
        path = self._verified_manifest_path(manifest)
        try:
            encoded = path.read_bytes()
        except OSError as error:
            raise RawIntegrityError("raw segment is missing or unreadable") from error
        checksum = hashlib.sha256(encoded).hexdigest()
        if checksum != manifest.checksum_sha256:
            raise RawIntegrityError("raw segment checksum mismatch")
        try:
            records = tuple(json.loads(line) for line in encoded.splitlines())
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RawIntegrityError("raw segment is not valid NDJSON") from error
        if len(records) != manifest.record_count or not all(
            isinstance(record, dict) for record in records
        ):
            raise RawIntegrityError("raw segment record count or shape mismatch")
        return records

    def _verified_manifest_path(self, manifest: SegmentManifest) -> Path:
        if manifest.dataset_version != self._dataset_version:
            raise RawIntegrityError("manifest dataset version mismatch")
        expected = (
            self._dataset_root
            / "segments"
            / manifest.event_type
            / f"{manifest.segment_id}.ndjson"
        ).resolve()
        actual = (self._root / manifest.relative_path).resolve()
        if actual != expected or not actual.is_relative_to(self._root):
            raise RawIntegrityError("manifest raw path mismatch")
        return actual


def _event_time(record: Mapping[str, object]) -> str:
    for name in ("exchange_datetime", "occurred_at", "detected_at", "received_at"):
        value = record.get(name)
        if isinstance(value, str) and value:
            return value
    raise ValueError("raw event has no timestamp")


def _event_id(record: Mapping[str, object]) -> str:
    value = record.get("event_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("raw event has no event_id")
    return value


def _validate_path_component(value: str, name: str) -> None:
    if value in {".", ".."} or _SAFE_PATH_COMPONENT.fullmatch(value) is None:
        raise ValueError(f"{name} must be a safe path component")


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
