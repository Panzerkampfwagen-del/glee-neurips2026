"""Empirical opener pricing (Phase B).

Picks opener ratios maximizing realized payoff/value from live outcome data
(data/share/opener_outcome_table.json, refreshed by scripts/opener_analysis.py).
Falls back to the legacy heuristic when the table is missing/thin or when
GLEE_ABLATE contains opener_pricing.
"""

import json
import os

_TABLE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "share", "opener_outcome_table.json")
MIN_N = 3


def _load_table():
    try:
        with open(_TABLE_PATH) as f:
            raw = json.load(f)
        out = {}
        for role, buckets in raw.items():
            rows = []
            for b, v in buckets.items():
                n = int(v.get("n", 0))
                deals = int(v.get("deals", 0))
                psum = float(v.get("payoff_sum", 0.0))
                if n >= MIN_N:
                    rows.append((float(b), psum / n))
            out[role] = rows
        return out
    except Exception:
        return {}


def best_ratio(role: str) -> tuple[float | None, float | None]:
    """(best_ratio, expected_payoff_per_value) or (None, None) if no data."""
    rows = sorted(_load_table().get(role, []))
    if not rows:
        return None, None
    return max(rows, key=lambda x: x[1])


def priced_opener(my_value: float, is_seller: bool,
                  legacy_mult: float = 2.1) -> tuple[float, str]:
    """Returns (price, source). source ∈ {empirical, legacy}."""
    role = "seller" if is_seller else "buyer"
    ratio, ev = best_ratio(role)
    ablated = "opener_pricing" in set(
        a.strip() for a in os.environ.get("GLEE_ABLATE", "").split(",") if a.strip())
    if ratio is None or ablated:
        mult = legacy_mult * (1.0 if is_seller else 1.0 / 0.45 * 0.45)
        mult = 2.1 if is_seller else 0.45
        return my_value * mult, "legacy"
    return my_value * ratio, "empirical"
