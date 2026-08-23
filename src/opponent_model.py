"""Opponent modeling + cross-game profiles for the GLEE agent."""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class BetaPosterior:
    alpha: float = 1.0
    beta: float = 1.0
    decay: float = 0.95

    def update(self, success: bool, weight: float = 1.0) -> None:
        self.alpha *= self.decay
        self.beta *= self.decay
        if success:
            self.alpha += weight
        else:
            self.beta += weight

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def confidence(self) -> float:
        return (self.alpha + self.beta - 2.0) / (
            (self.alpha + self.beta - 2.0) + 8.0
        )


class IntervalEstimator:
    """Tracks [lo, hi] bounds on an opponent private value from offers."""

    def __init__(self, hard_lo: float, hard_hi: float):
        self.hard_lo = hard_lo
        self.hard_hi = hard_hi
        self.lo = hard_lo
        self.hi = hard_hi

    def observe_offer(self, value: float, side: str) -> None:
        if side == "seller":
            self.lo = max(self.lo, value)
        else:
            self.hi = min(self.hi, value)

    def midpoint(self) -> float:
        return (self.lo + self.hi) / 2.0

    def width(self) -> float:
        return max(0.0, self.hi - self.lo)


def concession_slope(offers: list[float]) -> float:
    """Average per-move movement toward the other side; negative = stubborn."""
    if len(offers) < 2:
        return 0.0
    diffs = [offers[i + 1] - offers[i] for i in range(len(offers) - 1)]
    return sum(diffs) / len(diffs)


def infer_discount_factor(
    own_delta: float, shares_demanded: list[float], rounds_played: int
) -> float:
    """Rough opponent-patience read: fast concession => impatient (low delta)."""
    if not shares_demanded or rounds_played == 0:
        return 0.9
    slope = concession_slope(shares_demanded)
    impatience = _clamp(-slope * 4.0)
    return own_delta * (1.0 - 0.5 * impatience)


class InGameModel:
    """Per-game Bayesian tracking across all three families."""

    def __init__(self, game: dict):
        state = game["game_state"]
        self.game_id = game["game_id"]
        self.opponent_name = (game.get("opponent") or {}).get("name")
        self.disclosed = (game.get("opponent") or {}).get("type") not in (
            None,
            "hidden",
        )
        self.family = game["game_family"]
        self.reliability = BetaPosterior(decay=0.85)
        self.accepts_lowball = BetaPosterior(decay=0.9)
        self.interval: IntervalEstimator | None = None
        self._init_family(state)

    def _init_family(self, state: dict) -> None:
        if self.family == "negotiation":
            me = state.get("current_player", "player_1")
            my_role = state.get(f"{me}_role", "seller")
            prior_span = 200.0
            if my_role == "seller":
                self.interval = IntervalEstimator(state.get(f"{me}_value", 50), state.get(f"{me}_value", 50) + prior_span)
            else:
                v = state.get(f"{me}_value", 150)
                self.interval = IntervalEstimator(max(0.0, v - prior_span), v)
        elif self.family == "persuasion":
            pass

    def observe_bargaining_offer(self, share: float, rounds_played: int) -> None:
        self._shares = getattr(self, "_shares", [])
        self._shares.append(share)
        self.implied_delta = infer_discount_factor(0.9, self._shares, rounds_played)

    def observe_negotiation_offer(self, price: float, opp_is_seller: bool) -> None:
        if self.interval:
            self.interval.observe_offer(price, "seller" if opp_is_seller else "buyer")

    def observe_persuasion_round(self, recommended: bool, quality_high: bool | None) -> None:
        if quality_high is None:
            return
        if recommended and not quality_high:
            self.reliability.update(False, weight=3.0)
        elif recommended and quality_high:
            self.reliability.update(True)

    def trust_in_recommendations(self, round_no: int, total_rounds: int) -> float:
        base = self.reliability.mean
        conf = self.reliability.confidence
        blended = base * conf + 0.5 * (1.0 - conf)
        remaining = max(0, total_rounds - round_no)
        endgame_suspicion = 1.0 - 0.25 * (round_no / max(1, total_rounds)) ** 2
        if remaining <= 2:
            endgame_suspicion -= 0.15
        return _clamp(blended * endgame_suspicion)


PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".profiles")


@dataclass
class OpponentProfile:
    games_seen: int = 0
    concession_rate: float = 0.0
    accept_threshold_est: float = 0.45
    honesty_rate: float = 0.5
    aggression: float = 0.5
    updated_at: float = field(default_factory=time.time)


def _profile_path() -> str:
    return os.path.join(PROFILE_DIR, "profiles.json")


def load_profile(opponent_name: str | None) -> OpponentProfile | None:
    if not opponent_name:
        return None
    try:
        with open(_profile_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get(opponent_name)
        return OpponentProfile(**raw) if raw else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def save_profile(profile: OpponentProfile, opponent_name: str | None) -> None:
    if not opponent_name:
        return
    os.makedirs(PROFILE_DIR, exist_ok=True)
    try:
        with open(_profile_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    prev = data.get(opponent_name, {})
    old_games = prev.get("games_seen", 0)
    k = 1.0 / (old_games + 1.0)
    merged = {}
    for key in ("concession_rate", "accept_threshold_est", "honesty_rate", "aggression"):
        new_v = getattr(profile, key)
        old_v = prev.get(key)
        merged[key] = old_v + (new_v - old_v) * k if old_v is not None else new_v
    merged["games_seen"] = old_games + 1
    merged["updated_at"] = time.time()
    data[opponent_name] = merged
    tmp = _profile_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, _profile_path())


def finalize_game_profile(model: InGameModel, outcome_stats: dict) -> None:
    profile = OpponentProfile(
        games_seen=1,
        concession_rate=outcome_stats.get("concession_rate", 0.0),
        accept_threshold_est=_clamp(outcome_stats.get("accept_threshold_est", 0.45)),
        honesty_rate=_clamp(outcome_stats.get("honesty_rate", model.reliability.mean)),
        aggression=_clamp(outcome_stats.get("aggression", 0.5)),
    )
    save_profile(profile, model.opponent_name)
