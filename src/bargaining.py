"""Bargaining (Divide the Dollar) strategy module."""

from __future__ import annotations

from src.opponent_model import InGameModel, load_profile

_MODELS: dict[str, InGameModel] = {}


def _model(game: dict) -> InGameModel:
    gid = game["game_id"]
    if gid not in _MODELS:
        profile = load_profile((game.get("opponent") or {}).get("name"))
        m = InGameModel(game)
        if profile:
            m.implied_delta = 0.9 * (1.0 - 0.5 * profile.aggression)
        _MODELS[gid] = m
    return _MODELS[gid]


def safe_action(game: dict) -> dict:
    vtype = game["valid_actions"]["type"]
    money = game["game_state"].get("money_to_divide", 1000)
    me = game["game_state"].get("current_player", "player_1")
    if vtype == "offer":
        mine = money / 2
        theirs = money - mine
        return (
            {"alice_gain": mine, "bob_gain": theirs}
            if me == "player_1"
            else {"alice_gain": theirs, "bob_gain": mine}
        )
    return {"decision": "accept"}


def _effective_rounds_left(state: dict) -> int | None:
    if not state.get("horizon_known", False):
        return None
    max_r = state.get("max_rounds")
    if max_r is None:
        return None
    return max(0, max_r - state.get("round", 1))


def _target_share(state: dict, model: InGameModel) -> float:
    own_delta = state.get(f"delta_{state.get('current_player', 'player_1')[-1]}", 0.9)
    opp_delta = getattr(model, "implied_delta", 0.9)
    left = _effective_rounds_left(state)

    patience_edge = (own_delta - opp_delta) / max(own_delta, 1e-6)
    share = 0.5 + 0.25 * max(-0.4, min(0.4, patience_edge))

    rounds_played = state.get("round", 1) - 1
    concede_per_round = 0.06
    share -= concede_per_round * rounds_played

    if left is not None:
        if left <= 1:
            share = 0.92
        elif left == 2:
            share = 0.72
        elif left == 3:
            share = 0.62
    else:
        share = min(share + 0.05, 0.85)
    return max(0.34, min(0.95, share))


def bargaining_strategy(game: dict) -> dict:
    state = game["game_state"]
    model = _model(game)
    action_type = game["valid_actions"]["type"]
    money = state["money_to_divide"]
    me = state.get("current_player", "player_1")
    my_key = "alice_gain" if me == "player_1" else "bob_gain"
    opp_key = "bob_gain" if me == "player_1" else "alice_gain"

    try:
        if action_type == "offer":
            target = _target_share(state, model)
            mine = round(money * target, 2)
            theirs = round(money - mine, 2)
            offer = {my_key: mine, opp_key: theirs}
            pct = int(target * 100)
            offer["message"] = (
                f"{pct}/{100 - pct} is fair — waiting only shrinks the pie for both of us."
            )
            return offer

        last = state.get("last_offer")
        if not last:
            return safe_action(game)
        offered_share = last[f"{me}_gain"] / money
        left = _effective_rounds_left(state)
        own_delta = state.get(f"delta_{me[-1]}", 0.9)

        if left is not None and left == 0:
            threshold = 0.001
        elif left is not None and left == 1:
            threshold = 0.30 * own_delta
        else:
            continuation = 0.42 * own_delta
            threshold = max(continuation, 0.36)

        if offered_share >= threshold or (offered_share > 0.01 and offered_share >= threshold * 0.97):
            decision = "accept"
        else:
            decision = "reject"
        return {"decision": decision}
    except Exception:
        return safe_action(game)


def observe(game: dict, submitted: dict) -> None:
    state = game["game_state"]
    model = _MODELS.get(game["game_id"])
    if not model:
        return
    if game["valid_actions"]["type"] == "decision":
        last = state.get("last_offer")
        if last:
            me = state.get("current_player", "player_1")
            opp_share = 1.0 - last[f"{me}_gain"] / max(1e-9, state["money_to_divide"])
            model.observe_bargaining_offer(opp_share, state.get("round", 1))
