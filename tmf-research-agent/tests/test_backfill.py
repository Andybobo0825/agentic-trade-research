from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from tmf_research.collection.backfill import (
    BackfillError,
    normalize_tick_batch,
    run_backfill,
)
from tmf_research.domain.contracts import ContractInfo, KbarBatch, TickBatch
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore


TAIPEI = ZoneInfo("Asia/Taipei")
FIXED_NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
EPOCH = datetime(1970, 1, 1)


def wall_ns(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    """Shioaji historical ts: Taipei wall-clock encoded as epoch nanoseconds."""

    wall = datetime(year, month, day, hour, minute, second)
    return int((wall - EPOCH).total_seconds()) * 1_000_000_000


def contract() -> ContractInfo:
    return ContractInfo(
        alias_code="TMFR1",
        target_code="TMF202607",
        symbol="TMFR1",
        category="TMF",
        delivery_month="202607",
        delivery_date="2026-07-15",
        resolved_at=FIXED_NOW,
        resolver_version="shioaji-near-v1",
    )


def day_payload(day: int, count: int = 2) -> dict[str, object]:
    return {
        "ts": [wall_ns(2026, 7, day, 9, 1, index) for index in range(count)],
        "close": [21500.0 + index for index in range(count)],
        "volume": [1 + index for index in range(count)],
        "bid_price": [21499.0 + index for index in range(count)],
        "ask_price": [21501.0 + index for index in range(count)],
        "tick_type": [1 for _index in range(count)],
    }


class FakeGateway:
    def __init__(self, days: dict[str, dict[str, object]]) -> None:
        self.days = days
        self.fetch_calls: list[str] = []

    def resolve_near_contract(self) -> ContractInfo:
        return contract()

    def fetch_ticks(self, contract_info: ContractInfo, date: str) -> TickBatch:
        self.fetch_calls.append(date)
        payload = self.days.get(date)
        if payload is None:
            raise ConnectionError(f"gateway offline for {date}")
        return TickBatch(
            contract=contract_info,
            date=date,
            fetched_at=FIXED_NOW,
            payload=payload,
        )

    def fetch_kbars(self, contract_info: ContractInfo, start: str, end: str) -> KbarBatch:
        raise AssertionError("backfill must not fetch kbars")


class NormalizationTests(unittest.TestCase):
    def test_normalizes_arrays_into_taipei_stamped_immutable_records(self) -> None:
        batch = TickBatch(
            contract=contract(), date="2026-07-16",
            fetched_at=FIXED_NOW, payload=day_payload(16),
        )

        records = normalize_tick_batch(batch)

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first.event_id, "hist-tick-TMF202607-2026-07-16-000000")
        self.assertEqual(
            first.exchange_datetime,
            datetime(2026, 7, 16, 9, 1, 0, tzinfo=TAIPEI),
        )
        self.assertEqual(first.received_at, FIXED_NOW)
        self.assertEqual(first.source, "SHIOAJI_HISTORICAL_TICKS")
        self.assertEqual(first.target_code, "TMF202607")
        self.assertEqual(first.fields["close"], 21500.0)
        self.assertEqual(first.fields["bid_price"], 21499.0)
        self.assertEqual(first.fields["ask_price"], 21501.0)
        self.assertNotIn("ts", first.fields)

    def test_ragged_or_missing_ts_payloads_fail_closed(self) -> None:
        ragged = {"ts": [wall_ns(2026, 7, 16, 9, 1)], "close": [1.0, 2.0]}
        with self.assertRaisesRegex(BackfillError, "ragged"):
            normalize_tick_batch(TickBatch(
                contract=contract(), date="2026-07-16",
                fetched_at=FIXED_NOW, payload=ragged,
            ))
        with self.assertRaisesRegex(BackfillError, "ts"):
            normalize_tick_batch(TickBatch(
                contract=contract(), date="2026-07-16",
                fetched_at=FIXED_NOW, payload={"close": [1.0]},
            ))

    def test_empty_payload_normalizes_to_no_records(self) -> None:
        batch = TickBatch(
            contract=contract(), date="2026-07-16",
            fetched_at=FIXED_NOW, payload={"ts": [], "close": []},
        )

        self.assertEqual(normalize_tick_batch(batch), ())


class RunBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = AppendOnlyRawStore(
            self.root, writer_version="backfill-v1", dataset_version="dataset-v1",
        )

    def test_stores_one_immutable_segment_per_day_with_gaps_reported(self) -> None:
        gateway = FakeGateway({
            "2026-07-15": day_payload(15),
            "2026-07-16": {"ts": [], "close": []},
            "2026-07-17": day_payload(17, count=3),
        })

        summary = run_backfill(
            gateway, self.store,
            start_date="2026-07-15", end_date="2026-07-17",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(summary.target_code, "TMF202607")
        self.assertEqual(
            tuple((result.date, result.status, result.record_count) for result in summary.results),
            (
                ("2026-07-15", "STORED", 2),
                ("2026-07-16", "NO_DATA", 0),
                ("2026-07-17", "STORED", 3),
            ),
        )
        self.assertEqual(summary.stored_days, 2)
        self.assertEqual(summary.no_data_days, 1)
        segment = (
            self.root / "datasets" / "dataset-v1" / "segments" / "historical-tick"
            / "backfill-tick-TMF202607-2026-07-15.ndjson"
        )
        self.assertTrue(segment.is_file())
        lines = segment.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        record = json.loads(lines[0])
        self.assertEqual(record["exchange_datetime"], "2026-07-15T09:01:00+08:00")
        self.assertEqual(record["source"], "SHIOAJI_HISTORICAL_TICKS")

    def test_rerun_skips_already_stored_days_without_refetching(self) -> None:
        gateway = FakeGateway({"2026-07-15": day_payload(15)})
        run_backfill(
            gateway, self.store,
            start_date="2026-07-15", end_date="2026-07-15",
            clock=lambda: FIXED_NOW,
        )
        self.assertEqual(gateway.fetch_calls, ["2026-07-15"])

        summary = run_backfill(
            gateway, self.store,
            start_date="2026-07-15", end_date="2026-07-15",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(gateway.fetch_calls, ["2026-07-15"])
        self.assertEqual(summary.results[0].status, "ALREADY_STORED")

    def test_fetch_failure_fails_closed_with_day_context(self) -> None:
        gateway = FakeGateway({"2026-07-15": day_payload(15)})

        with self.assertRaisesRegex(BackfillError, "2026-07-16"):
            run_backfill(
                gateway, self.store,
                start_date="2026-07-15", end_date="2026-07-16",
                clock=lambda: FIXED_NOW,
            )

        self.assertTrue(self.store.has_segment(
            "historical-tick", "backfill-tick-TMF202607-2026-07-15",
        ))
        self.assertFalse(self.store.has_segment(
            "historical-tick", "backfill-tick-TMF202607-2026-07-16",
        ))

    def test_invalid_date_ranges_are_rejected(self) -> None:
        gateway = FakeGateway({})

        with self.assertRaisesRegex(BackfillError, "range"):
            run_backfill(
                gateway, self.store,
                start_date="2026-07-17", end_date="2026-07-15",
                clock=lambda: FIXED_NOW,
            )
        with self.assertRaisesRegex(BackfillError, "date"):
            run_backfill(
                gateway, self.store,
                start_date="July 15", end_date="2026-07-16",
                clock=lambda: FIXED_NOW,
            )
        self.assertEqual(gateway.fetch_calls, [])

    def test_pause_runs_between_fetched_days_only(self) -> None:
        gateway = FakeGateway({
            "2026-07-15": day_payload(15),
            "2026-07-16": day_payload(16),
        })
        pauses: list[int] = []

        run_backfill(
            gateway, self.store,
            start_date="2026-07-15", end_date="2026-07-16",
            clock=lambda: FIXED_NOW,
            pause=lambda: pauses.append(1),
        )
        run_backfill(
            gateway, self.store,
            start_date="2026-07-15", end_date="2026-07-16",
            clock=lambda: FIXED_NOW,
            pause=lambda: pauses.append(1),
        )

        self.assertEqual(len(pauses), 1)


if __name__ == "__main__":
    unittest.main()
