"""Offline sanity harness: plays our solver strategies against scripted
opponents across simulated games (no API, no LLM). Complements pytest unit
tests with end-to-end payoff checks.

Usage: python scripts/smoke_test.py
"""

import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import bargaining, negotiation, persuasion


def barg_game(money, round_, max_rounds, proposer, last_offer, atype,
              d1=0.9, d2=0.9, history=None):
    return {
        "game_family": "bargaining", "your_player": "player_1", "game_id": "t",
        "valid_actions": {"type": atype, "fields": {}},
        "game_state": {"money_to_divide": money, "round": round_,
                       "max_rounds": max_rounds, "horizon_known": True,
                       "delta_1": d1, "delta_2": d2,
                       "current_player": proposer, "proposer": proposer,
                       "last_offer": last_offer, "history": history or [],
                       "complete_information": True, "messages_allowed": False},
    }


def play_bargaining_vs_fairness(seed) -> float:
    rng = random.Random(seed)
    money, r = 1000.0, 1
    last = None
    while r <= 8:
        # we propose when odd rounds
        if r % 2 == 1:
            a = bargaining.decide(barg_game(money, r, 8, "player_1", last, "offer"))
            offer_to_them = a["bob_gain"]
            if offer_to_them / money >= rng.uniform(0.38, 0.5):
                return offer_to_them * (0.9 ** (r - 1))
            last = {"player_1_gain": a["alice_gain"], "player_2_gain": a["bob_gain"]}
        else:
            a = bargaining.decide(barg_game(money, r, 8, "player_2", last, "decision"))
            if a["decision"] == "accept":
                return last["player_1_gain"] * (0.9 ** (r - 1))
            # fairness opponent counters 50/50-ish; we accept next
            last = {"player_1_gain": money * rng.uniform(0.4, 0.48),
                    "player_2_gain": None}
            last["player_2_gain"] = money - last["player_1_gain"]
            if r == 8:
                return last["player_1_gain"]
        r += 1
    return 0.0


def neg_game(role, value, atype, round_, last, history):
    me = "player_1" if role == "seller" else "player_2"
    return {
        "game_family": "negotiation", "your_player": me, "game_id": "t",
        "valid_actions": {"type": atype, "fields": {}},
        "game_state": {"current_player": me, f"{me}_role": role,
                       f"{me}_value": value, "round": round_, "max_rounds": 5,
                       "horizon_known": True, "last_offer": last,
                       "complete_information": False, "messages_allowed": False,
                       "history": history or []},
    }


def play_negotiation(seed) -> float:
    """We are buyer with value 100; seller's true value drawn uniform(20, 80);
    greedy-but-conceding seller opponent."""
    rng = random.Random(seed)
    seller_value = rng.uniform(20, 80)
    history, last, r = [], None, 1
    ask = None
    while r <= 5:
        if r % 2 == 1:  # seller proposes/asks
            ask = seller_value * rng.uniform(1.6, 2.2) / (1 + 0.15 * (r - 1))
            last = {"price": ask, "from_player": "player_1"}
            a = negotiation.decide(neg_game("buyer", 100.0, "decision", r, last, history))
            if a["decision"] == "AcceptOffer":
                return 100.0 - ask
            if a["decision"] == "WalkAway":
                return 0.0
            counter = a.get("product_price")
            history.append({"offer": last, "decision": "RejectOffer",
                            "counteroffer": counter})
            last = {"price": counter, "from_player": "player_2"}
        else:
            a = negotiation.decide(neg_game("buyer", 100.0, "offer", r, last, history))
            bid = a["product_price"]
            if bid >= seller_value * rng.uniform(1.02, 1.15):
                return 100.0 - bid
            history.append({"offer": {"price": bid, "from_player": "player_2"},
                            "decision": None})
        r += 1
    return 0.0


def play_persuasion_seller(seed) -> float:
    """We sell to a bayesian buyer (buys iff posterior EV > price*1.05,
    tracks outcomes); quality ~ Bernoulli(0.5), price 30, v=100."""
    rng = random.Random(seed)
    price, v, p = 30.0, 100.0, 0.5
    pol = persuasion.SellerPolicy()
    history, payoff = [], 0.0
    for rnd in range(1, 11):
        quality = "high" if rng.random() < p else "low"
        g = {"game_family": "persuasion", "your_player": "player_1",
             "game_id": "t",
             "valid_actions": {"type": "seller_recommendation", "fields": {}},
             "game_state": {"product_price": price, "p": p, "v": v, "u": 0.0,
                            "current_quality": quality, "round": rnd,
                            "total_rounds": 10, "history": list(history),
                            "seller_message_type": "binary"}}
        rec = persuasion.seller_decide(g, pol)["decision"]
        # bayesian buyer: empirical rate of truthfulness among recs
        recs = [h for h in history if h.get("rec")]
        if not recs:
            buy = True
        else:
            honest = sum(1 for h in recs if h["quality"] == "high") / len(recs)
            buy = honest * v > price * 1.05
        if buy:
            payoff += price
        history.append({"round": rnd, "bought": buy, "quality": quality, "rec": True})
    return payoff


if __name__ == "__main__":
    n = 300
    b = sum(play_bargaining_vs_fairness(i) for i in range(n)) / n
    ng = sum(play_negotiation(i) for i in range(n)) / n
    ps = sum(play_persuasion_seller(i) for i in range(n)) / n
    print(f"bargaining vs fairness-bot : avg payoff {b:8.1f} of 1000")
    print(f"negotiation as buyer       : avg surplus {ng:8.1f} of 100-value scale x{100}")
    print(f"persuasion seller vs bayes : avg payoff {ps:8.1f} (10 rounds x $30)")
