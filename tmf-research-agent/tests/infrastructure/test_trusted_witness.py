from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import stat
import unittest

from tmf_research.infrastructure.trusted_witness import (
    SqliteTrustedWitness,
    WitnessConflict,
    witness_subject,
)


class TrustedWitnessTests(unittest.TestCase):
    def test_sqlite_witness_registers_and_exactly_one_concurrent_cas_wins(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "state" / "witness.sqlite3"
            witness = SqliteTrustedWitness(path)
            subject = witness_subject("EXPERIMENT", b"g" * 32, "a" * 64)
            genesis = witness.register(subject, "a" * 64)
            self.assertEqual((genesis.count, genesis.head), (0, "a" * 64))

            def advance(value: str) -> bool:
                try:
                    witness.compare_and_swap(genesis, value * 64)
                except WitnessConflict:
                    return False
                return True

            with ThreadPoolExecutor(max_workers=2) as pool:
                won = tuple(pool.map(advance, ("b", "c")))
            self.assertEqual(sum(won), 1)
            self.assertEqual(witness.current(subject).count, 1)

    def test_permissions_and_subject_generation_are_strict(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "private" / "witness.sqlite3"
            SqliteTrustedWitness(path)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(ValueError):
                SqliteTrustedWitness(Path("relative.sqlite3"))
            subject = witness_subject("HOLDOUT", os.urandom(32), "d" * 64)
            self.assertEqual(len(subject), 64)


if __name__ == "__main__":
    unittest.main()
