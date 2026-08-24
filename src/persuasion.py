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

    def __init__(self, seed_kind: str | None = None):
        self.burned_then_bought = seed_kind == "myopic"
        self.burned_then_passed = seed_kind == "bayesian"
        self.recents: list[tuple[bool, str | None]] = []
        self.pass_streak = 0
        self.probe_pending = False

    def fresh(self) -> bool:
        """True until any in-game observation — profile seeds only apply then."""
        return not self.recents

    def observe(self, history: list):
        info = infer_seller_type(history)
        if info["kind"] != "unknown":
            self.burned_then_bought = info["burned_then_bought"]
            self.burned_then_passed = info["burned_then_passed"]
        for entry in (history or [])[-5:]:
            bought = entry.get("bought")
            if bought:
                self.recents.append((True, entry.get("quality")))
            elif bought is False:
                self.recents.append((False, None))
        # Recovery mode: a buyer passing repeatedly is re-earning trust only
        # from honest rounds — stop exploiting entirely until they return.
        self.pass_streak = 0
        for entry in reversed(history or []):
            if entry.get("bought"):
                break
            self.pass_streak += 1
        # Explicit probe: right after a successful low-sale, recommend yes ONCE
        # more. Buying again proves myopia (farm them); passing proves they
        # condition on history (go honest). Passive waiting costs many rounds.
        self.probe_pending = False
        hist = history or []
        for i in range(len(hist) - 1, -1, -1):
            e = hist[i]
            if e.get("bought") and e.get("quality") == "low":
                # most recent burn; probe only if no reaction observed yet
                self.probe_pending = i == len(hist) - 1
                break
            if e.get("bought"):
                break

    def exploit_rate(self, rounds_left: int) -> float:
        if self.pass_streak >= 3 and not self.probe_pending:
            return 0.0
        if self.probe_pending:
            return 0.95
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


def seller_decide(game: dict, policy: SellerPolicy | None = None,
                  seed_kind: str | None = None) -> dict:
    st = compile_persuasion(game)
    policy = policy or SellerPolicy(seed_kind=seed_kind)
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


def _claim_of(entry: dict) -> bool | None:
    """True/False if the seller's claim this round is classifiable."""
    msg = entry.get("seller_message")
    if isinstance(msg, str) and msg.strip().lower() in ("yes", "no"):
        return msg.strip().lower() == "yes"
    if isinstance(msg, dict):
        d = msg.get("decision")
        if d in ("yes", "no"):
            return d == "yes"
    return None


def buyer_posterior(history: list, claimed_yes: bool | None) -> tuple[DecayedBeta, int]:
    """Posterior over quality CONDITIONED on the seller's current claim class,
    plus overall purchase count. In binary mode a selective liar says 'no' on
    lows — so P(high | yes) >> base rate and P(high | no) << base rate."""
    yes = DecayedBeta(alpha=2.0, beta=2.0, decay=0.65)
    no = DecayedBeta(alpha=2.0, beta=2.0, decay=0.65)
    n_all = 0
    for entry in history or []:
        if not entry.get("bought"):
            continue
        n_all += 1
        claim = _claim_of(entry)
        target = yes if claim else no
        target.update(entry.get("quality") == "high")
    return (yes if claimed_yes else no), n_all


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


def signal_regime(history: list) -> str:
    """'uninformative' if the seller's claims are effectively constant —
    a constant signal carries zero information, so P(high) stays at the base
    rate p and purchase history must NOT shift our belief (the seller cannot
    influence quality draws). 'informative' = varying claims. 'unknown' =
    too few classified rounds."""
    known = [c for c in (_claim_of(e) for e in history or [])
             if c is not None]
    if len(known) < 3:
        return "unknown"
    yes_rate = sum(known) / len(known)
    if yes_rate >= 0.95 or yes_rate <= 0.05:
        return "uninformative"
    return "informative"


def buyer_decide(game: dict, skip_regime: bool = False) -> dict:
    st = compile_persuasion(game)
    history = st.history or []
    regime = "informative" if skip_regime else signal_regime(history)

    # Uninformative seller: quality draws are independent of their constant
    # claim — no posteriors, no streaks, no endgame suspicion (none of it
    # applies when the message carries no information about this round).
    if regime == "uninformative":
        v_hat = st.v if st.v is not None else estimate_v(history, st.price, st.p)
        ev = st.p * v_hat + (1.0 - st.p) * st.u
        return {"decision": "yes" if ev > st.price else "no"}

    last = history[-1] if history else {}
    claimed_yes = _claim_of(last)
    beta, n_all = buyer_posterior(history, claimed_yes)

    n_eff = beta.n_effective
    w_emp = n_eff / (n_eff + 1.5)
    p_hat = (1 - w_emp) * st.p + w_emp * beta.mean

    # Recency-limited deception penalty (informative regime only): a low
    # purchase among the last two buys suggests their differentiated claims
    # are polluted — but it must fade, else one burn locks us out forever.
    recent_buys = [e for e in history if e.get("bought")][-2:]
    if any(e.get("quality") == "low" for e in recent_buys):
        p_hat *= 0.8

    v_hat = st.v if st.v is not None else estimate_v(history, st.price, st.p)
    ev = p_hat * v_hat + (1.0 - p_hat) * st.u

    # Two consecutive low purchases on our buys while their claims varied:
    # near-certain active liar — demand far stronger evidence.
    margin = _buy_margin(st.rounds_left)
    bought_seq = [e for e in history if e.get("bought")]
    if len(bought_seq) >= 2 and all(
            e.get("quality") == "low" for e in bought_seq[-2:]):
        margin *= 3.0

    decision = "yes" if ev > st.price * margin else "no"
    return {"decision": decision}


def decide(game: dict, policy: SellerPolicy | None = None,
           seed_kind: str | None = None,
           disable_signal_regime: bool = False) -> dict:
    """disable_signal_regime: ablation flag — reproduces pre-F6 buyer behavior
    by skipping the uninformative-regime branch."""
    st = compile_persuasion(game)
    if st.am_seller:
        return seller_decide(game, policy, seed_kind=seed_kind)
    return buyer_decide(game, skip_regime=disable_signal_regime)
