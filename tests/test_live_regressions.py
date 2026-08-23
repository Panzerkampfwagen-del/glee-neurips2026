"""Regressions from live-run forensics (Aug 23 2026 session)."""

from src import bargaining, negotiation, persuasion
from src.safety import safe_action, validate_and_fix


def _live_negotiation_648cfcad(atype="decision"):
    """Exact state of live game 648cfcad where we wrongly accepted price 260
    against buyer value 120 (complete_information=True)."""
    return {
        "game_family": "negotiation",
        "your_player": "player_2",
        "valid_actions": {"type": atype,
                          "fields": {"decision": "'AcceptOffer', 'RejectOffer', or 'WalkAway'",
                                     "product_price": "number (required if RejectOffer - your counteroffer)",
                                     "message": "string (optional)"}},
        "game_state": {
            "round": 1, "max_rounds": 10, "horizon_known": True,
            "current_player": "player_2",
            "player_1_role": "seller", "player_2_role": "buyer",
            "player_1_value": 100.0, "player_2_value": 120.0,
            "complete_information": True, "messages_allowed": True,
            "last_offer": {"price": 260.0, "message": "",
                           "from_player": "player_1", "round": 1},
            "history": [],
        },
    }


def test_regression_648cfcad_never_accepts_unprofitable():
    game = _live_negotiation_648cfcad()
    a = negotiation.decide(game)
    assert a["decision"] == "RejectOffer"
    assert isinstance(a["product_price"], (int, float))
    submitted = validate_and_fix(game, a)
    assert submitted["decision"] == "RejectOffer"


def test_regression_enum_parser_handles_or_string():
    game = _live_negotiation_648cfcad()
    good = {"decision": "RejectOffer", "product_price": 110.0}
    assert validate_and_fix(game, good)["decision"] == "RejectOffer"


def test_safe_action_negotiation_rejects_unprofitable():
    game = _live_negotiation_648cfcad()
    assert safe_action(game)["decision"] != "AcceptOffer"


def test_safe_action_negotiation_accepts_profitable():
    game = _live_negotiation_648cfcad()
    game["game_state"]["last_offer"]["price"] = 90.0
    assert safe_action(game) == {"decision": "AcceptOffer"}


def test_persuasion_hidden_v_does_not_crash():
    game = {
        "game_family": "persuasion",
        "your_player": "player_2",
        "valid_actions": {"type": "buyer_decision", "fields": {}},
        "game_state": {
            "product_price": 25.0, "p": 0.5,
            "seller_message_type": "binary",
            "history": [],
            "current_player": "player_2",
            "round": 1, "total_rounds": 12,
        },
    }
    a = persuasion.buyer_decide(game)
    assert a["decision"] in ("yes", "no")


def test_persuasion_hidden_v_uses_revealed_history():
    game = {
        "game_family": "persuasion",
        "your_player": "player_2",
        "valid_actions": {"type": "buyer_decision", "fields": {}},
        "game_state": {
            "product_price": 30.0, "p": 0.5,
            "seller_message_type": "binary",
            "history": [
                {"round": 1, "bought": True, "quality": "high", "buyer_payoff": 70.0},
                {"round": 2, "bought": True, "quality": "low", "buyer_payoff": -30.0},
                {"round": 3, "bought": True, "quality": "low", "buyer_payoff": -30.0},
            ],
            "current_player": "player_2",
            "round": 4, "total_rounds": 12,
        },
    }
    assert persuasion.buyer_decide(game)["decision"] == "no"


def test_bargaining_opener_concedes_field_minimum():
    money = 10000.0
    game = {
        "game_family": "bargaining",
        "your_player": "player_1",
        "valid_actions": {"type": "offer", "fields": {}},
        "game_state": {
            "money_to_divide": money, "round": 1, "max_rounds": 8,
            "horizon_known": True,
            "delta_1": 0.9, "delta_2": 0.9,
            "current_player": "player_1", "proposer": "player_1",
            "last_offer": None, "complete_information": True,
            "messages_allowed": False, "history": [],
        },
    }
    a = bargaining.decide(game, type_confidence=0.0)
    conceded_to_p2 = a["bob_gain"] / money
    assert conceded_to_p2 >= bargaining.FIELD_MIN_CONCESSION - 1e-9


def test_regression_c697c812_no_walkaway_with_visible_surplus():
    """Live game c697c812: complete info, surplus [12000,15000], seller asked
    24000/22800 — old estimator inflated their floor off their own asks and
    walked away. Must counter near the fair split instead."""
    game = {
        "game_family": "negotiation", "your_player": "player_2", "game_id": "x",
        "valid_actions": {"type": "decision",
                          "fields": {"decision": "'AcceptOffer', 'RejectOffer', or 'WalkAway'",
                                     "product_price": "number"}},
        "game_state": {
            "round": 3, "max_rounds": 10, "horizon_known": True,
            "current_player": "player_2",
            "player_1_role": "seller", "player_2_role": "buyer",
            "player_1_value": 12000.0, "player_2_value": 15000.0,
            "complete_information": True, "messages_allowed": False,
            "last_offer": {"price": 22800.0, "from_player": "player_1", "round": 3},
            "history": [
                {"round": 1, "offer": {"price": 24000.0, "from_player": "player_1"},
                 "decision": "RejectOffer", "decided_by": "player_2"},
                {"round": 2, "offer": {"price": 12753.0, "from_player": "player_2"},
                 "decision": "RejectOffer", "decided_by": "player_1"},
            ],
        },
    }
    a = negotiation.decide(game)
    assert a["decision"] == "RejectOffer"
    assert 12500 <= a["product_price"] <= 14600


def test_interval_estimator_rejection_semantics():
    hist = [
        {"round": 1, "offer": {"price": 100.0, "from_player": "player_2"},
         "decision": "RejectOffer", "decided_by": "player_1"},
    ]
    lo, hi = negotiation.estimate_opponent_interval(hist, "seller")
    assert lo >= 85.0 and hi == float("inf")

    hist2 = [
        {"round": 1, "offer": {"price": 90.0, "from_player": "player_1"},
         "decision": "RejectOffer", "decided_by": "player_2"},
    ]
    lo2, hi2 = negotiation.estimate_opponent_interval(hist2, "buyer")
    assert hi2 <= 103.5
    assert lo2 < 50.0
