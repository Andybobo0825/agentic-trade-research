from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields


RECORD_KINDS = (
    "EVENT", "BAR", "FEATURES", "LABEL", "PREDICTION", "FILL", "LEDGER",
    "REPORT",
)


class ReplayIdentityError(ValueError):
    """Raised when a replay identity would be overwritten."""


@dataclass(frozen=True, slots=True)
class ReplayManifest:
    """Canonical replay identity: versions and seed only, nothing volatile."""

    raw_checksum: str
    dataset_version: str
    feature_version: str
    label_version: str
    model_version: str
    experiment_id: str
    code_commit: str
    seed: int
    calendar_version: str
    cost_policy_version: str

    def __post_init__(self) -> None:
        if len(self.raw_checksum) != 64 or any(
            character not in "0123456789abcdef" for character in self.raw_checksum
        ):
            raise ValueError("raw checksum must be a SHA-256 hex digest")
        for item in fields(self):
            if item.name in ("raw_checksum", "seed"):
                continue
            value = getattr(self, item.name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{item.name} is required")
        if isinstance(self.seed, bool) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")

    @property
    def content_hash(self) -> str:
        payload = {
            item.name: getattr(self, item.name) for item in fields(self)
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class ReplayRecorder:
    """Append-only canonical output stream for one replay identity."""

    __slots__ = ("_manifest", "_lines")

    def __init__(self, manifest: ReplayManifest) -> None:
        if not isinstance(manifest, ReplayManifest):
            raise TypeError("recorder requires a canonical replay manifest")
        self._manifest = manifest
        self._lines: list[str] = [f"MANIFEST {manifest.content_hash}"]

    @property
    def manifest(self) -> ReplayManifest:
        return self._manifest

    @property
    def identity(self) -> str:
        return self._manifest.content_hash

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(self._lines)

    def record(self, kind: str, payload: str) -> None:
        if kind not in RECORD_KINDS:
            raise ValueError(f"unknown replay record kind {kind!r}")
        if "\n" in payload:
            raise ValueError("replay payloads must be single normalized lines")
        self._lines.append(f"{kind} {payload}")

    def final_checksum(self) -> str:
        joined = "\n".join(self._lines) + "\n"
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class ReplayArchive:
    """Write-once registry mapping replay identities to final checksums."""

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: dict[str, str] = {}

    @property
    def entries(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._entries.items())

    def publish(self, recorder: ReplayRecorder) -> str:
        identity = recorder.identity
        if identity in self._entries:
            raise ReplayIdentityError(
                "replay identity already published; versions or seed must"
                " change to create a new identity"
            )
        checksum = recorder.final_checksum()
        self._entries[identity] = checksum
        return checksum
