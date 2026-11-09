# PETAL — paper v1 codebase

Implementation of `PETAL_execution_plan.md` (paper-v1 plan) against the theory in
`PETAL_v2.md`.

**One empirical claim** (disclosure–use separability δ is higher for decision-type
uses of restricted content than content-type uses) and **two theory claims**
(T1 ceiling with side inputs, T3 stochastic-ladder contraction), testable on real
models for under ~$8.

## Status

| Phase | Content | State |
|---|---|---|
| 1 | Repo, OpenRouter client, disk cache, cost meter, model verification | **done** |
| 2 | 60 scenarios + deterministic scorers | pending |
| 3 | 3-hop relay harness, 8 arms, gap detection, petal, decision-only relay | pending |
| 4 | Local NLI detector + judge escalation + Rogan–Gladen | pending |
| 5 | Exp 2 stochastic ladder + probes | pending |
| 6 | Analysis + figures | pending |
| 7 | Dry runs → live Exp 1 / Exp 2 | pending |
| 8 | Paper draft | pending |

## Setup

Python 3.12 (`py -3.12`). Dependencies in `requirements.txt` are already present
in the system interpreter; `statsmodels` is deliberately **not** required —
McNemar, Wilcoxon and Holm are implemented against `scipy` in phase 6.

Put the key in the environment or in a local `.env` (git-ignored):

```
OPENROUTER_API_KEY=sk-or-...
```

With no key present every component silently falls back to `MockBackend`, so the
whole pipeline runs end-to-end at zero cost. `LLMClient.is_paid` is the switch.

## Scripts

```
py -3.12 scripts/check_models.py [--write]   # verify plan model ids, snapshot catalogue, price them
py -3.12 scripts/budget_report.py [--ledger] # project spend; --ledger adds observed per-call cost
py -3.12 -m unittest discover -s tests -t . -v
```

## Phase 1 guarantees

Everything below is enforced in code and covered by `tests/test_phase1.py`.

* **Reproducible routing.** Every request carries `provider.allow_fallbacks=false`,
  `provider.require_parameters=true`, a fixed `seed`, and a per-role temperature.
  Without the provider pins the same OpenRouter model id can be served at
  different quantisations with different seed semantics, which would quietly
  break the paired comparisons in Exp 1.
* **Cache correctness.** The cache key is a sha256 over the canonicalised request
  *plus* role and backend. Changing model, messages, seed, temperature,
  max_tokens or routing produces a new key, so a cached response is never reused
  under settings it was not generated under. Writes are atomic; a corrupt entry
  is a miss, not a crash.
* **Two independent spend guards.** `reserve()` refuses a paid call whose
  worst-case cost (catalogue price × `max_tokens`) would cross the ceiling.
  `commit()` appends actual cost to an append-only JSONL ledger, and the running
  total is recomputed from that ledger on construction — a crashed run cannot
  forget what it already spent. Mock calls are never reserved against.
* **Provenance.** The `model` and `provider` that OpenRouter actually served are
  logged with every call, as the plan requires.

### Model verification result

All four model ids in the plan exist in the live catalogue (461 models,
snapshotted to `data/openrouter_models.json`):

| role | model | price (per M tokens, in/out) |
|---|---|---|
| agent A (primary) | `qwen/qwen3.8-27b` | $0.150 / $1.875 |
| agent B | `meta-llama/llama-3.3-70b-instruct` | $0.590 / $0.790 |
| judge | `deepseek/deepseek-v4-pro` | $0.894 / $1.788 |
| dev | `openai/gpt-oss-20b` | $0.030 / $0.130 |

### Budget check

Recomputing the plan's matrix from real prices gives **$5.76**, against the
plan's estimate of $5.50 and a $9.00 ceiling — so it fits, with $3.24 headroom.
The per-block split differs from the plan, which matters for where to economise:

* Llama-3.3-70B is ~2.5× the plan's guess ($2.04 vs $0.80) — it is now the
  largest single line, not the judge.
* The judge is ~half the plan's guess ($1.44 vs $3.10), because escalations are
  short.
* Qwen's completion price ($1.875/M) dominates its own cost, so `max_tokens` on
  agent calls is the most effective knob.

Full report: `results/budget.md`, `results/model_check.md`.
