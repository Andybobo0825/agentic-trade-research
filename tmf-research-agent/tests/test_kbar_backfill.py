from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from tmf_research.collection.kbar_backfill import (
    KbarPullError,
    normalize_kbar_batch,
    read_shioaji_credentials,
    run_kbar_pull,
)
from tmf_research.domain.contracts import ContractInfo, KbarBatch
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore


TAIPEI = ZoneInfo("Asia/Taipei")
FIXED_NOW = datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc)
EPOCH = datetime(1970, 1, 1)


def wall_ns(year: int, month: int, day: int, hour: int, minute: int) -> int:
    wall = datetime(year, month, day, hour, minute)
    return int((wall - EPOCH).total_seconds()) * 1_000_000_000


def contract() -> ContractInfo:
    return ContractInfo(
        alias_code="TXFR1",
        target_code="TXFR1",
        symbol="TX continuous near-month",
        category="TXF",
        delivery_month="202006",
        delivery_date="",
        resolved_at=FIXED_NOW,
        resolver_version="shioaji-near-v1",
    )


def payload(*, day: int = 16, count: int = 2) -> dict[str, object]:
    return {
        "ts": [wall_ns(2020, 3, day, 8, 45 + index) for index in range(count)],
        "Open": [100.0 + index for index in range(count)],
        "High": [101.0 + index for index in range(count)],
        "Low": [99.0 + index for index in range(count)],
        "Close": [100.5 + index for index in range(count)],
        "Volume": [index + 1 for index in range(count)],
    }


def field_value(values: dict[str, object], name: str, index: int) -> object:
    column = values[name]
    assert isinstance(column, list)
    return column[index]


class ServerError(Exception):
    pass


class FakeKbarGateway:
    def __init__(
        self,
        batches: dict[tuple[str, str], dict[str, object]],
        failures: dict[tuple[str, str], int] | None = None,
    ) -> None:
        self.batches = batches
        self.failures = dict(failures or {})
        self.calls: list[tuple[str, str]] = []

    def resolve_near_contract(self) -> ContractInfo:
        return contract()

    def fetch_kbars(
        self,
        contract_info: ContractInfo,
        start: str,
        end: str,
    ) -> KbarBatch:
        del contract_info
        key = (start, end)
        self.calls.append(key)
        remaining = self.failures.get(key, 0)
        if remaining:
            self.failures[key] = remaining - 1
            raise ServerError("temporary server error")
        return KbarBatch(
            contract=contract(),
            start=start,
            end=end,
            fetched_at=FIXED_NOW,
            payload=self.batches[key],
        )


class KbarNormalizationTests(unittest.TestCase):
    def test_preserves_vendor_fields_and_derives_only_storage_timestamp(self) -> None:
        batch = KbarBatch(
            contract=contract(),
            start="2020-03-16",
            end="2020-03-20",
            fetched_at=FIXED_NOW,
            payload=payload(count=1),
        )

        records = normalize_kbar_batch(batch)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].fields["ts"], field_value(payload(count=1), "ts", 0))
        self.assertEqual(records[0].fields["Open"], 100.0)
        self.assertEqual(records[0].fields["Volume"], 1)
        self.assertEqual(
            records[0].exchange_datetime,
            datetime(2020, 3, 16, 8, 45, tzinfo=TAIPEI),
        )

    def test_rejects_ragged_vendor_arrays(self) -> None:
        values = payload(count=2)
        values["Close"] = [100.0]

        with self.assertRaisesRegex(KbarPullError, "ragged"):
            normalize_kbar_batch(KbarBatch(
                contract=contract(),
                start="2020-03-16",
                end="2020-03-20",
                fetched_at=FIXED_NOW,
                payload=values,
            ))

    def test_preserves_identical_vendor_duplicate_rows_with_unique_storage_ids(self) -> None:
        values = payload(count=1)
        for name in ("ts", "Open", "High", "Low", "Close", "Volume"):
            column = values[name]
            assert isinstance(column, list)
            values[name] = column + column

        records = normalize_kbar_batch(KbarBatch(
            contract=contract(),
            start="2020-03-16",
            end="2020-03-16",
            fetched_at=FIXED_NOW,
            payload=values,
        ))

        self.assertEqual(len(records), 2)
        self.assertNotEqual(records[0].event_id, records[1].event_id)
        self.assertEqual(records[0].fields, records[1].fields)


