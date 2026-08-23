"""GLEE competition agent: dispatcher + run loop.

Usage:
    export GLEE_API_KEY=glee_...
    python agent.py [--concurrency 8] [--max-time 3600] [--families ...]
"""

import argparse
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
GAME_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "games.jsonl")


def log_game(game: dict, action: dict):
    """Full replay material for forensics — schema surprises get caught here."""
    try:
        os.makedirs(os.path.dirname(GAME_LOG), exist_ok=True)
        with open(GAME_LOG, "a") as f:
            f.write(json.dumps({"t": game.get("game_id"), "s": game.get("game_state"),
                                "a": action}) + "\n")
    except Exception:
        pass


def update_tracker_from_history(game_id: str, game: dict):
    st = game.get("game_state") or {}
    history = st.get("history") or []
    me = game.get("your_player", "player_1")
    opp = "player_2" if me == "player_1" else "player_1"
    money = float(st.get("money_to_divide") or 1.0)
    tracker = STATE.tracker(game_id)
    for entry in history:
        if entry.get("decision") in ("reject", "rejected") and \
                entry.get("proposer") not in (None, me):
            try:
                their_gain = float((entry.get("offer") or {}).get(f"{opp}_gain", 0.0))
                tracker.observe_rejection(their_gain / money)
            except (TypeError, ValueError):
                pass


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
    try:
        family = game["game_family"]
        game_id = game["game_id"]
        opp_name = (game.get("opponent") or {}).get("name")
        profile = STATE.profiles.get(opp_name)

        if family == "bargaining":
            update_tracker_from_history(game_id, game)
            tracker = STATE.tracker(game_id)
            delta_hat = tracker.delta_hat()
            if profile is not None and profile.implied_delta:
                w = min(0.5, profile.games_seen / 10.0)
                delta_hat = (1 - w) * delta_hat + w * profile.implied_delta
            raw = bargaining.decide(game, opp_delta_hat=delta_hat)
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
            seed = profile.buyer_kind if profile else None
            policy = STATE.seller_policy(game_id)
            raw = persuasion.decide(game, policy=policy,
                                    seed_kind=seed if policy.fresh() else None)
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
        try:
            atype = game["valid_actions"]["type"]
            pivotal = simulate.is_pivotal(game)
            if llm.enabled() and atype == "offer" and \
                    family in ("bargaining", "negotiation"):
                st = game["game_state"]
                if family == "bargaining":
                    cands = simulate.bargaining_candidates(
                        st, game.get("your_player", "player_1"), raw)
                    money = float(st["money_to_divide"])
                    my_key = f"{game.get('your_player')}_gain"
                    gains = [float(c[my_key]) for c in cands]
                    best, mode = simulate.rank_offers(
                        game, cands, "money splits (alice_gain, bob_gain)", gains)
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
                    cands = negotiation.negotiation_candidates(
                        v, is_seller, lo_b, hi_b,
                        float(raw.get("product_price", v)))
                    gains = [(c["product_price"] - v) if is_seller
                             else max(0.0, v - c["product_price"])
                             for c in cands]
                    best, mode = simulate.rank_offers(
                        game, cands, "price offers", gains)
                if best:
                    raw = dict(best)
                    logger.info("[%s %s] sim-rank %s", family, game_id[:8], mode)
            elif llm.enabled() and pivotal and game["valid_actions"].get("fields", {}).get("message") is not None:
                role = {"bargaining": "a negotiator splitting a pot under inflation",
                        "negotiation": "a buyer or seller trading one product",
                        "persuasion": "a seller recommending products of hidden quality"}[family]
                drafted = simulate.draft_message(game, action, role)
                if drafted:
                    action["message"] = drafted
        except Exception:
            logger.exception("llm layer failed; keeping deterministic move")

        logger.info("[%s %s r%s] %s -> %s", family, game_id[:8],
                    game.get("game_state", {}).get("round"),
                    game["valid_actions"]["type"], action)
        log_game(game, action)
        return action

    except Exception:
        logger.exception("strategy failure on %s; using safe action", game.get("game_id"))
        from src.safety import safe_action
        return safe_action(game)


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
