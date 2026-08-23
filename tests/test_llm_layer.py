"""LLM-layer tests — all offline via mocks; never hit Groq from pytest."""

from unittest import mock

from src import llm, simulate


def _negotiation_game(history=None, atype="offer"):
    return {
        "game_family": "negotiation", "your_player": "player_1",
        "game_id": "t",
        "valid_actions": {"type": atype, "fields": {}},
        "game_state": {"round": 1, "max_rounds": 6, "horizon_known": True,
                       "current_player": "player_1",
                       "player_1_role": "seller", "player_1_value": 50.0,
                       "history": history or [], "last_offer": None,
                       "money_to_divide": 1000,
                       "complete_information": False,
                       "messages_allowed": True},
    }


CANDS = [{"product_price": 108.0}, {"product_price": 114.6},
         {"product_price": 121.2}]


def test_rank_picks_best_expected_value():
    game = _negotiation_game()
    gains = [c["product_price"] - 50.0 for c in CANDS]
    with mock.patch.object(llm, "_enabled", True), \
         mock.patch.object(llm, "json_chat",
                           lambda *a, **k: {"p_accept": [0.2, 0.8, 0.5]}):
        best, mode = simulate.rank_offers(game, CANDS, "price", gains)
    assert mode == "simulated"
    assert best["product_price"] == 114.6  # 0.8 * 64.6 beats alternatives


def test_rank_falls_back_when_llm_down():
    game = _negotiation_game()
    gains = [c["product_price"] - 50.0 for c in CANDS]
    with mock.patch.object(llm, "_enabled", True), \
         mock.patch.object(llm, "chat", lambda *a, **k: None), \
         mock.patch.object(llm, "json_chat", lambda *a, **k: None):
        best, mode = simulate.rank_offers(game, CANDS, "price", gains)
    assert best is None
    assert mode in ("llm-failed", "budget")


def test_rank_disabled_reports_budget():
    game = _negotiation_game()
    gains = [10.0, 20.0, 30.0]
    with mock.patch.object(llm, "enabled", lambda: False):
        best, mode = simulate.rank_offers(game, CANDS, "price", gains)
    assert best is None and mode == "budget"


def test_pivotal_gate():
    assert simulate.is_pivotal(_negotiation_game()) is True  # opening offer

    decided = _negotiation_game(atype="decision")
    assert simulate.is_pivotal(decided) is False

    deadlock = _negotiation_game(history=[
        {"round": r, "offer": {"price": 100 + r * 0.4, "from_player": "player_1"},
         "decision": "RejectOffer"}
        for r in range(1, 5)
    ])
    deadlock["game_state"]["last_offer"] = {"price": 101.2}
    assert simulate.is_pivotal(deadlock) is True

    midgame = _negotiation_game(history=[
        {"round": r, "offer": {"price": 90 + r * 25, "from_player": "player_2"},
         "decision": "RejectOffer"}
        for r in range(1, 3)
    ])
    assert simulate.is_pivotal(midgame) is False


def test_rate_limiter_caps():
    from collections import deque
    fake = {"keyA": deque(), "keyB": deque()}
    with mock.patch.object(llm, "_buckets", fake), \
         mock.patch.object(llm, "_enabled", True):
        ok = sum(1 for _ in range(60) if llm._take())
        assert ok == llm.RPM_CAP * 2
        assert llm.available(1) is False
    for q in fake.values():
        q.clear()


def test_bargaining_candidates_use_alice_bob_keys():
    state = {"money_to_divide": 1000.0}
    base = {"alice_gain": 580.0, "bob_gain": 420.0}
    cands = simulate.bargaining_candidates(state, "player_1", base, n=3)
    assert len(cands) == 3
    for c in cands:
        assert abs(c["alice_gain"] + c["bob_gain"] - 1000.0) < 1e-6
    # player_2 perspective keys flip correctly
    base2 = {"alice_gain": 420.0, "bob_gain": 580.0}
    cands2 = simulate.bargaining_candidates(state, "player_2", base2, n=3)
    for c in cands2:
        assert abs(c["alice_gain"] + c["bob_gain"] - 1000.0) < 1e-6


def test_agent_imports_candidates_from_simulate():
    import agent as agent_mod
    import inspect
    src = inspect.getsource(agent_mod)
    assert "negotiation.negotiation_candidates" not in src
    assert "simulate.negotiation_candidates" in src


def test_agent_bargaining_gains_use_alice_bob_keys():
    """Regression: agent.py computed gains with player_N keys against
    alice/bob-keyed candidates (live KeyError spam 2026-08-24 01:17)."""
    import inspect
    import agent as agent_mod
    src = inspect.getsource(agent_mod)
    assert 'my_key = f"{game.get' not in src
