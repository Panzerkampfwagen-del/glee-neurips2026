#!/bin/bash
# Live-run supervisor: waits out crash-loop cooldowns, relaunches forever.
# Sessions are bounded by agent.py --max-time so code updates get picked up.
# Survives terminal exit (use setsid).
cd "$(dirname "$0")/.."
LOG=${1:-/tmp/opencode/live_supervised.log}
while true; do
  echo "[$(date -Is)] launching agent" >> "$LOG"
  set -a; [ -f .env ] && . ./.env; set +a
  # E2 live A/B (deadline Aug 29): alternate the bargaining opp_model arm
  # every session so hourly rating deltas are paired by time of day.
  # arm file is authoritative; analysis joins hourly_status.jsonl + these lines.
  ARM_FILE=/tmp/glee_ab_arm
  CUR=$(cat "$ARM_FILE" 2>/dev/null || echo off)
  if [ "$CUR" = "opp_model" ]; then NEXT=off; else NEXT=opp_model; fi
  echo "$NEXT" > "$ARM_FILE"
  if [ "$NEXT" = "opp_model" ]; then export GLEE_ABLATE=opp_model; else unset GLEE_ABLATE; fi
  echo "[$(date -Is)] arm=$NEXT" >> "$LOG"
  /home/aryan/glee-comp/.venv/bin/python agent.py --concurrency 8 --max-time 1800 \
    >> "$LOG" 2>&1
  echo "[$(date -Is)] agent exited code=$?" >> "$LOG"
  if tail -5 "$LOG" | grep -q "timed out"; then
    echo "[$(date -Is)] 403 cooldown detected, sleeping 300s" >> "$LOG"
    sleep 300
  else
    sleep 20
  fi
done
