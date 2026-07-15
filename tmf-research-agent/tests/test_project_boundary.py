from __future__ import annotations

import unittest
from pathlib import Path


SIDECAR_ROOT = Path(__file__).resolve().parents[1]
HOST_ROOT = SIDECAR_ROOT.parent


class ProjectBoundaryTests(unittest.TestCase):
    def test_sidecar_declares_an_isolated_python_project(self) -> None:
        pyproject = (SIDECAR_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('name = "tmf-research-agent"', pyproject)
        self.assertIn('tmf = "tmf_research.cli:main"', pyproject)
        self.assertTrue((SIDECAR_ROOT / "README.md").is_file())
        self.assertTrue((SIDECAR_ROOT / "SPEC.md").is_file())
        self.assertTrue((SIDECAR_ROOT / "AGENTS.md").is_file())

    def test_host_entry_points_do_not_reference_the_sidecar(self) -> None:
        host_files = (
            HOST_ROOT / "src" / "cli.js",
            HOST_ROOT / "src" / "mcp-server.js",
            HOST_ROOT / "src" / "trade-runtime.js",
            HOST_ROOT / "package.json",
        )

        for host_file in host_files:
            with self.subTest(host_file=host_file):
                self.assertNotIn(
                    "tmf-research-agent",
                    host_file.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
