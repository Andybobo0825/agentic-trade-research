from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import pine_holdout_verdict  # noqa: E402


PERIOD_DATES = {
    "2020H1": "2020-04-01",
    "2020H2": "2020-07-01",
    "2021H1": "2021-01-15",
    "2021H2": "2021-07-15",
    "2022H1": "2022-01-15",
    "2022H2": "2022-07-15",
    "2023H1": "2023-01-15",
    "2023H2": "2023-07-15",
    "2024H1": "2024-07-15",
}


def _deltas(net: float) -> dict[str, float]:
    # SHORT net = -delta - 3.0.
    delta = -(net + pine_holdout_verdict.COST)
    return {
        horizon: delta
        for horizon in pine_holdout_verdict.HORIZONS
    }


def _row(
    *,
    period: str,
    trading_date: str,
    kind: str,
    net: float,
    index: int,
) -> dict[str, object]:
    if kind == "signal":
        fields = {
            "kind": "signal",
            "timeframe": 15,
            "signal": "rejection",
            "variant": "orig",
            "direction": -1,
        }
    else:
        fields = {
            "kind": "random",
            "timeframe": 0,
            "signal": "random",
            "variant": "random",
            "direction": 1,
        }
    return {
        "trading_date": trading_date,
        "session": "DAY",
        "period": period,
        **fields,
        "when": f"{trading_date}T09:{index % 60:02d}:00+08:00",
        "minute_of_session": 30,
        "deltas": _deltas(net),
    }


def _rows(
    *,
    signal_values: dict[str, list[float]] | None = None,
    signal_count: dict[str, int] | None = None,
    control_values: dict[str, list[float]] | None = None,
) -> list[dict[str, object]]:
    signal_values = signal_values or {
        period: [1.0] * 100
        for period in PERIOD_DATES
    }
    signal_count = signal_count or {
        period: len(values)
        for period, values in signal_values.items()
    }
    control_values = control_values or {
        period: [0.0] * 20
        for period in PERIOD_DATES
    }
    rows: list[dict[str, object]] = []
    for period, trading_date in PERIOD_DATES.items():
        values = signal_values.get(period, [1.0] * signal_count.get(period, 100))
        if len(values) != signal_count.get(period, len(values)):
            raise AssertionError("signal_count does not match signal_values")
        rows.extend(
            _row(
                period=period,
                trading_date=trading_date,
                kind="signal",
                net=value,
                index=index,
            )
            for index, value in enumerate(values)
        )
        rows.extend(
            _row(
                period=period,
                trading_date=trading_date,
                kind="random",
                net=value,
                index=index,
            )
            for index, value in enumerate(control_values.get(period, ()))
        )
    return rows


class PineHoldoutVerdictTests(unittest.TestCase):
    def _evaluate(
        self,
        rows: list[dict[str, object]],
    ) -> pine_holdout_verdict.VerdictReport:
        # Keep the production protocol at 10,000 while keeping unit tests fast.
        with patch.object(pine_holdout_verdict, "BOOTSTRAP", 200):
            return pine_holdout_verdict.evaluate(rows)

    def test_case_passes_all_four_criteria(self) -> None:
        report = self._evaluate(_rows())

        for result in report.horizons:
            self.assertTrue(result.p1_pass)
            self.assertTrue(result.p2_pass)
            self.assertTrue(result.p3_pass)
            self.assertTrue(result.p4_pass)
            self.assertTrue(result.full_pass)
            self.assertEqual(result.label, "PASS")
        self.assertEqual(report.label, "PASS")

    def test_period_split_is_derived_from_trading_date(self) -> None:
        rows = _rows()
        rows[0]["period"] = "2024H2"

        report = self._evaluate(rows)

        self.assertEqual(report.horizons[0].periods[0].signal_n, 100)

    def test_rejects_rows_outside_the_holdout_window(self) -> None:
        rows = _rows()
        rows[0]["trading_date"] = "2024-07-29"

        with self.assertRaises(ValueError):
            self._evaluate(rows)

    def test_each_criterion_can_fail_individually(self) -> None:
        p1_values = {
            period: [1.0] * 100
            for period in PERIOD_DATES
        }
        p1_controls = {
            period: ([2.0] * 20 if index < 3 else [0.0] * 20)
            for index, period in enumerate(PERIOD_DATES)
        }

        p2_values = {
            period: ([-99.0, 101.0] * 50)
            for period in PERIOD_DATES
        }

        p3_values = {
            period: ([-1.0] * 100 if index < 3 else [1.0] * 100)
            for index, period in enumerate(PERIOD_DATES)
        }
        p3_controls = {
            period: [-2.0] * 20
            for period in PERIOD_DATES
        }

        p4_values = {
            period: [1.0] * (99 if index < 5 else 100)
            for index, period in enumerate(PERIOD_DATES)
        }

        cases = {
            "P1": _rows(signal_values=p1_values, control_values=p1_controls),
            "P2": _rows(signal_values=p2_values),
            "P3": _rows(signal_values=p3_values, control_values=p3_controls),
            "P4": _rows(signal_values=p4_values),
        }
        for criterion, rows in cases.items():
            with self.subTest(criterion=criterion):
                result = self._evaluate(rows).horizons[0]
                self.assertFalse(getattr(result, f"{criterion.lower()}_pass"))
                self.assertFalse(result.full_pass)

    def test_crash_exclusion_changes_pass_to_crash_dependent(self) -> None:
        crash_dates = {
            "2020H1": "2020-03-16",
            "2021H1": "2021-05-17",
            "2022H1": "2022-06-15",
        }
        signal_values = {
            period: ([100.0] * 100 if period in crash_dates else [-99.0, 101.0] * 50)
            for period in PERIOD_DATES
        }
        rows: list[dict[str, object]] = []
        for period, default_date in PERIOD_DATES.items():
            trading_date = crash_dates.get(period, default_date)
            rows.extend(
                _row(
                    period=period,
                    trading_date=trading_date,
                    kind="signal",
                    net=value,
                    index=index,
                )
                for index, value in enumerate(signal_values[period])
            )
            rows.extend(
                _row(
                    period=period,
                    trading_date=trading_date,
                    kind="random",
                    net=0.0,
                    index=index,
                )
                for index in range(20)
            )

        report = self._evaluate(rows)

        for result in report.horizons:
            self.assertTrue(result.full_pass)
            self.assertFalse(result.crash_p2_pass)
            self.assertEqual(result.label, "PASS (crash-dependent)")
        self.assertEqual(report.label, "PASS (crash-dependent)")


if __name__ == "__main__":
    unittest.main()
