from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import pine_gate_checks  # noqa: E402
from tmf_research.features.context_builder import ResearchBuildSpec  # noqa: E402
from tmf_research.processing.session_resolver import SessionResolver  # noqa: E402


def _row(day: str, session: str, minute: int, when: str) -> dict[str, object]:
    return {
        "trading_date": day,
        "session": session,
        "period": "2026+",
        "kind": "signal",
        "timeframe": 15,
        "signal": "rejection",
        "variant": "orig",
        "direction": -1,
        "when": when,
        "minute_of_session": minute,
        "deltas": {"15": 1.0, "60": 2.0, "240": 3.0, "sclose": 4.0},
    }


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


class PineGateChecksTests(unittest.TestCase):
    def test_gate_a_excludes_saturday_kbar_segments(self) -> None:
        def manifest(day: str) -> dict[str, object]:
            return {
                "segment_id": f"backfill-kbar-1m-TXFR1-{day}",
                "event_type": "historical-kbar-1m",
                "dataset_version": "tx-holdout-kbars-v1",
                "relative_path": f"segments/{day}.ndjson",
                "checksum_sha256": "0" * 64,
                "record_count": 1,
                "schema_version": "1.0.0",
                "writer_version": "test",
                "created_at": "2026-07-18T00:00:00+08:00",
                "minimum_event_time": "2026-07-18T00:00:00+08:00",
                "maximum_event_time": "2026-07-18T00:00:00+08:00",
            }

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.ndjson").write_text(
                "\n".join(
                    json.dumps(manifest(day))
                    for day in ("2026-07-17", "2026-07-18", "2026-07-20")
                )
                + "\n",
                encoding="utf-8",
            )

            selected = pine_gate_checks._selected_manifests(
                root,
                dataset_version="tx-holdout-kbars-v1",
                event_type="historical-kbar-1m",
                alias_code="TXFR1",
                start_day="2026-07-17",
                end_day="2026-07-20",
                weekdays_only=True,
            )

        self.assertEqual(
            tuple(manifest.segment_id for manifest in selected),
            (
                "backfill-kbar-1m-TXFR1-2026-07-17",
                "backfill-kbar-1m-TXFR1-2026-07-20",
            ),
        )

    def test_source_minutes_are_intersected_per_session(self) -> None:
        start = datetime.fromisoformat("2026-07-27T23:45:00+08:00")
        key = ("2026-07-27", "NIGHT")

        result = pine_gate_checks._intersect_source_minutes(
            {key: (start, start + timedelta(minutes=1))},
            {key: (
                start,
                start + timedelta(minutes=1),
                start + timedelta(minutes=2),
            )},
        )

        self.assertEqual(
            result,
            {key: frozenset((start, start + timedelta(minutes=1)))},
        )

    def test_comparison_is_signal_by_signal_on_the_same_15_minute_bar(self) -> None:
        left = [
            _row("2026-07-08", "DAY", 15, "2026-07-08T09:00:00+08:00"),
            _row("2026-07-08", "DAY", 30, "2026-07-08T09:15:00+08:00"),
            _row("2026-07-08", "DAY", 30, "2026-07-08T09:15:00+08:00"),
        ]
        right = [
            _row("2026-07-08", "DAY", 15, "2026-07-08T09:00:00+08:00"),
            _row("2026-07-08", "DAY", 45, "2026-07-08T09:30:00+08:00"),
        ]
        with TemporaryDirectory() as directory:
            left_path = Path(directory) / "left.ndjson"
            right_path = Path(directory) / "right.ndjson"
            _write(left_path, left)
            _write(right_path, right)

            result = pine_gate_checks.compare(
                left_path,
                right_path,
                left_label="tick",
                right_label="bar",
            )

        self.assertEqual(result.left_count, 3)
        self.assertEqual(result.right_count, 2)
        self.assertEqual(result.matched, 1)
        self.assertEqual(result.left_only, 2)
        self.assertEqual(result.right_only, 1)
        self.assertEqual(result.left_agreement_pct, 33.3333)
        self.assertEqual(result.right_agreement_pct, 50.0)
        self.assertEqual(result.left_only_examples[0]["bar_minute_of_session"], 30)
        self.assertEqual(result.right_only_examples[0]["bar_minute_of_session"], 45)

    def test_gate_day_reader_rejects_the_holdout_prefix(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "days.txt"
            path.write_text("2024-07-26\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                pine_gate_checks._read_gate_days(path)

    def test_manifest_day_inventory_is_alias_and_dataset_specific(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.ndjson").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "dataset_version": "tx-gate-ticks-v1",
                                "event_type": "historical-tick",
                                "segment_id": "backfill-tick-TXFR1-2026-07-08",
                            }
                        ),
                        json.dumps(
                            {
                                "dataset_version": "dataset-v1",
                                "event_type": "historical-tick",
                                "segment_id": "backfill-tick-TMFR1-2026-07-08",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            tx_days = pine_gate_checks._manifest_days(
                root,
                dataset_version="tx-gate-ticks-v1",
                event_type="historical-tick",
                alias_code="TXFR1",
                gate_days=("2026-07-08",),
            )
            tmf_days = pine_gate_checks._manifest_days(
                root,
                dataset_version="dataset-v1",
                event_type="historical-tick",
                alias_code="TMFR1",
                gate_days=("2026-07-08",),
            )

        self.assertEqual(tx_days, {"2026-07-08"})
        self.assertEqual(tmf_days, {"2026-07-08"})

    def test_filled_weekend_calendar_does_not_span_into_monday(self) -> None:
        source = Path(__file__).resolve().parents[1] / "data" / "calendar-v2.json"
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.json"
            pine_gate_checks._write_gate_calendar(
                source,
                ("2025-12-08",),
                path,
            )
            calendar = ResearchBuildSpec(calendar=path).trading_calendar()

        resolution = SessionResolver(calendar).resolve(
            datetime.fromisoformat("2025-12-06T12:00:00+08:00")
        )
        self.assertEqual(resolution.session, "CLOSED")


if __name__ == "__main__":
    unittest.main()
