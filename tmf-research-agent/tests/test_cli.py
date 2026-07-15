from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path

from tmf_research.cli import main


SIDECAR_ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_verify_readonly_succeeds_for_the_sidecar(self) -> None:
        output = StringIO()

        status = main(
            ["verify-readonly", "--root", str(SIDECAR_ROOT)],
            stdout=output,
        )

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "READONLY VERIFIED\n")

    def test_verify_readonly_reports_violations_and_returns_one(self) -> None:
        output = StringIO()
        capability = "place" + "_order"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src" / "tmf_research" / "unsafe.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                f"def run(api):\n    return api.{capability}()\n",
                encoding="utf-8",
            )

            status = main(
                ["verify-readonly", "--root", str(root)],
                stdout=output,
            )

        self.assertEqual(status, 1)
        self.assertIn("READONLY VIOLATION", output.getvalue())
        self.assertIn("forbidden-symbol", output.getvalue())
        self.assertIn(capability, output.getvalue())

    def test_verify_readonly_fails_closed_for_missing_project(self) -> None:
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"

            status = main(
                ["verify-readonly", "--root", str(missing)],
                stdout=output,
            )

        self.assertEqual(status, 1)
        self.assertIn("invalid-source-root", output.getvalue())


if __name__ == "__main__":
    unittest.main()
