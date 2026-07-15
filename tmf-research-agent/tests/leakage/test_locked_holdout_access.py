from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tmf_research.validation.locked_holdout import HoldoutAccessError, HoldoutRow, LockedHoldout


class LockedHoldoutAccessTests(unittest.TestCase):
    def test_no_public_read_before_exact_freeze(self) -> None:
        with TemporaryDirectory() as directory:
            vault = LockedHoldout.create(
                Path(directory) / "holdout",
                (HoldoutRow("1", "2026-01-01", {"secret": 1}),),
            )
            self.assertFalse(hasattr(vault, "rows"))
            self.assertFalse(hasattr(vault, "read"))
            with self.assertRaises(HoldoutAccessError):
                vault.mark_rerun_attempt()


if __name__ == "__main__":
    unittest.main()
