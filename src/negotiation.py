"""Negotiation (Bilateral Trade) strategy module."""

from __future__ import annotations

from src.opponent_model import InGameModel, load_profile

_MODELS: dict[str, InGameModel] = {}


def _model(game: dict) -> InGameModel:
    gid = game["game_id"]
    if gid not in _MODELS:
        profile = load_profile((game.get("opponent") or {}).get("name"))
        m = InGameModel(game)
        if profile:
            if m.interval:
                span = 200.0 * (1.0 - 0.4 * profile.aggression)
                m.interval.lo = max(m.interval.hard_lo, m.interval.hard_lo)
                m.interval.hi = min(m.interval.hi, m.interval.hi)
        _MODELS[gid] = m
    return _MODELS[gid]


def safe_action(game: dict) -> dict:
    vtype = game["valid_actions"]["type"]
    state = game["game_state"]
    me = state.get("current_player", "player_1")
    role = state.get(f"{me}_role", "seller")
    value = state.get(f"{me}_value", 100)
    if vtype == "offer":
        price = value * (1.5 if role == "seller" else 0.7)
        return {"product_price": round(price, 2)}
    last = state.get("last_offer")
    price = last["price"] if last else value
    profitable = price >= value if role == "seller" else price <= value
    if profitable:
        return {"decision": "AcceptOffer"}
    if game["valid_actions"].get("fields", {}).get("product_price") is not None or "max_rounds" not in state:
        pass
    return {"decision": "RejectOffer"}


def _rounds_left(state: dict) -> int | None:
    if not state.get("horizon_known", False):
        return None
    max_r = state.get("max_rounds")
    if max_r is None:
        return None
    return max(0, max_r - state.get("round", 1))


def negotiation_strategy(game: dict) -> dict:
    state = game["game_state"]
    model = _model(game)
    action_type = game["valid_actions"]["type"]
    me = state.get("current_player", "player_1")
    role = state.get(f"{me}_role", "seller")
    my_value = float(state.get(f"{me}_value", 100))

    try:
        interval = model.interval
        if interval is None:
            return safe_action(game)

        left = _rounds_left(state)

        if action_type == "offer":
            lo, hi = interval.lo, interval.hi
            if role == "seller":
                lo = max(lo, my_value + 0.01)
                hi = max(hi, lo)
                width = hi - lo
                patience = 0.65 if left is None else min(0.85, 0.35 + 0.25 * left)
                target = lo + width * (1.0 - patience) if left is not None else lo + width * 0.7
            else:
                hi = min(hi, my_value - 0.01) if my_value > 0 else hi
                lo = min(lo, hi)
                width = max(hi - lo, 0.0)
                patience = 0.65 if left is None else min(0.85, 0.35 + 0.25 * left)
                target = hi - width * (1.0 - patience) if left is not None else hi - width * 0.3

            if left is not None and left <= 1:
                last = state.get("last_offer")
                if last:
                    opp_price = last["price"]
                    feasible = (
                        opp_price > my_value if role == "buyer" else opp_price < my_value
                    )
                    if feasible:
                        target = (
                            opp_price - 0.5 if role == "buyer" else opp_price + 0.5
                        )
            price = round(max(0.01, target), 2)
            direction = "at most" if role == "buyer" else "at least"
            msg = f"My walk-away number here is {price:.0f} — I can do {price:.0f}, {direction}."
            return {"product_price": price, "message": msg}

        last = state.get("last_offer")
        if not last:
            return safe_action(game)
        price = float(last["price"])

        if role == "seller":
            profitable = price >= my_value
            edge = price >= interval.lo - 0.01
        else:
            profitable = price <= my_value
            edge = price <= interval.hi + 0.01

        if profitable and (left in (None, 0, 1) or edge):
            return {"decision": "AcceptOffer"}

        final_round = left == 0
        if final_round:
            return {"decision": "RejectOffer"}
        counter = round(
            price + 8.0 if role == "seller" else price - 8.0, 2
        )
        if role == "seller":
            counter = max(counter, my_value + 0.5)
        else:
            counter = min(counter, my_value - 0.5) if my_value > 1 else counter
        counter = round(max(0.01, counter), 2)
        return {
            "decision": "RejectOffer",
            "product_price": counter,
            "message": f"Meet me at {counter:.0f} and we have a deal today.",
        }
    except Exception:
        return safe_action(game)


def observe(game: dict, submitted: dict) -> None:
    model = _MODELS.get(game["game_id"])
    if not model or not model.interval:
        return
    state = game["game_state"]
    me = state.get("current_player", "player_1")
    role = state.get(f"{me}_role", "seller")
    if game["valid_actions"]["type"] == "offer":
        last = state.get("last_offer")
        if last:
            model.observe_negotiation_offer(float(last["price"]), opp_is_seller=(role != "seller"))
