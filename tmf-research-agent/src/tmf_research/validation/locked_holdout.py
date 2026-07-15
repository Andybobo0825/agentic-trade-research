from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast


HoldoutStatus = Literal["LOCKED", "FROZEN", "UNLOCKED", "CONSUMED", "CONTAMINATED"]
REQUIRED_FREEZE_COMPONENTS = ("model", "features", "labels", "parameters", "thresholds", "rules")
_APPROVAL_SEAL = object()


class HoldoutAccessError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HoldoutRow:
    row_id: str
    trading_date: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.row_id.strip() or not self.trading_date.strip():
            raise ValueError("holdout rows require id and effective trading date")
        copied = json.loads(json.dumps(dict(self.payload), allow_nan=False))
        if not isinstance(copied, dict):
            raise ValueError("holdout row payload must be a JSON object")
        object.__setattr__(self, "payload", MappingProxyType(copied))

    def to_dict(self) -> dict[str, object]:
        return {"row_id": self.row_id, "trading_date": self.trading_date, "payload": dict(self.payload)}


@dataclass(frozen=True, slots=True)
class HoldoutSelection:
    development: tuple[HoldoutRow, ...]
    holdout: tuple[HoldoutRow, ...]
    required_rows_by_percent: int
    required_effective_days: int
    percentage: float
    status: Literal["READY", "RESEARCH_INSUFFICIENT_DATA"]
    source_hash: str
    holdout_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        combined = self.development + self.holdout
        expected = _selection_payload(combined, self.percentage, self.required_effective_days)
        if (
            self.development != expected["development"]
            or self.holdout != expected["holdout"]
            or self.required_rows_by_percent != expected["percent_count"]
            or self.status != expected["status"]
            or self.source_hash != expected["source_hash"]
            or self.holdout_hash != expected["holdout_hash"]
        ):
            raise ValueError("locked holdout selection is not the canonical final suffix")
        payload = self._payload_without_hash()
        if self.content_hash != _hash(payload):
            raise ValueError("locked holdout selection content hash mismatch")

    def _payload_without_hash(self) -> dict[str, object]:
        return {
            "source_hash": self.source_hash,
            "holdout_hash": self.holdout_hash,
            "development_count": len(self.development),
            "holdout_count": len(self.holdout),
            "required_rows_by_percent": self.required_rows_by_percent,
            "required_effective_days": self.required_effective_days,
            "percentage": self.percentage,
            "status": self.status,
        }

    def to_manifest(self) -> dict[str, object]:
        return {**self._payload_without_hash(), "content_hash": self.content_hash}


def select_locked_holdout(
    rows: Sequence[HoldoutRow],
    *,
    percentage: float = 0.15,
    effective_days: int = 40,
) -> HoldoutSelection:
    expected = _selection_payload(tuple(rows), percentage, effective_days)
    payload = {
        "source_hash": expected["source_hash"],
        "holdout_hash": expected["holdout_hash"],
        "development_count": len(cast(tuple[HoldoutRow, ...], expected["development"])),
        "holdout_count": len(cast(tuple[HoldoutRow, ...], expected["holdout"])),
        "required_rows_by_percent": expected["percent_count"],
        "required_effective_days": effective_days,
        "percentage": percentage,
        "status": expected["status"],
    }
    return HoldoutSelection(
        cast(tuple[HoldoutRow, ...], expected["development"]),
        cast(tuple[HoldoutRow, ...], expected["holdout"]),
        cast(int, expected["percent_count"]),
        effective_days,
        percentage,
        cast(Literal["READY", "RESEARCH_INSUFFICIENT_DATA"], expected["status"]),
        cast(str, expected["source_hash"]),
        cast(str, expected["holdout_hash"]),
        _hash(payload),
    )


@dataclass(frozen=True, slots=True)
class FrozenCandidate:
    hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        if set(self.hashes) != set(REQUIRED_FREEZE_COMPONENTS):
            raise ValueError("freeze requires model/features/labels/parameters/thresholds/rules hashes")
        for name, value in self.hashes.items():
            _sha256(value, name)
        object.__setattr__(self, "hashes", MappingProxyType(dict(sorted(self.hashes.items()))))

    @property
    def content_hash(self) -> str:
        return _hash(dict(self.hashes))


@dataclass(frozen=True, slots=True)
class HoldoutToken:
    token: str
    candidate_hash: str


