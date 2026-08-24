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


def test_opener_aggression_scale_bounds():
    # pushover (reject_rate 0 -> scale 1.2): seller anchors harder
    hard = negotiation.opener(100.0, True, False, aggression_scale=1.2)
    soft = negotiation.opener(100.0, True, False, aggression_scale=0.8)
    base = negotiation.opener(100.0, True, False)
    assert hard >= base >= soft > 102
    # buyer openers stay strictly below value at any scale
    for s in (0.8, 1.0, 1.2):
        assert negotiation.opener(100.0, False, False, aggression_scale=s) < 100


def test_seller_recovery_mode_after_pass_streak():
    from src.persuasion import SellerPolicy
    pol = SellerPolicy()
    hist = [{"round": r, "bought": False} for r in range(1, 5)]
    pol.observe(hist)
    assert pol.pass_streak == 4
    assert pol.exploit_rate(10) == 0.0
    hist2 = hist + [{"round": 5, "bought": True, "quality": "high"}]
    pol.observe(hist2)
    assert pol.exploit_rate(10) > 0.0


def test_profile_seed_kinds():
    myopic = persuasion.SellerPolicy(seed_kind="myopic")
    assert myopic.burned_then_bought and not myopic.burned_then_passed
    bayes = persuasion.SellerPolicy(seed_kind="bayesian")
    assert bayes.burned_then_passed and not bayes.burned_then_bought


def test_audit_c1_tracker_learns_from_opponent_rejections_only():
    """Audit C1: tracker ingests OPPONENT rejections of OUR offers only,
    each event exactly once."""
    from agent import STATE, update_tracker_from_history
    game = {
        "game_family": "bargaining", "your_player": "player_1",
        "game_id": "audit-c1",
        "valid_actions": {"type": "decision", "fields": {}},
        "game_state": {
            "money_to_divide": 1000.0, "round": 2, "max_rounds": None,
            "horizon_known": False, "current_player": "player_1",
            "delta_1": 0.9, "delta_2": 0.9,
            "history": [
                {"round": 1, "proposer": "player_1",
                 "offer": {"player_1_gain": 700, "player_2_gain": 300},
                 "decision": "reject"},
            ],
        },
    }
    STATE.tracker_pos.pop("audit-c1", None)
    t = STATE.tracker("audit-c1")
    before = (t.patience.alpha, t.patience.beta)
    update_tracker_from_history("audit-c1", game)
    mid = (t.patience.alpha, t.patience.beta)
    assert mid != before
    update_tracker_from_history("audit-c1", game)
    after = (t.patience.alpha, t.patience.beta)
    assert mid == after
    STATE.tracker_pos.pop("audit-c1", None)


def test_audit_h5_own_share_never_crumbs_under_uncertainty():
    money = 100.0
    game = {
        "game_family": "bargaining", "your_player": "player_1",
        "game_id": "audit-h5",
        "valid_actions": {"type": "offer", "fields": {}},
        "game_state": {
            "money_to_divide": money, "round": 1, "max_rounds": 4,
            "horizon_known": True, "delta_1": 0.9, "delta_2": 0.95,
            "current_player": "player_1", "proposer": "player_1",
            "last_offer": None, "complete_information": True,
            "messages_allowed": False, "history": [],
        },
    }
    a = bargaining.decide(game, type_confidence=0.0)
    own = a["alice_gain"] / money
    assert own >= bargaining.FIELD_MIN_CONCESSION * 0.99


def test_audit_m5_floor_uses_counterpart_offers_only():
    hist = [
        {"round": 1, "offer": {"price": 90.0, "from_player": "player_2"},
         "decision": "RejectOffer"},
        {"round": 2, "offer": {"price": 300.0, "from_player": "player_1"},
         "decision": "RejectOffer"},
    ]
    floor = negotiation.seller_floor_from_history(hist)
    assert floor == 300.0  # our own 90-bid must NOT count as their floor
