#!/usr/bin/env python
"""Opener-pricing analysis (Phase A): builds empirical outcome tables for
negotiation openers by joining games.jsonl metadata with API results.

Usage:
    python scripts/opener_analysis.py [--max N] [--out FILE]

Produces: opener_outcome_table.json — seller/buyer tables keyed by
opener-ratio buckets: {n, deals, payoff_sum}. Phase B pricing consumes this.
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KEY = None


def api_game(gid):
    import requests
    r = requests.get(f"https://glee-competition.com/api/agent/games/{gid}",
                     headers={"Authorization": f"Bearer {KEY}"}, timeout=10)
    if r.status_code != 200:
        return None
    return r.json()


def load_meta():
    meta = {}
    path = os.path.join(ROOT, "data", "games.jsonl")
    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            s = d.get("s") or {}
            if s.get("game_family") != "negotiation":
                continue
            gid = d.get("t")
            h = s.get("history") or []
            me = d.get("me") or s.get("current_player")
            vk = f"{me}_value"
            if not h or vk not in s:
                continue
            try:
                v = float(s[vk])
            except (TypeError, ValueError):
                continue
            mine = [float(e["offer"]["price"]) for e in h
                    if isinstance(e.get("offer"), dict)
                    and e["offer"].get("from_player") == me
                    and isinstance(e["offer"].get("price"), (int, float))]
            if not mine or v <= 0:
                continue
            g = meta.setdefault(gid, {"maxlen": -1})
            if len(h) >= g["maxlen"]:
                g.update({"role": s.get(f"{me}_role") or "seller",
                          "opener_ratio": round(mine[0] / v, 2),
                          "value": v, "maxlen": len(h)})
    return meta


def main():
    global KEY
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=400,
                    help="max API lookups per run (rate-limit friendly)")
    ap.add_argument("--out", default=os.path.join(
        ROOT, "data", "share", "opener_outcome_table.json"))
    args = ap.parse_args()

    KEY = os.environ.get("GLEE_API_KEY")
    if not KEY:
        envp = os.path.join(ROOT, ".env")
        if os.path.exists(envp):
            for line in open(envp):
                if line.startswith("GLEE_API_KEY="):
                    KEY = line.strip().split("=", 1)[1]
    if not KEY:
        sys.exit("set GLEE_API_KEY")

    # prior runs cache: gid -> result summary (avoid re-querying)
    cache_path = os.path.join(ROOT, "data", "opener_results_cache.json")
    cache = {}
    if os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path))
        except Exception:
            cache = {}

    meta = load_meta()
    todo = [gid for gid in meta if gid not in cache][:args.max]
    print(f"meta games: {len(meta)} | cached results: {len(cache)} | querying: {len(todo)}")

    import requests
    for i, gid in enumerate(todo):
        try:
            r = api_game(gid)
            g = (r or {})
            res = g.get("result") or {}
            if g.get("status") == "completed" and res:
                cache[gid] = {"outcome": res.get("outcome"),
                              "payoff_p1": res.get("player_1_payoff"),
                              "payoff_p2": res.get("player_2_payoff")}
        except Exception:
            pass
        if (i + 1) % 20 == 0:
            json.dump(cache, open(cache_path, "w"))
            time.sleep(2)

    json.dump(cache, open(cache_path, "w"))

    table = {"seller": defaultdict(lambda: [0, 0, 0.0]),
             "buyer": defaultdict(lambda: [0, 0, 0.0])}
    for gid, g in meta.items():
        c = cache.get(gid)
        if not c or "outcome" not in c:
            continue
        role = "seller" if g["role"] == "seller" else "buyer"
        b = min(max(int(g["opener_ratio"] * 5) / 5, 0.2), 4.0) if role == "seller" \
            else min(max(int(g["opener_ratio"] * 10) / 10, 0.2), 0.9)
        pay = float(c.get("payoff_p1" if role == "seller" else "payoff_p2") or 0)
        t = table[role][b]
        t[0] += 1
        t[2] += pay
        if c.get("outcome") == "agreement":
            t[1] += 1

    out = {r: {str(b): {"n": v[0], "deals": v[1], "payoff_sum": round(v[2], 2)}
               for b, v in sorted(table[r].items())} for r in ("seller", "buyer")}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(out, open(args.out, "w"), indent=1)
    print(f"wrote {args.out}")
    for role in ("seller", "buyer"):
        print(f"{role}:")
        for b, v in sorted(table[role].items(), key=lambda x: float(x[0])):
            n, nd, sp = v
            print(f"  {b:>4.1f}: n={n:3d} deal={nd/max(1,n):.2f} avg_payoff={sp/max(1,n):>12,.0f}")


if __name__ == "__main__":
    main()
