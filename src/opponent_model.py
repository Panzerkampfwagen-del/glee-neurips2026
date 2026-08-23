"""Opponent modeling: decayed Beta counters, valuation intervals, type posteriors.

Explicit external filter (per TERMS-Bench finding): all belief updating is
numeric code, never LLM reflection.
"""

import json
import math
import os
import threading


class DecayedBeta:
    """Beta-Bernoulli counter with exponential decay on old evidence."""

    def __init__(self, alpha: float = 1.0, beta: float = 1.0, decay: float = 0.7):
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.decay = decay
        self.n_since = 0.0

    def update(self, success: bool):
        self.alpha *= self.decay
        self.beta *= self.decay
        if success:
            self.alpha += 1.0
        else:
            self.beta += 1.0
        self.n_since += 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def n_effective(self) -> float:
        return self.alpha + self.beta - 2.0

    def confidence(self) -> float:
        """0..1 how much evidence we have (saturates around 8 effective obs)."""
        return 1.0 - math.exp(-max(0.0, self.n_effective) / 4.0)


class IntervalEstimator:
    """Running [lo, hi] bounds on opponent's private value from their offers."""

    def __init__(self, prior_lo: float, prior_hi: float):
        self.lo = prior_lo
        self.hi = prior_hi

    def tighten_from_offer(self, offer: float, slack: float, side: str):
        """side: what the offer implies. A seller's ask s => value <= s.
        A buyer's bid b => value >= b."""
        if side == "upper":
            self.hi = min(self.hi, offer + slack)
        else:
            self.lo = max(self.lo, offer - slack)

    def merge_observation(self, lo: float | None = None, hi: float | None = None):
        if lo is not None:
            self.lo = max(self.lo, lo)
        if hi is not None:
            self.hi = min(self.hi, hi)

    @property
    def midpoint(self) -> float:
        return (self.lo + self.hi) / 2.0

    @property
    def width(self) -> float:
        return max(0.0, self.hi - self.lo)


class OpponentProfile:
    """Cross-game profile for one named opponent (identity-disclosed games)."""

    VERSION = 1

    def __init__(self, name: str):
        self.name = name
        self.games_seen = 0
        self.accept_speed = DecayedBeta(decay=0.85)
        self.reliability = DecayedBeta(decay=0.7)
        self.deception_prior = {"human": 0.3, "frontier_llm": 0.5, "small_model": 0.6}
        self.concession_slope_ema: float | None = None
        self.notes: list[str] = []

    def to_dict(self) -> dict:
        return {
            "version": self.VERSION,
            "name": self.name,
            "games_seen": self.games_seen,
            "accept_speed": [self.accept_speed.alpha, self.accept_speed.beta],
            "reliability": [self.reliability.alpha, self.reliability.beta],
            "concession_slope_ema": self.concession_slope_ema,
            "notes": self.notes[-20:],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OpponentProfile":
        p = cls(d["name"])
        p.games_seen = d.get("games_seen", 0)
        a, b = d.get("accept_speed", [1.0, 1.0])
        p.accept_speed = DecayedBeta(a, b)
        r = d.get("reliability", [1.0, 1.0])
        p.reliability = DecayedBeta(r[0], r[1])
        p.concession_slope_ema = d.get("concession_slope_ema")
        p.notes = d.get("notes", [])
        return p


class ProfileStore:
    """Flat JSON file of per-opponent profiles; thread-safe; crash-tolerant."""

    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get(
            "GLEE_PROFILES_PATH",
            os.path.join(os.path.dirname(__file__), "..", "data", "profiles.json"),
        )
        self._lock = threading.Lock()
        self._profiles: dict[str, OpponentProfile] = {}
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                raw = json.load(f)
            for name, d in raw.items():
                self._profiles[name] = OpponentProfile.from_dict(d)
        except (OSError, json.JSONDecodeError, KeyError):
            self._profiles = {}

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w") as f:
                    json.dump({k: v.to_dict() for k, v in self._profiles.items()}, f, indent=1)
                os.replace(tmp, self.path)
            except OSError:
                pass

    def get(self, name: str | None) -> OpponentProfile | None:
        if not name or name == "hidden":
            return None
        with self._lock:
            if name not in self._profiles:
                self._profiles[name] = OpponentProfile(name)
            return self._profiles[name]

    def all_profiles(self) -> dict[str, OpponentProfile]:
        return dict(self._profiles)


def infer_seller_type(history: list) -> dict:
    """From persuasion history, estimate whether the buyer conditions on
    history (bayesian) or buys regardless (myopic).

    Returns {"kind": "unknown"|"myopic"|"bayesian", "burned_then_bought": bool,
             "burned_then_passed": bool}
    """
    burned_at = None
    bought_after_burn = False
    passed_after_burn = False
    for entry in history:
        bought = entry.get("bought")
        quality = entry.get("quality")
        if bought and quality == "low" and burned_at is None:
            burned_at = entry.get("round", 0)
            continue
        if burned_at is not None and entry.get("round", 0) > burned_at:
            if bought:
                bought_after_burn = True
            elif bought is False:
                passed_after_burn = True
    if bought_after_burn and not passed_after_burn:
        kind = "myopic"
    elif passed_after_burn:
        kind = "bayesian"
    else:
        kind = "unknown"
    return {
        "kind": kind,
        "burned_then_bought": bought_after_burn,
        "burned_then_passed": passed_after_burn,
    }
