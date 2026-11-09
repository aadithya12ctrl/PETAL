# PETAL — Paper v1 Plan (small-budget, real models)
*Companion to PETAL_v2.md and PETAL_execution_plan.md · 9 Nov 2026 · budget: $10.54 OpenRouter balance*

---

## 1. What paper v1 is

A short paper (workshop-length, 4–6 pages + appendix) that makes **one empirical claim and two theory claims**, all testable on real models for under ~$8.

**Working title**
*Can Agents Use What They Cannot Say? Disclosure–Use Separability in Multi-Agent LLM Relays*

**Claims v1 makes**
1. **Empirical (headline):** separability δ differs by how S is used — higher for decision-type uses than content-type uses (Conjecture C1). A context-grown petal or a decision-only relay beats both a placebo filler and dropping the fact on decision-type tasks.
2. **Theory:** the corrected framework — the ceiling with side channels (T1) and the stochastic-ladder contraction bound (T3).
3. **Small check of T3:** measured decay of S along a 5-hop relay is at least as fast as the bound predicts.

**Claims v1 does NOT make** (left for the full study): dose–response curves, event-triggered collapse, adaptive attackers, CSS, AgentLeak/MAGPIE results.

---

## 2. Models (real, paid, pinned)

| Role | Model | Why |
|---|---|---|
| Agent family A (primary) | `qwen/qwen3.8-27b`, **thinking off** | Open-weight, cheap, agent-oriented; same weights can later run CSS locally |
| Agent family B | `meta-llama/llama-3.3-70b-instruct` | Different lab; directly comparable to the models in AgentLeak and MAGPIE |
| Judge (escalations only) | `deepseek/deepseek-v4-pro` | Strong; a family not used by any agent |
| Fast detector (all messages) | DeBERTa-MNLI on Colab | Free; first pass before the LLM judge |
| Dev / debugging only | `openai/gpt-oss-20b` or `:free` models | Never used for reported numbers |

**Settings:** provider pinned, `allow_fallbacks: false`, `require_parameters: true`, `seed` fixed, temperature 0.7 (agents) / 0 (judge). Log the `model` and `provider` returned with every call.

---

## 3. Testbed (synthetic, kept small and cheap)

