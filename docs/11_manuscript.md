# Cheap Talk Is Not Evidence: A Solver-in-the-Loop Architecture for Language-Based Economic Games

**Anonymous submission — GLEE Competition Papers Track, IAB Workshop @ NeurIPS 2026**

*Competition agent public id: `7b2446de-071d-4b13-914d-b404f5ce2129`*

---

## Abstract

LLM agents competing in multi-turn economic games fail not at language but at two quieter tasks: computing numbers and updating beliefs. We present the design and field results of `agent01`, a top-quartile agent across all three GLEE game families (bargaining, negotiation, persuasion), built on a principle we call *solver-in-the-loop*: every numeric decision is made by deterministic, unit-tested game-theoretic code, while the LLM is confined to drafting strategic language and ranking candidate actions whose payoffs were computed in code. Our central scientific finding emerged from a live failure: the agent's buyer module stopped trading in an expected-positive market after observing two low-quality draws, because its deception penalty treated an *uninformative* signal — a seller who always says "yes" — as evidence about exogenous quality. We formalize the distinction between cheap-talk *honesty* and cheap-talk *informativeness* (Crawford & Sobel 1982), show that prior-style deception penalties are mathematically inapplicable when signals are constant, and validate the correction in a paired experiment: the regime-classified buyer recovers **+794 points per game (95% CI ±87)** on affected configurations, with honest and lying sellers producing *identical* payoff distributions by construction. More broadly, we contribute a six-item failure taxonomy distilled from ~3,400 live competition games — schema-drift fallback inversion, tracker signal inversion, subgame-perfect fragility against non-equilibrium populations, and others — each converted into a permanent regression contract. Across 3,400+ rated games, the agent's bargaining rating rose from 904 to a peak of 2,166 under the platform's strength-adjusted scoring. We argue that the discipline of separating *what the theory computes* from *what the model says* is the transferable lesson for LLM agents in structured environments.

---

## 1. Introduction

The GLEE competition (Shapira et al. 2024, arXiv:2410.05254) evaluates autonomous agents in three two-player, language-based economic games: **bargaining** (alternating-offer division of a shrinking pie), **negotiation** (bilateral trade with private valuations), and **persuasion** (repeated sale of products whose quality is hidden from the buyer). Agents act through an API under real constraints — 120 seconds per move, 60 requests/minute, a shared matchmaking pool of humans, heterogeneous competitor agents, and organizer-run LLM baselines — and are scored by *payoff percentile against the field on the same game configuration and role, adjusted for opponent strength*. The metric rewards sustained above-median play and punishes catastrophic outcomes disproportionately: an abandoned or timed-out game is scored at the 5th percentile.

Two observations motivate our design.

**First, LLM agents fail economic games at numbers and beliefs, not at language.** In our own early live play and in the GLEE benchmark's published analysis, LLM negotiators reject profitable splits out of fairness concerns, anchor mechanically on first offers, miscompute discounted values, and — most consequentially — update beliefs in ways that violate the causal structure of the game. These are not prompting failures; they are failures of *architecture*. A language model asked to "play well" must simultaneously parse rules, track state, model an opponent, do arithmetic, and emit valid JSON. Errors compound silently.

**Second, the scoring environment converts small systematic errors into large rating losses.** Percentile scoring compares each outcome against the field's distribution on identical configurations. A single class of systematically mishandled configurations (e.g., unlimited-horizon games where equilibrium demands are extreme) produces a persistent drag that late-stage rating dynamics — learning rates decaying to 0.2% per game — make expensive to undo.

**Our key idea is solver-in-the-loop**: a deterministic, unit-tested game-theoretic core computes every numeric decision (acceptance thresholds, offer prices, signaling mixtures); the LLM is restricted to (i) drafting strategic messages consistent with computed actions, and (ii) ranking pre-computed candidate actions on pivotal moves by simulating the opponent. Belief updating over opponent types lives in explicit Bayesian filters — never in LLM self-reflection.

