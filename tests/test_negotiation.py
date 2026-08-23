from src import negotiation


def _mk_game(role="seller", value=50.0, atype="offer", round_=1, max_rounds=4,
             horizon=True, last_offer=None, history=None, complete_info=False):
    my_p1 = role == "seller"
    me = "player_1" if my_p1 else "player_2"
    return {
        "game_family": "negotiation",
        "your_player": me,
        "valid_actions": {"type": atype, "fields": {}},
        "game_state": {
            "current_player": me,
            f"{me}_role": role,
            f"{me}_value": value,
            "round": round_,
            "max_rounds": max_rounds if horizon else None,
            "horizon_known": horizon,
            "last_offer": last_offer,
            "complete_information": complete_info,
            "messages_allowed": False,
            "history": history or [],
        },
    }


def test_seller_opener_above_value_nonround():
    game = _mk_game()
    a = negotiation.decide(game)
    p = a["product_price"]
    assert p > 50 * 1.3
    assert p % 5 != 0


def test_buyer_opener_below_value():
    game = _mk_game(role="buyer", value=100.0)
    a = negotiation.decide(game)
    assert a["product_price"] < 100.0


def test_interval_tightening_from_history():
    # Seller asks 90; WE (buyer) reject it -> only a hi bound on their value.
    hist = [
        {"round": 1, "offer": {"price": 90, "from_player": "player_1"},
         "decision": "RejectOffer", "decided_by": "player_2"},
        {"round": 2, "offer": {"price": 40, "from_player": "player_2"},
         "decision": "RejectOffer", "decided_by": "player_1"},
    ]
    lo, hi = negotiation.estimate_opponent_interval(hist, "buyer", prior_lo=0.0,
                                                    prior_hi=None)
    assert hi <= 103.5
    assert lo >= 36.0


def test_buyer_walkaway_on_certain_negative_surplus():
    hist = [
        {"offer": {"price": 200, "from_player": "player_1"}, "decision": "RejectOffer",
         "counteroffer": 190},
        {"offer": {"price": 185, "from_player": "player_1"}, "decision": "RejectOffer",
         "counteroffer": 180},
    ]
    game = _mk_game(role="buyer", value=100.0, atype="decision", round_=3,
                    last_offer={"price": 175, "from_player": "player_1"},
                    history=hist)
    assert negotiation.decide(game)["decision"] == "WalkAway"


def test_final_round_accept_irrational_offer():
    game = _mk_game(atype="decision", round_=4, max_rounds=4,
                    last_offer={"price": 55, "from_player": "player_2"})
    assert negotiation.decide(game)["decision"] == "AcceptOffer"


def test_final_round_reject_unprofitable():
    game = _mk_game(atype="decision", round_=4, max_rounds=4,
                    last_offer={"price": 45, "from_player": "player_2"})
    assert negotiation.decide(game)["decision"] == "RejectOffer"


def test_counter_always_carries_price():
    game = _mk_game(atype="decision", round_=2,
                    last_offer={"price": 30, "from_player": "player_2"})
    a = negotiation.decide(game)
    assert a["decision"] == "RejectOffer"
    assert isinstance(a["product_price"], float) or isinstance(a["product_price"], int)
