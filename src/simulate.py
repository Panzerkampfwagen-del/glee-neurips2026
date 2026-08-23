"""Pivotal-move detection + simulation-ranked candidate selection.

Deterministic solver stays canonical; the LLM only ranks candidates on
pivotal moves and drafts language. Every LLM path has a deterministic
fallback — the agent never depends on Groq being up.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from src import llm

logger = logging.getLogger("glee.llm")


def is_pivotal(game: dict, deadlock_threshold: float = 0.05) -> bool:
    st = game.get("game_state") or {}
    if game["valid_actions"]["type"] != "offer":
        return False
    # opening offer of the game
    history = st.get("history") or []
    if not history:
        return True
    # deadlock: recent counters barely moving
    offers = []
    money = float(st.get("money_to_divide") or 0)
    for h in (st.get("history") or [])[-6:]:
        o = h.get("offer") or {}
        if isinstance(o.get("price"), (int, float)):
            offers.append(float(o["price"]))
        elif money and isinstance(o.get("player_1_gain"), (int, float)):
            me = game.get("your_player", "player_1")
            offers.append(float(o.get(f"{me}_gain") or 0))
    if len(offers) >= 4:
        gaps = [abs(offers[i] - offers[i + 1]) / max(abs(offers[i]), 1e-9)
                for i in range(len(offers) - 1)]
        if sum(gaps[-2:]) / 2 < deadlock_threshold:
            return True
    horizon = st.get("horizon_known") and st.get("max_rounds") is not None
    if horizon:
        left = st["max_rounds"] - st.get("round", 1) + 1
        if left <= 2:
            return True
    return False


def bargaining_candidates(state: dict, me: str, base_action: dict,
                          n: int = 5) -> list[dict]:
    """Variants around the solver target: ±concession nudges on my gain."""
    money = float(state["money_to_divide"])
    key = f"{me}_gain"
    opp_key = "bob_gain" if key == "alice_gain" else "alice_gain"
    mine = float(base_action[key])
    out = []
    for delta in (-0.06, -0.03, 0.0, 0.03, 0.06)[:max(3, n)]:
        m = min(max(mine * (1.0 + delta), money * 0.05), money * 0.95)
        a = {key: round(m, 2), opp_key: round(money - m, 2)}
        if abs(a[key] + a[opp_key] - money) > 1e-6:
            a[opp_key] = round(money - a[key], 6)
        out.append(a)
    return out


def negotiation_candidates(my_value: float, is_seller: bool,
                           z_lo: float, z_hi: float,
                           base_price: float, n: int = 5) -> list[dict]:
    span = (z_hi - z_lo) if z_hi > z_lo else max(base_price * 0.08, 1.0)
    out = []
    for frac in (-0.12, -0.06, 0.0, 0.06, 0.12)[:max(3, n)]:
        p = base_price + frac * span
        if is_seller:
            p = min(max(p, my_value * 1.01), z_hi * 1.15)
        else:
            p = min(max(p, z_lo * 0.85), my_value * 0.99)
        out.append({"product_price": round(max(p, 1.0), 2)})
    return out


def summarize_history(game: dict, limit: int = 8) -> str:
    st = game.get("game_state") or {}
    fam = game["game_family"]
    lines = []
    for h in (st.get("history") or [])[-limit:]:
        if fam == "bargaining":
            o = h.get("offer") or {}
            lines.append(f"r{h.get('round')}: proposer={h.get('proposer')} "
                         f"split=({o.get('player_1_gain')},{o.get('player_2_gain')}) "
                         f"decision={h.get('decision')}")
        elif fam == "negotiation":
            o = h.get("offer") or {}
            lines.append(f"r{h.get('round')}: price={o.get('price')} "
                         f"from={o.get('from_player')} decision={h.get('decision')}")
        else:
            lines.append(f"r{h.get('round')}: bought={h.get('bought')} "
                         f"quality={h.get('quality')}")
    return "\n".join(lines) or "(no history yet)"


SIM_PROMPT = """You are predicting how an opponent will respond in a 2-player \
economic negotiation. Based on their observed behavior, estimate the \
probability they ACCEPT each candidate offer.

Opponent behavior so far:
{history}

Candidates (my proposed {target_desc}):
{candidates}

Reply with ONLY JSON: {{"p_accept": [<number 0-1 per candidate, same order>]}}"""


def rank_offers(game: dict, candidates: list[dict], target_desc: str,
                gains: list[float], timeout_per_call: float = 9.0) -> tuple[dict | None, str]:
    """Returns (best_candidate_or_None, mode). mode explains what happened."""
    if not candidates:
        return None, "no-candidates"
    if not llm.enabled() or len(candidates) == 1 or \
            not llm.available(len(candidates)):
        return None, "budget"
    prompt = SIM_PROMPT.format(
        history=summarize_history(game),
        target_desc=target_desc,
        candidates="\n".join(f"{i+1}. {json_dumps(c)}" for i, c in enumerate(candidates)),
    )
    messages = [
        {"role": "system", "content":
            "You are a concise game-theory assistant. Output only valid JSON."},
        {"role": "user", "content": prompt},
    ]
    with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as pool:
        futures = [pool.submit(llm.json_chat, messages, None, timeout_per_call, 120)
                   for _ in range(1)]
        probs = None
        for f in futures:
            probs = f.result()
    if not probs or "p_accept" not in probs:
        return None, "llm-failed"
    try:
        plist = [min(max(float(x), 0.0), 1.0) for x in probs["p_accept"]][:len(candidates)]
    except (TypeError, ValueError):
        return None, "llm-failed"
    if len(plist) < len(candidates):
        plist += [0.5] * (len(candidates) - len(plist))
    best_i = max(range(len(candidates)),
                 key=lambda i: plist[i] * gains[i])
    logger.info("sim-ranked %d candidates, p=%s -> #%d",
                len(candidates), [round(p, 2) for p in plist], best_i + 1)
    return candidates[best_i], "simulated"


def json_dumps(d: dict) -> str:
    import json
    return json.dumps(d)


DRAFT_PROMPT = """You are {role} in {family}. Your chosen action: {action}
Game context:
{context}
Write ONE short strategic message (under 45 words) to send with this action.
Stay perfectly consistent with the action and your prior claims. No quotes,
no explanation — just the message text."""


def draft_message(game: dict, action: dict, role_desc: str) -> str | None:
    if not llm.available(1):
        return None
    context = summarize_history(game, limit=5)
    text = llm.chat([
        {"role": "system", "content":
            "You are a sharp, credible negotiator. Output only the message."},
        {"role": "user", "content": DRAFT_PROMPT.format(
            role=role_desc, family=game["game_family"],
            action=json_dumps({k: v for k, v in action.items() if k != "message"}),
            context=context)},
    ], timeout=8.0, max_tokens=80)
    if not text:
        return None
    text = text.strip().strip('"').strip()
    return text[:200] if text else None
