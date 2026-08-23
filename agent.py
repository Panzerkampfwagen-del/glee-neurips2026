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

from src import bargaining, negotiation, persuasion
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

        if family == "bargaining":
            update_tracker_from_history(game_id, game)
            tracker = STATE.tracker(game_id)
            raw = bargaining.decide(game, opp_delta_hat=tracker.delta_hat())
        elif family == "negotiation":
            lo, hi = opponent_value_interval(game)
            raw = negotiation.decide(game, opp_value_hat=(lo, hi))
        elif family == "persuasion":
            policy = STATE.seller_policy(game_id)
            raw = persuasion.decide(game, policy=policy)
        else:
            from src.safety import safe_action
            raw = safe_action(game)

        action = validate_and_fix(game, raw)
        logger.info("[%s %s r%s] %s -> %s", family, game["game_id"][:8],
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
