#!/usr/bin/env bash
# On-demand pull of collected raw data from the collector Mac over Tailscale.
# Brings Tailscale up if it is stopped, pulls straight into the repo's raw
# store, and merges the new catalog entries. Segments are create-once, so the
# pull is additive and safe to re-run; the collector Mac keeps its own copy as
# the authoritative store and nothing is deleted there.
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE_HOST="wei@100.81.136.85"
REMOTE_ROOT="/Users/wei/agentic-trade-research-main/tmf-research-agent/data"
LOCAL_ROOT="data"

if ! tailscale status >/dev/null 2>&1; then
    echo "Tailscale 未啟動,正在連線..."
    tailscale up
    for _ in $(seq 1 15); do
        tailscale status >/dev/null 2>&1 && break
        sleep 1
    done
fi

if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$REMOTE_HOST" true 2>/dev/null; then
    echo "無法連線到收集機 ($REMOTE_HOST):請確認該台已開機且在 Tailscale 網路上" >&2
    exit 1
fi

# Pull whatever event types the collector actually has rather than a fixed
# list: the weekly backfill writes historical-tick, and hardcoding the two
# live types left its catalog entries pointing at files that never arrived.
for event_type in $(ssh "$REMOTE_HOST" "ls -1 $REMOTE_ROOT/datasets/dataset-v1/segments"); do
    mkdir -p "$LOCAL_ROOT/datasets/dataset-v1/segments/$event_type"
    rsync -az --ignore-existing \
        "$REMOTE_HOST:$REMOTE_ROOT/datasets/dataset-v1/segments/$event_type/" \
        "$LOCAL_ROOT/datasets/dataset-v1/segments/$event_type/"
done

REMOTE_MANIFEST="$(mktemp)"
trap 'rm -f "$REMOTE_MANIFEST"' EXIT
rsync -az "$REMOTE_HOST:$REMOTE_ROOT/manifest.ndjson" "$REMOTE_MANIFEST"

python3 - "$REMOTE_MANIFEST" "$LOCAL_ROOT/manifest.ndjson" <<'PY'
import json
import sys
from pathlib import Path

source_path, local_path = sys.argv[1], Path(sys.argv[2])

existing_ids = set()
if local_path.exists():
    with local_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                existing_ids.add(json.loads(line)["segment_id"])

added = 0
with open(source_path, encoding="utf-8") as f, local_path.open("a", encoding="utf-8") as out:
    for line in f:
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if record["segment_id"] in existing_ids:
            continue
        existing_ids.add(record["segment_id"])
        out.write(line + "\n")
        added += 1

print(f"新增 {added} 筆目錄項目")
PY

exec ./scripts/data-health.sh
