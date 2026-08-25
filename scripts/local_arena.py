"""Local arena: plays src/ strategies against scripted opponents across all
three families per the official rules, for the docs/07 E2 ablation ladder.

No API, no LLM. Arms are selected by setting GLEE_ABLATE before importing
agent.strategy (mirrors production code paths exactly).
"""

import importlib
import json
import os
import random
import statistics
import sys

sys.path.insert(0, ".")

BARGAINING_OPP = {
    "fair": {"open": 0.5, "concede": 0.04, "min_accept": 0.42},
    "greedy": {"open": 0.78, "concede": 0.02, "min_accept": 0.30},
}
NEGOTIATION_OPP = {
    "fair": {"margin": 1.25, "concede": 0.94, "floor": 1.05},
    "greedy": {"margin": 1.6, "concede": 0.97, "floor": 1.01},
}


def play_bargaining(strategy, opp_kind, rng):
    import logging
    logging.disable(logging.CRITICAL)
    money = float(rng.choice([100, 1000, 1000000]))
    max_rounds = rng.choice([6, 10, None])
    known = max_rounds is not None
    d_me, d_opp = 0.95, rng.choice([0.85, 0.9, 0.95])
    round_no = 1
    proposer = "player_1"
    last_offer = None
    my_player = rng.choice(["player_1", "player_2"])
    opp = "player_2" if my_player == "player_1" else "player_1"
    hist = []

    def _pn(off_alice, off_bob):
        return {"player_1_gain": off_alice if my_player == "player_1" else off_bob,
                "player_2_gain": off_bob if my_player == "player_1" else off_alice}

    while True:
        if proposer == my_player:
            g = _bgame(my_player, round_no, known, max_rounds, money,
                       d_me, d_opp, last_offer, "offer", my_player, hist)
            a = strategy(g)
            split = _split(a, my_player, money)
            last_offer = split
            dec = _opp_bargain_decide(opp_kind, split, my_player, money)
            hist.append({"round": round_no, "proposer": my_player,
                         "offer": _pn(split["alice_gain"], split["bob_gain"]),
                         "decision": "accept" if dec == "accept" else "reject"})
            if dec == "accept":
                return _pay_split(split, my_player, round_no, d_me, d_opp, False)
            last_offer = hist[-1]["offer"]
        else:
            share = BARGAINING_OPP[opp_kind]["open"] if round_no == 1 else max(
                BARGAINING_OPP[opp_kind]["min_accept"],
                BARGAINING_OPP[opp_kind]["open"]
                - BARGAINING_OPP[opp_kind]["concede"] * (round_no - 1))
            mine_to_them = 1.0 - share
            p1g = money * (share if my_player == "player_1" else mine_to_them)
            last_offer = {"player_1_gain": p1g, "player_2_gain": money - p1g}
            g = _bgame(my_player, round_no, known, max_rounds, money,
                       d_me, d_opp, last_offer, "decision", my_player, hist)
            a = strategy(g)
            dec = a.get("decision", "reject")
            hist.append({"round": round_no, "proposer": opp,
                         "offer": dict(last_offer),
                         "decision": "accept" if dec == "accept" else "reject"})
            if dec == "accept":
                return _pay_split(last_offer, my_player, round_no, d_me, d_opp, False)
            if dec == "walkaway":
                return 0.0
        round_no += 1
        proposer = "player_2" if proposer == "player_1" else "player_1"
        if known and round_no > max_rounds:
            return 0.0
        if not known and round_no > 80:
            return 0.0


def _bgame(me, rnd, known, maxr, money, d1, d2, last, vtype, cur, hist=None):
    st = {"money_to_divide": money, "round": rnd, "horizon_known": known,
          "delta_1": d1 if me == "player_1" else d2,
          "delta_2": d2 if me == "player_1" else d1,
          "current_player": cur, "proposer": cur, "messages_allowed": False,
          "complete_information": False, "history": hist or [],
          "last_offer": last}
    if known:
        st["max_rounds"] = maxr
    return {"game_id": f"L{os.environ.get('_ARM','x')}-{rnd}-{id(st)}",
            "game_family": "bargaining", "your_player": me,
            "valid_actions": {"type": vtype, "fields": {}},
            "opponent": {"type": "hidden", "name": None}, "game_state": st,
            "prompt": ""}


