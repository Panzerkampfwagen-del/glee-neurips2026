#!/bin/bash
# Hourly health snapshot for post-hoc review by either agent.
cd "$(dirname "$0")/.." || exit 1
mkdir -p data/logs
OUT=data/logs/hourly_status.jsonl
KEY=$(grep '^GLEE_API_KEY=' .env | cut -d= -f2)
STATS=$(curl -s --max-time 10 -H "Authorization: Bearer $KEY" \
  https://glee-competition.com/api/agent/stats)
ERR=$(tail -2000 data/logs/live.log 2>/dev/null | grep -c ERROR)
SIM=$(grep -ac 'sim-rank' data/logs/live.log 2>/dev/null)
ALIVE=$(pgrep -fc 'agent.py --conc')
python3 - "$OUT" "$STATS" "$ERR" "$SIM" "$ALIVE" <<'PY'
import json, sys, datetime
out, stats, err, sim, alive = sys.argv[1:6]
try:
    s = json.loads(stats)
    scores = {k: {"r": v["rating"], "g": v["games_played"]} for k, v in s.get("scores", {}).items()}
    active = s.get("active_games")
except Exception:
    scores, active = {}, None
rec = {"t": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
       "scores": scores, "active": active, "errors_recent": int(err or 0),
       "sim_ranks": int(sim or 0), "agent_alive": int(alive or 0)}
with open(out, "a") as f:
    f.write(json.dumps(rec) + "\n")
PY
