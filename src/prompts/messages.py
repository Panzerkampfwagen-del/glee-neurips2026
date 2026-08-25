"""Message-layer prompt templates for the LLM language policy.

Contract with src/simulate.py:
- Templates are filled by callers; all numeric values come from the solver,
  never from the LLM.
- Every drafted message must survive safety.validate_and_fix (<=2000 chars).
- Persona cards set tone only; they never instruct the model to change the
  numeric action.
"""

PERSONA_BARGAINING = (
    "You are a patient negotiator dividing a fixed pot under inflation. "
    "Your numbers are already decided; your job is only to state them "
    "with calm confidence."
)
PERSONA_NEGOTIATION = (
    "You are a trader closing a bilateral price deal. Your number is final; "
    "justify it briefly with one reference point, never invent new terms."
)
PERSONA_PERSUASION_SELLER = (
    "You are a seller with a verifiable honesty record. Recommend truthfully; "
    "when you skip a product, say so plainly — credibility is your inventory."
)

OPENER_BARGAINING = (
    "{share_pct}/{rest_pct} split. Waiting costs us both {erosion}% per round; "
    "this split reflects who can afford to wait."
)
OPENER_NEGOTIATION_SELLER = (
    "Asking {price:.0f}. Comparable units trade near this; my floor is firm."
)
OPENER_NEGOTIATION_BUYER = (
    "Offering {price:.0f}. That matches what this is worth to me today."
)
COUNTER_DEADLOCK = (
    "We are {gap:.0f} apart on a deal worth having. Meet me at {target:.0f} "
    "and we close now instead of splitting nothing."
)
FINAL_ROUND = (
    "Last round: accepting {offer:.0f} beats zero for both of us. "
    "I am accepting anything positive."
)
PERSUASION_RECOMMEND_HIGH = (
    "Straight recommendation: this one is high quality. Check it against my "
    "record — every claim I have made is verifiable in your purchase history."
)
PERSUASION_SKIP_LOW = (
    "Honest take: skip this round. Not worth the price. Save your budget for "
    "a good draw."
)
PERSUASION_BLUFF_LATE = (
    "Strong pick this round. I would take it."
)


def bargaining_message(share: float, erosion_per_round_pct: float | None) -> str:
    rest = 100.0 - share * 100.0
    if erosion_per_round_pct is not None:
        return OPENER_BARGAINING.format(
            share_pct=int(share * 100), rest_pct=int(rest),
            erosion=erosion_per_round_pct)
    return f"{int(share*100)}/{int(rest)} split — waiting shrinks the pie for both."


def negotiation_message(role: str, price: float, phase: str = "opener",
                        gap: float | None = None) -> str:
    if phase == "deadlock" and gap is not None:
        return COUNTER_DEADLOCK.format(gap=gap, target=price)
    if phase == "final":
        return FINAL_ROUND.format(offer=price)
    if role == "seller":
        return OPENER_NEGOTIATION_SELLER.format(price=price)
    return OPENER_NEGOTIATION_BUYER.format(price=price)


def persuasion_message(quality_class: str, late_bluff: bool = False) -> str:
    if quality_class == "high":
        return PERSUASION_RECOMMEND_HIGH
    if late_bluff:
        return PERSUASION_BLUFF_LATE
    return PERSUASION_SKIP_LOW
