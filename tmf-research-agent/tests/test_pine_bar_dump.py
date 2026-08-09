from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from tmf_research.infrastructure.raw_store import AppendOnlyRawStore


SIDECAR_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = SIDECAR_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import pine_bar_dump  # noqa: E402
import pine_signal_report  # noqa: E402
from tmf_research.collection.kbar_backfill import HistoricalKbarRecord  # noqa: E402


TAIPEI = ZoneInfo("Asia/Taipei")
UTC_NOW = datetime(2026, 8, 6, 0, 0, tzinfo=timezone.utc)
EPOCH = datetime(1970, 1, 1)


def wall_ns(value: datetime) -> int:
    naive = value.replace(tzinfo=None)
    return int((naive - EPOCH).total_seconds()) * 1_000_000_000


class PineBarDumpTests(unittest.TestCase):
    def test_reuses_the_authoritative_pine_symbols(self) -> None:
        self.assertIs(pine_bar_dump.PineState, pine_signal_report.PineState)
        self.assertIs(pine_bar_dump.PRESETS, pine_signal_report.PRESETS)
        self.assertIs(pine_bar_dump.HORIZONS, pine_signal_report.HORIZONS)
        self.assertIs(pine_bar_dump._period, pine_signal_report._period)

    def test_dump_writes_schema_and_twenty_seeded_controls(self) -> None:
        # Vendor ts values are minute closing labels; 08:46 is the first
        # stored label for the 08:45..08:46 interval.
        day = datetime(2026, 8, 3, 8, 46, tzinfo=TAIPEI)
        calendar = {
            "version": "pine-bar-test-v1",
            "timezone": "Asia/Taipei",
            "days": [{
                "trading_date": "2026-08-03",
                "day_open": "08:45:00",
                "day_close": "09:16:01",
                "night_open": None,
                "night_close": None,
                "is_expiry": False,
            }],
        }
        records = []
        for index in range(31):
            value = 100.0 + index
            timestamp = day + timedelta(minutes=index)
            records.append(HistoricalKbarRecord(
                schema_version="1.0.0",
                event_id=f"hist-kbar-1m-TXFR1-{wall_ns(timestamp)}",
                exchange_datetime=timestamp,
                received_at=UTC_NOW,
                source="SHIOAJI_KBARS_1M_CONTINUOUS_NEAR",
                alias_code="TXFR1",
                contract_code="TXF202608",
                delivery_month="202608",
                fields={
                    "ts": wall_ns(timestamp),
                    "Open": value,
                    "High": value + 1.0,
                    "Low": value - 1.0,
                    "Close": value + 0.5,
                    "Volume": 10,
                },
            ))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = AppendOnlyRawStore(
                root,
                writer_version="kbar-backfill-v1",
                dataset_version=pine_bar_dump.DEFAULT_DATASET_VERSION,
            )
            store.append_segment(
                "historical-kbar-1m",
                records,
                segment_id="backfill-kbar-1m-TXFR1-2026-08-03-2026-08-03",
                created_at=UTC_NOW,
            )
            calendar_path = root / "calendar.json"
            calendar_path.write_text(json.dumps(calendar), encoding="utf-8")
            output_path = root / "events.ndjson"

            status = pine_bar_dump.dump(
                root,
                calendar_path,
                "2026-08-03",
                "2026-08-03",
                output_path,
            )

            self.assertEqual(status, 0)
            rows = [json.loads(line) for line in output_path.read_text().splitlines()]

        self.assertEqual(sum(row["kind"] == "random" for row in rows), 20)
        self.assertTrue(rows)
        expected_keys = {
            "trading_date", "session", "period", "kind", "timeframe",
            "signal", "variant", "direction", "when", "minute_of_session",
            "deltas",
        }
        self.assertTrue(all(set(row) == expected_keys for row in rows))
        self.assertTrue(all(set(row["deltas"]) == {"15", "60", "240", "sclose"}
                            for row in rows))
        random_rows = [row for row in rows if row["kind"] == "random"]
        self.assertTrue(all(row["variant"] == "random" for row in random_rows))
        self.assertTrue(all(row["when"].endswith("+08:00") for row in rows))


if __name__ == "__main__":
    unittest.main()
