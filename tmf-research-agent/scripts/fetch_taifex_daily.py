"""Pull TAIFEX daily futures quotes straight from the exchange's own download.

The stored tick archive covers under a year, which is not enough to say
anything about horizons measured in weeks or months — the momentum result
this is meant to test is documented over one to twelve months. Daily bars go
back years and are published free, so the horizon question is answerable from
public data rather than from an archive that cannot be extended.

The endpoint takes queryStartDate and queryEndDate but silently returns an
error page past about a month, so this walks month by month rather than day
by day — a year costs 12 requests instead of 250. Stdlib only, matching the
rest of the sidecar, and paced between requests: this is a public service
being asked for bulk history.
"""
from __future__ import annotations

import calendar
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://www.taifex.com.tw/cht/3/futDataDown"
SESSION_COLUMN = "交易時段"
REGULAR = "一般"


def fetch_range(product: str, start: str, end: str) -> list[dict[str, str]]:
    payload = urllib.parse.urlencode({
        "down_type": "1",
        "commodity_id": product,
        "queryStartDate": start.replace("-", "/"),
        "queryEndDate": end.replace("-", "/"),
    }).encode()
    request = urllib.request.Request(
        ENDPOINT, data=payload, headers={"User-Agent": "tmf-research/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        text = response.read().decode("big5-hkscs", errors="replace")
    rows = list(csv.DictReader(line for line in text.splitlines() if line.strip()))
    return [row for row in rows if row.get("交易日期")]


def _number(row: dict[str, str], column: str) -> float | None:
    value = (row.get(column) or "").strip().replace(",", "")
    if not value or value in {"-", "－"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def nearest_month_bars(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    """One bar per trading date: the regular session of the nearest expiry.

    Each date lists every listed expiry and both sessions. The near contract is
    the one research follows, and taking the smallest expiry code present on
    that date rolls at the same point the exchange stops listing it.
    """

    by_date: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if (row.get(SESSION_COLUMN) or "").strip() != REGULAR:
            continue
        by_date.setdefault(row["交易日期"].strip().replace("/", "-"), []).append(row)

    bars: list[dict[str, object]] = []
    for day in sorted(by_date):
        # Weekly contracts carry a W suffix; the plain monthly code sorts first
        # and is the liquid one.
        candidates = sorted(by_date[day], key=lambda row: row["到期月份(週別)"].strip())
        for row in candidates:
            values = {
                name: _number(row, column)
                for name, column in (
                    ("open", "開盤價"), ("high", "最高價"),
                    ("low", "最低價"), ("close", "收盤價"),
                )
            }
            volume = _number(row, "成交量")
            if any(value is None or value <= 0 for value in values.values()):
                continue
            bars.append({
                "trading_date": day,
                "contract": row["到期月份(週別)"].strip(),
                **values,
                "volume": 0.0 if volume is None else volume,
            })
            break
    return bars


def main(product: str, first_year: int, last_year: int, out: Path) -> int:
    collected: list[dict[str, str]] = []
    for year in range(first_year, last_year + 1):
        yearly = 0
        for month in range(1, 13):
            last_day = calendar.monthrange(year, month)[1]
            start = f"{year}-{month:02d}-01"
            end = f"{year}-{month:02d}-{last_day:02d}"
            try:
                rows = fetch_range(product, start, end)
            except urllib.error.URLError as error:
                print(f"{start}: 取得失敗 {error}", file=sys.stderr)
                return 1
            collected.extend(rows)
            yearly += len(rows)
            time.sleep(1.5)
        print(f"  {year}: {yearly} 列", flush=True)

    bars = nearest_month_bars(collected)
    out.write_text(
        "\n".join(json.dumps(bar, ensure_ascii=False) for bar in bars) + "\n",
        encoding="utf-8",
    )
    if bars:
        print(f"\n{len(bars)} 個交易日  {bars[0]['trading_date']} .. {bars[-1]['trading_date']}")
        print(f"寫入 {out}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("用法: fetch_taifex_daily.py <商品> <起始年> <結束年> <輸出檔>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(
        sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]),
    ))