class KbarPullTests(unittest.TestCase):
    def test_dotenv_parser_ignores_unquoted_shell_commands(self) -> None:
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "SJ_API_KEY='api-key'\n"
                "UNQUOTED_COMMAND=$(do-not-run-this)\n"
                "SJ_SEC_KEY=secret-key\n",
                encoding="utf-8",
            )

            credentials = read_shioaji_credentials(env_file)

        self.assertEqual((credentials.api_key, credentials.secret_key), ("api-key", "secret-key"))

    def test_fetches_daily_chunks_stores_raw_records_and_resumes(self) -> None:
        batches = {
            ("2020-03-16", "2020-03-16"): payload(day=16),
            ("2020-03-17", "2020-03-17"): payload(day=17, count=1),
        }
        gateway = FakeKbarGateway(batches)
        sleeps: list[float] = []

        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = AppendOnlyRawStore(
                root, writer_version="kbar-backfill-v1", dataset_version="dataset-v1",
            )
            summary = run_kbar_pull(
                gateway,
                store,
                start_date="2020-03-16",
                end_date="2020-03-17",
                clock=lambda: FIXED_NOW,
                sleep=sleeps.append,
            )

            self.assertEqual(summary.stored_records, 3)
            self.assertEqual(gateway.calls, list(batches))
            segment = (
                root / "datasets" / "dataset-v1" / "segments"
                / "historical-kbar-1m"
                / "backfill-kbar-1m-TXFR1-2020-03-16-2020-03-16.ndjson"
            )
            self.assertTrue(segment.is_file())
            stored = json.loads(segment.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(stored["fields"]["Close"], 100.5)
            fields = stored["fields"]
            assert isinstance(fields, dict)
            self.assertEqual(fields["ts"], field_value(payload(), "ts", 0))

            rerun = run_kbar_pull(
                gateway,
                store,
                start_date="2020-03-16",
                end_date="2020-03-17",
                clock=lambda: FIXED_NOW,
                sleep=sleeps.append,
            )

        self.assertEqual(gateway.calls, list(batches))
        self.assertEqual(rerun.already_stored_chunks, 2)

    def test_fetches_one_trading_day_per_request_and_resumes(self) -> None:
        batches = {
            ("2020-03-20", "2020-03-20"): payload(day=20),
            ("2020-03-23", "2020-03-23"): payload(day=23),
        }
        gateway = FakeKbarGateway(batches)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = AppendOnlyRawStore(
                root, writer_version="kbar-backfill-v1", dataset_version="dataset-v1",
            )
            summary = run_kbar_pull(
                gateway,
                store,
                start_date="2020-03-20",
                end_date="2020-03-23",
                clock=lambda: FIXED_NOW,
            )

            self.assertEqual(summary.stored_records, 4)
            self.assertEqual(summary.non_trading_days, 2)
            self.assertEqual(gateway.calls, list(batches))
            for day in ("2020-03-20", "2020-03-23"):
                segment = (
                    root / "datasets" / "dataset-v1" / "segments"
                    / "historical-kbar-1m"
                    / f"backfill-kbar-1m-TXFR1-{day}-{day}.ndjson"
                )
                self.assertTrue(segment.is_file(), segment)

            rerun = run_kbar_pull(
                gateway,
                store,
                start_date="2020-03-20",
                end_date="2020-03-23",
                clock=lambda: FIXED_NOW,
            )

        self.assertEqual(gateway.calls, list(batches))
        self.assertEqual(rerun.already_stored_chunks, 2)
        self.assertEqual(rerun.non_trading_days, 2)

    def test_single_day_404_is_no_data_without_retry_or_failure(self) -> None:
        missing = ("2020-03-17", "2020-03-17")

        class MissingDayGateway(FakeKbarGateway):
            def fetch_kbars(
                self,
                contract_info: ContractInfo,
                start: str,
                end: str,
            ) -> KbarBatch:
                if (start, end) == missing:
                    self.calls.append((start, end))
                    raise ServerError("ServerError 404 Data not found")
                return super().fetch_kbars(contract_info, start, end)

        gateway = MissingDayGateway({
            ("2020-03-16", "2020-03-16"): payload(day=16),
            ("2020-03-18", "2020-03-18"): payload(day=18),
        })
        sleeps: list[float] = []

        with TemporaryDirectory() as directory:
            store = AppendOnlyRawStore(
                Path(directory), writer_version="kbar-backfill-v1",
            )
            summary = run_kbar_pull(
                gateway,
                store,
                start_date="2020-03-16",
                end_date="2020-03-18",
                max_retries=3,
                retry_backoff_seconds=0.25,
                sleep=sleeps.append,
                clock=lambda: FIXED_NOW,
            )

        self.assertEqual(summary.stored_records, 4)
        self.assertEqual(summary.no_data_chunks, 1)
        self.assertEqual(gateway.calls, [
            ("2020-03-16", "2020-03-16"),
            missing,
            ("2020-03-18", "2020-03-18"),
        ])
        self.assertEqual(sleeps, [])

    def test_retries_server_error_with_backoff(self) -> None:
        key = ("2020-03-16", "2020-03-16")
        gateway = FakeKbarGateway({key: payload()}, failures={key: 2})
        sleeps: list[float] = []

        with TemporaryDirectory() as directory:
            store = AppendOnlyRawStore(
                Path(directory), writer_version="kbar-backfill-v1",
            )
            summary = run_kbar_pull(
                gateway,
                store,
                start_date=key[0],
                end_date=key[1],
                max_retries=2,
                retry_backoff_seconds=0.25,
                sleep=sleeps.append,
                clock=lambda: FIXED_NOW,
            )

        self.assertEqual(summary.stored_records, 2)
        self.assertEqual(gateway.calls, [key, key, key])
        self.assertEqual(sleeps, [0.25, 0.5])

    def test_pre_history_404_is_reported_as_no_data(self) -> None:
        class NoHistoryGateway(FakeKbarGateway):
            def fetch_kbars(
                self,
                contract_info: ContractInfo,
                start: str,
                end: str,
            ) -> KbarBatch:
                del contract_info, start, end
                raise ServerError("ServerError 404 Data not found")

        gateway = NoHistoryGateway({})
        with TemporaryDirectory() as directory:
            store = AppendOnlyRawStore(
                Path(directory), writer_version="kbar-backfill-v1",
            )
            summary = run_kbar_pull(
                gateway,
                store,
                start_date="2020-02-03",
                end_date="2020-02-03",
                max_retries=0,
                clock=lambda: FIXED_NOW,
            )

        self.assertEqual(summary.no_data_chunks, 1)


if __name__ == "__main__":
    unittest.main()