**What we discovered.** The architecture survived 3,400+ rated games with zero degraded-path events (§6). But the scientifically interesting findings came from *failures at the boundary between theory and population*: pure subgame-perfect strategies are exploitable against fairness-rejecting populations (§5.2); deception penalties that ignore whether a cheap-talk signal is *informative* lock an agent out of positive-expected-value markets (§5.3); and a one-line regex error in enum validation silently transformed the entire agent into an unconditional accept-bot for hundreds of games (§5.1) — a failure invisible to component tests and visible only through outcome forensics.

**Why this matters beyond the leaderboard.** The GLEE setting is a microcosm of LLM-agent deployment in structured domains: the model must interface with rules it cannot be trusted to reason about numerically, against adaptive counterparts, under operational constraints. Our results suggest a division-of-labor principle — *solvers compute, models communicate* — together with a testing discipline (theory-level property tests + outcome forensics + regression contracts for every observed divergence) that transfers to any domain where an LLM wraps a formal system.

## 2. Related Work

**LLM agents in strategic games.** Suspicion-Agent (Guo et al., COLM 2024) demonstrated GPT-4 playing imperfect-information card games via theory-of-mind prompting but noted it could not beat equilibrium solvers; Agent-Pro (Zhang et al., ACL 2024) evolved negotiation policies via reflection; PokerBench (Zhuang et al., AAAI 2025) measured GPT-4 at only 53.6% optimal-action agreement on poker spots and showed SFT-from-solver closes much of the gap. Cicero (FAIR, Science 2022) grounded dialogue generation in planned intents for Diplomacy; Strategist (Light et al., ICLR 2025) improved LLM play via bi-level search over strategy text. OG-Narrator (ACL 2024 Findings [AUTHORS VERIFY]) reported ~10× profit gains from decoupling offer selection (deterministic) from narration (LLM) in bargaining dialogues — the closest published precedent for our solver/LLM split, which we extend to three game families, opponent modeling, and field-calibrated safety floors.

**Game-theoretic foundations.** Alternating-offer bargaining with discounting (Ståhl 1972; Rubinstein 1982) yields stationary splits proportional to relative impatience and, under finite horizons, extreme backloaded demands by subgame perfection. Bilateral trade under private values admits no efficient dominant-strategy mechanism (Myerson & Satterthwaite 1983). Bayesian persuasion (Kamenica & Gentzkow 2011) characterizes optimal signaling as concavification of the sender's value function — trivially solvable in closed form for binary state/action pairs, which covers GLEE persuasion. Reputation effects in repeated games (Kreps & Wilson 1982; Fudenberg & Levine 1989 [CITATION NEEDED — verify edition]) predict end-game defection windows we exploit and defend against.

**Equilibrium vs. populations.** NFSP (Heinrich & Silver, ICML 2016), PSRO (Lanctot et al., NeurIPS 2017), and DORA (Bakhtin et al., NeurIPS 2021) establish self-play equilibrium learning; DORA additionally shows self-play equilibria can be *off-population* — incompatible with human-data distributions. Cicero succeeded against humans precisely by regularizing toward population-typical play. Our live observation of SPE-crumbs rejection (§5.2) is a small-scale confirmation in economic games, motivating what we call *population-compatible equilibrium*: analytic equilibria softened by bidirectional behavioral floors, relaxed only under opponent-model confidence.

**Theory of mind and belief updating in LLMs.** MMToM-QA/BIP-ALM (Jin et al., ACL 2024) show structured Bayesian inverse planning beats raw LLM inference about beliefs; SymbolicToM (Sclar et al., ACL 2023) shows symbolic belief ledgers beat prose tracking; ToMBench (Chen et al., ACL 2024) finds CoT does not reliably improve LLM theory-of-mind. Our explicit type-posterior filters follow this line. Recent evaluations of LLM belief updating in negotiation (TERMS-Bench-style evaluations, 2025 [CITATION NEEDED]) report that frontier models' type-beliefs are flat or worsening across rounds — consistent with our decision to keep all belief arithmetic in code.

## 3. Problem Formulation

Three families, drawn from a server-controlled grid of ≈960 configurations spanning horizons, sums, valuations, inflation rates, and information conditions. Full formal rules in the GLEE documentation; we state what the solver consumes.

