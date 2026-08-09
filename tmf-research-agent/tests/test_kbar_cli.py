from __future__ import annotations

import unittest
from contextlib import chdir
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from tmf_research.cli import GatewayFactory, main
from tmf_research.domain.contracts import ContractInfo, KbarBatch


SIDECAR_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc)


class KbarCliTests(unittest.TestCase):
    def test_pull_kbars_reads_dotenv_and_forces_real_read_only_session(self) -> None:
        contract = ContractInfo(
            alias_code="TXFR1",
            target_code="TXFH6",
            symbol="TX continuous near-month",
            category="TXF",
            delivery_month="202608",
            delivery_date="2026-08-19",
            resolved_at=NOW,
            resolver_version="shioaji-near-v1",
        )
        created: dict[str, object] = {}

        class FakeGateway:
            def resolve_near_contract(self) -> ContractInfo:
                return contract

            def fetch_kbars(
                self,
                contract_info: ContractInfo,
                start: str,
                end: str,
            ) -> KbarBatch:
                self.last_request = (contract_info, start, end)
                return KbarBatch(
                    contract=contract_info,
                    start=start,
                    end=end,
                    fetched_at=NOW,
                    payload={
                        "ts": [1584348360000000000],
                        "Open": [9919.0],
                        "High": [9964.0],
                        "Low": [9914.0],
                        "Close": [9958.0],
                        "Volume": [3139],
                    },
                )

        def factory(
            *,
            api_key: str,
            secret_key: str,
            simulation: bool,
            alias_code: str,
        ) -> FakeGateway:
            created.update(
                api_key=api_key,
                secret_key=secret_key,
                simulation=simulation,
                alias_code=alias_code,
            )
            return FakeGateway()

        output = StringIO()
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "SJ_API_KEY=key-from-file\nSJ_SEC_KEY=secret-from-file\n",
                encoding="utf-8",
            )
            data_root = Path(directory) / "data"
            with chdir(SIDECAR_ROOT):
                status = main(
                    [
                        "pull-kbars",
                        "--start", "2020-03-16",
                        "--end", "2020-03-16",
                        "--data-root", str(data_root),
                        "--env-file", str(env_file),
                        "--pause-seconds", "0",
                    ],
                    stdout=output,
                    gateway_factory=cast(GatewayFactory, factory),
                )

        self.assertEqual(status, 0, output.getvalue())
        self.assertEqual(created["api_key"], "key-from-file")
        self.assertEqual(created["secret_key"], "secret-from-file")
        self.assertEqual(created["simulation"], False)
        self.assertEqual(created["alias_code"], "TXFR1")
        self.assertIn("stored_records=1", output.getvalue())

    def test_pull_kbars_returns_nonzero_when_fetch_fails(self) -> None:
        from tmf_research.collection.kbar_backfill import KbarPullError

        class FailingGateway:
            def resolve_near_contract(self) -> ContractInfo:
                return ContractInfo(
                    alias_code="TXFR1",
                    target_code="TXFR1",
                    symbol="TX continuous near-month",
                    category="TXF",
                    delivery_month="202608",
                    delivery_date="2026-08-19",
                    resolved_at=NOW,
                    resolver_version="shioaji-near-v1",
                )

            def fetch_kbars(
                self,
                contract_info: ContractInfo,
                start: str,
                end: str,
            ) -> KbarBatch:
                del contract_info, start, end
                raise KbarPullError("deterministic pull failure")

        def factory(**kwargs: object) -> FailingGateway:
            return FailingGateway()

        output = StringIO()
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "SJ_API_KEY=key\nSJ_SEC_KEY=secret\n",
                encoding="utf-8",
            )
            with chdir(SIDECAR_ROOT):
                status = main(
                    [
                        "pull-kbars",
                        "--start", "2020-03-16",
                        "--end", "2020-03-16",
                        "--data-root", str(Path(directory) / "data"),
                        "--env-file", str(env_file),
                        "--pause-seconds", "0",
                        "--max-retries", "0",
                    ],
                    stdout=output,
                    gateway_factory=cast(GatewayFactory, factory),
                )

        self.assertEqual(status, 1, output.getvalue())
        self.assertIn("KBAR PULL FAILED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
