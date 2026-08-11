#!/bin/sh
# Weekly TMFR1 tick harvest. Shioaji keeps only ~2-3 weeks of history, so a
# missed week is data lost forever; the window overlaps the previous run and
# the append-only store deduplicates by event id.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SJ_API_KEY="$(sed -n 's/^SJ_API_KEY=//p' ../.env | tail -1)"
SJ_SEC_KEY="$(sed -n 's/^SJ_SEC_KEY=//p' ../.env | tail -1)"
export SJ_API_KEY SJ_SEC_KEY
START="$(date -v-20d +%Y-%m-%d)"
END="$(date -v-1d +%Y-%m-%d)"
mkdir -p logs
{
    echo "=== weekly backfill $(date '+%Y-%m-%d %H:%M:%S') range ${START}..${END} ==="
    PYTHONPATH=src .venv/bin/python -m tmf_research.cli backfill \
        --start "$START" --end "$END"
} >> logs/weekly-backfill.log 2>&1
