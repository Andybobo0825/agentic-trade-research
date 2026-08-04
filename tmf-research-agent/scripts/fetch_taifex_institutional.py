"""Pull the daily institutional futures positions TAIFEX publishes.

Every signal tested so far has been derived from price and the order book,
and all of them failed: intraday direction lost to the spread, basis turned
out to be a weaker restatement of price level, and daily momentum lost to
buying and holding. Institutional positioning is the one remaining input of a
genuinely different kind — who is holding what, rather than where the price
has been — and it is published free, daily, going back years.

Same shape as the daily quote fetcher: the endpoint caps a query at about a
month, so this walks month by month, paced between requests.

The figures publish after the close, so the reader must lag them by at least
one trading day before using them against that day's session. This script
only records the date the exchange assigned; enforcing the lag belongs to
whatever consumes the file.
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

ENDPOINT = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
PRODUCT = "臺股期貨"
# The exchange labels the three institution types in full; short keys keep the
# stored rows readable without translating them into something they are not.
PARTIES = {
    "自營商": "dealer",
    "投信": "trust",
    "外資及陸資": "foreign",
}
NET_OPEN_LOTS = "多空未平倉口數淨額"
NET_TRADE_LOTS = "多空交易口數淨額"


def fetch_month(year: int, month: int) -> list[dict[str, str]]:
    last_day = calendar.monthrange(year, month)[1]
    payload = urllib.parse.urlencode({
        "queryStartDate": f"{year}/{month:02d}/01",
        "queryEndDate": f"{year}/{month:02d}/{last_day:02d}",
    }).encode()
    request = urllib.request.Request(
        ENDPOINT, data=payload, headers={"User-Agent": "tmf-research/1.0"},
    )
    # A 429 here already cost this project a multi-day block. Retrying after
    # one is what earned it, so a refusal ends the run and the caller keeps
    # whatever it had; waiting hours and starting again is the only recovery.
    with urllib.request.urlopen(request, timeout=60) as response:
        text = response.read().decode("big5-hkscs", errors="replace")
    # Dates beyond the roughly three years this endpoint serves come back as an
    # HTML error page under a 200. Parsed as CSV that yields rows which survive
    # every later filter as "no data", so the shortfall has to be caught here.
    if text.lstrip()[:1] == "<":
        raise ValueError(f"{year}-{month:02d}: 回應不是 CSV,該期間無資料")
    return list(csv.DictReader(line for line in text.splitlines() if line.strip()))


def _lots(row: dict[str, str], column: str) -> int | None:
    value = (row.get(column) or "").strip().replace(",", "")
    if not value or value in {"-", "－"}:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def daily_positions(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    """One record per trading date, with each party's net position in lots."""

    by_date: dict[str, dict[str, object]] = {}
    for row in rows:
        if (row.get("商品名稱") or "").strip() != PRODUCT:
            continue
        party = PARTIES.get((row.get("身份別") or "").strip())
        if party is None:
            continue
        day = (row.get("日期") or "").strip().replace("/", "-")
        if not day:
            continue
        net_open = _lots(row, NET_OPEN_LOTS)
        net_trade = _lots(row, NET_TRADE_LOTS)
        if net_open is None or net_trade is None:
            continue
        record = by_date.setdefault(day, {"trading_date": day})
        record[f"{party}_open"] = net_open
        record[f"{party}_trade"] = net_trade

    complete = [f"{party}_{field}" for party in PARTIES.values() for field in ("open", "trade")]
    return [
        record for _day, record in sorted(by_date.items())
        if all(key in record for key in complete)
    ]


def main(first_year: int, last_year: int, out: Path) -> int:
    collected: list[dict[str, str]] = []
    stopped = False
    for year in range(first_year, last_year + 1):
        if stopped:
            break
        yearly = 0
        for month in range(1, 13):
            try:
                rows = fetch_month(year, month)
            except urllib.error.URLError as error:
                # Whatever arrived before this is still worth writing out, so
                # a refusal halfway through does not throw away the hours the
                # pacing cost.
                print(f"{year}-{month:02d}: 中止 {error}", file=sys.stderr)
                stopped = True
                break
            collected.extend(rows)
            yearly += len(rows)
            time.sleep(10.0)
        print(f"  {year}: {yearly} 列", flush=True)

    records = daily_positions(collected)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    if records:
        print(
            f"\n{len(records)} 個交易日  "
            f"{records[0]['trading_date']} .. {records[-1]['trading_date']}"
        )
        print(f"寫入 {out}")
    return 1 if stopped else 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("用法: fetch_taifex_institutional.py <起始年> <結束年> <輸出檔>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(int(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])))
