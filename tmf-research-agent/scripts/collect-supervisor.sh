#!/bin/sh
# Session-aware collection supervisor.
#
# launchd's StartCalendarInterval fires in a stale cached timezone on this
# machine (verified: an 08:44 trigger fired at 23:44, a consistent +15h skew),
# so calendar triggers cannot be trusted. This runs on a plain StartInterval
# tick instead, which carries no timezone, and decides from the system clock
# whether a TAIFEX session is open right now.
#
# The collector runs in the foreground: launchd skips a tick while the job is
# still alive, so one collector runs per session. If it ever dies mid-session
# the next tick restarts it with the same session end, bounding any hole to
# one tick rather than losing the rest of the session.
#
# TAIFEX day session 08:45-13:45, night session 15:00-05:00 the next calendar
# day, Monday through Friday. Night sessions settle into the following
# trading date, so a Friday night runs into Saturday morning.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="logs/collect-supervisor.log"

# One FLUSHED line per segment is ~5MB a day, so keep one rolled generation
# rather than letting the log grow without bound on the collector's disk.
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 52428800 ]; then
    mv "$LOG" "$LOG.1"
fi

if pgrep -f "tmf_research.cli collect" >/dev/null 2>&1; then
    exit 0
fi

DOW="$(date +%u)"
NOW="$((10#$(date +%H%M)))"
SESSION=""
UNTIL=""

if [ "$DOW" -le 5 ] && [ "$NOW" -ge 844 ] && [ "$NOW" -lt 1346 ]; then
    SESSION="DAY"
    UNTIL="$(date +%Y-%m-%d)T13:46:00+08:00"
elif [ "$DOW" -le 5 ] && [ "$NOW" -ge 1458 ]; then
    SESSION="NIGHT"
    UNTIL="$(date -v+1d +%Y-%m-%d)T05:01:00+08:00"
elif [ "$DOW" -ge 2 ] && [ "$DOW" -le 6 ] && [ "$NOW" -lt 501 ]; then
    SESSION="NIGHT"
    UNTIL="$(date +%Y-%m-%d)T05:01:00+08:00"
fi

if [ -z "$SESSION" ]; then
    exit 0
fi

SJ_API_KEY="$(sed -n 's/^SJ_API_KEY=//p' ../.env | tail -1)"
SJ_SEC_KEY="$(sed -n 's/^SJ_SEC_KEY=//p' ../.env | tail -1)"
export SJ_API_KEY SJ_SEC_KEY

{
    echo "=== ${SESSION} collect $(date '+%Y-%m-%d %H:%M:%S %Z') until ${UNTIL} ==="
    if PYTHONPATH=src .venv/bin/python -m tmf_research.cli collect --until "$UNTIL"; then
        :
    else
        echo "!!! collector exited non-zero at $(date '+%Y-%m-%d %H:%M:%S')"
    fi
} >> "$LOG" 2>&1

if tail -20 "$LOG" | grep -q "stored_records=0 "; then
    echo "!!! WARNING ${SESSION} session $(date '+%Y-%m-%d') stored no records" >> "$LOG"
fi
