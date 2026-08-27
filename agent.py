"""GLEE competition agent: dispatcher + run loop.

Usage:
    export GLEE_API_KEY=glee_...
    python agent.py [--concurrency 8] [--max-time 3600] [--families ...]
"""

import argparse
import datetime
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from glee_sdk import GleeClient

from src import bargaining, negotiation, persuasion, simulate
from src import llm
from src.opponent_model import ProfileStore
from src.safety import validate_and_fix

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("glee-agent")


class AgentState:
    """Per-process state shared across concurrent games."""

    def __init__(self):
        self.profiles = ProfileStore()
        self.bargaining_trackers: dict[str, bargaining.BargainingOpponentTracker] = {}
        self.seller_policies: dict[str, persuasion.SellerPolicy] = {}
        self.tracker_pos: dict[str, int] = {}
        self.counted_games: set[str] = set()

    def tracker(self, game_id: str) -> bargaining.BargainingOpponentTracker:
        if game_id not in self.bargaining_trackers:
            self.bargaining_trackers[game_id] = bargaining.BargainingOpponentTracker()
        return self.bargaining_trackers[game_id]

    def seller_policy(self, game_id: str) -> persuasion.SellerPolicy:
        if game_id not in self.seller_policies:
            self.seller_policies[game_id] = persuasion.SellerPolicy()
        return self.seller_policies[game_id]

    def cleanup(self, game_id: str):
        self.bargaining_trackers.pop(game_id, None)
        self.seller_policies.pop(game_id, None)


STATE = AgentState()
ABLATE = {a.strip() for a in
          os.environ.get("GLEE_ABLATE", "").split(",") if a.strip()}
GAME_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "games.jsonl")


JSONL_MAX_BYTES = 64 * 1024 * 1024


def log_game(game: dict, action: dict, origin: str = "strategy"):
    """Full replay material for forensics — schema surprises get caught here.
    Rotates at JSONL_MAX_BYTES to .prev (audit H6: unbounded disk growth)."""
    try:
        os.makedirs(os.path.dirname(GAME_LOG), exist_ok=True)
        if os.path.exists(GAME_LOG) and \
                os.path.getsize(GAME_LOG) > JSONL_MAX_BYTES:
            os.replace(GAME_LOG, GAME_LOG + ".prev")
        with open(GAME_LOG, "a") as f:
            f.write(json.dumps({"t": game.get("game_id"), "s": game.get("game_state"),
                                "a": action,
                                "origin": origin,
                                "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds")
                                }) + "\n")
    except Exception:
        pass


def update_tracker_from_history(game_id: str, game: dict):
    """Feed OPPONENT impatience signals to the tracker.

    Evidence semantics (audit C1 fix): the signal is THE OPPONENT rejecting
    OUR offer (proposer == me, decided_by == opp). Our own rejections of their
    offers say nothing about THEIR patience. Each event ingested exactly once
    per game via a processed-index watermark."""
    st = game.get("game_state") or {}
    history = st.get("history") or []
    me = game.get("your_player", "player_1")
    opp = "player_2" if me == "player_1" else "player_1"
    money = float(st.get("money_to_divide") or 1.0)
    tracker = STATE.tracker(game_id)
    start = STATE.tracker_pos.get(game_id, 0)
    for i in range(start, len(history)):
        entry = history[i]
        if str(entry.get("decision", "")).lower() not in ("reject", "rejected"):
            continue
        if entry.get("proposer") != me:
            continue
        try:
            their_gain = float((entry.get("offer") or {}).get(f"{opp}_gain", -1))
            if their_gain >= 0:
                tracker.observe_rejection(their_gain / money)
        except ZeroDivisionError:
            continue
    STATE.tracker_pos[game_id] = len(history)


def _negotiation_reject_rate(game: dict) -> float | None:
    """Fraction of OUR offers the opponent rejected (aggression proxy)."""
    st = game.get("game_state") or {}
    me = game.get("your_player", "player_1")
    opp = "player_2" if me == "player_1" else "player_1"
    mine = [h for h in (st.get("history") or [])
            if (h.get("offer") or {}).get("from_player") == me]
    if not mine:
        return None
    rejects = sum(1 for h in mine
                  if str(h.get("decision", "")).lower().startswith("reject"))
    return rejects / len(mine)


