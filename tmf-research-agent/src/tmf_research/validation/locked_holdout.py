from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


HoldoutStatus = Literal[
    "LOCKED",
    "FROZEN",
    "UNLOCKED",
    "CONSUMED",
    "CONTAMINATED",
    "INSUFFICIENT_DATA",
]
REQUIRED_FREEZE_COMPONENTS = (
    "model",
    "features",
    "labels",
    "parameters",
    "thresholds",
    "rules",
)


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
        object.__setattr__(self, "payload", dict(self.payload))

    def to_dict(self) -> dict[str, object]:
        return {"row_id": self.row_id, "trading_date": self.trading_date, "payload": dict(self.payload)}


@dataclass(frozen=True, slots=True)
class HoldoutSelection:
    development: tuple[HoldoutRow, ...]
    holdout: tuple[HoldoutRow, ...]
    required_rows_by_percent: int
    required_effective_days: int
    status: Literal["READY", "RESEARCH_INSUFFICIENT_DATA"]


def select_locked_holdout(
    rows: Sequence[HoldoutRow],
    *,
    percentage: float = 0.15,
    effective_days: int = 40,
) -> HoldoutSelection:
    if not 0.0 < percentage < 1.0 or effective_days <= 0:
        raise ValueError("invalid locked holdout sizing")
    ordered = tuple(rows)
    if not ordered or len({row.row_id for row in ordered}) != len(ordered):
        raise ValueError("locked holdout requires unique chronological rows")
    dates = tuple(dict.fromkeys(row.trading_date for row in ordered))
    if tuple(row.trading_date for row in ordered) != tuple(
        sorted((row.trading_date for row in ordered))
    ):
        raise ValueError("holdout input must be chronological")
    percent_count = math.ceil(len(ordered) * percentage)
    percent_start = len(ordered) - percent_count
    if len(dates) >= effective_days:
        first_required_date = dates[-effective_days]
        day_start = next(index for index, row in enumerate(ordered) if row.trading_date == first_required_date)
        status: Literal["READY", "RESEARCH_INSUFFICIENT_DATA"] = "READY"
    else:
        day_start = 0
        status = "RESEARCH_INSUFFICIENT_DATA"
    start = min(percent_start, day_start)
    holdout = ordered[start:]
    development = ordered[:start]
    if not development:
        status = "RESEARCH_INSUFFICIENT_DATA"
    return HoldoutSelection(development, holdout, percent_count, effective_days, status)


@dataclass(frozen=True, slots=True)
class FrozenCandidate:
    hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        if set(self.hashes) != set(REQUIRED_FREEZE_COMPONENTS):
            raise ValueError("freeze requires model/features/labels/parameters/thresholds/rules hashes")
        for name, value in self.hashes.items():
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"invalid {name} SHA-256")
        object.__setattr__(self, "hashes", dict(sorted(self.hashes.items())))

    @property
    def content_hash(self) -> str:
        return _hash(dict(self.hashes))


@dataclass(frozen=True, slots=True)
class HoldoutToken:
    token: str
    candidate_hash: str


class LockedHoldout:
    """Durable, fail-closed single-use capability for the terminal suffix."""

    __slots__ = ("_root",)

    def __init__(self, root: Path) -> None:
        self._root = root
        self._verify_files()

    @classmethod
    def create(cls, root: Path, rows: Sequence[HoldoutRow], *, insufficient: bool = False) -> LockedHoldout:
        if root.exists():
            raise FileExistsError(root)
        root.mkdir(parents=True)
        payload = [row.to_dict() for row in rows]
        data = _canonical(payload)
        _write_exclusive(root / "holdout.data.json", data)
        state: dict[str, object] = {
            "version": 1,
            "status": "INSUFFICIENT_DATA" if insufficient else "LOCKED",
            "data_hash": hashlib.sha256(data).hexdigest(),
            "row_count": len(rows),
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
        state = self._state()
        if state["status"] != "LOCKED":
            self._contaminate("INVALID_FREEZE_TRANSITION")
            raise HoldoutAccessError("holdout may be frozen exactly once from LOCKED")
        state["candidate_hash"] = candidate.content_hash
        state["candidate_hashes"] = dict(candidate.hashes)
        state["status"] = "FROZEN"
        self._save(state)

    def unlock_once(self, candidate: FrozenCandidate) -> HoldoutToken:
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
        state = self._state()
        expected_token = hashlib.sha256(token.token.encode("ascii")).hexdigest()
        if (
            state["status"] != "UNLOCKED"
            or state["token_hash"] != expected_token
            or state["candidate_hash"] != token.candidate_hash
        ):
            self._contaminate("HOLDOUT_READ_RETRY_OR_INVALID_TOKEN")
            raise HoldoutAccessError("holdout is unreadable before freeze/unlock and after its single read")
        data = (self._root / "holdout.data.json").read_bytes()
        if hashlib.sha256(data).hexdigest() != state["data_hash"]:
            self._contaminate("HOLDOUT_DATA_MUTATED")
            raise HoldoutAccessError("holdout data integrity failure")
        rows = tuple(_row(value) for value in _list(json.loads(data)))
        state["status"] = "CONSUMED"
        state["read_count"] = _integer(state["read_count"]) + 1
        self._save(state)
        return rows

    def assert_candidate_unchanged(self, candidate: FrozenCandidate) -> None:
        state = self._state()
        if state["candidate_hash"] != candidate.content_hash:
            self._contaminate("POST_HOLDOUT_CANDIDATE_MUTATION")
            raise HoldoutAccessError("candidate changed after locked holdout freeze")

    def mark_rerun_attempt(self) -> None:
        self._contaminate("LOCKED_HOLDOUT_RERUN_ATTEMPT")
        raise HoldoutAccessError("locked holdout cannot be re-run")

    def approval_eligible(self, candidate: FrozenCandidate) -> bool:
        state = self._state()
        return (
            state["status"] == "CONSUMED"
            and state["candidate_hash"] == candidate.content_hash
            and _integer(state["unlock_count"]) == 1
            and _integer(state["read_count"]) == 1
            and not _list(state["contamination_reasons"])
        )

    def _verify_files(self) -> None:
        if not (self._root / "holdout.state.json").is_file() or not (self._root / "holdout.data.json").is_file():
            raise HoldoutAccessError("holdout state is incomplete")
        state = self._state()
        data = (self._root / "holdout.data.json").read_bytes()
        if hashlib.sha256(data).hexdigest() != state["data_hash"]:
            self._contaminate("HOLDOUT_DATA_MUTATED")
            raise HoldoutAccessError("holdout data integrity failure")

    def _state(self) -> dict[str, object]:
        envelope = json.loads((self._root / "holdout.state.json").read_text(encoding="utf-8"))
        if not isinstance(envelope, dict) or set(envelope) != {"state", "checksum"}:
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


def _row(value: object) -> HoldoutRow:
    if not isinstance(value, dict):
        raise HoldoutAccessError("holdout row is invalid")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise HoldoutAccessError("holdout row payload is invalid")
    return HoldoutRow(str(value["row_id"]), str(value["trading_date"]), payload)


def _write_state(path: Path, state: Mapping[str, object], *, exclusive: bool) -> None:
    envelope = {"state": dict(state), "checksum": _hash(state)}
    payload = _canonical(envelope)
    if exclusive:
        _write_exclusive(path, payload)
        return
    temporary = path.with_suffix(".tmp")
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


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise HoldoutAccessError("expected list")
    return value


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise HoldoutAccessError("expected integer")
    return value