@dataclass(frozen=True, slots=True, init=False)
class LockedHoldoutApprovalEvidence:
    selection_hash: str
    candidate_hash: str
    model_hash: str
    data_hash: str
    state_hash: str
    status: Literal["PASSED"]
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> LockedHoldoutApprovalEvidence:
        raise TypeError("holdout approval evidence must be issued by a consumed locked holdout")

    def __post_init__(self) -> None:
        if self._seal is not _APPROVAL_SEAL or self.status != "PASSED":
            raise TypeError("locked holdout approval evidence can only be issued by a verified consumed holdout")
        for name, value in (
            ("selection", self.selection_hash), ("candidate", self.candidate_hash), ("model", self.model_hash),
            ("data", self.data_hash), ("state", self.state_hash),
        ):
            _sha256(value, name)


class LockedHoldout:
    """Durable fail-closed capability for a canonical, sufficient terminal suffix."""

    __slots__ = ("_root",)

    def __init__(self, root: Path) -> None:
        self._root = root
        self._verify_files(contaminate=True)

    @classmethod
    def create(cls, root: Path, selection: HoldoutSelection) -> LockedHoldout:
        if not isinstance(selection, HoldoutSelection):
            raise TypeError("LockedHoldout.create requires a canonical HoldoutSelection")
        if selection.status != "READY" or not selection.development or not selection.holdout:
            raise ValueError("insufficient or empty locked holdout selection cannot be persisted")
        canonical = select_locked_holdout(
            selection.development + selection.holdout,
            percentage=selection.percentage,
            effective_days=selection.required_effective_days,
        )
        if canonical != selection:
            raise ValueError("locked holdout selection must be revalidated before persistence")
        if root.exists():
            raise FileExistsError(root)
        root.mkdir(parents=True)
        data = _canonical([row.to_dict() for row in selection.holdout])
        manifest = selection.to_manifest()
        manifest_hash = _hash(manifest)
        genesis = {
            "version": 2,
            "manifest_hash": manifest_hash,
            "selection_hash": selection.content_hash,
            "data_hash": hashlib.sha256(data).hexdigest(),
        }
        genesis_hash = _hash(genesis)
        _write_exclusive(root / "holdout.data.json", data)
        _write_exclusive(root / "holdout.manifest.json", _canonical(manifest))
        _write_exclusive(root / f"holdout.genesis.{genesis_hash}.json", _canonical(genesis))
        state: dict[str, object] = {
            "version": 2,
            "status": "LOCKED",
            "genesis_hash": genesis_hash,
            "manifest_hash": manifest_hash,
            "selection_hash": selection.content_hash,
            "data_hash": hashlib.sha256(data).hexdigest(),
            "row_count": len(selection.holdout),
            "candidate_hash": None,
            "candidate_hashes": None,
            "token_hash": None,
            "unlock_count": 0,
            "read_count": 0,
            "contamination_reasons": [],
        }
        _write_state(root / "holdout.state.json", state, exclusive=True)
        return cls(root)

    @property
    def status(self) -> HoldoutStatus:
        return cast(HoldoutStatus, self._state()["status"])

    @property
    def contaminated(self) -> bool:
        return self.status == "CONTAMINATED"

    @property
    def contamination_reasons(self) -> tuple[str, ...]:
        return tuple(str(value) for value in _list(self._state()["contamination_reasons"]))

    def freeze(self, candidate: FrozenCandidate) -> None:
        self._verify_files(contaminate=True)
        state = self._state()
        if state["status"] != "LOCKED":
            self._contaminate("INVALID_FREEZE_TRANSITION")
            raise HoldoutAccessError("holdout may be frozen exactly once from LOCKED")
        state["candidate_hash"] = candidate.content_hash
        state["candidate_hashes"] = dict(candidate.hashes)
        state["status"] = "FROZEN"
        self._save(state)

    def unlock_once(self, candidate: FrozenCandidate) -> HoldoutToken:
        self._verify_files(contaminate=True)
        state = self._state()
        if state["status"] != "FROZEN" or state["candidate_hash"] != candidate.content_hash:
            self._contaminate("UNLOCK_BEFORE_EXACT_FREEZE_OR_RETRY")
            raise HoldoutAccessError("holdout unlock requires the exact frozen candidate and is single-use")
        raw = secrets.token_hex(32)
        state["status"] = "UNLOCKED"
        state["unlock_count"] = _integer(state["unlock_count"]) + 1
        state["token_hash"] = hashlib.sha256(raw.encode("ascii")).hexdigest()
        self._save(state)
        return HoldoutToken(raw, candidate.content_hash)

    def read_once(self, token: HoldoutToken) -> tuple[HoldoutRow, ...]:
        self._verify_files(contaminate=True)
        state = self._state()
        expected_token = hashlib.sha256(token.token.encode("ascii")).hexdigest()
        if (
            state["status"] != "UNLOCKED"
            or state["token_hash"] != expected_token
            or state["candidate_hash"] != token.candidate_hash
        ):
            self._contaminate("HOLDOUT_READ_RETRY_OR_INVALID_TOKEN")
            raise HoldoutAccessError("holdout is unreadable before exact freeze/unlock or after its single read")
        before = (self._root / "holdout.data.json").read_bytes()
        rows = tuple(_row(value) for value in _list(json.loads(before)))
        after = (self._root / "holdout.data.json").read_bytes()
        if before != after or hashlib.sha256(after).hexdigest() != state["data_hash"]:
            self._contaminate("HOLDOUT_DATA_MUTATED_DURING_READ")
            raise HoldoutAccessError("holdout data changed during the single evaluation")
        manifest = self._manifest()
        if _hash([row.to_dict() for row in rows]) != manifest["holdout_hash"]:
            self._contaminate("HOLDOUT_CONTENT_HASH_MISMATCH")
            raise HoldoutAccessError("holdout rows do not match the frozen canonical suffix")
        state["status"] = "CONSUMED"
        state["read_count"] = _integer(state["read_count"]) + 1
        self._save(state)
        self._verify_files(contaminate=True)
        return rows

    def assert_candidate_unchanged(self, candidate: FrozenCandidate) -> None:
        self._verify_files(contaminate=True)
        state = self._state()
        if state["candidate_hash"] != candidate.content_hash or state["candidate_hashes"] != dict(candidate.hashes):
            self._contaminate("POST_HOLDOUT_CANDIDATE_MUTATION")
            raise HoldoutAccessError("candidate model/features/labels/parameters/thresholds/rules changed")

    def mark_rerun_attempt(self) -> None:
        self._contaminate("LOCKED_HOLDOUT_RERUN_ATTEMPT")
        raise HoldoutAccessError("locked holdout cannot be re-run")

    def approval_evidence(self, candidate: FrozenCandidate) -> LockedHoldoutApprovalEvidence:
        self.assert_candidate_unchanged(candidate)
        self._verify_files(contaminate=True)
        state = self._state()
        if not self._approval_eligible_state(state, candidate):
            raise HoldoutAccessError("locked holdout is not eligible for approval")
        return _sealed_approval(
            selection_hash=str(state["selection_hash"]),
            candidate_hash=candidate.content_hash,
            model_hash=candidate.hashes["model"],
            data_hash=str(state["data_hash"]),
            state_hash=_hash(state),
        )

    def approval_eligible(self, candidate: FrozenCandidate) -> bool:
        try:
            self.approval_evidence(candidate)
        except (HoldoutAccessError, OSError, ValueError):
            return False
        return True

    def _approval_eligible_state(self, state: Mapping[str, object], candidate: FrozenCandidate) -> bool:
        return (
            state["status"] == "CONSUMED"
            and state["candidate_hash"] == candidate.content_hash
            and state["candidate_hashes"] == dict(candidate.hashes)
            and _integer(state["unlock_count"]) == 1
            and _integer(state["read_count"]) == 1
            and _integer(state["row_count"]) > 0
            and not _list(state["contamination_reasons"])
            and self._manifest()["status"] == "READY"
        )

    def _verify_files(self, *, contaminate: bool) -> None:
        try:
            state = self._state()
            genesis_files = tuple(self._root.glob("holdout.genesis.*.json"))
            if len(genesis_files) != 1:
                raise HoldoutAccessError("exactly one immutable holdout genesis is required")
            genesis_file = genesis_files[0]
            genesis = _object(genesis_file)
            genesis_hash = _hash(genesis)
            if genesis_file.name != f"holdout.genesis.{genesis_hash}.json" or state["genesis_hash"] != genesis_hash:
                raise HoldoutAccessError("holdout genesis anchor mismatch")
            manifest = self._manifest()
            manifest_hash = _hash(manifest)
            data = (self._root / "holdout.data.json").read_bytes()
            data_hash = hashlib.sha256(data).hexdigest()
            if (
                genesis["manifest_hash"] != manifest_hash
                or genesis["selection_hash"] != manifest["content_hash"]
                or genesis["data_hash"] != data_hash
                or state["manifest_hash"] != manifest_hash
                or state["selection_hash"] != manifest["content_hash"]
                or state["data_hash"] != data_hash
                or manifest["status"] != "READY"
                or _integer(manifest["holdout_count"]) <= 0
                or _integer(manifest["development_count"]) <= 0
            ):
                raise HoldoutAccessError("holdout data/manifest/genesis integrity failure")
            values = tuple(_row(value) for value in _list(json.loads(data)))
            if len(values) != _integer(manifest["holdout_count"]) or _hash([row.to_dict() for row in values]) != manifest["holdout_hash"]:
                raise HoldoutAccessError("holdout data content does not match manifest")
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, HoldoutAccessError) as error:
            if contaminate:
                self._contaminate("HOLDOUT_INTEGRITY_FAILURE")
            if isinstance(error, HoldoutAccessError):
                raise
            raise HoldoutAccessError("holdout integrity verification failed") from error

    def _manifest(self) -> dict[str, object]:
        return _object(self._root / "holdout.manifest.json")

    def _state(self) -> dict[str, object]:
        envelope = _object(self._root / "holdout.state.json")
        if set(envelope) != {"state", "checksum"}:
            raise HoldoutAccessError("holdout state envelope invalid")
        state = envelope["state"]
        if not isinstance(state, dict) or envelope["checksum"] != _hash(state):
            raise HoldoutAccessError("holdout state checksum invalid")
        return cast(dict[str, object], state)

    def _save(self, state: Mapping[str, object]) -> None:
        _write_state(self._root / "holdout.state.json", state, exclusive=False)

    def _contaminate(self, reason: str) -> None:
        try:
            state = self._state()
        except (OSError, ValueError, HoldoutAccessError):
            return
        reasons = [str(value) for value in _list(state["contamination_reasons"])]
        if reason not in reasons:
            reasons.append(reason)
        state["contamination_reasons"] = reasons
        state["status"] = "CONTAMINATED"
        self._save(state)


