from src import persuasion
from src.opponent_model import DecayedBeta, infer_seller_type


def _mk_game(am_seller=True, atype="seller_recommendation", quality="high",
             history=None, price=30.0, p=0.5, v=100.0, u=0.0, round_=1,
             total=10, msg=None, mode="binary"):
    me = "player_1" if am_seller else "player_2"
    state = {
        "product_price": price,
        "p": p,
        "v": v,
        "u": u,
        "round": round_,
        "total_rounds": total,
        "seller_message_type": mode,
        "history": history or [],
        "current_player": me,
    }
    if am_seller:
        state["current_quality"] = quality
    if msg is not None:
        state["seller_message"] = msg
    return {
        "game_family": "persuasion",
        "your_player": me,
        "valid_actions": {"type": atype, "fields": {}},
        "game_state": state,
    }


def test_seller_honest_on_high_early():
    pol = persuasion.SellerPolicy()
    game = _mk_game(quality="high", round_=1)
    assert persuasion.seller_decide(game, pol)["decision"] == "yes"


def test_seller_builds_reputation_early():
    pol = persuasion.SellerPolicy()
    for _ in range(20):
        assert pol.recommend("low", rounds_left=9) ["decision"] in ("yes", "no")
    rates = [pol.exploit_rate(9) < 0.2]
    assert any(rates)


def test_seller_farms_myopic_buyer():
    hist = [
        {"round": 1, "bought": True, "quality": "low"},
        {"round": 2, "bought": True, "quality": "high"},
        {"round": 3, "bought": True, "quality": "low"},
        {"round": 4, "bought": True, "quality": "low"},
    ]
    info = infer_seller_type(hist)
    assert info["kind"] == "myopic"
    pol = persuasion.SellerPolicy()
    pol.observe(hist)
    assert pol.exploit_rate(5) > 0.8


def test_seller_cautious_after_buyer_punishes():
    hist = [
        {"round": 1, "bought": True, "quality": "high"},
        {"round": 2, "bought": True, "quality": "low"},
        {"round": 3, "bought": False},
        {"round": 4, "bought": False},
    ]
    info = infer_seller_type(hist)
    assert info["kind"] == "bayesian"
    pol = persuasion.SellerPolicy()
    pol.observe(hist)
    assert pol.exploit_rate(5) < 0.3


def test_seller_endgame_exploits_banked_trust():
    hist = [{"round": r, "bought": True, "quality": "high"} for r in range(1, 7)]
    pol = persuasion.SellerPolicy()
    pol.observe(hist)
    assert pol.exploit_rate(2) >= 0.45


def test_buyer_buys_good_prior():
    game = _mk_game(am_seller=False, atype="buyer_decision", price=30.0, p=0.6)
    assert persuasion.buyer_decide(game)["decision"] == "yes"


def test_buyer_passes_bad_prior():
    game = _mk_game(am_seller=False, atype="buyer_decision", price=60.0, p=0.4)
    assert persuasion.buyer_decide(game)["decision"] == "no"


def test_buyer_distrusts_caught_liar():
    clean = []
    burned = [
        {"round": 1, "bought": True, "quality": "high"},
        {"round": 2, "bought": True, "quality": "low"},
        {"round": 3, "bought": True, "quality": "low"},
    ]
    g_clean = _mk_game(False, "buyer_decision", price=40.0, p=0.5, history=clean)
    g_burned = _mk_game(False, "buyer_decision", price=40.0, p=0.5, history=burned)
    d_clean = persuasion.buyer_decide(g_clean)["decision"]
    d_burned = persuasion.buyer_decide(g_burned)["decision"]
    assert d_clean == "yes"
    assert d_burned == "no"


def test_buyer_endgame_suspicion():
    from src.persuasion import _buy_margin
    assert _buy_margin(1) > _buy_margin(10)
    early = _mk_game(False, "buyer_decision", price=53.0, p=0.5,
                     v=100.0, history=[{"round": 1, "bought": True, "quality": "high"}],
                     round_=1, total=12)
    late = _mk_game(False, "buyer_decision", price=53.0, p=0.5,
                    v=100.0, history=[{"round": r, "bought": True, "quality": "high"}
                                       for r in (1,)],
                     round_=9, total=10)
    a_early = persuasion.buyer_decide(early)["decision"]
    a_late = persuasion.buyer_decide(late)["decision"]
    assert a_early == "yes"
    assert a_late == "no"


def test_text_mode_returns_message():
    game = _mk_game(atype="seller_message", quality="high", msg=None, mode="text")
    out = persuasion.seller_decide(game, persuasion.SellerPolicy())
    assert isinstance(out.get("message"), str) and len(out["message"]) <= 2000


def test_regression_a9919bf1_no_death_spiral_after_single_burn():
    """Live game: EV=150 > price=100. One early low burn locked the old buyer
    out for 18 rounds. Posterior + exploration must keep us in the market."""
    hist = [
        {"round": 1, "bought": True, "quality": "high", "seller_message": "yes"},
        {"round": 2, "bought": True, "quality": "low", "seller_message": "yes"},
        {"round": 3, "bought": False, "seller_message": "no"},
    ]
    game = _mk_game(False, "buyer_decision", price=100.0, p=0.5,
                    v=300.0, history=hist, round_=4, total=20)
    assert persuasion.buyer_decide(game)["decision"] == "yes"


def test_buyer_still_boycotts_active_liar():
    hist = [
        {"round": r, "bought": True, "quality": "low", "seller_message": "yes"}
        for r in (1, 2, 3)
    ]
    game = _mk_game(False, "buyer_decision", price=100.0, p=0.5,
                    v=300.0, history=hist, round_=4, total=20)
    assert persuasion.buyer_decide(game)["decision"] == "no"


def test_buyer_rewards_selective_honesty():
    # seller says 'no' on lows (never bought), 'yes' on highs we bought
    hist = [
        {"round": 1, "bought": True, "quality": "high", "seller_message": "yes"},
        {"round": 2, "bought": False, "quality": None, "seller_message": "no"},
        {"round": 3, "bought": False, "quality": None, "seller_message": "no"},
        {"round": 4, "bought": True, "quality": "high", "seller_message": "yes"},
    ]
    game = _mk_game(False, "buyer_decision", price=150.0, p=0.5,
                    v=400.0, history=hist, round_=5, total=20)
    # P(high|yes) high -> buy even at 150
    assert persuasion.buyer_decide(game)["decision"] == "yes"
