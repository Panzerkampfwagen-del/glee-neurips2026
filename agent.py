"""GLEE agent dispatcher + run loop (thin glue only)."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from src.bargaining import bargaining_strategy, observe as b_observe
from src.negotiation import negotiation_strategy
from src.persuasion import persuasion_strategy

load_dotenv()

STRATEGIES = {
    "bargaining": bargaining_strategy,
    "negotiation": negotiation_strategy,
    "persuasion": persuasion_strategy,
}


def my_strategy(game: dict) -> dict:
    family = game["game_family"]
    handler = STRATEGIES.get(family)
    if handler is None:
        raise ValueError(f"no strategy for family {family!r}")
    action = handler(game)
    if family == "bargaining":
        b_observe(game, action)
    return action


def main() -> None:
    from glee_sdk import GleeClient

    api_key = os.environ.get("GLEE_API_KEY")
    if not api_key:
        raise SystemExit("GLEE_API_KEY not set — put it in .env")
    client = GleeClient(api_key=api_key)
    client.run(
        my_strategy,
        concurrency=int(os.environ.get("GLEE_CONCURRENCY", "8")),
        poll_interval=float(os.environ.get("GLEE_POLL_INTERVAL", "2.0")),
    )


if __name__ == "__main__":
    main()
