#!/usr/bin/env bash
# Audit the collected raw store for the holes that silently cost training days:
# a trading date with no session, a session that started late or ended early,
# a mid-session dropout, and catalog entries whose segment file never arrived.
# Run after syncing; sync-data.sh calls it automatically.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - "${1:-data}" <<'PY'
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

# Collection reached its production shape on 2026-07-23; the two earlier days
# are the manual bring-up and are shown but not flagged, so the warning list
# only ever carries problems that are still actionable.
AUDIT_FROM = "2026-07-23"

root = Path(sys.argv[1])
records = [
    json.loads(line)
    for line in (root / "manifest.ndjson").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
live = [r for r in records if r["event_type"] in ("live-tick", "live-bidask")]
absent = [r for r in live if not (root / r["relative_path"]).is_file()]

sessions = defaultdict(list)
unresolved = 0
for record in live:
    _prefix, separator, suffix = record["segment_id"].rpartition("TMFR1-")
    parts = suffix.split("-") if separator else []
    if len(parts) < 4 or not parts[0].isdigit():
        unresolved += 1
        continue
    sessions[("-".join(parts[:3]), parts[3])].append(record)

def when(value: str) -> datetime:
    return datetime.fromisoformat(value)

problems: list[str] = []
rows: list[tuple[str, str, int, str, str, str]] = []

for key in sorted(sessions):
    trading_date, session = key
    segments = sorted(sessions[key], key=lambda r: r["minimum_event_time"])
    first, last = when(segments[0]["minimum_event_time"]), when(segments[-1]["maximum_event_time"])
    count = sum(r["record_count"] for r in segments)

    quotes = sorted(
        (r for r in segments if r["event_type"] == "live-bidask"),
        key=lambda r: r["minimum_event_time"],
    )
    holes = [
        (a["maximum_event_time"], b["minimum_event_time"])
        for a, b in zip(quotes, quotes[1:])
        if (when(b["minimum_event_time"]) - when(a["maximum_event_time"])).total_seconds() > 60
    ]

    if session == "DAY":
        late, early = first.strftime("%H:%M") > "08:46", last.strftime("%H:%M") < "13:44"
    else:
        late, early = first.strftime("%H:%M") > "15:01", last.strftime("%H:%M") < "04:59"

    flags = []
    if late:
        flags.append(f"開始過晚 {first:%H:%M}")
    if early:
        flags.append(f"提早結束 {last:%H:%M}")
    if holes:
        flags.append(f"中斷 {len(holes)} 次")
    rows.append((
        trading_date, session, count,
        f"{first:%m-%d %H:%M}", f"{last:%m-%d %H:%M}",
        "、".join(flags) if flags else "完整",
    ))
    if flags and trading_date >= AUDIT_FROM:
        problems.append(f"  {trading_date} {session}: {'、'.join(flags)}")
        for hole in holes[:3]:
            problems.append(f"    中斷: {hole[0]} -> {hole[1]}")

print(f"\n即時 segment 總數 {len(live)}   目錄缺檔 {len(absent)}   盤前/收盤外 {unresolved}")
print(f"{'交易日':<12}{'時段':<7}{'筆數':>9}  {'起':<12}{'迄':<12}狀態")
for trading_date, session, count, first, last, status in rows:
    print(f"{trading_date:<12}{session:<7}{count:>9,}  {first:<12}{last:<12}{status}")

covered = {d for d, _ in sessions}
today = date.today()
if covered:
    cursor, finish = date.fromisoformat(AUDIT_FROM), min(date.fromisoformat(max(covered)), today)
    blank, half = [], []
    while cursor <= finish:
        stamp = cursor.isoformat()
        if cursor.weekday() < 5:
            present = {s for d, s in sessions if d == stamp}
            if not present:
                blank.append(stamp)
            elif present != {"DAY", "NIGHT"}:
                half.append(f"{stamp} 只有 {'/'.join(sorted(present))}")
        cursor += timedelta(days=1)
    if blank:
        problems.append(f"  完全沒有資料的平日: {', '.join(blank)}（可能是休市日,需人工確認）")
    for entry in half:
        problems.append(f"  缺少半個交易日: {entry}")

if absent:
    problems.append(f"  {len(absent)} 筆目錄項目找不到對應檔案（同步未完成,重跑一次即可）")

# The Phase 5 build needs a trading date in the calendar before it will accept
# that day's live data, and the calendar is derived from the weekly historical
# backfill — so it lags live collection and silently drops the newest days.
calendar_path = next(
    (p for p in (root / "calendar-v2.json", root / "calendar.json") if p.is_file()),
    None,
)
if calendar_path is not None and covered:
    calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
    entries = calendar.get("days", calendar) if isinstance(calendar, dict) else calendar
    calendar_days = {
        entry["trading_date"] if isinstance(entry, dict) else entry for entry in entries
    }
    uncovered = sorted(
        day for day in covered
        if day >= AUDIT_FROM and day <= today.isoformat() and day not in calendar_days
    )
    if uncovered:
        problems.append(
            f"  行事曆未涵蓋 {len(uncovered)} 個已收集交易日 "
            f"({uncovered[0]}..{uncovered[-1]})，Phase 5 會靜默拒絕這些天"
        )
        problems.append(
            "    修法: 在收集機執行 backfill 後重建行事曆 "
            "(tmf build-calendar --data-root data --out data/calendar-v2.json)"
        )

if problems:
    print("\n⚠️  需要注意:")
    for line in problems:
        print(line)
    sys.exit(1)

print("\n✅ 無資料缺口")
PY
