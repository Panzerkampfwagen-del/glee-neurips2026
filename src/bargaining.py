"""Bargaining solver: Rubinstein infinite-horizon + finite-horizon backward induction.

Deltas are per-round discount multipliers (0.9 = lose 10%/round).
Offers must sum EXACTLY to money_to_divide.
"""

from .opponent_model import DecayedBeta
from .state import compile_bargaining

DEFAULT_DELTA_OPP_PRIOR = 0.9
FAIRNESS_PAD = 0.06
FIELD_MIN_CONCESSION = 0.36


def infinite_horizon_shares(d_me: float, d_opp: float, money: float) -> tuple[float, float]:
    """Stationary Rubinstein split (my share, opponent share)."""
    d_me = min(max(d_me, 0.01), 0.999)
    d_opp = min(max(d_opp, 0.01), 0.999)
    s_me = (1.0 - d_opp) / (1.0 - d_me * d_opp)
    return money * s_me, money * (1.0 - s_me)


def backward_induction(d_me: float, d_opp: float, money: float,
                       rounds_left: int) -> tuple[list[float], list[float]]:
    """V_ip[k]: my pie-value when I propose with k offers left (incl. this one).
    V_tp[k]: same when the opponent proposes. Alternating proposers."""
    V_ip = [0.0] * (rounds_left + 1)
    V_tp = [0.0] * (rounds_left + 1)
    for k in range(1, rounds_left + 1):
        opp_cont = d_opp * V_tp[k - 1]
        V_ip[k] = money - min(max(opp_cont, 0.0), money)
        my_cont = d_me * V_ip[k - 1]
        V_tp[k] = money - min(max(my_cont, 0.0), money)
    return V_ip, V_tp


def solve_thresholds(d_me: float, d_opp: float, money: float,
                     rounds_left: int | None) -> dict:
    """Returns accept_floor (share of current pot), propose_share,
    opp_share_when_i_propose."""
    if rounds_left is None:
        mine, theirs = infinite_horizon_shares(d_me, d_opp, money)
        return {"accept_floor": d_me * mine, "propose_share": mine,
                "opp_share_when_i_propose": theirs}

    if rounds_left <= 0:
        return {"accept_floor": 0.0, "propose_share": money,
                "opp_share_when_i_propose": 0.0}

    V_ip, V_tp = backward_induction(d_me, d_opp, money, rounds_left)

    if rounds_left == 1:
        accept_floor = 0.0
        propose_share = money
        opp_share = 0.0
    else:
        accept_floor = d_me * V_ip[rounds_left - 1]
        opp_cont = d_opp * V_tp[rounds_left - 1]
        propose_share = money - min(max(opp_cont, 0.0), money)
        opp_share = money - propose_share

    return {"accept_floor": max(accept_floor, 0.0),
            "propose_share": max(propose_share, 0.0),
            "opp_share_when_i_propose": max(opp_share, 0.0),
            "continuation": V_ip[rounds_left - 1] if rounds_left > 1 else 0.0}


def decide(game: dict, opp_delta_hat: float = DEFAULT_DELTA_OPP_PRIOR,
           type_confidence: float = 0.0) -> dict:
    """Main entry: choose a bargaining action from the raw game dict."""
    st = compile_bargaining(game)
    money = st.money
    action_type = game["valid_actions"]["type"]

    rl = max(1, st.rounds_left) if st.horizon_known and st.rounds_left else None
    sol = solve_thresholds(st.delta_me, opp_delta_hat, money, rl)

    if action_type == "offer":
        opp_share = sol["opp_share_when_i_propose"]
        pad = FAIRNESS_PAD * money * (1.0 - type_confidence)
        opp_share = max(opp_share + pad, 0.0)

        # Population floor: pure finite-horizon SPE demands crumbs the field
        # will reject (live-verified 9.3% outcome). Blend toward SPE only as
        # opponent-type confidence grows (exploitability-gated deviation).
        spe_frac = opp_share / money if money > 0 else 0.5
        blended_frac = type_confidence * spe_frac + (1.0 - type_confidence) * max(
            spe_frac, FIELD_MIN_CONCESSION)
        opp_share = max(0.02 * money, min(blended_frac * money, money))
        my_gain = money - opp_share

        alice = my_gain if st.my_player == "player_1" else opp_share
        bob = money - alice
        action = {"alice_gain": round(alice, 2), "bob_gain": round(money - alice, 2)}
        if abs(action["alice_gain"] + action["bob_gain"] - money) > 1e-6:
            action["bob_gain"] = round(money - action["alice_gain"], 6)

        if st.messages_allowed:
            frac = sol["propose_share"] / money
            action["message"] = _offer_message(frac)
        return action

    if action_type == "decision":
        offer = st.last_offer or {}
        key = f"{st.current_player}_gain"
        try:
            my_gain = float(offer.get(key, 0.0))
        except (TypeError, ValueError):
            my_gain = 0.0

        buffer = 0.01 * money if (rl is None or rl > 2) else 0.0
        if my_gain >= sol["accept_floor"] + buffer:
            return {"decision": "accept"}
        if rl is not None and rl <= 1 and my_gain > 0:
            return {"decision": "accept"}
        return {"decision": "reject"}

    return {}


def _offer_message(demand_frac: float) -> str:
    if demand_frac >= 0.58:
        return "Waiting costs us both every round — this split reflects who can afford to wait."
    if demand_frac >= 0.45:
        return "Close to even; we both walk away better than a no-deal."
    return "The math favors this split — dragging it out only shrinks the pot."


class BargainingOpponentTracker:
    """In-game estimate of opponent impatience from their rejection behavior."""

    def __init__(self):
        self.patience = DecayedBeta(alpha=3.0, beta=3.0, decay=0.8)

    def observe_rejection(self, offered_frac_to_them: float):
        if offered_frac_to_them >= 0.45:
            self.patience.update(True)
        elif offered_frac_to_them < 0.35:
            self.patience.update(False)

    def delta_hat(self) -> float:
        conf = self.patience.confidence()
        est = 0.55 + 0.42 * self.patience.mean
        return (1.0 - conf) * DEFAULT_DELTA_OPP_PRIOR + conf * est
