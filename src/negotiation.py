"""Negotiation (bilateral trade) solver.

Core: maintain interval estimates of the opponent's private value from their
offers and accept/reject behavior; price inside the estimated ZOPA; anchor
aggressively-but-plausibly at open; never reject an individually-rational
offer when rounds are scarce; walk away only on near-certain negative surplus.
"""

from .state import compile_negotiation


def _round_odd(x: float) -> float:
    """Avoid round-number anchors (anchoring studies: non-round anchors work
    better and leak less precision)."""
    base = round(x)
    for delta in (3, -7, 13, 1, -1, 5, 11):
        cand = base + delta
        if cand % 10 not in (0, 5) and cand > 0:
            return float(cand)
    return float(base + 3)


def estimate_opponent_interval(history: list, role: str,
                               prior_lo: float = 0.0,
                               prior_hi: float | None = None) -> tuple[float, float]:
    """Return [lo, hi] bounds on opponent's value.
    We are seller -> estimating buyer max: their bids b imply b <= v_b? No:
    a buyer bids hoping to pay less; their true max >= bid. Rejections of our
    ask a imply v_b < a. Acceptance of a implies v_b >= a."""
    lo, hi = prior_lo, prior_hi if prior_hi is not None else float("inf")
    i_am_seller = role == "seller"
    for entry in history or []:
        decision = entry.get("decision")
        counter = entry.get("counteroffer")
        offer = entry.get("offer") or {}
        price = offer.get("price") if isinstance(offer, dict) else None
        from_player = offer.get("from_player") if isinstance(offer, dict) else None

        if i_am_seller:
            if isinstance(counter, (int, float)) and counter > 0:
                lo = max(lo, float(counter) * 0.9)
            elif price is not None and from_player == "player_2":
                lo = max(lo, float(price) * 0.85)
            if decision == "RejectOffer" and price is not None:
                hi = min(hi, float(price) * 1.15)
        else:
            if isinstance(price, (int, float)) and from_player == "player_1":
                hi = min(hi, float(price) * 1.15)
                lo = max(lo, float(price) * 0.5)
            if isinstance(counter, (int, float)):
                hi = min(hi, float(counter))
            if decision == "RejectOffer" and price is not None:
                lo = max(lo, float(price) * 0.9)
    return lo, hi


def opener(my_value: float, is_seller: bool, complete_information: bool,
           opp_hint: float | None = None) -> float:
    if complete_information:
        mid = opp_hint if opp_hint is not None else my_value * (1.6 if is_seller else 0.55)
        return _round_odd((mid + my_value * (1.4 if is_seller else 0.7)) / 2)
    mult = 2.1 if is_seller else 0.45
    return _round_odd(my_value * mult)


def seller_floor_from_history(history: list) -> float | None:
    """Lowest price the counterpart ever offered (their revealed floor proxy)."""
    prices = []
    for entry in history or []:
        offer = entry.get("offer") or {}
        if isinstance(offer, dict) and isinstance(offer.get("price"), (int, float)):
            prices.append(float(offer["price"]))
        if isinstance(entry.get("counteroffer"), (int, float)):
            prices.append(float(entry["counteroffer"]))
    return min(prices) if prices else None


