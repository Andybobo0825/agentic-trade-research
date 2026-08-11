#!/bin/sh
# Live TMF night-session collection: TAIFEX night session runs 15:00 on a
# trading weekday through 05:00 the next calendar day. TAIFEX has no Friday
# night session (no Saturday day session follows it), so this is only
# scheduled Monday-Thursday.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SJ_API_KEY="$(sed -n 's/^SJ_API_KEY=//p' ../.env | tail -1)"
SJ_SEC_KEY="$(sed -n 's/^SJ_SEC_KEY=//p' ../.env | tail -1)"
export SJ_API_KEY SJ_SEC_KEY
UNTIL="$(date -v+1d +%Y-%m-%d)T05:01:00+08:00"
mkdir -p logs
{
    echo "=== night-session collect $(date '+%Y-%m-%d %H:%M:%S') until ${UNTIL} ==="
    PYTHONPATH=src .venv/bin/python -m tmf_research.cli collect --until "$UNTIL"
} >> logs/night-session-collect.log 2>&1
