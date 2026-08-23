"""Persuasion (Strategic Information Transmission) strategy module."""

from __future__ import annotations

from src.opponent_model import InGameModel, load_profile

_MODELS: dict[str, InGameModel] = {}


def _model(game: dict) -> InGameModel:
    gid = game["game_id"]
    if gid not in _MODELS:
        profile = load_profile((game.get("opponent") or {}).get("name"))
        m = InGameModel(game)
        if profile:
            m.reliability.alpha += profile.honesty_rate * 2.0
            m.reliability.beta += (1.0 - profile.honesty_rate) * 2.0
        _MODELS[gid] = m
    return _MODELS[gid]


def safe_action(game: dict) -> dict:
    vtype = game["valid_actions"]["type"]
    state = game["game_state"]
    me = state.get("current_player", "player_1")
    if vtype in ("seller_message", "seller_recommendation"):
        if vtype == "seller_message":
            return {"message": "Honest take: buy only if this fits your needs."}
        quality = state.get("current_quality")
        return {"decision": "yes" if quality == "high" else "no"}
    price = float(state.get("product_price", 0))
    p = float(state.get("p", 0.5))
    v = float(state.get("v", price * 2))
    u = float(state.get("u", 0))
    expected = p * v + (1 - p) * u
    return {"decision": "yes" if expected > price else "no"}


def _empirical_honesty(state: dict) -> tuple[float, int]:
    """P(HIGH | recommended) from rounds the BUYER purchased (only those reveal)."""
    history = state.get("history", [])
    recs_high = 0
    recs_total = 0
    for h in history:
        bought = h.get("bought") or h.get("buyer_decision") == "yes"
        msg = h.get("seller_message")
        recommended = (
            msg == "yes"
            or (isinstance(msg, str) and msg.lower().startswith(("yes", "buy", "recommend")))
            or (isinstance(msg, dict) and msg.get("recommend"))
        )
        quality = h.get("quality")
        if bought and recommended and quality is not None:
            recs_total += 1
            if quality == "high":
                recs_high += 1
    return (recs_high / recs_total if recs_total else None), recs_total


def seller_strategy(game: dict, model: InGameModel) -> dict:
    state = game["game_state"]
    vtype = game["valid_actions"]["type"]
    quality = state.get("current_quality")
    total = int(state.get("total_rounds", 10))
    rnd = int(state.get("round", 1))
    remaining = max(0, total - rnd)
    history = state.get("history", [])
    trust_proxy = sum(
        1
        for h in history
        if (h.get("seller_message") == "yes" or h.get("bought"))
        and h.get("buyer_decision") == "yes"
    )

    if vtype == "seller_recommendation":
        if quality == "high":
            return {"decision": "yes"}
        bluff_value = 0.0
        if remaining <= 1 and trust_proxy >= 3:
            bluff_value = 0.8
        elif remaining <= 2 and trust_proxy >= 5:
            bluff_value = 0.35
        return {"decision": "yes" if bluff_value > 0.5 else "no"}

    if quality == "high":
        return {
            "message": (
                "Straight recommendation: this one is high quality. "
                "You know my record — check it against what you've received."
            )
        }
    if remaining <= 1 and trust_proxy >= 4:
        return {"message": "Strong pick this round — I'd grab it."}
    return {
        "message": (
            "Honest take: skip this one, it's not worth the price. "
            "Better to keep your budget for a good round."
        )
    }


def buyer_strategy(game: dict, model: InGameModel) -> dict:
    state = game["game_state"]
    price = float(state.get("product_price", 0))
    p_prior = float(state.get("p", 0.5))
    v = float(state.get("v", 0))
    u = float(state.get("u", 0))
    total = int(state.get("total_rounds", 10))
    rnd = int(state.get("round", 1))

    emp, n = _empirical_honesty(state)
    if emp is None or n < 2:
        post_h = p_prior
    else:
        w = min(1.0, n / 6.0)
        post_h = w * emp + (1 - w) * p_prior

    trust = model.trust_in_recommendations(rnd, total)
    msg_type = state.get("seller_message_type")
    last_msg = state.get("seller_message")

    if msg_type == "binary" or last_msg == "yes":
        effective_p = post_h * trust + p_prior * (1 - trust) * 0.5 + 0.5 * trust * (1 - post_h)
        effective_p = post_h * trust + p_prior * 0.5 * (1 - trust)
    else:
        hedged = isinstance(last_msg, str) and any(
            t in last_msg.lower() for t in ("maybe", "perhaps", "might", "skip")
        )
        text_trust = trust * (0.6 if not hedged else 0.3)
        effective_p = post_h * 0.7 + p_prior * 0.3
        effective_p = effective_p * (0.9 + 0.2 * text_trust)

    expected = effective_p * v + (1 - effective_p) * u
    margin_buffer = price * (0.05 if rnd < total - 2 else 0.0)
    buy = expected > price + margin_buffer
    return {"decision": "yes" if buy else "no"}


def persuasion_strategy(game: dict) -> dict:
    try:
        model = _model(game)
        state = game["game_state"]
        action_type = game["valid_actions"]["type"]
        me = state.get("current_player", "player_1")
        if action_type in ("seller_message", "seller_recommendation"):
            return seller_strategy(game, model)
        if action_type == "buyer_decision":
            return buyer_strategy(game, model)
        return safe_action(game)
    except Exception:
        return safe_action(game)


def observe(game: dict, submitted: dict) -> None:
    model = _MODELS.get(game["game_id"])
    if not model:
        return
    state = game["game_state"]
    if game["valid_actions"]["type"] == "seller_recommendation":
        if submitted.get("decision") == "yes":
            model._purchases_following_recs = getattr(model, "_purchases_following_recs", 0)
