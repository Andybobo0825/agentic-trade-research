#!/usr/bin/env bash
# Reclaim space on the collector Mac, whose disk holds roughly 70 trading days
# of live data before it fills and collection starts failing.
#
# A remote segment is deleted only after the local copy is confirmed byte
# identical to its catalog checksum, so the main Mac always holds a verified
# copy first. Recent days are kept on the collector as a rolling second copy.
#
# Dry run by default; pass --apply to actually delete.
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE_HOST="wei@100.81.136.85"
REMOTE_ROOT="/Users/wei/agentic-trade-research-main/tmf-research-agent/data"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
APPLY=""
[ "${1:-}" = "--apply" ] && APPLY=1

LIST="$(mktemp)"
trap 'rm -f "$LIST"' EXIT

python3 - "$RETAIN_DAYS" "$LIST" <<'PY'
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

retain_days, list_path = int(sys.argv[1]), Path(sys.argv[2])
root = Path("data")
cutoff = (date.today() - timedelta(days=retain_days)).isoformat()

records = [
    json.loads(line)
    for line in (root / "manifest.ndjson").read_text(encoding="utf-8").splitlines()
    if line.strip()
]

verified, unverified, skipped = [], [], 0
for record in records:
    if record["event_type"] not in ("live-tick", "live-bidask"):
        continue
    _prefix, separator, suffix = record["segment_id"].rpartition("TMFR1-")
    parts = suffix.split("-") if separator else []
    if len(parts) < 3 or not parts[0].isdigit():
        continue
    if "-".join(parts[:3]) >= cutoff:
        skipped += 1
        continue

    path = root / record["relative_path"]
    if not path.is_file():
        unverified.append(f"{record['segment_id']} (本機沒有這個檔案)")
        continue
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["checksum_sha256"]:
        unverified.append(f"{record['segment_id']} (checksum 不符)")
        continue
    verified.append(record["relative_path"])

list_path.write_text("\n".join(verified), encoding="utf-8")
print(f"保留天數 {retain_days} 天,{cutoff} 之後的 {skipped} 個 segment 保留在收集機")
print(f"已在本機驗證、可從收集機刪除: {len(verified)}")
if unverified:
    print(f"⚠️  {len(unverified)} 個無法驗證,一律不刪除:")
    for entry in unverified[:10]:
        print(f"    {entry}")
PY

COUNT="$(grep -c . "$LIST" || true)"
if [ "$COUNT" -eq 0 ]; then
    echo "沒有可刪除的項目"
    exit 0
fi

if [ -z "$APPLY" ]; then
    echo "（乾跑,未刪除任何東西。確認無誤後執行: ./scripts/prune-collector.sh --apply）"
    exit 0
fi

REMOTE_SIZE_BEFORE="$(ssh "$REMOTE_HOST" "du -sh $REMOTE_ROOT | cut -f1")"
< "$LIST" ssh "$REMOTE_HOST" "cd $REMOTE_ROOT && xargs -I{} rm -f {}"
REMOTE_SIZE_AFTER="$(ssh "$REMOTE_HOST" "du -sh $REMOTE_ROOT | cut -f1")"
echo "已從收集機刪除 $COUNT 個已驗證的 segment（$REMOTE_SIZE_BEFORE -> $REMOTE_SIZE_AFTER）"
