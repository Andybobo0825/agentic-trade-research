#!/bin/sh
# Weekly historical backfill on an interval trigger.
#
# StartCalendarInterval fires 15 hours late on this machine (verified: a 06:00
# Sunday trigger ran at 21:00, the same skew seen on the collection jobs), so
# the weekly cadence is kept here instead: an hourly tick that runs the harvest
# only once its stamp is a week old. Shioaji keeps roughly 2-3 weeks of tick
# history, so a run that slips a few hours costs nothing but a missed week is
# lost forever.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
STAMP="logs/.backfill-stamp"

# Never compete with a live session for the same Shioaji credentials.
if pgrep -f "tmf_research.cli collect" >/dev/null 2>&1; then
    exit 0
fi

if [ -f "$STAMP" ] && [ -n "$(find "$STAMP" -mtime -6 2>/dev/null)" ]; then
    exit 0
fi

SJ_API_KEY="$(sed -n 's/^SJ_API_KEY=//p' ../.env | tail -1)"
SJ_SEC_KEY="$(sed -n 's/^SJ_SEC_KEY=//p' ../.env | tail -1)"
export SJ_API_KEY SJ_SEC_KEY
START="$(date -v-20d +%Y-%m-%d)"
END="$(date -v-1d +%Y-%m-%d)"

{
    echo "=== weekly backfill $(date '+%Y-%m-%d %H:%M:%S %Z') range ${START}..${END} ==="
    PYTHONPATH=src .venv/bin/python -m tmf_research.cli backfill --start "$START" --end "$END"
} >> logs/weekly-backfill.log 2>&1

touch "$STAMP"
