# agent01 — GLEE 2026 Competition Agent

Solver-in-the-loop autonomous agent for the [GLEE competition](https://glee-competition.com)
(NeurIPS 2026, IAB Workshop): three two-player, language-based economic games —
**bargaining**, **negotiation**, **persuasion** — played through the official
Python SDK (`glee-sdk`). Competition window: Aug 1 – Aug 29, 2026 (AoE).

Agent public id: `7b2446de-071d-4b13-914d-b404f5ce2129`

## Results (final leaderboard window)

| Family | Final rating | Peak | Games |
|---|---|---|---|
| Bargaining | 2,026 | 2,166 | 9,829 |
| Negotiation | 1,842 | 1,972 | 9,797 |
| Persuasion | 1,293 | 1,636 | 9,735 |

Ratings are payoff-percentile vs the field (same config + role),
strength-adjusted; the display rating is shrunk by `g/(g+30)`.

## Design: solver-in-the-loop

Every numeric decision is emitted by deterministic, unit-tested
game-theoretic code. The LLM (Groq-hosted open-weights 120B/20B models) only
(i) ranks ~5 solver-generated candidates on pivotal turns by estimated
acceptance probability × code-computed gain, and (ii) drafts strategic
language consistent with the chosen action. Every action passes
schema/enum/arithmetic validation; any failure returns the deterministic
action. A turn-clock guard (90s vs the 120s server budget) means a slow LLM
call can only be discarded, never delay a submission.

Measured over the full competition (14,808 moves): **100% strategy-path,
0% fallback**, 3,950 pivotal-gated LLM ranking waves.

Key components (all in `src/`):
- `bargaining.py` — discount-adjusted accept thresholds, Rubinstein-style
  offers, opponent-patience tracker, deadlock floor decay
- `negotiation.py` — direction-correct ZOPA interval estimation,
  capture-threshold acceptance, negative-surplus walk-away, field-calibrated
  openers
- `persuasion.py` — concavification-derived sparse signaling (seller),
  signal-regime classifier + base-rate posteriors (buyer)
- `opponent_model.py` — persistent cross-game profiles keyed by opponent name
  (implied impatience / rejection-rate scaling / buyer kind)
- `simulate.py`, `llm.py` — candidate generation, ranking waves, Groq client
  with token-bucket rate limiting
- `safety.py` — `validate_and_fix()` on every action; `safe_action()` fallback

## Repository layout

```
agent.py                 # dispatcher + GleeClient run loop (thin glue)
src/                     # solvers, opponent model, LLM shell, state, safety
scripts/
  local_arena.py         # scripted-opponent arena for ablation ladders (no API)
  analyze_paper_tables.py# paper-table analysis over the replay ledger
  live_supervisor.sh     # relaunch loop w/ 403 backoff + arm alternation
  hourly_status.sh       # watchdog: ratings snapshot + self-heal
  status.sh, smoke_test.py, opener_analysis.py
tests/                   # 67 tests incl. F1–F6 regression contracts
data/                    # games.jsonl replay ledger, profiles.json, logs
                         # (gitignored; ledger format: {t, s, a, origin, ts})
experiments/             # ablation artifacts (t2_ladder_pilot/n120)
docs/                    # analysis, paper drafts, submission
  12_submission_neurips.tex  # 4-page NeurIPS-format competition paper
  11_manuscript.tex/.md      # extended manuscript
  06_behavior_analysis.md    # behavior-analysis working notes
COORDINATION.md          # two-agent development log (Agent A / Agent B)
AGENTS.md                # ownership map + sync protocol for the two agents
```

## Running

```bash
# venv used in production: ~/glee-comp/.venv (Python 3.14)
pip install glee-sdk requests pytest

export GLEE_API_KEY=glee_...          # required (competition API key)
export GROQ_API_KEY_1=gsk_...         # optional; enables the LLM shell
export GROQ_API_KEY_2=gsk_...         # second key = doubled rate budget

python agent.py --concurrency 8       # play all three families
python agent.py --families bargaining # single family
```

Environment flags:

- `GLEE_USE_LLM=0` — disable the LLM shell entirely (deterministic core)
- `GLEE_ABLATE=opp_model|profiles|sim|all` — ablation flags mirroring the
  paper's ladder (comma-separated)
- `GLEE_LLM_FAST` / `GLEE_LLM_STRONG` — override model names
- `GLEE_PROFILES_PATH` — profile store location (tests/arena use isolated paths)

Production is run under `scripts/live_supervisor.sh` (relaunch loop,
drain-on-exit, 403-cooldown backoff) with `scripts/hourly_status.sh` on a
cron watchdog (ratings snapshot + self-heal).

## Tests

```bash
python -m pytest -q    # 67 passed
```

Includes regression contracts for every documented live failure F1–F6
(parser fallback inversion, class-blind belief updates, non-directional
intervals, rating-damage persistence, crash-loop session management,
cheap-talk conflation).

## Key findings

1. **Cheap talk is not evidence** (F6): a constant seller signal is
   *uninformative*, not *dishonest* — deception penalties are mathematically
   inapplicable on constant signals. The regime-classified buyer recovered
   +794 points/game (95% CI ±87) on affected configurations.
2. **Arena–field flip**: the bargaining patience tracker *lost* 3.4pp in the
   scripted arena (n=120) but *won* +13.7pp of pot share in a live A/B —
   local ablations can rank components backwards.
3. **Reliability is strategy**: abandoned games score at the 5th percentile,
   so drain-on-exit, supervision, and deadline guards carry direct rating
   value.

## Competition paper

`docs/12_submission_neurips.tex` — 4-page NeurIPS 2026 format submission for
the IAB Workshop competition-paper track (due Sep 5, 2026 AoE), including the
required Agent Behavior Analysis section. Requires `neurips_2026.sty` +
`checklist.tex` from neurips.cc to compile. The extended manuscript is
`docs/11_manuscript.tex`.

## Fair play & operations notes

- The agent plays autonomously; no human-in-the-loop during games.
- API keys live in `.env` (gitignored) — never committed.
- JSONL ledger rotates at 64 MB to `.prev` (H6 audit); origin tags enable
  per-move provenance audits.
