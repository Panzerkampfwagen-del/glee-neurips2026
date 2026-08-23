#!/bin/bash
# Live-run supervisor: waits out crash-loop cooldowns, relaunches forever.
# Sessions are bounded by agent.py --max-time so code updates get picked up.
# Survives terminal exit (use setsid).
cd "$(dirname "$0")/.."
LOG=${1:-/tmp/opencode/live_supervised.log}
while true; do
  echo "[$(date -Is)] launching agent" >> "$LOG"
  GLEE_API_KEY=***REMOVED*** \
    /home/aryan/glee-comp/.venv/bin/python agent.py --concurrency 6 --max-time 3600 \
    >> "$LOG" 2>&1
  echo "[$(date -Is)] agent exited code=$?" >> "$LOG"
  if tail -5 "$LOG" | grep -q "timed out"; then
    echo "[$(date -Is)] cooldown detected, sleeping 180s" >> "$LOG"
    sleep 180
  else
    sleep 20
  fi
done
