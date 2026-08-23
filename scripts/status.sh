#!/bin/bash
# Quick ops status: ratings + recent game outcomes + error count.
echo "=== $(date -u -Is) ==="
curl -s -H "Authorization: Bearer ${GLEE_API_KEY:?set GLEE_API_KEY}" \
  https://glee-competition.com/api/agent/stats | python3 -m json.tool
echo "=== last results ==="
grep -oE "'player_[12]_payoff': [-0-9.]+" /tmp/opencode/live_supervised.log | tail -12
echo "=== errors (last 1000 lines) ==="
tail -1000 /tmp/opencode/live_supervised.log | grep -c ERROR
