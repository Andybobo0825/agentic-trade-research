from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_driver(workdir: Path, *, timezone_name: str, locale_name: str) -> bytes:
    environment = {
        name: value for name, value in os.environ.items()
        if name not in ("TZ", "LC_ALL", "LANG", "PYTHONHASHSEED")
    }
    environment["TZ"] = timezone_name
    environment["LC_ALL"] = locale_name
    environment["LANG"] = locale_name
    environment["PYTHONPATH"] = os.pathsep.join((
        str(PROJECT_ROOT / "src"), str(PROJECT_ROOT),
    ))
    completed = subprocess.run(
        (sys.executable, "-m", "tests.replay.replay_driver"),
        cwd=workdir,
        env=environment,
        capture_output=True,
        timeout=600,
        check=True,
    )
    return completed.stdout


class CrossProcessDeterminismTests(unittest.TestCase):
    def test_two_processes_produce_byte_identical_replays(self) -> None:
        with TemporaryDirectory() as first_root, TemporaryDirectory() as second_root:
            first = run_driver(
                Path(first_root), timezone_name="UTC", locale_name="C",
            )
            second = run_driver(
                Path(second_root),
                timezone_name="Asia/Taipei",
                locale_name="en_US.UTF-8",
            )

        self.assertTrue(first.strip())
        self.assertIn(b"FINAL_SHA256", first)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
