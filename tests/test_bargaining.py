import math

from src import bargaining


def _mk_game(money=1000.0, round_=1, max_rounds=5, horizon=True,
             me="player_1", proposer="player_1", last_offer=None, atype="offer"):
    return {
        "game_family": "bargaining",
        "your_player": me,
        "valid_actions": {"type": atype, "fields": {}},
        "game_state": {
            "money_to_divide": money,
            "round": round_,
            "max_rounds": max_rounds if horizon else None,
            "horizon_known": horizon,
            "delta_1": 0.9,
            "delta_2": 0.9,
            "current_player": me,
            "proposer": proposer,
            "last_offer": last_offer,
            "complete_information": True,
            "messages_allowed": False,
            "history": [],
        },
    }


def test_offer_sums_exactly():
    for money in (1000.0, 777.77, 250.0):
        game = _mk_game(money=money)
        a = bargaining.decide(game)
        assert abs(a["alice_gain"] + a["bob_gain"] - money) < 1e-6
        assert a["alice_gain"] >= 0 and a["bob_gain"] >= 0


def test_infinite_horizon_split_valid():
    s_me, s_opp = bargaining.infinite_horizon_shares(0.9, 0.9, 1000.0)
    assert math.isclose(s_me + s_opp, 1000.0)
    assert s_me > s_opp
    assert abs(s_me - 500) < 100


def test_patient_player_gets_more():
    patient_me, _ = bargaining.infinite_horizon_shares(0.98, 0.7, 1000.0)
    even_me, even_opp = bargaining.infinite_horizon_shares(0.9, 0.9, 1000.0)
    assert patient_me > even_me
    _, opp_of_impatient = bargaining.infinite_horizon_shares(0.7, 0.98, 1000.0)
    assert opp_of_impatient > even_opp


def test_final_round_receiver_accepts_anything_positive():
    game = _mk_game(round_=5, max_rounds=5, atype="decision", proposer="player_2",
                    last_offer={"player_1_gain": 10.0, "player_2_gain": 990.0})
    assert bargaining.decide(game)["decision"] == "accept"


def test_receiver_rejects_insulting_offer_mid_game():
    game = _mk_game(atype="decision", proposer="player_2",
                    last_offer={"player_1_gain": 20.0, "player_2_gain": 980.0})
    assert bargaining.decide(game)["decision"] == "reject"


def test_receiver_accepts_fair_offer():
    game = _mk_game(atype="decision", proposer="player_2",
                    last_offer={"player_1_gain": 500.0, "player_2_gain": 500.0})
    assert bargaining.decide(game)["decision"] == "accept"


def test_unknown_horizon_never_zero_floor():
    game = _mk_game(horizon=False, max_rounds=None, atype="offer")
    a = bargaining.decide(game)
    assert a["alice_gain"] < 1000.0


def test_tracker_delta_updates():
    t = bargaining.BargainingOpponentTracker()
    for _ in range(6):
        t.observe_rejection(0.2)
    assert t.delta_hat() < 0.75
    t2 = bargaining.BargainingOpponentTracker()
    for _ in range(6):
        t2.observe_rejection(0.5)
    assert t2.delta_hat() > 0.85


def test_unlimited_horizon_deadlock_decay():
    """Live forensics: six no-deal games from repeating one frozen offer 49
    rounds on unknown horizons. After round 14 we must converge toward even
    and accept token-positive offers."""
    def mk(round_, last_offer, atype="offer", proposer="player_1"):
        return {
            "game_family": "bargaining", "your_player": "player_1",
            "valid_actions": {"type": atype, "fields": {}},
            "game_state": {
                "money_to_divide": 10000.0, "round": round_, "max_rounds": None,
                "horizon_known": False, "delta_1": 0.9, "delta_2": 0.95,
                "current_player": proposer, "proposer": proposer,
                "last_offer": last_offer, "complete_information": True,
                "messages_allowed": False, "history": [],
            },
        }
    # round 30 as proposer: demand must be well under the greedy 97%
    a = bargaining.decide(mk(30, None))
    my_share = a["alice_gain"] / 10000.0
    assert my_share < 0.75

    # round 30 as receiver: any positive offer gets accepted
    d = bargaining.decide(mk(30, {"player_1_gain": 300.0, "player_2_gain": 9700.0},
                             atype="decision", proposer="player_2"))
    assert d["decision"] == "accept"
