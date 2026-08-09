from __future__ import annotations

import unittest

from tmf_research.processing.calendar_builder import (
    CalendarBuilderError,
    build_calendar_payload,
)


def manifest(
    day: str,
    minimum: str,
    maximum: str,
    *,
    event_type: str = "historical-tick",
) -> dict[str, object]:
    return {
        "segment_id": f"backfill-tick-TMFR1-{day}",
        "event_type": event_type,
        "minimum_event_time": minimum,
        "maximum_event_time": maximum,
    }


def kbar_manifest(
    day: str,
    minimum: str,
    maximum: str,
    *,
    alias: str = "TXFR1",
    dataset_version: str = "tx-holdout-kbars-v1",
) -> dict[str, object]:
    return {
        "segment_id": f"backfill-kbar-1m-{alias}-{day}-{day}",
        "event_type": "historical-kbar-1m",
        "dataset_version": dataset_version,
        "minimum_event_time": minimum,
        "maximum_event_time": maximum,
    }


class CalendarBuilderTests(unittest.TestCase):
    def test_normal_day_gets_night_and_1345_close(self) -> None:
        payload = build_calendar_payload([
            manifest(
                "2024-08-01",
                "2024-07-31T15:00:00.019000+08:00",
                "2024-08-01T13:44:59.900000+08:00",
            ),
        ], version="cal-v1")

        self.assertEqual(payload["timezone"], "Asia/Taipei")
        days = payload["days"]
        assert isinstance(days, list)
        self.assertEqual(len(days), 1)
        entry = days[0]
        assert isinstance(entry, dict)
        self.assertEqual(entry["trading_date"], "2024-08-01")
        self.assertEqual(entry["day_close"], "13:45:01")
        self.assertEqual(entry["night_open"], "2024-07-31T15:00:00")
        self.assertEqual(entry["night_close"], "2024-08-01T05:00:01")
        self.assertFalse(entry["is_expiry"])

    def test_expiry_day_closes_1330_and_is_flagged(self) -> None:
        payload = build_calendar_payload([
            manifest(
                "2024-08-21",
                "2024-08-20T15:00:00.001000+08:00",
                "2024-08-21T13:29:55.771000+08:00",
            ),
        ], version="cal-v1")

        days = payload["days"]
        assert isinstance(days, list)
        entry = days[0]
        assert isinstance(entry, dict)
        self.assertEqual(entry["day_close"], "13:30:01")
        self.assertTrue(entry["is_expiry"])

    def test_holiday_night_attaches_to_the_next_trading_date(self) -> None:
        payload = build_calendar_payload([
            manifest(
                "2024-09-16",
                "2024-09-13T15:00:00.010000+08:00",
                "2024-09-16T13:44:59.000000+08:00",
            ),
            manifest(
                "2024-09-17",
                "2024-09-16T15:00:00.059000+08:00",
                "2024-09-17T04:59:56.816000+08:00",
            ),
            manifest(
                "2024-09-18",
                "2024-09-18T08:45:00.100000+08:00",
                "2024-09-18T13:29:57.533000+08:00",
            ),
        ], version="cal-v1")

        days = payload["days"]
        assert isinstance(days, list)
        self.assertEqual(
            [entry["trading_date"] for entry in days if isinstance(entry, dict)],
            ["2024-09-16", "2024-09-18"],
        )
        expiry_day = days[1]
        assert isinstance(expiry_day, dict)
        self.assertEqual(expiry_day["night_open"], "2024-09-16T15:00:00")
        self.assertEqual(expiry_day["night_close"], "2024-09-17T05:00:01")

    def test_day_only_first_day_has_no_night(self) -> None:
        payload = build_calendar_payload([
            manifest(
                "2024-07-29",
                "2024-07-29T08:45:00.500000+08:00",
                "2024-07-29T13:44:58.000000+08:00",
            ),
        ], version="cal-v1")

        days = payload["days"]
        assert isinstance(days, list)
        entry = days[0]
        assert isinstance(entry, dict)
        self.assertIsNone(entry["night_open"])
        self.assertIsNone(entry["night_close"])

    def test_conflicting_nights_and_trailing_night_fail_closed(self) -> None:
        with self.assertRaisesRegex(CalendarBuilderError, "both attach"):
            build_calendar_payload([
                manifest(
                    "2024-09-17",
                    "2024-09-16T15:00:00+08:00",
                    "2024-09-17T04:59:00+08:00",
                ),
                manifest(
                    "2024-09-18",
                    "2024-09-17T15:00:00+08:00",
                    "2024-09-18T04:59:00+08:00",
                ),
                manifest(
                    "2024-09-19",
                    "2024-09-19T08:45:00+08:00",
                    "2024-09-19T13:44:00+08:00",
                ),
            ], version="cal-v1")
        with self.assertRaisesRegex(CalendarBuilderError, "no following"):
            build_calendar_payload([
                manifest(
                    "2024-09-16",
                    "2024-09-16T08:45:00+08:00",
                    "2024-09-16T13:44:00+08:00",
                ),
                manifest(
                    "2024-09-17",
                    "2024-09-16T15:00:00+08:00",
                    "2024-09-17T04:59:00+08:00",
                ),
            ], version="cal-v1")

    def test_ignores_other_event_types_and_is_deterministic(self) -> None:
        rows = [
            manifest(
                "2024-08-01",
                "2024-07-31T15:00:00+08:00",
                "2024-08-01T13:44:59+08:00",
            ),
            manifest(
                "2024-08-01",
                "2024-07-31T15:00:00+08:00",
                "2024-08-01T13:44:59+08:00",
                event_type="tick",
            ),
        ]

        first = build_calendar_payload(rows, version="cal-v1")
        second = build_calendar_payload(rows, version="cal-v1")

        self.assertEqual(first, second)
        days = first["days"]
        assert isinstance(days, list)
        self.assertEqual(len(days), 1)


