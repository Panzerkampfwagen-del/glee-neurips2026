"""Smoke tests: drive src/ strategies through synthetic game trajectories."""

import random
import sys

sys.path.insert(0, ".")

from src.bargaining import bargaining_strategy, safe_action as b_safe
from src.negotiation import negotiation_strategy, safe_action as n_safe
from src.persuasion import persuasion_strategy, safe_action as p_safe


def mk_game(family, state, vtype, player="player_1", opponent=None):
    fields = {"offer": {"alice_gain": "num", "bob_gain": "num"},
              "decision": {"decision": "enum"},
              "seller_message": {"message": "str"},
              "seller_recommendation": {"decision": "enum"},
              "buyer_decision": {"decision": "enum"}}[vtype]
    return {
        "game_id": f"g-{random.random()}",
        "game_family": family,
        "your_player": player,
        "phase": vtype,
        "game_state": state,
        "valid_actions": {"type": vtype, "fields": fields},
        "opponent": opponent or {"type": "hidden", "name": None},
        "prompt": "test",
    }


def test_bargaining_full_trajectory():
    money = 1000.0
    for horizon_known, max_rounds in [(True, 5), (False, None)]:
        for proposer in ["player_1", "player_2"]:
            state = {
                "phase": "offer", "current_player": proposer, "proposer": proposer,
                "round": 1, "money_to_divide": money,
                "delta_1": 0.95, "delta_2": 0.85,
                "horizon_known": horizon_known,
                "messages_allowed": True, "complete_information": False,
                "history": [], "last_offer": None,
            }
            if max_rounds:
                state["max_rounds"] = max_rounds
            g = mk_game("bargaining", dict(state), "offer", player=proposer)
            a = bargaining_strategy(g)
            assert abs(a["alice_gain"] + a["bob_gain"] - money) < 0.01, a
            assert a["alice_gain"] >= 0 and a["bob_gain"] >= 0

            state["phase"] = "decision"
            state["last_offer"] = {"player_1_gain": 600, "player_2_gain": 400,
                                   "message": "", "proposer": proposer, "round": 1}
            g = mk_game("bargaining", dict(state), "decision", player=proposer)
            d = bargaining_strategy(g)
            assert d["decision"] in ("accept", "reject"), d

            state["round"] = max_rounds or 99
            g = mk_game("bargaining", dict(state), "decision", player=proposer)
            d = bargaining_strategy(g)
            assert d["decision"] == "accept", ("final round must accept positive", d)
    print("bargaining OK")


def test_negotiation_full_trajectory():
    for role_player, role in [("player_1", "seller"), ("player_2", "buyer")]:
        value_key = f"{role_player}_value"
        for horizon_known, max_rounds in [(True, 4), (False, None)]:
            state = {
                "phase": "offer", "current_player": role_player,
                "player_1_role": "seller", "player_2_role": "buyer",
                "player_1_value": 80, "player_2_value": 120,
                "horizon_known": horizon_known,
                "round": 1, "history": [], "last_offer": None,
                "messages_allowed": True, "complete_information": False,
            }
            if max_rounds:
                state["max_rounds"] = max_rounds
            state[value_key] = 80 if role == "seller" else 120
            g = mk_game("negotiation", dict(state), "offer", player=role_player)
            a = negotiation_strategy(g)
            price = a["product_price"]
            assert price > 0, a
            if role == "seller":
                assert price > 80, ("seller priced below value", a)
            else:
                assert price < 120, ("buyer bid above value", a)

            state["phase"] = "decision"
            state["last_offer"] = {"price": 100 if role == "seller" else 70,
                                   "message": "", "from_player":
                                   "player_2" if role == "seller" else "player_1",
                                   "round": 1}
            g = mk_game("negotiation", dict(state), "decision", player=role_player)
            d = negotiation_strategy(g)
            assert d["decision"] == "AcceptOffer", (
                "profitable deal must be accepted", role, d)
    print("negotiation OK")


def test_persuasion_seller_and_buyer():
    base = {
        "product_price": 10.0, "p": 0.5, "v": 30.0, "u": 0.0,
        "total_rounds": 8, "round": 1, "history": [],
        "player_1_role": "seller", "player_2_role": "buyer",
        "current_player": "player_1",
    }
    s_high = dict(base, current_quality="high")
    g = mk_game("persuasion", s_high, "seller_recommendation")
    assert persuasion_strategy(g) == {"decision": "yes"}
    s_low = dict(base, current_quality="low", round=1)
    g = mk_game("persuasion", s_low, "seller_recommendation")
    assert persuasion_strategy(g) == {"decision": "no"}, "early lemon must not be pushed"

    hist = [{"round": i, "seller_message": "yes", "buyer_decision": "yes",
             "bought": True, "quality": "high", "seller_payoff": 10,
             "buyer_payoff": 20} for i in range(5)]
    s_late_bluff = dict(base, current_quality="low", round=7, history=hist,
                        seller_total_payoff=50, buyer_total_payoff=100)
    g = mk_game("persuasion", s_late_bluff, "seller_recommendation")
    print("  late-game bluff decision:", persuasion_strategy(g))

    b_state = dict(base, current_player="player_2", seller_message="yes",
                   seller_message_type="binary")
    g = mk_game("persuasion", b_state, "buyer_decision", player="player_2")
    d = persuasion_strategy(g)
    assert d["decision"] in ("yes", "no")
    b_liar_hist = [{"round": i, "seller_message": "yes", "buyer_decision": "yes",
                    "bought": True, "quality": "low", "seller_payoff": 10,
                    "buyer_payoff": -10} for i in range(6)]
    b_state["history"] = b_liar_hist
    g = mk_game("persuasion", b_state, "buyer_decision", player="player_2")
    d = persuasion_strategy(g)
    assert d["decision"] == "no", ("buyer must boycott confirmed liar", d)
    print("persuasion OK")


def test_safe_actions_never_invalid():
    g = mk_game("bargaining", {"money_to_divide": 1000, "current_player": "player_1",
                               "horizon_known": False, "history": []}, "offer")
    a = b_safe(g)
    assert abs(a["alice_gain"] + a["bob_gain"] - 1000) < 0.01
    g = mk_game("negotiation", {"current_player": "player_1", "player_1_role": "seller",
                                "player_1_value": 50}, "offer")
    assert n_safe(g)["product_price"] > 0
    g = mk_game("persuasion", {"product_price": 10, "p": 0.5, "v": 15, "u": 0,
                               "current_player": "player_2"}, "buyer_decision")
    assert p_safe(g)["decision"] == "no"
    print("safe actions OK")


if __name__ == "__main__":
    random.seed(7)
    test_bargaining_full_trajectory()
    test_negotiation_full_trajectory()
    test_persuasion_seller_and_buyer()
    test_safe_actions_never_invalid()
    print("ALL SMOKE TESTS PASSED")
