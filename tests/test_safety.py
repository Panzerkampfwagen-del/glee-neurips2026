from src.safety import safe_action, validate_and_fix


def _mk(family, atype, **state):
    return {
        "game_family": family,
        "your_player": "player_1",
        "valid_actions": {"type": atype, "fields": {}},
        "game_state": state,
    }


def test_safe_actions_all_families():
    b = _mk("bargaining", "offer", money_to_divide=100.0, current_player="player_1",
            player_1_value=10)
    assert sum(safe_action(b)[k] for k in ("alice_gain", "bob_gain")) == 100.0

    n = _mk("negotiation", "offer", current_player="player_1", player_1_value=42)
    assert safe_action(n)["product_price"] == 42

    d = _mk("bargaining", "decision")
    assert safe_action(d) == {"decision": "accept"}

    p = _mk("persuasion", "seller_message")
    assert "message" in safe_action(p)


def test_repairs_bad_sum():
    game = _mk("bargaining", "offer", money_to_divide=100.0)
    fixed = validate_and_fix(game, {"alice_gain": 70.0, "bob_gain": 50.0})
    assert abs(fixed["alice_gain"] + fixed["bob_gain"] - 100.0) < 0.01


def test_repairs_garbage_input():
    game = _mk("bargaining", "offer", money_to_divide=100.0)
    fixed = validate_and_fix(game, {"alice_gain": "lots"})
    assert abs(fixed["alice_gain"] + fixed["bob_gain"] - 100.0) < 0.01


def test_truncates_long_message():
    game = _mk("bargaining", "offer", money_to_divide=100.0)
    long_msg = "x" * 5000
    fixed = validate_and_fix(game, {"alice_gain": 50.0, "bob_gain": 50.0,
                                    "message": long_msg})
    assert len(fixed["message"]) <= 2000


def test_invalid_enum_falls_back():
    game = {
        "game_family": "negotiation",
        "your_player": "player_1",
        "valid_actions": {"type": "decision",
                          "fields": {"decision": "'AcceptOffer', 'RejectOffer', or 'WalkAway'"}},
        "game_state": {},
    }
    fixed = validate_and_fix(game, {"decision": "maybe"})
    assert fixed["decision"] == "AcceptOffer"


def test_none_action_falls_back():
    game = _mk("persuasion", "buyer_decision")
    assert validate_and_fix(game, None) == {"decision": "yes"}
