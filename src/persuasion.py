"""Persuasion (repeated strategic information transmission) solver.

Seller: reputation-aware signaling policy — build trust, exploit in the
endgame window against buyers proven to condition on history; farm myopic
buyers immediately.
Buyer: decayed reliability posterior over the seller's recommendations;
message text carries zero evidential weight; endgame suspicion escalation.
"""

from .opponent_model import DecayedBeta, infer_seller_type
from .state import compile_persuasion

HONEST_PHASE_EXPLOIT = 0.05
MID_EXPLOIT = 0.15


class SellerPolicy:
    """Per-game seller state machine."""

    def __init__(self):
        self.burned_then_bought = False
        self.burned_then_passed = False
        self.recents: list[tuple[bool, str | None]] = []

    def observe(self, history: list):
        info = infer_seller_type(history)
        self.burned_then_bought = info["burned_then_bought"]
        self.burned_then_passed = info["burned_then_passed"]
        for entry in (history or [])[-5:]:
            bought = entry.get("bought")
            if bought:
                self.recents.append((True, entry.get("quality")))
            elif bought is False:
                self.recents.append((False, None))

    def exploit_rate(self, rounds_left: int) -> float:
        if self.burned_then_bought and not self.burned_then_passed:
            return 0.95
        if self.burned_then_passed or len(self.recents) < 2:
            if rounds_left <= 3:
                return 0.35 + 0.15 * (4 - min(rounds_left, 4))
            return HONEST_PHASE_EXPLOIT if rounds_left > 6 else MID_EXPLOIT
        trust = sum(1 for b, _ in self.recents[-4:] if b) / max(1, min(4, len(self.recents)))
        if rounds_left <= 2 and trust >= 0.75:
            return 0.7
        if rounds_left <= 3 and trust >= 0.6:
            return 0.45
        return MID_EXPLOIT

    def recommend(self, quality: str, rounds_left: int, rng=None) -> dict:
        import random
        rng = rng or random
        rate = self.exploit_rate(rounds_left)
        claim_high = quality == "high" or rng.random() < rate
        decision = "yes" if claim_high else "no"
        return {"decision": decision}

    def message(self, quality: str, rounds_left: int, rng=None) -> dict:
        import random
        rng = rng or random
        rate = self.exploit_rate(rounds_left)
        claiming_high = quality == "high" or rng.random() < rate
        if claiming_high:
            msg = ("Inspected this one personally — it's the high-grade unit today. "
                   "At this price it's an easy call.")
        else:
            msg = ("Today's unit is serviceable — nothing fancy, does the job. "
                   "Worth it if you need one now.")
        return {"message": msg}


def seller_decide(game: dict, policy: SellerPolicy | None = None) -> dict:
    st = compile_persuasion(game)
    policy = policy or SellerPolicy()
    policy.observe(st.history)
    rl = st.rounds_left

    action_type = game["valid_actions"]["type"]
    if action_type == "seller_recommendation":
        return policy.recommend(st.current_quality, rl)
    if action_type == "seller_message":
        return policy.message(st.current_quality, rl)
    return {}


def buyer_reliability(history: list) -> DecayedBeta:
    """Evidence from purchased rounds only (only those reveal quality)."""
    beta = DecayedBeta(alpha=2.0, beta=2.0, decay=0.65)
    for entry in history or []:
        if not entry.get("bought"):
            continue
        beta.update(entry.get("quality") == "high")
    return beta


def _buy_margin(rounds_left: int | None) -> float:
    """Required EV/price ratio. Grows superlinearly with the seller's
    endgame defection incentive."""
    if rounds_left is None:
        return 1.05
    steps = min(max(0, 4 - rounds_left), 4)
    return 1.0 + 0.04 * steps ** 1.5


def estimate_v(history: list, price: float, p: float) -> float:
    """Estimate the buyer's high-quality value when v is hidden.

    Bought rounds reveal realized value: buyer_payoff = value - price on a
    high purchase. Fall back to a p-scaled prior so we still participate."""
    revealed = []
    for entry in history or []:
        if not entry.get("bought"):
            continue
        payoff = entry.get("buyer_payoff")
        if payoff is None:
            continue
        try:
            val = float(payoff) + float(price)
            if val > 0 and entry.get("quality") != "low":
                revealed.append(val)
        except (TypeError, ValueError):
            continue
    if revealed:
        return max(revealed[-3:])
    return (price / max(p, 0.1)) * 1.2


def buyer_decide(game: dict) -> dict:
    st = compile_persuasion(game)
    beta = buyer_reliability(st.history)

    n_eff = beta.n_effective
    w_emp = n_eff / (n_eff + 1.5)
    p_hat = (1 - w_emp) * st.p + w_emp * beta.mean

    # Deception penalty: a low-quality purchase among recent buys is direct
    # evidence of active misrepresentation — discount harder than Bayes alone.
    recent_buys = [e for e in (st.history or []) if e.get("bought")][-3:]
    if any(e.get("quality") == "low" for e in recent_buys):
        p_hat *= 0.7

    v_hat = st.v if st.v is not None else estimate_v(st.history, st.price, st.p)
    ev = p_hat * v_hat + (1.0 - p_hat) * st.u
    decision = "yes" if ev > st.price * _buy_margin(st.rounds_left) else "no"
    return {"decision": decision}


def decide(game: dict, policy: SellerPolicy | None = None) -> dict:
    st = compile_persuasion(game)
    if st.am_seller:
        return seller_decide(game, policy)
    return buyer_decide(game)
