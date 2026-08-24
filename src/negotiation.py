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
    """Return [lo, hi] bounds on opponent's private value.

    Semantics matter (live-bug 2026-08-23): only the OPPONENT's own offers and
    the OPPONENT's responses to OUR offers are evidence.
      We are seller -> estimating buyer max v_b:
        their bid b          => v_b >= ~b          (lo bound)
        they reject our ask a => v_b < a           (hi bound)
        they accept our ask a => v_b >= a          (lo bound)
      Symmetric when we are buyer estimating seller min v_s."""
    lo, hi = prior_lo, prior_hi if prior_hi is not None else float("inf")
    i_am_seller = role == "seller"
    opp = "player_2" if i_am_seller else "player_1"
    for entry in history or []:
        offer = entry.get("offer") or {}
        price = offer.get("price") if isinstance(offer, dict) else None
        frm = offer.get("from_player") if isinstance(offer, dict) else None
        decision = entry.get("decision")
        decider = entry.get("decided_by")

        if isinstance(price, (int, float)) and frm == opp and price > 0:
            if i_am_seller:
                lo = max(lo, float(price) * 0.85)
            else:
                hi = min(hi, float(price) * 1.15)

        if isinstance(price, (int, float)) and decider == opp:
            if str(decision).lower().startswith("reject"):
                if i_am_seller:
                    hi = min(hi, float(price))
                else:
                    lo = max(lo, float(price) * 0.92)
            elif str(decision).lower().startswith("accept"):
                if i_am_seller:
                    lo = max(lo, float(price))
                else:
                    hi = min(hi, float(price))
    return lo, hi


def opener(my_value: float, is_seller: bool, complete_information: bool,
           opp_hint: float | None = None,
           aggression_scale: float = 1.0) -> float:
    """aggression_scale: >1 anchors harder vs pushovers, <1 softens vs
    opponents who punish aggressive openers (profile-derived)."""
    scale = min(max(aggression_scale, 0.8), 1.2)
    if complete_information:
        mid = opp_hint if opp_hint is not None else my_value * (1.6 if is_seller else 0.55)
        return _round_odd((mid + my_value * (1.4 if is_seller else 0.7)) / 2)
    mult = (2.1 if is_seller else 0.45)
    mult = 1 + (mult - 1) * scale if is_seller else 1 - (1 - mult) * scale
    raw = my_value * mult
    if is_seller:
        raw = min(max(raw, my_value * 1.02), my_value * 3.5)
    else:
        raw = min(max(raw, my_value * 0.2), my_value * 0.98)
    return _round_odd(raw)


def _min_capture(rounds_left: int | None, known_opp: bool) -> float:
    """Minimum share of estimated surplus we demand before accepting.
    Decays toward the endgame; complete information lets us hold firmer."""
    if rounds_left is not None and rounds_left <= 1:
        return 0.0
    base = 0.35 if known_opp else 0.2
    if rounds_left is not None:
        base *= min(1.0, (rounds_left - 1) / 4.0 + 0.3)
    return max(0.0, base)


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
           type_confidence: float = 0.0,
           aggression_scale: float = 1.0) -> dict:
    st = compile_negotiation(game)
    action_type = game["valid_actions"]["type"]
    v = st.my_value

    lo_hat, hi_hat = opp_value_hat if opp_value_hat else (None, None)

    # Complete information: both values visible — play the near-optimal split.
    if st.complete_information and st.opp_value is not None:
        fair = (v + st.opp_value) / 2.0
        if st.is_seller:
            z_lo, z_hi = v, max(st.opp_value, v)
        else:
            z_lo = min(st.opp_value, v)
            z_hi = v
    elif st.is_seller:
        z_lo = v
        z_hi = hi_hat if hi_hat is not None else v * 1.8
    else:
        z_lo = lo_hat if lo_hat is not None else v * 0.45
        z_hi = v

    surplus_est = z_hi - z_lo
    fair = ((v + z_hi) / 2.0) if st.is_seller else ((z_lo + v) / 2.0)
    if st.complete_information and st.opp_value is not None:
        fair = (v + st.opp_value) / 2.0

    if action_type == "offer":
        if st.complete_information and st.opp_value is not None:
            target = fair
        else:
            last = st.last_offer.get("price") if st.last_offer else None
            urgent = st.horizon_known and st.rounds_left is not None and st.rounds_left <= 2

            if last is None:
                target = opener(v, st.is_seller, False,
                                opp_hint=(hi_hat if st.is_seller else lo_hat),
                                aggression_scale=aggression_scale)
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
                    target = opener(v, False, False,
                                    aggression_scale=aggression_scale)
        price = _round_odd(max(target, 1.0))
        # IR clamps: never offer below our value as seller / above it as buyer
        # (F3 family — rounding snaps must not accept guaranteed losses)
        if st.is_seller:
            price = max(price, v * 1.001)
        else:
            price = min(price, v * 0.999)
        price = _round_odd(max(price, 1.0))
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
        known_opp = st.complete_information and st.opp_value is not None

        if st.is_seller:
            ir = price >= v
            capture = ((price - z_lo) / surplus_est) if surplus_est > 0 else 1.0
            want = capture >= _min_capture(st.rounds_left, known_opp)
            if ir and (want or not squeeze_room or _firmness(st.history)):
                return {"decision": "AcceptOffer"}
            if final:
                return {"decision": "AcceptOffer" if ir else "RejectOffer"}
            counter = fair if known_opp else _round_odd(
                max(v, (price / 0.92 + z_hi) / 2 if hi_hat else price * 1.18))
            counter = max(counter, v * 1.001)
            action = {"decision": "RejectOffer", "product_price": _round_odd(counter)}
            if st.messages_allowed:
                action["message"] = _negotiation_message(st, counter)
            return action

        ir = price <= v
        capture = ((z_hi - price) / surplus_est) if surplus_est > 0 else 1.0
        want = capture >= _min_capture(st.rounds_left, known_opp)
        if ir and (want or not squeeze_room):
            return {"decision": "AcceptOffer"}
        if final:
            return {"decision": "AcceptOffer" if ir else "RejectOffer"}

        # Walk away only on near-certain negative surplus.
        neg_surplus = (known_opp and st.opp_value > v) or \
            (lo_hat is not None and lo_hat > v * 1.05)
        if neg_surplus:
            return {"decision": "WalkAway"}
        floor = seller_floor_from_history(st.history)
        if floor is not None and st.rounds_left is not None and st.rounds_left <= 3 \
                and floor > v * 1.02:
            return {"decision": "WalkAway"}
        if known_opp:
            counter = fair
        else:
            counter = _round_odd(min(v, price * 1.06 if price and price < v else v * 0.85))
        # hard ceiling: never counter above our own max (F3 — rounding snap
        # could overshoot by a few units, accepting a guaranteed loss)
        counter = min(counter, v * 0.999)
        action = {"decision": "RejectOffer", "product_price": _round_odd(counter)}
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