- **60 scenarios:** 30 decision-type, 30 content-type, spread across 6 domains (clinic scheduling, insurance claims, HR leave, legal intake, loan pre-screen, travel with accessibility needs).
- **Topology:** 3-hop chain (planner → worker → reporter); shared memory **off** in v1 so T1's side-channel term is zero by design.
- **Short contexts:** about 1.5k tokens per scenario, so each run is roughly 3 calls × (2k in, 300 out).
- **Each scenario has:** A, Y, S, S′ (swap), the restricted statement, and a deterministic scorer.
- Hand-check all 60 (it's only 60).

---

## 4. Experiment matrix

### Exp 1 — separability (the headline)

| Arm | Description |
|---|---|
| Full | S present, no defence → U_full |
| Swap | S replaced by S′ → for the causal leak Λ |
| Drop | S removed from context → U_drop, inference floor |
| B1 | Privacy instruction |
| B4 | Restriction-aware relay (drops overlapping facts) |
| B6 | Placebo filler, matched length and style |
| Petal-text | Context-grown filler at detected gaps |
| Decision-only | Relay carries the decision computed with S, not S |

- 60 scenarios × 8 arms × 2 models × 1 seed = **960 runs**
- Plus a second seed on the primary model for the 4 key arms (Full, Drop, Petal-text, Decision-only): 60 × 4 = **240 runs**

### Exp 2 — ladder decay (T3 check)

- 20 scenarios, 5-hop chain, primary model only.
- Schedules: none / deterministic ladder / stochastic ladder (product of η ≈ 0.1) / random-dropout control.
- 20 × 4 = **80 runs** (5 calls each).
- At each hop, train a small probe (logistic regression on embeddings, run locally) to predict S from the relay message. Compare accuracy decay with the bound.

### Detector validation (E0, no extra API cost)

- Hand-label 200 relay messages drawn from Exp 1 runs (stratified by arm and by the fast detector's verdict).
- Report sensitivity and specificity; correct all leak rates with Rogan–Gladen.
- If a second labeller is available, report Cohen's κ on 100 of them.

---

## 5. Cost estimate

| Item | Runs | Cost per run | Total |
|---|---|---|---|
| Exp 1 agents, Qwen (8 arms + 2nd seed) | 720 | ~$0.0016 | ~$1.15 |
| Exp 1 agents, Llama-3.3-70B | 480 | ~$0.0017 | ~$0.80 |
| Exp 2 agents (5-hop) | 80 | ~$0.003 | ~$0.25 |
| LLM judge (~1.4 escalated texts/run) | ~1,280 | ~$0.0024 | ~$3.10 |
| Dry runs (10 per model, 2×) | ~40 | — | ~$0.20 |
| **Subtotal** | | | **~$5.50** |
| **Reserve** (reruns, bugs, prices drifting) | | | **~$5.00** |

The judge is the biggest line. If the fast detector turns out accurate in E0, raise its threshold and send fewer texts to the judge.

**Hard rules**
- Spending limit on the API key: **$9**.
- Disk-cache every call by hash of (model, provider, messages, seed).
- After the 40 dry runs, recompute cost per run from the logs before launching the full matrix.

---

## 6. Analysis

- **δ per use type**, computed as (U_arm − U_drop) / (U_full − U_drop) for Petal-text and Decision-only, with bootstrap 95% CIs over scenarios.
- **Corrected leak rates** per arm; causal leak Λ = leak(Full) − leak(Swap); floor = leak(Drop).
- **Paired tests:** Petal-text vs B6 and vs B1 (McNemar on leaks, Wilcoxon on utility); Holm correction.
- **Empirical decision rule:** U_petal − U_B4 vs κ·Δleak, using κ = 2 as in the toy, with κ ∈ {1, 5} as sensitivity.
- **Exp 2:** probe accuracy (converted to a mutual-information lower bound) per hop vs Π η_r.

**Power, stated honestly:** with 30 paired scenarios per use type, v1 can detect large effects only (roughly a δ gap of 0.25 or more between use types). The paper says so and reports CIs, not just p-values.

---

## 7. Paper outline (v1)

1. **Introduction:** internal-channel leakage evidence (AgentLeak, MAGPIE); the use-without-saying question.
2. **Framework:** setting, causal leak vs floor, δ; T1 and T3 with proofs; toy decision rule (both readings, briefly).
3. **Method:** text petal; decision-only relay; stochastic ladder.
4. **Experiments:** testbed, models, detector validation, Exp 1, Exp 2.
5. **Results:** δ by use type; leakage–utility table per arm and model; ladder decay vs bound.
6. **Limitations:** small n, synthetic only, two models, no adaptive attacker.
7. **Roadmap:** collapse, CSS, attackers, benchmarks — i.e. the full study.

---

## 8. Timeline (about 3 weeks)

| Week | Work | API spend |
|---|---|---|
| 1 | Repo, client, cache, cost meter; write and hand-check 60 scenarios; debug on free models | ~$0 |
| 2 | Dry runs → full Exp 1 → hand-label 200 → Exp 2 | ~$5.5 |
| 3 | Analysis, figures, writing | ~$0 |

From Nov 20, ArkenOS agents can take over engineering, scenario drafting and critique passes at no cost (the scenarios still need your hand-check).

---

## 9. Upgrade path

If v1 shows δ clearly above zero on decision-type tasks, the full study (PETAL_execution_plan.md) scales the same pipeline: 400 scenarios, 3 seeds, a third model family, then MAGPIE/AgentLeak, collapse, CSS and attackers. The v1 results and preregistered config carry over unchanged.

If δ ≈ 0 for both use types, v1 is still publishable as a negative result plus the corrected theory, and the full study is not funded.