def decide(game: dict, opp_value_hat: tuple[float, float] | None = None,
           type_confidence: float = 0.0) -> dict:
    st = compile_negotiation(game)
    action_type = game["valid_actions"]["type"]
    v = st.my_value

    lo_hat, hi_hat = opp_value_hat if opp_value_hat else (None, None)

    if st.is_seller:
        z_lo = v
        z_hi = hi_hat if hi_hat is not None else v * 1.8
    else:
        z_lo = lo_hat if lo_hat is not None else v * 0.45
        z_hi = v

    surplus_est = z_hi - z_lo

    if action_type == "offer":
        if st.complete_information:
            target = (v + (z_hi if st.is_seller else z_lo)) / 2 if surplus_est > 0 else v
        else:
            last = st.last_offer.get("price") if st.last_offer else None
            urgent = st.horizon_known and st.rounds_left is not None and st.rounds_left <= 2

            if last is None:
                target = opener(v, st.is_seller, False,
                                opp_hint=(hi_hat if st.is_seller else lo_hat))
            elif st.is_seller:
                # concede toward the estimated buyer max, never below our value
                anchor = max(v, last * 0.9)
                pull = 0.5 if urgent else 0.3
                gap = max(0.0, z_hi - anchor)
                target = anchor + pull * gap
                if last < v * 0.7:
                    target = max(target, last * 1.12)
            else:
                # buyer: bid up toward our value as seller firms up, capped at v
                if z_lo >= v:
                    target = v * 0.98
                elif last is not None:
                    concession = min(v, max(last * (1.06 if urgent else 1.02), (last + v) / 2))
                    target = concession
                else:
                    target = opener(v, False, False)
        price = _round_odd(max(target, 1.0))
        action = {"product_price": price}
        if st.messages_allowed:
            action["message"] = _negotiation_message(st, price)
        return action

    if action_type == "decision":
        offer = st.last_offer or {}
        try:
            price = float(offer.get("price", float("nan")))
        except (TypeError, ValueError):
            price = float("nan")

        final = st.is_final_round
        squeeze_room = (st.rounds_left is None) or (st.rounds_left > 2)

        if st.is_seller:
            ir = price >= v
            firm = _firmness(st.history)
            if ir and (not squeeze_room or price >= v * 1.02 or firm):
                return {"decision": "AcceptOffer"}
            if final:
                if ir:
                    return {"decision": "AcceptOffer"}
                return {"decision": "RejectOffer"}
            counter = _round_odd(max(v, (price / 0.92 + z_hi) / 2 if hi_hat else price * 1.18))
            action = {"decision": "RejectOffer", "product_price": counter}
            if st.messages_allowed:
                action["message"] = _negotiation_message(st, counter)
            return action

        ir = price <= v
        if ir and (not squeeze_room or price <= v * 0.98):
            return {"decision": "AcceptOffer"}
        if final:
            if ir:
                return {"decision": "AcceptOffer"}
            return {"decision": "RejectOffer"}

        if lo_hat is not None and lo_hat > v * 1.05:
            return {"decision": "WalkAway"}
        floor = seller_floor_from_history(st.history)
        if floor is not None and st.rounds_left is not None and st.rounds_left <= 3 \
                and floor > v * 1.02:
            return {"decision": "WalkAway"}
        counter = _round_odd(min(v, price * 1.06 if price and price < v else v * 0.85))
        action = {"decision": "RejectOffer", "product_price": counter}
        if st.messages_allowed:
            action["message"] = _negotiation_message(st, counter)
        return action

    return {}


def _firmness(history: list, window: int = 2) -> bool:
    """Opponent conceded <5% over their last offers => they're near their floor;
    grab the deal rather than risk it."""
    asks = []
    for entry in (history or [])[-window:]:
        offer = entry.get("offer") or {}
        if isinstance(offer, dict) and offer.get("price") is not None:
            asks.append(float(offer["price"]))
    if len(asks) < 2:
        return False
    return abs(asks[-1] - asks[-2]) / max(asks[-2], 1e-9) < 0.05


def _negotiation_message(st, price: float) -> str:
    if st.is_seller:
        if st.last_offer and st.last_offer.get("price") and price <= st.last_offer["price"]:
            return f"I've come down to {int(price)} — that's genuinely my floor."
        return f"Comparable units go for well above {int(price)}. Serious buyers move at this level."
    if st.last_offer and st.last_offer.get("price") and price >= st.last_offer["price"]:
        return f"I'll stretch to {int(price)}, but that's the end of my budget."
    return f"My research says units like this trade around {int(price)}. That's what I can do."
