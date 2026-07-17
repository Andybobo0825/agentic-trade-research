from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from tmf_research.collection.backfill import (
    BackfillError,
    derived_near_target,
    normalize_tick_batch,
    run_backfill,
    third_wednesday,
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
        self.assertEqual(first.event_id, "hist-tick-TMFR1-2026-07-16-000000")
        self.assertEqual(
            first.exchange_datetime,
            datetime(2026, 7, 16, 9, 1, 0, tzinfo=TAIPEI),
        )
        self.assertEqual(first.received_at, FIXED_NOW)
        self.assertEqual(first.source, "SHIOAJI_HISTORICAL_TICKS_CONTINUOUS_NEAR")
        self.assertEqual(first.alias_code, "TMFR1")
        self.assertEqual(first.derived_target_code, "TMF202608")
        self.assertEqual(first.derived_delivery_date, "2026-08-19")
        self.assertEqual(first.target_derivation, "taifex-third-wednesday-v1")
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

        self.assertEqual(summary.alias_code, "TMFR1")
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
            / "backfill-tick-TMFR1-2026-07-15.ndjson"
        )
        self.assertTrue(segment.is_file())
        lines = segment.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        record = json.loads(lines[0])
        self.assertEqual(record["exchange_datetime"], "2026-07-15T09:01:00+08:00")
        self.assertEqual(record["source"], "SHIOAJI_HISTORICAL_TICKS_CONTINUOUS_NEAR")
        self.assertEqual(record["derived_target_code"], "TMF202607")

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
            "historical-tick", "backfill-tick-TMFR1-2026-07-15",
        ))
        self.assertFalse(self.store.has_segment(
            "historical-tick", "backfill-tick-TMFR1-2026-07-16",
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


class TargetDerivationTests(unittest.TestCase):
    def test_third_wednesday_matches_listed_taifex_expiries(self) -> None:
        from datetime import date

        self.assertEqual(third_wednesday(2026, 7), date(2026, 7, 15))
        self.assertEqual(third_wednesday(2026, 8), date(2026, 8, 19))
        self.assertEqual(third_wednesday(2026, 9), date(2026, 9, 16))
        self.assertEqual(third_wednesday(2026, 10), date(2026, 10, 21))
        self.assertEqual(third_wednesday(2026, 12), date(2026, 12, 16))

    def test_near_target_rolls_the_day_after_expiry(self) -> None:
        from datetime import date

        self.assertEqual(
            derived_near_target(date(2026, 7, 14)),
            ("TMF202607", "2026-07-15"),
        )
        self.assertEqual(
            derived_near_target(date(2026, 7, 15)),
            ("TMF202607", "2026-07-15"),
        )
        self.assertEqual(
            derived_near_target(date(2026, 7, 16)),
            ("TMF202608", "2026-08-19"),
        )

    def test_december_rolls_into_the_next_year(self) -> None:
        from datetime import date

        self.assertEqual(
            derived_near_target(date(2026, 12, 17)),
            ("TMF202701", "2027-01-20"),
        )


class VendorWindowTests(unittest.TestCase):
    def test_payload_entirely_outside_the_date_window_is_no_data(self) -> None:
        stale = {
            "ts": [wall_ns(2026, 7, 9, 15, 0), wall_ns(2026, 7, 10, 4, 59)],
            "close": [21500.0, 21501.0],
        }

        records = normalize_tick_batch(TickBatch(
            contract=contract(), date="2026-07-12",
            fetched_at=FIXED_NOW, payload=stale,
        ))

        self.assertEqual(records, ())

    def test_partially_out_of_window_payload_fails_closed(self) -> None:
        mixed = {
            "ts": [wall_ns(2026, 7, 11, 15, 0), wall_ns(2026, 7, 9, 15, 0)],
            "close": [21500.0, 21501.0],
        }

        with self.assertRaisesRegex(BackfillError, "window"):
            normalize_tick_batch(TickBatch(
                contract=contract(), date="2026-07-12",
                fetched_at=FIXED_NOW, payload=mixed,
            ))

    def test_night_and_day_session_bounds_stay_inside_the_window(self) -> None:
        edges = {
            "ts": [
                wall_ns(2026, 7, 15, 15, 0),
                wall_ns(2026, 7, 16, 4, 59, 59),
                wall_ns(2026, 7, 16, 8, 45),
                wall_ns(2026, 7, 16, 13, 44, 59),
            ],
            "close": [1.0, 2.0, 3.0, 4.0],
        }

        records = normalize_tick_batch(TickBatch(
            contract=contract(), date="2026-07-16",
            fetched_at=FIXED_NOW, payload=edges,
        ))

        self.assertEqual(len(records), 4)


class WeekendSkipTests(unittest.TestCase):
    def test_weekends_are_never_fetched_and_friday_night_lives_in_monday(self) -> None:
        friday_night_and_monday = {
            "ts": [
                wall_ns(2026, 7, 3, 15, 0),
                wall_ns(2026, 7, 6, 9, 0),
            ],
            "close": [21500.0, 21510.0],
        }
        gateway = FakeGateway({
            "2026-07-03": day_payload(3),
            "2026-07-06": friday_night_and_monday,
        })
        with TemporaryDirectory() as directory:
            store = AppendOnlyRawStore(
                Path(directory), writer_version="backfill-v1",
                dataset_version="dataset-v1",
            )

            summary = run_backfill(
                gateway, store,
                start_date="2026-07-03", end_date="2026-07-06",
                clock=lambda: FIXED_NOW,
            )

        self.assertEqual(gateway.fetch_calls, ["2026-07-03", "2026-07-06"])
        self.assertEqual(
            tuple((result.date, result.status) for result in summary.results),
            (
                ("2026-07-03", "STORED"),
                ("2026-07-04", "NON_TRADING_DAY"),
                ("2026-07-05", "NON_TRADING_DAY"),
                ("2026-07-06", "STORED"),
            ),
        )
        self.assertEqual(summary.non_trading_days, 2)
