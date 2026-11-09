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
| 2 | 60 scenarios + deterministic scorers | **done** |
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
py -3.12 scripts/check_models.py [--write]     # verify plan model ids, snapshot catalogue, price them
py -3.12 scripts/budget_report.py [--ledger]   # project spend; --ledger adds observed per-call cost
py -3.12 scripts/build_scenarios.py [--strict] # build + validate the 60-scenario testbed
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

## Phase 2: the testbed

60 scenarios (30 decision-type, 30 content-type) across the plan's six domains,
from twelve hand-written templates in
[petal/scenarios/templates.py](petal/scenarios/templates.py). Permitted contexts
run 1247–1412 tokens. All people, organisations and identifiers are fictional.

**Decision instances are built by elimination, not by assertion.** Four options,
each with a *permitted* requirement printed in the case file. The restricted
annex bars exactly two; a permitted service-level constraint removes one more;
exactly one survives. So three options are viable without S — the floor for
U_drop is 1/3 — and the answer follows from the annex rather than sitting next to
it. The swap S′ is drawn from the categories that bar the answer-under-S while
leaving the eliminated option alone, which guarantees the swap *changes the
answer*: the Swap arm can therefore show that an agent used S, not merely that it
talked about S.

**The δ ceiling, and why the headline claim is not circular.** Conjecture C1 says
δ is low when the output must *contain* S-derived content. If content rubrics put
all their credit on items requiring an assertion of S, δ ≈ 0 would follow from
rubric design and measuring it would prove nothing. So every rubric item records
whether earning it requires asserting the restricted proposition, and each
scenario publishes

```
delta_ceiling = (U_max_without_asserting_S − U_chance) / (1 − U_chance)
```

which is **1.00 for decision-type and 0.40 for content-type**. A measured δ is
read against its own ceiling, so the claim under test becomes "δ sits near
ceiling for decision-type and far below it for content-type" — a statement about
agents, not about our rubric. `tests/test_phase2.py` pins this down: an answer
that satisfies every non-entailing rubric item and asserts nothing scores
*exactly* 0.40.

**Validation is a build gate.** `validate()` rejects a scenario whose swap leaves
the answer unchanged, whose correct answer is reachable by elimination alone,
whose rubric is all-entailing or none-entailing, or — the one that actually fired
— whose permitted context contains any surface form of the restricted content.
That last check caught the Tier A requirement in the loan domain naming the
restricted condition outright ("no active debt-management arrangement"), which
would have turned causal leaks into inference-floor events across that whole
domain. Reworded to "a clear conduct marker on the member record"; all 60 now
pass under `--strict`.

**For your hand-check:** `data/scenarios/handcheck.md` has one block per scenario
— annex, swap, watched surface forms, answer key or rubric, and the full
permitted context. Per scenario, confirm (a) the annex really does rule out the
options the build note claims, (b) the answer under S is the only survivor,
(c) the swap changes the answer, (d) nothing in the permitted context gives the
proposition away. Summary: `results/testbed_summary.md`.