def opponent_value_interval(game: dict) -> tuple[float | None, float | None]:
    family = game["game_family"]
    if family != "negotiation":
        return None, None
    st = game["game_state"]
    me = game.get("your_player", "player_1")
    role = st.get(f"{me}_role") or ("seller" if me == "player_1" else "buyer")
    my_value = float(st.get(f"{me}_value") or 100.0)
    lo, hi = negotiation.estimate_opponent_interval(
        st.get("history"), role,
        prior_lo=0.0,
        prior_hi=my_value * 4.0 if role == "seller" else None,
    )
    return lo, hi


def strategy(game: dict) -> dict:
    import time as _t
    _turn_start = _t.monotonic()  # server turn clock starts here
    fb = False
    try:
        family = game["game_family"]
        game_id = game["game_id"]
        opp_name = (game.get("opponent") or {}).get("name")
        profile = None if ("profiles" in ABLATE or "all" in ABLATE) \
            else STATE.profiles.get(opp_name)
        if profile is not None and game_id not in STATE.counted_games:
            STATE.counted_games.add(game_id)
            profile.games_seen += 1

        if family == "bargaining":
            update_tracker_from_history(game_id, game)
            if "opp_model" in ABLATE or "all" in ABLATE:
                delta_hat = bargaining.DEFAULT_DELTA_OPP_PRIOR
                raw = bargaining.decide(game, opp_delta_hat=delta_hat)
            else:
                tracker = STATE.tracker(game_id)
                delta_hat = tracker.delta_hat()
                if profile is not None and profile.implied_delta:
                    w = min(0.5, profile.games_seen / 10.0)
                    delta_hat = (1 - w) * delta_hat + w * profile.implied_delta
                raw = bargaining.decide(game, opp_delta_hat=delta_hat,
                                        type_confidence=tracker.patience.confidence())
                if profile is not None:
                    profile.implied_delta = round(tracker.delta_hat(), 3)
        elif family == "negotiation":
            lo, hi = opponent_value_interval(game)
            scale = 1.0
            if profile is not None and profile.reject_rate is not None \
                    and profile.games_seen >= 2:
                scale = 1.0 + 0.4 * (0.5 - profile.reject_rate)
            raw = negotiation.decide(game, opp_value_hat=(lo, hi),
                                     aggression_scale=scale)
            if profile is not None:
                rr = _negotiation_reject_rate(game)
                if rr is not None:
                    old = profile.reject_rate
                    profile.reject_rate = round(rr, 3) if old is None \
                        else round(0.7 * old + 0.3 * rr, 3)
        elif family == "persuasion":
            seed = None if ("profiles" in ABLATE or "all" in ABLATE) \
                else (profile.buyer_kind if profile else None)
            policy = STATE.seller_policy(game_id)
            if seed and policy.fresh():
                # audit H2: apply the profile seed directly — the constructor
                # branch was unreachable because the policy already existed
                policy.burned_then_bought = seed == "myopic"
                policy.burned_then_passed = seed == "bayesian"
            raw = persuasion.decide(game, policy=policy,
                                    disable_signal_regime="signal_regime" in ABLATE)
            if profile is not None and policy.burned_then_bought:
                pass  # kind inferred in-game; persisted below via history kind
            if profile is not None:
                from src.opponent_model import infer_seller_type
                kind = infer_seller_type(game.get("game_state", {}).get("history") or [])["kind"]
                if kind != "unknown":
                    profile.buyer_kind = kind
        else:
            from src.safety import safe_action
            raw = safe_action(game)

        action = validate_and_fix(game, raw)

        # LLM layer: simulation-ranked candidates + drafted language on
        # pivotal offers only — routine moves stay deterministic and free.
        # Hard move-deadline: if anything above ate >25s, skip the LLM phase
        # entirely so latency never stacks into the 120s turn clock.
        # Incident 2026-08-28 00:30: 3 games timed out server-side when slow
        # Groq responses stretched sim-rank waves past the turn clock -> 403
        # queue pause. Fixes: (a) an absolute TURN deadline (90s from turn
        # start) is threaded into rank_offers/draft_message so the wave
        # itself aborts; (b) rank_offers abandons rather than joins a wedged
        # worker; (c) the whole LLM phase is skipped when <30s remain.
        try:
            import time as _t
            _turn_deadline = _turn_start + 90.0
            _move_deadline = _t.monotonic() + 25.0
            atype = game["valid_actions"]["type"]
            pivotal = simulate.is_pivotal(game)
            llm_on = llm.enabled() and not ({"sim", "all"} & ABLATE) \
                and _t.monotonic() < _move_deadline \
                and _t.monotonic() < _turn_deadline - 30.0
            if llm_on and atype == "offer" and \
                    family in ("bargaining", "negotiation"):
                st = game["game_state"]
                if family == "bargaining":
                    cands = simulate.bargaining_candidates(
                        st, game.get("your_player", "player_1"), raw)
                    money = float(st["money_to_divide"])
                    my_key = ("alice_gain" if game.get("your_player") == "player_1"
                              else "bob_gain")
                    gains = [float(c[my_key]) for c in cands]
                    best, mode = simulate.rank_offers(
                        game, cands, "money splits (alice_gain, bob_gain)", gains,
                        deadline=_turn_deadline)
                else:
                    me = game.get("your_player", "player_2")
                    v = float(st.get(f"{me}_value") or 0)
                    is_seller = (st.get(f"{me}_role") == "seller")
                    z_lo, z_hi = opponent_value_interval(game)
                    if is_seller:
                        lo_b = v
                        hi_b = z_hi if z_hi is not None else raw["product_price"] * 1.3
                    else:
                        lo_b = z_lo if z_lo is not None else raw["product_price"] * 0.7
                        hi_b = v
                    cands = simulate.negotiation_candidates(
                        v, is_seller, lo_b, hi_b,
                        float(raw.get("product_price", v)))
                    gains = [(c["product_price"] - v) if is_seller
                             else max(0.0, v - c["product_price"])
                             for c in cands]
                    best, mode = simulate.rank_offers(
                        game, cands, "price offers", gains,
                        deadline=_turn_deadline)
                if best:
                    raw = dict(best)
                    logger.info("[%s %s] sim-rank %s", family, game_id[:8], mode)
            elif llm_on and _t.monotonic() < min(_move_deadline, _turn_deadline - 15.0) \
                    and pivotal and game["valid_actions"].get("fields", {}).get("message") is not None:
                role = {"bargaining": "a negotiator splitting a pot under inflation",
                        "negotiation": "a buyer or seller trading one product",
                        "persuasion": "a seller recommending products of hidden quality"}[family]
                drafted = simulate.draft_message(game, action, role,
                                                 deadline=_turn_deadline)
                if drafted:
                    action["message"] = drafted
        except Exception:
            logger.exception("llm layer failed; keeping deterministic move")

        logger.info("[%s %s r%s] %s -> %s", family, game_id[:8],
                    game.get("game_state", {}).get("round"),
                    game["valid_actions"]["type"], action)
        log_game(game, action, origin="fallback" if fb else "strategy")
        return action

    except Exception:
        fb = True
        logger.exception("strategy failure on %s; using safe action", game.get("game_id"))
        from src.safety import safe_action
        fb_action = safe_action(game)
        log_game(game, fb_action, origin="fallback")
        return fb_action


def main():
    parser = argparse.ArgumentParser(description="GLEE competition agent")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--max-time", type=int, default=None)
    parser.add_argument("--max-games", type=int, default=None)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--families", nargs="*", default=["bargaining", "negotiation", "persuasion"])
    args = parser.parse_args()

    api_key = os.environ.get("GLEE_API_KEY")
    if not api_key:
        logger.error("Set GLEE_API_KEY environment variable")
        sys.exit(1)

    base_url = os.environ.get("GLEE_API_URL")
    client = GleeClient(api_key=api_key, base_url=base_url) if base_url else GleeClient(api_key=api_key)

    logger.info("stats: %s", client.stats())

    kwargs = {"concurrency": args.concurrency, "poll_interval": args.poll_interval}
    if args.max_time:
        kwargs["max_time"] = args.max_time
    if args.max_games:
        kwargs["max_games"] = args.max_games

    try:
        client.run(strategy, game_families=args.families, **kwargs)
    finally:
        STATE.profiles.save()
        logger.info("profiles saved")


if __name__ == "__main__":
    main()
