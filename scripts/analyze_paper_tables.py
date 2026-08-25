"""Paper tables T1/T3/T4 + provenance extraction from Agent A(2)'s data-share.

Outputs markdown tables into stdout; results pasted into docs/09_table_results.md.
Honest-limitation notes embedded where data does not support a claim.
"""

import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

SHARE = Path("data/share")
F6_MARKER = datetime.fromisoformat("2026-08-24T14:00:00+07:00")
GEN2_IDX = 1


def load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def t1_rating_trajectory():
    print("## T1 — Rating trajectory\n")
    data = json.loads((SHARE / "stats_snapshots.json").read_text(encoding="utf-8"))
    snaps = data["snapshots"]
    print("| time | note | fam | displayed | games | raw* |")
    print("|---|---|---|---|---|---|")
    for s in snaps:
        for fam in ("bargaining", "negotiation", "persuasion"):
            d = s[fam]
            raw = d["r"] * (d["g"] + 30) / d["g"]
            print(f"| {s['t'][:16]} | {s.get('note','')} | {fam} | {d['r']:.1f} | {d['g']} | {raw:.1f} |")
    print("\n(*raw reconstructed from shrink formula r_disp*(g+30)/g)\n")

    def ols(xs, ys):
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / max(
            sum((x - mx) ** 2 for x in xs), 1e-9)
        return b

    print("### Piecewise slope, displayed rating vs games (rating points / 100 games)\n")
    print("| family | pre-gen2 slope | post-gen2 slope | ratio |")
    print("|---|---|---|---|")
    for fam in ("bargaining", "negotiation", "persuasion"):
        gs = [s[fam]["g"] for s in snaps]
        rs = [s[fam]["r"] for s in snaps]
        pre = ols(gs[:GEN2_IDX + 1], rs[:GEN2_IDX + 1])
        post = ols(gs[GEN2_IDX:], rs[GEN2_IDX:])
        ratio = post / pre if abs(pre) > 1e-9 else float("inf")
        print(f"| {fam} | {pre*100:+.1f} | {post*100:+.1f} | {ratio:+.2f}x |")
    print()


def parse_finished():
    """Parse finished_results.txt into records with timestamps."""
    pat = re.compile(
        r"^(\S+ \S+) INFO glee_sdk Game (\S+) finished! Result: (.*)$")
    out = []
    for line in (SHARE / "finished_results.txt").read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f").replace(
            tzinfo=F6_MARKER.tzinfo)
        try:
            res = eval(m.group(3))  # trusted local share file
        except Exception:
            continue
        out.append({"ts": ts, "gid": m.group(2), "res": res})
    return out


def family_of(res):
    if "rounds_bought" in res:
        return "persuasion"
    if "agreed_price" in res:
        return "negotiation"
    if "agreed_player_1_gain" in res:
        return "bargaining"
    return None


def t3_f6_prepost(recs):
    print("## T3 — Persuasion buyer payoffs pre/post F6 (marker 2026-08-24 14:00+07)\n")
    pre_h, post_h = [], []
    pre_l, post_l = [], []
    for r in recs:
        res = r["res"]
        if family_of(res) != "persuasion":
            continue
        bucket_h, bucket_l = (pre_h, pre_l) if r["ts"] < F6_MARKER else (post_h, post_l)
        bucket_h.append(res.get("bought_high", 0))
        bucket_l.append(res.get("bought_low", 0))

    def summarize(name, hs, ls):
        n = len(hs)
        if n == 0:
            print(f"- {name}: no games in window")
            return
        tot_h, tot_l = sum(hs), sum(ls)
        hi_rate = tot_h / max(tot_h + tot_l, 1)
        lemon_rate = tot_l / max(tot_h + tot_l, 1)
        print(f"- {name}: n={n} games, purchases={tot_h+tot_l}, "
              f"high-rate={hi_rate:.2%}, lemon-rate={lemon_rate:.2%}")

    summarize("PRE  (< marker)", pre_h, pre_l)
    summarize("POST (>= marker)", post_h, post_l)
    print("\nNOTE: finished-results lines do not record WHICH player we were;"
          "\nbuyer-payoff attribution needs games.jsonl roles (blocker filed).\n")


def t4_negotiation_outcomes(recs):
    print("## T4 — Negotiation outcomes from finished-log\n")
    agr, nd = 0, 0
    rounds_to_agree = []
    for r in recs:
        res = r["res"]
        if family_of(res) != "negotiation":
            continue
        if res.get("outcome") == "no_deal":
            nd += 1
        elif "agreed_price" in res:
            agr += 1
            if res.get("agreed_round"):
                rounds_to_agree.append(res["agreed_round"])
    tot = agr + nd
    print(f"- n={tot} negotiation games: agreements={agr} ({agr/tot:.0%}), "
          f"no-deal={nd} ({nd/tot:.0%})")
    if rounds_to_agree:
        rounds_to_agree.sort()
        mid = rounds_to_agree[len(rounds_to_agree)//2]
        print(f"- median rounds to agreement: {mid}")
    print()


def jsonl_role_analysis():
    print("## Recent-era per-role stats (games_recent.jsonl)\n")
    rows = load_jsonl(SHARE / "games_recent.jsonl")
    fam_count = {}
    barg_deals = 0
    barg_total = 0
    neg_margins = []
    pers_games = 0
    pers_lemons_bought = 0
    pers_purchases = 0
    for row in rows:
        st = row.get("s", {})
        a = row.get("a", {})
        fam = st.get("game_family", "?")
        fam_count[fam] = fam_count.get(fam, 0) + 1
        if fam == "negotiation":
            me = "player_1" if f"{chr(112)}layer_1_value" in st else (
                "player_2" if "player_2_value" in st else None)
            if me and "product_price" in a:
                v = float(st[f"{me}_value"])
                p = float(a["product_price"])
                if me.startswith("player_1"):
                    neg_margins.append((p - v) / max(p, 1e-9))
                else:
                    neg_margins.append((v - p) / max(v, 1e-9))
        elif fam == "persuasion":
            hist = st.get("history") or []
            if any(h.get("bought") for h in hist):
                pers_games += 1
            for h in hist:
                if h.get("bought"):
                    pers_purchases += 1
                    if h.get("quality") == "low":
                        pers_lemons_bought += 1
    print(f"- games in recent window: {fampretty(fam_count)}")
    if neg_margins:
        sm = sorted(neg_margins)
        med = sm[len(sm)//2]
        print(f"- negotiation quoted-margin vs own value: median {med:+.1%}, n={len(sm)}")
    if pers_purchases:
        print(f"- persuasion (recent window): purchases={pers_purchases}, "
              f"lemon-rate={pers_lemons_bought/pers_purchases:.2%}")
    print()


def fampretty(counts):
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


if __name__ == "__main__":
    t1_rating_trajectory()
    recs = parse_finished()
    t3_f6_prepost(recs)
    t4_negotiation_outcomes(recs)
    jsonl_role_analysis()
