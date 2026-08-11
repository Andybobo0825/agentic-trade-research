#!/bin/sh
# Live TMF day-session collection: TAIFEX day session runs 08:45-13:45
# Taipei time on trading weekdays. Triggered a few minutes early, exits a
# minute after the close to catch the closing-auction tail.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SJ_API_KEY="$(sed -n 's/^SJ_API_KEY=//p' ../.env | tail -1)"
SJ_SEC_KEY="$(sed -n 's/^SJ_SEC_KEY=//p' ../.env | tail -1)"
export SJ_API_KEY SJ_SEC_KEY
UNTIL="$(date +%Y-%m-%d)T13:46:00+08:00"
mkdir -p logs
{
    echo "=== day-session collect $(date '+%Y-%m-%d %H:%M:%S') until ${UNTIL} ==="
    PYTHONPATH=src .venv/bin/python -m tmf_research.cli collect --until "$UNTIL"
} >> logs/day-session-collect.log 2>&1
