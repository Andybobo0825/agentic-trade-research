from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tmf_research.security.readonly_verifier import ReadonlyReport, verify_readonly


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

    def test_detects_raw_adapter_imported_from_parent_package(self) -> None:
        report = self._verify(
            {
                "tmf_research/models/inference.py": (
                    "from tmf_research.infrastructure import shioaji_market_data\n"
                )
            }
        )

        self.assertIn("raw-adapter-dependency", self._rules(report))

    def test_detects_relative_raw_adapter_import(self) -> None:
        report = self._verify(
            {
                "tmf_research/models/inference.py": (
                    "from ..infrastructure.shioaji_market_data "
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

    def test_detects_raw_api_parameter_outside_adapter(self) -> None:
        report = self._verify(
            {"tmf_research/models/inference.py": "def leak(api):\n    return api\n"}
        )

        self.assertIn("raw-api-access", self._rules(report))

    def test_detects_constant_folded_getattr_capability_bypass(self) -> None:
        report = self._verify(
            {
                "tmf_research/models/inference.py": (
                    "def leak(gateway, contract):\n"
                    "    raw = getattr(gateway, '_' + 'api')\n"
                    "    return getattr(raw, 'place' + '_order')(contract)\n"
                )
            }
        )

        self.assertIn("raw-api-access", self._rules(report))
        self.assertIn("forbidden-symbol", self._rules(report))

    def test_detects_network_import_inside_paper_package(self) -> None:
        report = self._verify(
            {"tmf_research/paper/broker.py": "import socket\n"}
        )

        self.assertIn("paper-network-boundary", self._rules(report))

    def test_detects_process_capability_inside_paper_package(self) -> None:
        report = self._verify(
            {"tmf_research/paper/broker.py": "import subprocess\n"}
        )

        self.assertIn("paper-process-boundary", self._rules(report))

    def test_paper_import_allowlist_blocks_os_and_asyncio(self) -> None:
        os_report = self._verify(
            {
                "tmf_research/paper/broker.py": (
                    "import os\n"
                    "def escape():\n    return os.system('curl example.invalid')\n"
                )
            }
        )
        asyncio_report = self._verify(
            {
                "tmf_research/paper/broker.py": (
                    "import asyncio\n"
                    "async def escape():\n"
                    "    return await asyncio.open_connection('127.0.0.1', 1)\n"
                )
            }
        )

        self.assertIn("paper-import-boundary", self._rules(os_report))
        self.assertIn("paper-import-boundary", self._rules(asyncio_report))

    def test_paper_cannot_import_an_unsafe_internal_helper(self) -> None:
        report = self._verify(
            {
                "tmf_research/helpers/network.py": "import socket\n",
                "tmf_research/paper/broker.py": (
                    "from tmf_research.helpers.network import send\n"
                ),
            }
        )

        self.assertIn("paper-import-boundary", self._rules(report))

    def test_detects_dynamic_sdk_and_paper_network_imports(self) -> None:
        sdk_report = self._verify(
            {
                "tmf_research/models/inference.py": (
                    "import importlib\n"
                    "def load():\n    return importlib.import_module('shioaji')\n"
                )
            }
        )
        paper_report = self._verify(
            {
                "tmf_research/paper/broker.py": (
                    "def load():\n    return __import__('socket')\n"
                )
            }
        )

        self.assertIn("sdk-import-boundary", self._rules(sdk_report))
        self.assertIn("paper-network-boundary", self._rules(paper_report))

    def test_detects_constant_folded_dynamic_sdk_import(self) -> None:
        report = self._verify(
            {
                "tmf_research/models/inference.py": (
                    "import importlib\n"
                    "def load():\n"
                    "    return importlib.import_module('shio' + 'aji')\n"
                )
            }
        )

        self.assertIn("sdk-import-boundary", self._rules(report))

    def test_detects_relative_dynamic_raw_adapter_import(self) -> None:
        report = self._verify(
            {
                "tmf_research/models/inference.py": (
                    "import importlib\n"
                    "def load():\n"
                    "    return importlib.import_module(\n"
                    "        '..infrastructure.' + 'shioaji_market_data',\n"
                    "        __package__,\n"
                    "    )\n"
                )
            }
        )

        self.assertIn("raw-adapter-dependency", self._rules(report))

    def test_detects_dynamic_raw_adapter_with_explicit_package(self) -> None:
        report = self._verify(
            {
                "tmf_research/models/inference.py": (
                    "import importlib\n"
                    "def load():\n"
                    "    return importlib.import_module(\n"
                    "        '.shioaji_market_data',\n"
                    "        'tmf_research.infrastructure',\n"
                    "    )\n"
                )
            }
        )

        self.assertIn("raw-adapter-dependency", self._rules(report))

    def test_detects_dunder_import_with_explicit_relative_level(self) -> None:
        report = self._verify(
            {
                "tmf_research/models/inference.py": (
                    "def load():\n"
                    "    return __import__(\n"
                    "        'infrastructure.shioaji_market_data',\n"
                    "        globals(),\n"
                    "        locals(),\n"
                    "        (),\n"
                    "        2,\n"
                    "    )\n"
                )
            }
        )

        self.assertIn("raw-adapter-dependency", self._rules(report))

    def test_detects_forbidden_paper_boundary_class_names(self) -> None:
        class_names = (
            "Broker",
            "ExecutionBroker",
            "LiveExecution",
            "OrderGateway",
            "RealBroker",
        )

        for class_name in class_names:
            with self.subTest(class_name=class_name):
                report = self._verify(
                    {
                        "tmf_research/paper/unsafe.py": (
                            f"class {class_name}:\n    pass\n"
                        )
                    }
                )
                self.assertIn("forbidden-paper-class", self._rules(report))
                self.assertIn(
                    class_name,
                    {finding.symbol for finding in report.findings},
                )

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

    def _verify(self, files: dict[str, str]) -> ReadonlyReport:
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory) / "src"
            for relative, content in files.items():
                target = source_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            return verify_readonly(source_root)

    @staticmethod
    def _rules(report: ReadonlyReport) -> set[str]:
        return {finding.rule for finding in report.findings}


if __name__ == "__main__":
    unittest.main()
