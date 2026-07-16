from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class WitnessError(RuntimeError):
    pass


class WitnessMissing(WitnessError):
    pass


class WitnessConflict(WitnessError):
    pass


@dataclass(frozen=True, slots=True)
class WitnessHead:
    subject: str
    count: int
    head: str

    def __post_init__(self) -> None:
        _sha256(self.subject, "witness subject")
        _sha256(self.head, "witness head")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 0:
            raise ValueError("witness count must be a non-negative integer")


class TrustedWitness(Protocol):
    @property
    def location(self) -> Path | None: ...

    def register(self, subject: str, genesis_head: str) -> WitnessHead: ...
    def current(self, subject: str) -> WitnessHead: ...
    def compare_and_swap(self, expected: WitnessHead, new_head: str) -> WitnessHead: ...
    def history(self, subject: str) -> tuple[WitnessHead, ...]: ...


def witness_subject(kind: str, generation: bytes, genesis_hash: str) -> str:
    if not kind.strip() or len(generation) != 32:
        raise ValueError("witness subject requires a kind and internal 256-bit generation")
    _sha256(genesis_hash, "genesis")
    return _hash({"kind": kind, "generation": generation.hex(), "genesis": genesis_hash})


def default_witness_path() -> Path:
    configured = os.environ.get("TMF_TRUSTED_WITNESS_DB")
    if configured:
        path = Path(configured).expanduser()
    else:
        state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")).expanduser()
        path = state / "tmf-research-agent" / "trusted-witness.sqlite3"
    if not path.is_absolute():
        raise ValueError("trusted witness database path must be absolute")
    return path.resolve()


class SqliteTrustedWitness:
    def __init__(self, path: Path | None = None) -> None:
        resolved = default_witness_path() if path is None else path.expanduser()
        if not resolved.is_absolute():
            raise ValueError("trusted witness database path must be absolute")
        self._path = resolved.resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._path.parent, 0o700)
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS witness_heads (
                    subject TEXT PRIMARY KEY,
                    count INTEGER NOT NULL,
                    head TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS witness_history (
                    subject TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    head TEXT NOT NULL,
                    PRIMARY KEY(subject, count)
                );
                """
            )
        finally:
            connection.close()
        os.chmod(self._path, 0o600)

    @property
    def location(self) -> Path:
        return self._path

    def register(self, subject: str, genesis_head: str) -> WitnessHead:
        expected = WitnessHead(subject, 0, genesis_head)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO witness_heads(subject,count,head) VALUES(?,?,?)",
                    (subject, 0, genesis_head),
                )
                connection.execute(
                    "INSERT INTO witness_history(subject,count,head) VALUES(?,?,?)",
                    (subject, 0, genesis_head),
                )
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise WitnessConflict("witness subject already exists") from error
            connection.commit()
            return expected
        finally:
            connection.close()

    def current(self, subject: str) -> WitnessHead:
        _sha256(subject, "witness subject")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT count,head FROM witness_heads WHERE subject=?", (subject,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise WitnessMissing("trusted witness subject is missing")
        return WitnessHead(subject, int(row[0]), str(row[1]))

    def compare_and_swap(self, expected: WitnessHead, new_head: str) -> WitnessHead:
        _sha256(new_head, "new witness head")
        updated = WitnessHead(expected.subject, expected.count + 1, new_head)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE witness_heads SET count=?,head=? WHERE subject=? AND count=? AND head=?",
                (updated.count, updated.head, expected.subject, expected.count, expected.head),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise WitnessConflict("trusted witness compare-and-swap lost")
            connection.execute(
                "INSERT INTO witness_history(subject,count,head) VALUES(?,?,?)",
                (updated.subject, updated.count, updated.head),
            )
            connection.commit()
            return updated
        finally:
            connection.close()

    def history(self, subject: str) -> tuple[WitnessHead, ...]:
        _sha256(subject, "witness subject")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT count,head FROM witness_history WHERE subject=? ORDER BY count", (subject,),
            ).fetchall()
        finally:
            connection.close()
        if not rows:
            raise WitnessMissing("trusted witness subject is missing")
        return tuple(WitnessHead(subject, int(count), str(head)) for count, head in rows)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30.0, isolation_level=None)
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"invalid {name} SHA-256")
