from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import chdir
from io import StringIO
from pathlib import Path

from tmf_research.cli import main


SIDECAR_ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_build_calendar_restricts_evidence_to_named_dataset(self) -> None:
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.ndjson").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {
                            "segment_id": "backfill-kbar-1m-TXFR1-2020-03-06-2020-03-06",
                            "event_type": "historical-kbar-1m",
                            "dataset_version": "tx-holdout-kbars-v1",
                            "minimum_event_time": "2020-03-06T08:46:00+08:00",
                            "maximum_event_time": "2020-03-06T23:59:00+08:00",
                        },
                        {
                            "segment_id": "backfill-kbar-1m-TXFR1-2020-03-09-2020-03-09",
                            "event_type": "historical-kbar-1m",
                            "dataset_version": "tx-holdout-kbars-v1",
                            "minimum_event_time": "2020-03-09T08:46:00+08:00",
                            "maximum_event_time": "2020-03-09T13:44:00+08:00",
                        },
                        {
                            "segment_id": "backfill-tick-TMFR1-2020-03-06",
                            "event_type": "historical-tick",
                            "dataset_version": "dataset-v1",
                            "minimum_event_time": "2020-03-05T15:00:00+08:00",
                            "maximum_event_time": "2020-03-06T13:44:00+08:00",
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            out = root / "calendar.json"

            status = main(
                [
                    "build-calendar",
                    "--data-root", str(root),
                    "--dataset-version", "tx-holdout-kbars-v1",
                    "--start-date", "2020-03-06",
                    "--end-date", "2020-03-09",
                    "--out", str(out),
                ],
                stdout=output,
            )

            self.assertEqual(status, 0, output.getvalue())
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(
                [entry["trading_date"] for entry in payload["days"]],
                ["2020-03-06", "2020-03-09"],
            )
            self.assertEqual(
                payload["days"][1]["night_open"],
                "2020-03-06T15:00:00",
            )
        self.assertIn("CALENDAR WRITTEN days=2", output.getvalue())

    def test_phase5_status_fails_closed_offline_when_inputs_are_missing(self) -> None:
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = main([
                "phase5-status",
                "--raw-root", str(root / "missing-raw"),
                "--calendar", str(root / "missing-calendar.json"),
                "--witness-db", str(root / "witness" / "heads.sqlite3"),
            ], stdout=output)

        self.assertEqual(status, 0)
        import json as json_module

        payload = json_module.loads(output.getvalue())
        self.assertEqual(payload["status"], "REJECTED_INSUFFICIENT_DATA")
        self.assertIsInstance(payload["reasons"], list)

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

    def test_default_root_discovers_the_current_sidecar_checkout(self) -> None:
        output = StringIO()
        capability = "place" + "_order"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "tmf-research-agent"\n',
                encoding="utf-8",
            )
            source = root / "src" / "tmf_research" / "unsafe.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                f"def run(api):\n    return api.{capability}()\n",
                encoding="utf-8",
            )
            with chdir(root):
                status = main(["verify-readonly"], stdout=output)

        self.assertEqual(status, 1)
        self.assertIn(capability, output.getvalue())


if __name__ == "__main__":
    unittest.main()


class BackfillCliTests(unittest.TestCase):
    def test_backfill_requires_credentials_and_never_guesses(self) -> None:
        from unittest.mock import patch

        output = StringIO()
        with patch.dict("os.environ", {"SJ_API_KEY": "", "SJ_SEC_KEY": ""}):
            with chdir(SIDECAR_ROOT):
                status = main(
                    ["backfill", "--start", "2026-07-15", "--end", "2026-07-15"],
                    stdout=output,
                )

        self.assertEqual(status, 1)
        self.assertIn("CREDENTIALED_VALIDATION_NOT_RUN", output.getvalue())

    def test_backfill_runs_verifier_first_and_stores_days_via_injected_gateway(self) -> None:
        from datetime import datetime, timezone
        from unittest.mock import patch

        from tmf_research.domain.contracts import ContractInfo, TickBatch

        fixed_now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
        contract = ContractInfo(
            alias_code="TMFR1", target_code="TMF202607", symbol="TMFR1",
            category="TMF", delivery_month="202607", delivery_date="2026-07-15",
            resolved_at=fixed_now, resolver_version="shioaji-near-v1",
        )
        base = int((datetime(2026, 7, 15, 9, 1) - datetime(1970, 1, 1)).total_seconds())

        class FakeGateway:
            def resolve_near_contract(self) -> ContractInfo:
                return contract

            def fetch_ticks(self, contract_info: ContractInfo, date: str) -> TickBatch:
                return TickBatch(
                    contract=contract_info, date=date, fetched_at=fixed_now,
                    payload={
                        "ts": [base * 1_000_000_000],
                        "close": [21500.0],
                        "bid_price": [21499.0],
                        "ask_price": [21501.0],
                    },
                )

        created: dict[str, object] = {}

        def factory(
            *, api_key: str, secret_key: str, simulation: bool, alias_code: str,
        ) -> FakeGateway:
            created.update(
                api_key=api_key, simulation=simulation, alias_code=alias_code,
            )
            return FakeGateway()

        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                "os.environ", {"SJ_API_KEY": "key", "SJ_SEC_KEY": "secret"},
            ):
                with chdir(SIDECAR_ROOT):
                    status = main(
                        [
                            "backfill",
                            "--start", "2026-07-15",
                            "--end", "2026-07-15",
                            "--data-root", directory,
                            "--pause-seconds", "0",
                        ],
                        stdout=output,
                        gateway_factory=factory,
                    )

            self.assertEqual(status, 0, output.getvalue())
            self.assertEqual(created["api_key"], "key")
            self.assertEqual(created["simulation"], False)
            segment = (
                Path(directory) / "datasets" / "dataset-v1" / "segments"
                / "historical-tick" / "backfill-tick-TMFR1-2026-07-15.ndjson"
            )
            self.assertTrue(segment.is_file())
        self.assertIn("2026-07-15 STORED records=1", output.getvalue())
        self.assertIn("BACKFILL COMPLETE", output.getvalue())


class ManifestRangeFilterTests(unittest.TestCase):
    def test_dated_segments_filter_by_range_and_others_pass(self) -> None:
        from tmf_research.cli import _manifest_in_range

        segment = "backfill-tick-TMFR1-2025-06-30"
        self.assertTrue(_manifest_in_range(segment, "", ""))
        self.assertTrue(_manifest_in_range(segment, "2024-07-29", "2025-06-30"))
        self.assertFalse(_manifest_in_range(segment, "", "2025-06-29"))
        self.assertFalse(_manifest_in_range(segment, "2025-07-01", ""))
        self.assertTrue(_manifest_in_range("live-tick-0001", "2099-01-01", ""))
