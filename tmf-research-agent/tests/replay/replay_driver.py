"""Deterministic replay driver executed in isolated subprocesses.

Prints the canonical replay lines and the final checksum so two separate
processes (different working directories, timezone and locale noise) can be
compared byte-for-byte.
"""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.replay.replay_support import run_recorded_scenario


def main() -> int:
    with TemporaryDirectory() as root:
        checksum, lines = run_recorded_scenario(Path(root))
    for line in lines:
        sys.stdout.write(line + "\n")
    sys.stdout.write(f"FINAL_SHA256 {checksum}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
