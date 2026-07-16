from __future__ import annotations

from pathlib import Path
from threading import Lock

from tmf_research.infrastructure.trusted_witness import (
    WitnessConflict,
    WitnessHead,
    WitnessMissing,
)


class MemoryTrustedWitness:
    def __init__(self) -> None:
        self._heads: dict[str, WitnessHead] = {}
        self._history: dict[str, list[WitnessHead]] = {}
        self._lock = Lock()

    @property
    def location(self) -> Path | None:
        return None

    def register(self, subject: str, genesis_head: str) -> WitnessHead:
        head = WitnessHead(subject, 0, genesis_head)
        with self._lock:
            if subject in self._heads:
                raise WitnessConflict("subject exists")
            self._heads[subject] = head
            self._history[subject] = [head]
        return head

    def current(self, subject: str) -> WitnessHead:
        with self._lock:
            try:
                return self._heads[subject]
            except KeyError as error:
                raise WitnessMissing("subject missing") from error

    def compare_and_swap(self, expected: WitnessHead, new_head: str) -> WitnessHead:
        with self._lock:
            if self._heads.get(expected.subject) != expected:
                raise WitnessConflict("compare-and-swap lost")
            head = WitnessHead(expected.subject, expected.count + 1, new_head)
            self._heads[expected.subject] = head
            self._history[expected.subject].append(head)
            return head

    def history(self, subject: str) -> tuple[WitnessHead, ...]:
        with self._lock:
            try:
                return tuple(self._history[subject])
            except KeyError as error:
                raise WitnessMissing("subject missing") from error
