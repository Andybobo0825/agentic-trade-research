from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tmf_research.security.readonly_verifier import verify_readonly


SIDECAR_ROOT = Path(__file__).resolve().parents[1]


class ReadonlyVerifierTests(unittest.TestCase):
    def test_current_production_source_is_clean(self) -> None:
        report = verify_readonly(SIDECAR_ROOT / "src")

        self.assertTrue(report.ok, report.render())
        self.assertEqual(report.findings, ())

    def test_detects_forbidden_name_and_raw_string(self) -> None:
        capability = "place" + "_order"
        report = self._verify(
            {
                "tmf_research/unsafe.py": (
                    f"CAPABILITY = {capability!r}\n"
                    f"def run(api):\n    return api.{capability}()\n"
                )
            }
        )

        self.assertIn("forbidden-symbol", self._rules(report))
        self.assertIn(capability, {finding.symbol for finding in report.findings})

    def test_detects_sdk_import_outside_the_raw_adapter(self) -> None:
        report = self._verify(
            {"tmf_research/collection/live.py": "import shioaji\n"}
        )

        self.assertIn("sdk-import-boundary", self._rules(report))

    def test_allows_sdk_import_only_in_the_raw_adapter(self) -> None:
        report = self._verify(
            {
                "tmf_research/infrastructure/shioaji_market_data.py": (
                    "import shioaji\n"
                )
            }
        )

        self.assertTrue(report.ok, report.render())

    def test_detects_raw_adapter_dependency_from_a_consumer(self) -> None:
        report = self._verify(
            {
                "tmf_research/models/inference.py": (
                    "from tmf_research.infrastructure.shioaji_market_data "
                    "import ShioajiMarketDataGateway\n"
                )
            }
        )

        self.assertIn("raw-adapter-dependency", self._rules(report))

    def test_detects_raw_api_attribute_access_outside_adapter(self) -> None:
        report = self._verify(
            {
                "tmf_research/models/inference.py": (
                    "def leak(gateway):\n    return gateway._api\n"
                )
            }
        )

        self.assertIn("raw-api-access", self._rules(report))

    def test_detects_network_import_inside_paper_package(self) -> None:
        report = self._verify(
            {"tmf_research/paper/broker.py": "import socket\n"}
        )

        self.assertIn("paper-network-boundary", self._rules(report))

    def test_invalid_python_fails_closed(self) -> None:
        report = self._verify(
            {"tmf_research/broken.py": "def broken(:\n    pass\n"}
        )

        self.assertFalse(report.ok)
        self.assertIn("syntax-error", self._rules(report))

    def test_missing_source_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = verify_readonly(Path(directory) / "missing")

        self.assertFalse(report.ok)
        self.assertIn("invalid-source-root", self._rules(report))

    def _verify(self, files: dict[str, str]):
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory) / "src"
            for relative, content in files.items():
                target = source_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            return verify_readonly(source_root)

    @staticmethod
    def _rules(report) -> set[str]:
        return {finding.rule for finding in report.findings}


if __name__ == "__main__":
    unittest.main()
