from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType


class DataProvenanceKind(str, Enum):
    REAL_READONLY_MARKET_DATA = "REAL_READONLY_MARKET_DATA"
    SYNTHETIC_TEST_ONLY = "SYNTHETIC_TEST_ONLY"


_PROVENANCE_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class DataProvenanceEvidence:
    kind: DataProvenanceKind
    dataset_version: str
    dataset_hash: str
    source_contract_hash: str
    segment_manifest_hashes: tuple[str, ...]
    promotion_lineage_hash: str | None
    content_hash: str
    _root: Path | None
    _manifests: tuple[Mapping[str, object], ...]
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> DataProvenanceEvidence:
        raise TypeError("data provenance must be issued by a verified raw store or test fixture")

    def __copy__(self) -> DataProvenanceEvidence:
        raise TypeError("data provenance capabilities are non-copyable")

    def __deepcopy__(self, _memo: object) -> DataProvenanceEvidence:
        raise TypeError("data provenance capabilities are non-copyable")

    def __post_init__(self) -> None:
        if self._seal is not _PROVENANCE_SEAL or not isinstance(self.kind, DataProvenanceKind):
            raise TypeError("invalid data provenance authority")
        if not self.dataset_version.strip() or not self.segment_manifest_hashes:
            raise ValueError("complete data provenance identity is required")
        for value in (self.dataset_hash, self.source_contract_hash, self.content_hash, *self.segment_manifest_hashes):
            _sha256(value)
        if self.promotion_lineage_hash is not None:
            _sha256(self.promotion_lineage_hash)

    def assert_current(self) -> None:
        if self.kind is DataProvenanceKind.SYNTHETIC_TEST_ONLY:
            return
        from tmf_research.infrastructure.raw_store import RawIntegrityError

        if self._root is None:
            raise RawIntegrityError("real data provenance has no durable raw root")
        try:
            catalog = tuple(
                json.loads(line)
                for line in (self._root / "manifest.ndjson").read_text(encoding="utf-8").splitlines()
            )
            for manifest in self._manifests:
                if dict(manifest) not in catalog:
                    raise RawIntegrityError("raw provenance manifest is no longer catalogued")
                path = (self._root / str(manifest["relative_path"])).resolve()
                if not path.is_relative_to(self._root.resolve()):
                    raise RawIntegrityError("raw provenance segment escaped the raw root")
                encoded = path.read_bytes()
                if hashlib.sha256(encoded).hexdigest() != manifest["checksum_sha256"]:
                    raise RawIntegrityError("raw provenance segment checksum mismatch")
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            if isinstance(error, RawIntegrityError):
                raise
            raise RawIntegrityError("raw provenance is no longer current") from error


def _issue_real_data_provenance(
    root: Path,
    dataset_version: str,
    manifests: Sequence[Mapping[str, object]],
) -> DataProvenanceEvidence:
    frozen = tuple(MappingProxyType(dict(value)) for value in manifests)
    manifest_hashes = tuple(_hash(dict(value)) for value in frozen)
    source_contract = {
        "boundary": "MarketDataGateway",
        "capabilities": ["resolve_near_contract", "register_tick_callback", "register_bidask_callback", "subscribe_tick", "subscribe_bidask", "unsubscribe_tick", "unsubscribe_bidask", "fetch_ticks", "fetch_kbars"],
        "writers": sorted({str(value["writer_version"]) for value in frozen}),
        "event_types": sorted({str(value["event_type"]) for value in frozen}),
        "schema_versions": sorted({str(value["schema_version"]) for value in frozen}),
    }
    values: dict[str, object] = {
        "kind": DataProvenanceKind.REAL_READONLY_MARKET_DATA,
        "dataset_version": dataset_version,
        "dataset_hash": _hash(list(manifest_hashes)),
        "source_contract_hash": _hash(source_contract),
        "segment_manifest_hashes": manifest_hashes,
        "promotion_lineage_hash": None,
        "_root": root.resolve(),
        "_manifests": frozen,
        "_seal": _PROVENANCE_SEAL,
    }
    values["content_hash"] = _hash({
        "kind": DataProvenanceKind.REAL_READONLY_MARKET_DATA.value,
        "dataset_version": dataset_version,
        "dataset_hash": values["dataset_hash"],
        "source_contract_hash": values["source_contract_hash"],
        "segment_manifest_hashes": manifest_hashes,
        "promotion_lineage_hash": None,
    })
    return _make(values)


def _issue_synthetic_test_provenance(dataset_version: str = "synthetic-phase5-v1") -> DataProvenanceEvidence:
    synthetic_manifest = _hash({"fixture": dataset_version})
    values: dict[str, object] = {
        "kind": DataProvenanceKind.SYNTHETIC_TEST_ONLY,
        "dataset_version": dataset_version,
        "dataset_hash": _hash([synthetic_manifest]),
        "source_contract_hash": _hash({"fixture_issuer": "tests.phase5_test_support"}),
        "segment_manifest_hashes": (synthetic_manifest,),
        "promotion_lineage_hash": None,
        "_root": None,
        "_manifests": (),
        "_seal": _PROVENANCE_SEAL,
    }
    values["content_hash"] = _hash({
        "kind": DataProvenanceKind.SYNTHETIC_TEST_ONLY.value,
        "dataset_version": dataset_version,
        "dataset_hash": values["dataset_hash"],
        "source_contract_hash": values["source_contract_hash"],
        "segment_manifest_hashes": (synthetic_manifest,),
        "promotion_lineage_hash": None,
    })
    return _make(values)


def _make(values: Mapping[str, object]) -> DataProvenanceEvidence:
    instance = object.__new__(DataProvenanceEvidence)
    for name, value in values.items():
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("invalid provenance SHA-256")