def _split(a, me, money):
    ag = float(a.get("alice_gain", money / 2))
    bg = float(a.get("bob_gain", money - ag))
    tot = ag + bg
    return {"alice_gain": ag * money / tot, "bob_gain": bg * money / tot}


def _pay_split(off, me, rnd, d_me, d_opp, disc_opp):
    k = rnd - 1
    if "alice_gain" in off:
        money = off["alice_gain"] + off["bob_gain"]
        mine = off["alice_gain"] if me == "player_1" else off["bob_gain"]
    else:
        money = off["player_1_gain"] + off["player_2_gain"]
        mine = off[f"{me}_gain"]
    return (mine * (d_me ** k)) / max(money, 1e-9)


def _opp_bargain_decide(kind, off, me, money):
    their = off["bob_gain"] if me == "player_1" else off["alice_gain"]
    return "accept" if their / money >= BARGAINING_OPP[kind]["min_accept"] else "reject"


def play_negotiation(strategy, opp_kind, rng):
    import logging
    logging.disable(logging.CRITICAL)
    cfg = NEGOTIATION_OPP[opp_kind]
    i_am_seller = rng.random() < 0.5
    s_val = rng.choice([50, 80, 12000])
    b_val = s_val * rng.uniform(1.15, 1.8)
    me_role, me_val = ("seller", s_val) if i_am_seller else ("buyer", b_val)
    opp_val = b_val if i_am_seller else s_val
    price = None
    round_no = 1
    my_turn = rng.random() < 0.5
    surplus = b_val - s_val
    while round_no <= 30:
        if my_turn:
            g = _ngame(i_am_seller, me_val, round_no, price, "offer")
            a = strategy(g)
            price = float(a.get("product_price", me_val))
            ok = (price <= opp_val) if i_am_seller else (price >= opp_val)
            if ok:
                return _npay(price, me_val, i_am_seller) / max(surplus, 1e-9)
            price = _opp_price(cfg, opp_val, i_am_seller, round_no)
            ok2 = (price >= me_val) if i_am_seller else (price <= me_val)
            if ok2:
                return _npay(price, me_val, i_am_seller) / max(surplus, 1e-9)
        else:
            price = _opp_price(cfg, opp_val, i_am_seller, round_no)
            ok = (price >= me_val) if i_am_seller else (price <= me_val)
            if ok:
                return _npay(price, me_val, i_am_seller) / max(surplus, 1e-9)
            g = _ngame(i_am_seller, me_val, round_no, price, "decision",
                       last_from="opp")
            a = strategy(g)
            if a.get("decision") == "AcceptOffer":
                return _npay(float(price), me_val, i_am_seller) / max(surplus, 1e-9)
            if "product_price" in a:
                price = float(a["product_price"])
                ok2 = (price <= opp_val) if i_am_seller else (price >= opp_val)
                if ok2:
                    return _npay(price, me_val, i_am_seller) / max(surplus, 1e-9)
        round_no += 1
        my_turn = not my_turn
    return 0.0


def _opp_price(cfg, opp_val, i_am_seller, rnd):
    m = cfg["margin"] * (cfg["concede"] ** rnd)
    return opp_val * ((2.0 - m) if i_am_seller else m)


def _npay(price, my_val, i_am_seller):
    return (price - my_val) if i_am_seller else (my_val - price)


def _ngame(i_am_seller, val, rnd, last_price, vtype, last_from=None):
    role = "player_1" if i_am_seller else "player_2"
    st = {"round": rnd, "horizon_known": False,
          "player_1_role": "seller", "player_2_role": "buyer",
          f"{role}_value": val, "current_player": role,
          "messages_allowed": False, "complete_information": False,
          "history": [],
          "last_offer": ({"price": last_price, "message": "",
                          "from_player": last_from or (
                              "player_1" if i_am_seller else "player_2"),
                          "round": rnd} if last_price else None)}
    fields = {"product_price": "num"} if vtype == "offer" else \
        {"decision": "'AcceptOffer', 'RejectOffer', or 'WalkAway'",
         "product_price": "num"}
    return {"game_id": f"N-{rnd}-{id(st)}", "game_family": "negotiation",
            "your_player": role, "valid_actions": {"type": vtype,
                                                   "fields": fields},
            "opponent": {"type": "hidden", "name": None}, "game_state": st,
            "prompt": ""}


