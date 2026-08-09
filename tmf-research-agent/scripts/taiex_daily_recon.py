"""Reconnoitre the free FinMind daily TAIEX history.

The output is deliberately a small, portable CSV rather than a research
dataset: this script is a data-availability check for a possible low-
frequency study.  It uses only the Python standard library so it can run in
the sidecar's dependency-free runtime.
"""
from __future__ import annotations

import csv
import json
import sys
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ENDPOINT = "https://api.finmindtrade.com/api/v4/data"
START_DATE = "1990-01-01"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "taiex_daily.csv"

# Empirically, TaiwanStockPrice/TAIEX is the working weighted-index source
# (the initial recon returned data from 1999 onward).  The alternatives are
# retained only for the case where FinMind changes or empties that endpoint.
CANDIDATES = (
    ("TaiwanStockPrice", "TAIEX"),
    ("TaiwanStockTotalReturnIndex", "TAIEX"),
    ("TaiwanStockPrice", "TAIEX_index"),
    ("TaiwanStockTotalReturnIndex", "TAIEX_total_return"),
)


class ReconError(RuntimeError):
    """Raised when FinMind cannot provide a usable daily close series."""


def fetch_candidate(dataset: str, data_id: str) -> list[dict[str, object]]:
    """Fetch and retain rows that contain both a date and a daily close."""

    query = urlencode({
        "dataset": dataset,
        "data_id": data_id,
        "start_date": START_DATE,
    })
    request = Request(
        f"{ENDPOINT}?{query}",
        headers={"User-Agent": "taiex-daily-recon/1.0"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ReconError(f"{dataset}/{data_id}: {error}") from error

    if not isinstance(payload, Mapping):
        raise ReconError(f"{dataset}/{data_id}: unexpected response shape")
    raw_rows = payload.get("data")
    if not isinstance(raw_rows, list):
        return []

    rows: dict[str, dict[str, object]] = {}
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            continue
        row_date = raw_row.get("date")
        close = raw_row.get("close")
        if not isinstance(row_date, str) or not row_date or close is None:
            continue
        record: dict[str, object] = {
            "date": row_date,
            "close": close,
        }
        for output_name, source_names in (
            ("open", ("open",)),
            ("high", ("high", "max")),
            ("low", ("low", "min")),
            ("volume", ("volume", "Trading_Volume")),
        ):
            for source_name in source_names:
                value = raw_row.get(source_name)
                if value is not None:
                    record[output_name] = value
                    break
        rows[row_date] = record
    return [rows[row_date] for row_date in sorted(rows)]


def fetch_best_series() -> tuple[tuple[str, str], list[dict[str, object]]]:
    """Use the primary source, falling back to the longest usable candidate."""

    errors: list[str] = []
    primary = CANDIDATES[0]
    try:
        rows = fetch_candidate(*primary)
    except ReconError as error:
        errors.append(str(error))
        rows = []
    if rows:
        return primary, rows

    alternatives: list[tuple[tuple[str, str], list[dict[str, object]]]] = []
    for candidate in CANDIDATES[1:]:
        try:
            rows = fetch_candidate(*candidate)
        except ReconError as error:
            errors.append(str(error))
            continue
        if rows:
            alternatives.append((candidate, rows))
    if alternatives:
        return max(alternatives, key=lambda item: len(item[1]))
    detail = "; ".join(errors) if errors else "all candidates returned no rows"
    raise ReconError(f"no usable FinMind TAIEX series: {detail}")


def write_csv(rows: Iterable[Mapping[str, object]], output_path: Path) -> None:
    """Write the fetched daily values without deriving or padding any rows."""

    rows = list(rows)
    fieldnames = ["date"]
    for field in ("open", "high", "low", "close", "volume"):
        if field == "close" or any(row.get(field) is not None for row in rows):
            fieldnames.append(field)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fieldnames} for row in rows)


def drawdown_episodes(rows: list[Mapping[str, object]]) -> list[dict[str, object]]:
    """Return each running-peak drawdown that reaches at least twenty percent."""

    episodes: list[dict[str, object]] = []
    peak_date = ""
    peak_level = 0.0
    episode: dict[str, object] | None = None

    for row in rows:
        row_date = str(row["date"])
        try:
            close = float(row["close"])
        except (KeyError, TypeError, ValueError) as error:
            raise ReconError(f"invalid close on {row_date!r}") from error
        if close <= 0:
            raise ReconError(f"non-positive close on {row_date!r}: {close}")

        if episode is not None and close >= peak_level:
            episode["recovery_date"] = row_date
            episodes.append(episode)
            episode = None
        if not peak_date or close > peak_level:
            peak_date = row_date
            peak_level = close

        drawdown = close / peak_level - 1.0
        if episode is None and drawdown <= -0.20:
            episode = {
                "peak_date": peak_date,
                "peak_level": peak_level,
                "trough_date": row_date,
                "trough_level": close,
                "recovery_date": "not recovered",
            }
        elif episode is not None and close < float(episode["trough_level"]):
            episode["trough_date"] = row_date
            episode["trough_level"] = close

    if episode is not None:
        episodes.append(episode)
    return episodes


def print_summary(
    source: tuple[str, str],
    rows: list[Mapping[str, object]],
) -> None:
    first_date = str(rows[0]["date"])
    last_date = str(rows[-1]["date"])
    years = {date.fromisoformat(str(row["date"])).year for row in rows}
    missing_years = [
        year for year in range(int(first_date[:4]), int(last_date[:4]) + 1)
        if year not in years
    ]

    print(f"source: dataset={source[0]} data_id={source[1]}")
    print(f"first date: {first_date}")
    print(f"last date: {last_date}")
    print(f"row count: {len(rows)}")
    print(
        "calendar-year gaps: "
        + (", ".join(str(year) for year in missing_years) if missing_years else "none")
    )

    episodes = drawdown_episodes(rows)
    print("drawdown episodes (>=20% from running peak):")
    if not episodes:
        print("  none")
        return
    for episode in episodes:
        depth = (
            float(episode["trough_level"]) / float(episode["peak_level"]) - 1.0
        ) * 100.0
        recovery = str(episode["recovery_date"])
        print(
            f"  peak {episode['peak_date']} {float(episode['peak_level']):.2f}; "
            f"trough {episode['trough_date']} {float(episode['trough_level']):.2f}; "
            f"depth {depth:.2f}%; recovery {recovery}"
        )


def main() -> int:
    try:
        source, rows = fetch_best_series()
        write_csv(rows, OUTPUT_PATH)
        print_summary(source, rows)
        print(f"CSV: {OUTPUT_PATH}")
    except ReconError as error:
        print(f"TAIEX RECON FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
