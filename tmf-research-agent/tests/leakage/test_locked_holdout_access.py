from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tmf_research.validation.locked_holdout import HoldoutAccessError, HoldoutRow, LockedHoldout
from tmf_research.validation.locked_holdout import select_locked_holdout


class LockedHoldoutAccessTests(unittest.TestCase):
    def test_no_public_read_before_exact_freeze(self) -> None:
        with TemporaryDirectory() as directory:
            vault = LockedHoldout.create(
                Path(directory) / "holdout",
                select_locked_holdout(tuple(
                    HoldoutRow(str(index), f"2026-{1 + index // 28:02d}-{1 + index % 28:02d}", {"secret": index})
                    for index in range(100)
                )),
            )
            self.assertFalse(hasattr(vault, "rows"))
            self.assertFalse(hasattr(vault, "read"))
            with self.assertRaises(HoldoutAccessError):
                vault.mark_rerun_attempt()


if __name__ == "__main__":
    unittest.main()