if __name__ == "__main__":
    unittest.main()


class MidnightFragmentTests(unittest.TestCase):
    def test_after_midnight_night_fragment_starts_the_previous_evening(self) -> None:
        payload = build_calendar_payload([
            manifest(
                "2024-12-31",
                "2024-12-30T15:00:00.012000+08:00",
                "2024-12-31T13:44:59.748000+08:00",
            ),
            manifest(
                "2025-01-01",
                "2025-01-01T00:00:01.738000+08:00",
                "2025-01-01T04:59:59.603000+08:00",
            ),
            manifest(
                "2025-01-02",
                "2025-01-02T08:45:00.027000+08:00",
                "2025-01-02T13:44:59.888000+08:00",
            ),
        ], version="cal-v1")

        days = payload["days"]
        assert isinstance(days, list)
        by_date = {
            entry["trading_date"]: entry
            for entry in days
            if isinstance(entry, dict)
        }
        entry = by_date["2025-01-02"]
        self.assertEqual(entry["night_open"], "2024-12-31T15:00:00")
        self.assertEqual(entry["night_close"], "2025-01-01T05:00:01")


class DatasetAndAliasTests(unittest.TestCase):
    def test_txf_alias_and_dataset_are_selected_without_tmfr1_assumption(self) -> None:
        payload = build_calendar_payload([
            kbar_manifest(
                "2024-07-25",
                "2024-07-25T08:46:00+08:00",
                "2024-07-25T23:59:00+08:00",
            ),
            kbar_manifest(
                "2024-07-26",
                "2024-07-26T08:46:00+08:00",
                "2024-07-26T13:44:00+08:00",
            ),
            kbar_manifest(
                "2024-07-25",
                "2024-07-25T08:46:00+08:00",
                "2024-07-25T13:44:00+08:00",
                alias="TMFR1",
                dataset_version="dataset-v1",
            ),
        ], version="txf-holdout-v1", dataset_version="tx-holdout-kbars-v1")

        days = payload["days"]
        assert isinstance(days, list)
        self.assertEqual(
            [entry["trading_date"] for entry in days if isinstance(entry, dict)],
            ["2024-07-25", "2024-07-26"],
        )

    def test_friday_night_attaches_to_following_monday(self) -> None:
        payload = build_calendar_payload([
            kbar_manifest(
                "2020-03-06",
                "2020-03-06T08:46:00+08:00",
                "2020-03-06T23:59:00+08:00",
            ),
            kbar_manifest(
                "2020-03-09",
                "2020-03-09T03:06:00+08:00",
                "2020-03-09T13:44:00+08:00",
            ),
        ], version="txf-holdout-v1", dataset_version="tx-holdout-kbars-v1")

        days = payload["days"]
        assert isinstance(days, list)
        by_date = {
            entry["trading_date"]: entry
            for entry in days
            if isinstance(entry, dict)
        }
        self.assertIsNone(by_date["2020-03-06"]["night_open"])
        self.assertNotIn("2020-03-07", by_date)
        self.assertEqual(by_date["2020-03-09"]["night_open"], "2020-03-06T15:00:00")

    def test_date_range_filters_output_after_night_attribution(self) -> None:
        payload = build_calendar_payload([
            kbar_manifest(
                "2024-07-26",
                "2024-07-26T08:46:00+08:00",
                "2024-07-26T23:59:00+08:00",
            ),
            kbar_manifest(
                "2024-07-29",
                "2024-07-29T08:46:00+08:00",
                "2024-07-29T13:44:00+08:00",
            ),
        ],
            version="txf-holdout-v1",
            dataset_version="tx-holdout-kbars-v1",
            start_date="2024-07-26",
            end_date="2024-07-26",
        )

        days = payload["days"]
        assert isinstance(days, list)
        self.assertEqual(len(days), 1)
        self.assertEqual(days[0]["trading_date"], "2024-07-26")
