"""Action validation + guaranteed-safe fallbacks.

Never burn attempts or the turn clock: validate before submit, fall back to a
legal move on any failure.
"""

CHAR_LIMIT = 2000


def safe_action(game: dict) -> dict:
    family = game["game_family"]
    action_type = game["valid_actions"]["type"]
    state = game["game_state"]

    if action_type == "offer":
        if family == "bargaining":
            half = state["money_to_divide"] / 2
            return {"alice_gain": round(half, 2), "bob_gain": round(half, 2)}
        me = state.get("current_player", "player_1")
        value = state.get(f"{me}_value")
        if value is None:
            value = (state.get("player_1_value") if me == "player_1"
                     else state.get("player_2_value", 10.0))
        return {"product_price": float(value)}
    if action_type == "seller_message":
        return {"message": "I recommend this product."}

    if family == "bargaining":
        return {"decision": "accept"}
    if family == "negotiation":
        return {"decision": "AcceptOffer"}
    return {"decision": "yes"}


def _coerce_numbers(action: dict, game: dict) -> dict:
    state = game["game_state"]
    atype = game["valid_actions"]["type"]
    if atype == "offer" and game["game_family"] == "bargaining":
        money = float(state["money_to_divide"])
        try:
            a = float(action.get("alice_gain", money / 2))
            b = float(action.get("bob_gain", money - a))
        except (TypeError, ValueError):
            a, b = money / 2, money / 2
        if abs(a + b - money) > 0.01 or a < 0 or b < 0:
            a = min(max(a, 0.0), money)
            b = money - a
            if b < 0:
                b, a = 0.0, money
        out = dict(action)
        out["alice_gain"] = round(a, 4)
        out["bob_gain"] = round(b, 4)
        return out
    if "product_price" in action:
        try:
            action["product_price"] = round(float(action["product_price"]), 4)
        except (TypeError, ValueError):
            del action["product_price"]
    return action


def _check_enums(action: dict, game: dict) -> dict | None:
    atype = game["valid_actions"]["type"]
    family = game["game_family"]
    fields = (game.get("valid_actions") or {}).get("fields") or {}
    dec = action.get("decision")
    if dec is not None and "decision" in fields:
        allowed = [v.strip().strip("'\"") for v in
                   str(fields["decision"]).split("or")]
        allowed = [a for a in allowed if a]
        if dec not in allowed:
            return None
    elif dec is not None and family == "persuasion" and atype in ("seller_recommendation", "buyer_decision"):
        if dec not in ("yes", "no"):
            return None
    return action


def validate_and_fix(game: dict, action: dict) -> dict:
    """Return a best-effort legal version of `action`, else safe_action."""
    if not isinstance(action, dict) or not action:
        return safe_action(game)

    try:
        fixed = _coerce_numbers(dict(action), game)
        checked = _check_enums(fixed, game)
        if checked is None:
            return safe_action(game)

        msg = checked.get("message")
        if isinstance(msg, str) and len(msg) > CHAR_LIMIT:
            checked["message"] = msg[:CHAR_LIMIT - 1]

        atype = game["valid_actions"]["type"]
        if atype == "offer":
            required = {"bargaining": {"alice_gain", "bob_gain"},
                        "negotiation": {"product_price"}}[game["game_family"]]
            if not required.issubset(checked):
                return safe_action(game)
        if atype in ("decision", "buyer_decision", "seller_recommendation"):
            if "decision" not in checked:
                return safe_action(game)
        return checked
    except Exception:
        return safe_action(game)