def _selection_payload(rows: tuple[HoldoutRow, ...], percentage: float, effective_days: int) -> dict[str, object]:
    if not 0.0 < percentage < 1.0 or not math.isfinite(percentage) or effective_days <= 0:
        raise ValueError("invalid locked holdout sizing")
    if not rows or len({row.row_id for row in rows}) != len(rows):
        raise ValueError("locked holdout requires non-empty unique chronological rows")
    dates = tuple(row.trading_date for row in rows)
    if dates != tuple(sorted(dates)):
        raise ValueError("holdout input must be chronological")
    distinct_dates = tuple(dict.fromkeys(dates))
    percent_count = math.ceil(len(rows) * percentage)
    percent_start = len(rows) - percent_count
    if len(distinct_dates) >= effective_days:
        first_required_date = distinct_dates[-effective_days]
        day_start = next(index for index, row in enumerate(rows) if row.trading_date == first_required_date)
        status: Literal["READY", "RESEARCH_INSUFFICIENT_DATA"] = "READY"
    else:
        day_start = 0
        status = "RESEARCH_INSUFFICIENT_DATA"
    start = min(percent_start, day_start)
    development, holdout = rows[:start], rows[start:]
    if not development or not holdout:
        status = "RESEARCH_INSUFFICIENT_DATA"
    return {
        "development": development,
        "holdout": holdout,
        "percent_count": percent_count,
        "status": status,
        "source_hash": _hash([row.to_dict() for row in rows]),
        "holdout_hash": _hash([row.to_dict() for row in holdout]),
    }


def _sealed_approval(**values: object) -> LockedHoldoutApprovalEvidence:
    instance = object.__new__(LockedHoldoutApprovalEvidence)
    for name, value in (*values.items(), ("status", "PASSED"), ("_seal", _APPROVAL_SEAL)):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def _row(value: object) -> HoldoutRow:
    if not isinstance(value, dict) or not isinstance(value.get("payload"), dict):
        raise HoldoutAccessError("holdout row is invalid")
    return HoldoutRow(str(value["row_id"]), str(value["trading_date"]), cast(dict[str, object], value["payload"]))


def _write_state(path: Path, state: Mapping[str, object], *, exclusive: bool) -> None:
    envelope = {"state": dict(state), "checksum": _hash(state)}
    payload = _canonical(envelope)
    if exclusive:
        _write_exclusive(path, payload)
        return
    temporary = path.with_suffix(".tmp")
    if temporary.exists():
        temporary.unlink()
    _write_exclusive(temporary, payload)
    os.replace(temporary, path)


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HoldoutAccessError("expected JSON object")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise HoldoutAccessError("expected list")
    return value


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise HoldoutAccessError("expected integer")
    return value


def _sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"invalid {name} SHA-256")