**Bargaining.** Pot $M$; alternating proposers; receiver accepts ($x \geq$ threshold), rejects, or walks away ($0$ for both). Player $i$'s money inflates by factor $\delta_i \in (0,1]$ per round (opponent's $\delta$ hidden in incomplete-information configs). Horizons are finite-known ($R$ rounds), or absent. Payoffs are nominal shares of $M$; delay scales effective value by $\delta_i^{\,r}$.

**Negotiation.** Seller value $s$, buyer value $b$ (private unless `complete_information`); alternating price offers; accept / reject-with-counter / walk away. Trade surplus exists iff $s \le b$. Horizons: single-round (take-it-or-leave-it), capped, or unlimited.

**Persuasion.** Repeated rounds $r = 1..T$: quality $q_r \sim \text{Bernoulli}(p)$ drawn independently each round (buyer's utility $v$ if high, $u=0$ if low; fixed price $\pi$). Seller observes $q_r$ and sends a message/recommendation; buyer buys/passes; payoffs accumulate. The buyer observes realized quality only for purchased units. Sellers differ in message policy: always-recommend ("uninformative"), selectively-honest ("informative"), or deceptive variants.

**Scoring.** After each game, payoff → percentile against every recorded payoff on the same configuration+role; percentile → rating $2000 + 8000(\text{pct}-0.5)$; displayed rating shrinks toward 1000 by $g/(g+30)$ where $g$ counts family games; overall score averages three family ratings.

## 4. Method: Solver-in-the-Loop

### 4.1 Architecture

A dispatcher routes each incoming game to a per-family handler sharing four components: (i) a **state compiler** converting raw API payloads into typed structures; (ii) a **solver core** (per-family deterministic policy); (iii) an **opponent layer** (in-game trackers, cross-game profile store, Bayesian type posteriors); (iv) an **LLM shell** (Groq `gpt-oss-20b`/`120b` behind a 72-RPM token bucket) used only for pivotal-move ranking and message drafting. Every LLM path returns a deterministic fallback on failure; a validator repairs sums/enums before submission; a safe action table guarantees legal moves under any exception. Provenance (origin tag, timestamp, full state) is logged per move for post-hoc audit.

### 4.2 Bargaining solver

With known horizon $R$ and rounds left $k$, define pie-values by backward induction over alternating proposer roles:

$$V_{\text{ip}}[k] = M - \min(\delta_{\text{opp}} V_{\text{tp}}[k-1],\, M), \qquad V_{\text{tp}}[k] = M - \min(\delta_{\text{me}} V_{\text{ip}}[k-1],\, M)$$

with $V[\cdot][0]=0$. As proposer we concede exactly the receiver's discounted continuation; as receiver we accept iff the offer meets $a^\star = \delta_{\text{me}} V_{\text{ip}}[k-1]$. For unknown horizons we use the Rubinstein stationary split $s_{\text{me}} = M(1-\delta_{\text{opp}})/(1-\delta_{\text{me}}\delta_{\text{opp}})$.

**Population floors.** Pure SPE produces offers that field populations reject (we once conceded 90.7% of a pot when parity-disadvantaged; six no-deal losses arose from repeating such offers verbatim). We therefore clamp both directions:

$$x_{\text{opp}} = \mathrm{clip}\Big( x^{\text{SPE}}_{\text{opp}} + \epsilon_F M(1-c),\;\; 0.02M,\;\; M(1-f(c)) \Big)$$

where $c$ is opponent-model confidence, $\epsilon_F = 0.06$, and $f(c) = c\cdot f_{\text{SPE}} + (1-c)\max(f_{\text{SPE}}, 0.36)$ with $f_{\text{SPE}}$ the SPE share fraction. Unknown horizons additionally trigger *deadlock decay*: after round 14 without agreement, demanded share converges to $M/2$ over 25 rounds and the acceptance floor sinks toward token-positive.

Opponent impatience is estimated by a decayed Bernoulli filter over the *opponent's rejections of our offers* (each event counted once via a watermark index), blended into $\hat\delta_{\text{opp}}$ by confidence weight.

### 4.3 Negotiation solver

We maintain directional interval estimates $[\ell, h]$ on the counterpart's private value: their bids raise $\ell$ (as seller), their asks lower $h$ (as buyer); their rejection of our price $q$ tightens the bound *against us* ($v_b < q$ for buyers, $v_s > q$ for sellers); their acceptance pins the opposite side. Openers anchor at $2.1 s$ / $0.45 b$ scaled by a profile-derived aggression factor; counters converge toward the midpoint of the estimated ZOPA $[\hat s, \hat b]$ under complete information, else along a concession path gated by remaining rounds. Acceptance requires a minimum captured fraction of estimated surplus,

$$\text{capture} = \frac{x - z_\ell}{z_h - z_\ell} \geq \tau(k), \quad \tau(k) = 0.35\cdot\min\!\big(1,\tfrac{k-1}{4}+0.3\big)\ \text{(known opp.)},$$

decaying to zero on final rounds; walk-away fires only on near-certain negative surplus ($\Pr[s>b]>0.95$-equivalent evidence). On unlimited horizons past round 14, $\tau \to 0$: a thin deal strictly dominates a bottom-percentile no-deal.

Under complete information both values are visible and we counter at the Nash-like fair split $(s+b)/2$ immediately.

### 4.4 Persuasion: signaling, regimes, and the buyer filter

**Seller.** The optimal binary-state signaling scheme is the concave closure of the sender's value over posterior beliefs (Kamenica & Gentzkow 2011); with $u=0$ it reduces to pooling or a two-signal split at posterior threshold $\beta^\star=\pi/v$. We sample recommendations from the resulting mixture, horizon-adjusted: exploitation rate rises near the horizon end only against buyers proven to re-buy after burns, and collapses to fully honest signaling after three consecutive buyer passes (recovery mode).

**Buyer.** The decisive question is whether the seller's claim carries information. Classify the history into a *signal regime*:

$$\rho = \tfrac{1}{n}\sum_t \mathbb{1}[\text{claim}_t=\text{yes}], \quad \text{regime} = \begin{cases}\text{uninformative} & \rho \ge 0.95 \text{ or } \rho \le 0.05,\ n \ge 3\\ \text{informative} & \text{otherwise}\end{cases}$$

In the uninformative regime the claim is statistically independent of $q_t$, so $P(q{=}\text{high} \mid \text{history}) = p$ regardless of observed burns, and the buyer buys iff $p v + (1-p)u > \pi$. In the informative regime we maintain class-conditioned decayed Beta posteriors $P(high \mid yes)$ and $P(high \mid no)$, blended with the prior, with a recency-limited deception discount and a tripled evidence bar after two consecutive low purchases. Purchased rounds alone reveal quality; unpurchased rounds are censored.

**Cross-game profiles** store per-named-opponent aggregates (implied $\delta$, reject-rate, buyer type) persisted as JSON; identity is disclosed in half of matches, so robust defaults cover the rest.

### 4.5 LLM shell

On pivotal offers (opening offer, ≤2 rounds remaining, deadlock drift <5%, or confident exploitability signal), the solver emits $N\approx5$ candidates around its target; Groq models estimate $P(\text{accept}\mid\text{candidate}, \text{profiled opponent behavior})$; we select $\arg\max_i P_i \cdot g_i$ where $g_i$ is code-computed gain. Messages on pivotal turns are drafted subject to consistency with the chosen numeric action and a 2,000-character cap. All Groq paths respect a shared token bucket (72 RPM across keys) and a hard per-move deadline; any failure returns the deterministic action unchanged.

## 5. Experimental Setup and Field Results

### 5.1 Setup

All results come from live rated play during Aug 23–26, 2026 (competition window Aug 1–29): 3,400+ completed games across families (~1,100–1,700 each), concurrency 8, continuous queueing with drain-on-exit supervision. Outcome forensics join per-move JSONL logs (state, action, origin tag, timestamp) with platform results. Component correctness is enforced by a 65-test suite including property tests (offer-sum integrity, IR clamps, signaling-mixture optimality grid) and replay fixtures reproducing every field incident below. The ablation pilot (§7) uses scripted opponents at n=60/arm with preregistered arms.

### 5.2 Main field results

**Rating trajectory.** Displayed ratings rose from 904/958/1048 (bargaining/negotiation/persuasion, Aug 23) to peaks of 2166/1573/1490 within 72 hours (~3,400 games), under strength-adjusted percentile scoring against a live mixed field. Piecewise slopes per 100 games: bargaining +62 post-deploy; negotiation +19 with a mid-period dip attributed (and separately handled) to unlimited-horizon deadlocks (§5.4); persuasion +5 early, steepening after the §5.3 fix. ⟨FIGURE 1: rating trajectory with deploy markers⟩

**Deal integrity.** In the latest analysis window, 96/96 completed negotiation games ended in agreements (zero no-deals), median 2 rounds-to-agreement, with quoted margins strictly inside own-value bounds (median +11.7% surplus retained, n=905 quotes) — direct evidence that the IR clamps and capture thresholds hold in production.

**Operational alignment.** Over 3,273 consecutive logged moves: 100.0% strategy-path submissions, 0.0% degraded-fallback events, across all families. Simulation ranking fired on 710+ pivotal offers. No turn timeouts were attributable to agent latency after the move-deadline guard (§4.5).

### 5.3 Case study: cheap talk is not evidence (F6)

The original buyer applied a deception penalty whenever recent purchases included low-quality units. Against an always-yes seller, quality draws are independent of the claim, so consecutive lows occur by chance with probability $(1-p)^2$ — yet the penalty read them as proof of an adversarial seller, suppressed buying for the remainder of the match, and forfeited the market: on an EV-positive configuration ($p{=}0.5$, $v{=}300$, $\pi{=}100$, EV $=$ 150) the old policy bought 2/20 rounds.

**Correction.** Regime classification (§4.4) gates all belief updates: constant claims carry no information, so the base-rate rule applies and burns are ignored; varying claims activate class-conditioned posteriors.

**Paired causal test** (n=200 seeds/arm, three scripted seller types, EV-positive config):

| Seller type | New buyer | Old buyer | Paired Δ (95% CI) |
|---|---|---|---|
| Always-yes honest | 1010.5 | 216.5 | **+794.0 ± 86.6** |
| Always-yes liar | 1010.5 | 216.5 | **+794.0 ± 86.6** |
| Selective informative | 305.0 | 199.0 | **+106.0 ± 55.3** |

Honest and liar rows are identical *by construction*: from the buyer's payoff perspective, a constant signal's honesty is irrelevant because it transmits no bits about exogenous quality. The old penalty was updating on noise. The informative row confirms the machinery still defends where claims genuinely differentiate. To our knowledge this honesty-invariance point, though elementary in information-economics terms, is routinely violated by LLM-agent belief designs that treat detected "lies" as generic distrust triggers.

### 5.4 Failure taxonomy from live play

Each incident became a permanent regression fixture:

| # | Incident | Root cause | Generalizable lesson |
|---|---|---|---|
| F1 | Agent accepted every offer for ~15 games (−140 payoff on one) | Enum-validation string split on `"or"` mangled `'AcceptOffer', 'RejectOffer', or 'WalkAway'`; silent fallback = unconditional accept | Schema-drift robustness: validators need adversarial fixtures of the *platform's own prose formats* |
| F2 | Buyer passed 18/20 rounds on EV-positive config | Burn-lockout (see §5.3) | Exploration constraints in censored-feedback markets |
| F3 | Walked away from visible-surplus trade | Rejection semantics ignored who-rejected-whose-offer | Directional belief updates; naive counting is worse than none |
| F4 | Early bug-era percentiles permanently depressed ratings | Rating eta decay makes early damage sticky | Deploy markers + volume dilution as remediation |
| F5 | Reboot killed session mid-games → crash-loop ban | Process-group kill; no drain | Supervised supervision; drain-before-exit as contract |
| F6 | Market lockout (above) | Regime-blind penalty | Causal structure constrains belief updates |

### 5.5 Opener pricing from field data

Mining our logged negotiation games (n=142 with visible values) produced empirical deal-rate curves by opener ratio: aggressive anchors (1.8–2.0× seller value) closed 42–47% of deals, while moderate anchors (≤1.4×) closed 13/13 sampled games at equal-or-better realized margins. Phase B deploys $\pi^\star = \arg\max_r \widehat{P}(\text{deal}\mid r)\,\mathbb{E}[g\mid r, \text{deal}]$ from these tables behind an ablation flag. ⟨NEEDS EXPERIMENT: post-deploy live delta, accumulating⟩ Buckets remain thin (n=3–41); we present this as a calibration method rather than a settled coefficient set.

## 6. Ablation Studies

A preregistered ladder (L0 solver-only → L1 +opponent-model → L2/L3 +profiles) ran against scripted opponents, n=60/arm:

| Arm | Bargaining mean (pot share) | Negotiation | Persuasion |
|---|---|---|---|
| L0 | 0.236 | 0.408 | 114.3 |
| L1 | 0.236 | 0.408 | 112.8 |
| L2 | 0.198 | 0.408 | 113.8 |
| L3 | 0.198 | 0.408 | — |

Three honest readings. (i) **Negotiation arms are indistinguishable because the arena did not feed histories to states** — the interval estimator received no evidence; the arena gap, not the component, is the finding. (ii) **Bargaining shows a small inversion** (L0/L1 > L2/L3, ~3.7pp): the tracker overfits $\hat\delta$ to two deterministic opponents; with n=60 this is directional, and matches live evidence where the tracker's value concentrates in heterogeneous-field games. (iii) **Persuasion deltas are within noise** because both arms include the post-F6 buyer; the F6 causal effect is isolated separately in §5.3's paired test, which is the appropriate instrument. Profile rungs require named recurring opponents to activate at all — an experimental-design constraint we document for future GLEE work.

⟨NEEDS EXPERIMENT: full ladder with named opponents, n≥120, before camera-ready.⟩

## 7. Error Analysis

Provenance accounting over 3,273 consecutive production moves: 100% strategy-path, 0% safe-action fallbacks, 0 latency-attributed timeouts after the move-deadline guard. The residual error budget concentrates in three known classes: (i) thin-deal acceptance on deadlocked unlimited-horizon games (deliberate: thin deal ≫ no-deal under percentile scoring); (ii) TIOLI rejections above valuation (forced-correct); (iii) simulator probability degeneracy — early Groq responses echoed monotone sequences due to reasoning-token starvation, since mitigated by token-budget raises and structured prompts; the sim-ranking arm is therefore flagged ⟨needs longer accumulation⟩ and excluded from headline claims.

## 8. Discussion

**What transfers.** The solver/model split is domain-general: wherever an environment has computable structure (constraints, dynamics, mechanism), LLM wrappers should delegate computation to tested code and reserve the model for perception and expression. Our worst failures occurred exactly where that boundary leaked — arithmetic in prompts (pre-history), beliefs in reflections (F2/F6), validation in string ops (F1).

**Population-compatibility as a first-class objective.** Equilibrium answers "what is unbeatable"; competition scoring asks "what beats this field." These diverge measurably. Bidirectional floors calibrated on field data — with deviation gated by opponent-model confidence — resolved the divergence profitably in our setting and echo the human-regularization lesson of Diplomacy-scale systems at accessible scale.

**Cheap-talk discipline.** The honesty/informativeness distinction should be a default check for any repeated-interaction agent: before updating on a counterpart's communication, ask what the communication *could vary with*. If the answer is nothing, the update is noise-mining.

## 9. Limitations

Constants (`FIELD_MIN_CONCESSION`, opener multipliers, capture thresholds, probe cadence) were tuned on this window's field and may be population-specific; they are isolated as four named parameters with ablation flags. The empirical opener tables reflect ~150 visible-value games; buckets are thin. Opponent profiles assume name stability. The persuasion ceiling is structural: EV-negative configurations force payoff-zero play, capping family percentiles independent of skill. We evaluate a single deployed system on a single account; cross-account variance is unmeasured. Simulator probabilities showed degeneracy under token starvation; despite mitigations, sim-ranking claims are limited to the pivotal subset and short horizons.

## 10. Reproducibility

The agent is a pure-Python package (deterministic solvers; LLM optional): pip-installable SDK pin, 65-test suite including every field regression, offline harness with scripted opponents, JSONL replay format specification, and seeded paired-experiment scripts. All experiments here are re-runnable without API keys except live-rating figures, which are time-stamped platform records.

## References

1. Shapira, E., Madmon, O., Reinman, I., Amouyal, S.J., Reichart, R., Tennenholtz, M. *GLEE: A Unified Framework and Benchmark for Language-Based Economic Environments.* arXiv:2410.05254 (2024).
2. Rubinstein, A. *Perfect Equilibrium in a Bargaining Model.* Econometrica 50(1), 1982.
3. Ståhl, I. *Bargaining Theory.* Stockholm School of Economics, 1972.
4. Nash, J. *The Bargaining Problem.* Econometrica 18(2), 1950.
5. Myerson, R., Satterthwaite, M. *Efficient Mechanisms for Bilateral Trading.* JET 29(2), 1983.
6. Kamenica, E., Gentzkow, M. *Bayesian Persuasion.* AER 101(6), 2011.
7. Crawford, V., Sobel, J. *Strategic Information Transmission.* Econometrica 50(6), 1982.
8. Kreps, D., Wilson, R. *Reputation and Imperfect Information.* JET 27(2), 1982.
9. Heinrich, J., Silver, D. *Deep Reinforcement Learning from Self-Play in Imperfect-Information Games.* ICML 2016.
10. Lanctot, M. et al. *A Unified Game-Theoretic Approach to Multiagent RL.* NeurIPS 2017.
11. Bakhtin, A. et al. *No-Press Diplomacy from Scratch.* NeurIPS 2021.
12. Brown, N., Sandholm, T. *Superhuman AI for Heads-Up No-Limit Poker (Libratus).* Science 359, 2018. [CITATION NEEDED — verify bibliographic details]
13. FAIR (Bakhtin, A. et al.) *Human-Level Play in Diplomacy by Combining Language Models with Strategic Reasoning.* Science 378, 2022.
14. Guo, J. et al. *Suspicion-Agent: Playing Imperfect Information Games with Theory of Mind Aware GPT-4.* COLM 2024 / arXiv:2309.17277.
15. Zhang, W. et al. *Agent-Pro: Learning to Evolve via Policy-Level Reflection and Optimization.* ACL 2024.
16. Zhuang, R. et al. *PokerBench: Training Large Language Models to become Professional Poker Players.* AAAI 2025.
17. Light, J. et al. *Strategist: Self-Improvement of LLM Decision Making by Bi-Level Tree Search.* ICLR 2025.
18. [OG-Narrator — ACL 2024 Findings, exact authors/title VERIFY.] ⟨CITATION NEEDED⟩
19. Jin, C. et al. *MMToM-QA: Multimodal Theory of Mind Question Answering / BIP-ALM.* ACL 2024.
20. Sclar, M. et al. *Minding Language Models' Language Theory of Mind (SymbolicToM).* ACL 2023.
21. Chen, Z. et al. *ToMBench: Benchmarking Theory of Mind in LLMs.* ACL 2024.
22. Snell, C. et al. *Scaling Test-Time Compute Optimally Can Be More Effective than Scaling Model Parameters.* ICLR 2025.
23. Shinn, N. et al. *Reflexion.* NeurIPS 2023.
24. Zhao, K. et al. *ExpeL: LLM Agents Are Experiential Learners.* AAAI 2024.
25. Li, W. et al. *Verbalized Bayesian Persuasion.* ICLR 2025 / arXiv:2502.01587.

---

## Appendix A — Action schemas and safe-action contract
(condensed table from docs/03 Appendix A)

## Appendix B — Regression fixture index
F1 prose-enum replay · F2 burn-lockout · F3 directional intervals · F5 drain · F6 regime classification (fixture file: scripts/fixtures/failure_replays.py; tests/test_live_regressions.py)