def play_persuasion(strategy, opp_kind, rng, gid="P"):
    """We are always the SELLER here; opponent is a scripted buyer."""
    price = 10.0
    p = 0.5
    v = 30.0
    total = 20
    payoff = 0.0
    trust = 0.5
    hist = []
    for rnd in range(1, total + 1):
        high = rng.random() < p
        st = {"product_price": price, "p": p, "v": v, "u": 0.0,
              "total_rounds": total, "round": rnd, "history": hist,
              "current_quality": "high" if high else "low",
              "seller_message_type": "binary", "current_player": "player_1"}
        g = {"game_id": f"{gid}-{rnd}", "game_family": "persuasion",
             "your_player": "player_1",
             "valid_actions": {"type": "seller_recommendation",
                               "fields": {"decision": "enum"}},
             "opponent": {"type": "hidden", "name": None},
             "game_state": st, "prompt": ""}
        a = strategy(g)
        rec = a.get("decision", "yes") == "yes"
        buy = rec and rng.random() < (trust + 0.35 if rec else 0.0)
        if opp_kind == "bayesian":
            buy = rec and (trust > 0.45 or high)
        if buy:
            payoff += price
            if not high:
                trust = max(0.0, trust - 0.3)
            else:
                trust = min(1.0, trust + 0.08)
        hist.append({"round": rnd, "seller_message": "yes" if rec else "no",
                     "buyer_decision": "yes" if buy else "no",
                     "bought": bool(buy),
                     "quality": "high" if high else "low"})
    return payoff


def run_arm(arm_label, n_per_cell=20, seed=20260825):
    os.environ["_ARM"] = arm_label
    os.environ["GLEE_ABLATE"] = {"L3": "", "L2": "profiles",
                                 "L1": "opp_model", "L0": "all"}[arm_label]
    for m in list(sys.modules):
        if m.startswith("src") or m == "agent":
            del sys.modules[m]
    import agent as agent_mod
    importlib.reload(agent_mod)
    strat = agent_mod.strategy

    rng = random.Random(seed)
    results = {}
    for fam, runner, opps in [
        ("bargaining", play_bargaining, list(BARGAINING_OPP)),
        ("negotiation", play_negotiation, list(NEGOTIATION_OPP)),
        ("persuasion", play_persuasion, ["naive", "bayesian"]),
    ]:
        vals = []
        for oi, opp in enumerate(opps):
            r2 = random.Random(seed * 100 + oi)
            for gi in range(n_per_cell // len(opps)):
                try:
                    if fam == "persuasion":
                        vals.append(runner(strat, opp, r2, gid=f"{arm}-{oi}-{gi}"))
                    else:
                        vals.append(runner(strat, opp, r2))
                except Exception as e:
                    print(f"  [{arm_label} {fam}/{opp}] EXC {e}", file=sys.stderr)
        results[fam] = vals
    return results


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    seed = 20260825
    out = {}
    for arm in ["L0", "L1", "L2", "L3"]:
        res = run_arm(arm, n_per_cell=n)
        out[arm] = {}
        for fam, vals in res.items():
            nz = [v for v in vals]
            out[arm][fam] = {
                "n": len(nz),
                "exceptions": n - len(nz),
                "mean": round(statistics.mean(nz), 3) if nz else None,
                "median": round(statistics.median(nz), 3) if nz else None,
                "deal_rate": round(sum(1 for v in nz if v > 0) / len(nz), 3)
                if nz else None,
            }
        print(arm, json.dumps(out[arm]), flush=True)
    from pathlib import Path
    Path("experiments").mkdir(exist_ok=True)
    (Path("experiments") / "t2_ladder_pilot.json").write_text(
        json.dumps({"n_per_arm": n, "seed": seed,
                    "payoff_units": {"bargaining": "share of pot (discounted)",
                                     "negotiation": "surplus share",
                                     "persuasion": "$ at price=10, 20 rounds"},
                    "results": out}, indent=1))
    print("saved experiments/t2_ladder_pilot.json")
