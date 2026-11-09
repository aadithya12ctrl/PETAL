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
| 3 | 3-hop relay harness, 8 arms, gap detection, petal, decision-only relay | **done** |
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
py -3.12 scripts/run_exp1.py                   # Experiment 1, offline mock, zero cost
py -3.12 scripts/run_exp1.py --paid --yes ...  # Experiment 1 for real (needs both flags)
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

## Phase 3: the relay harness

Three hops (planner → worker → reporter), shared memory off, so the side-input
term of Theorem T1 is zero by construction. Only the planner sees the case file
or an annex; every hop sees the same permitted task brief, so an arm difference
can never be an artefact of one arm knowing the task better. The eight arms are
in [petal/arms.py](petal/arms.py), the prompts in
[petal/prompts.py](petal/prompts.py), gap detection and the two fillers in
[petal/gaps.py](petal/gaps.py).

**Gap detection.** Definition 2 wants positions where sampled continuations
assert S above τ_g. Sampling per position costs a call per position, which this
budget cannot carry, so we score *spans of the planner's own draft*: the draft
*is* the model's continuation, and a span that asserts S is a position where
asserting S is what the model in fact does. The scorer is swappable —
`LexicalScorer` now (surface forms, word-bounded, conservative), the Phase 4 NLI
scorer later, which is what makes τ_g a real probability rather than a 0/1 cut.

**The petal.** Flagged spans are masked and refilled by one extra call whose
context omits the annex, so the filler is drawn from `p(· | C \ S)` and
`f ⊥ S | A` holds for the filler itself. The unmasked remainder of the draft is
still conditioned on S; that residual is exactly what §4.2.3's filler-
independence test measures, and it is recorded per run rather than assumed away.

**B6 is a genuine matched placebo.** `full`, `b6_placebo` and `petal_text` send
the planner an identical prompt at an identical seed, so they share one cached
draft. B6 then fills *the same spans of the same text* with permitted but
irrelevant notices of matched length. A difference between B6 and the petal is
therefore attributable to *what* fills the slot, not to the draft differing or to
the mere fact that something fills it.

**Two things changed in Phase 2's output as a result.**

1. The permitted context stated the no-relay prohibition outright, which made
   `Full` already-defended and left `B1` with nothing to contribute. The
   prohibition now lives only in B1's prompt; the file keeps descriptive
   classification language. A test asserts the Full context contains no relay
   prohibition.
2. The file listed a "RESTRICTED ANNEX" section even in the Drop arm. "Something
   is being withheld" is itself information, and it differed between Drop and
   every other arm. The annex is now appended per arm by `prompts.annex_block`
   and A_text never mentions one.

**Swap-arm utility was being measured against the wrong key.** For content
scenarios the rubric is built from S's surface forms, so the Swap arm scored at
the permitted floor for a reason having nothing to do with the model. Each
content scenario now also carries `rubric_swap`, built around S′.

**A cache-correctness bug worth recording.** The cache key included the backend
*name* but not the mock's behaviour, so after the scripted agents were fixed,
four scenarios were still being served results generated by the superseded
logic — and they showed up as a plausible-looking 93% instead of 100%. Backends
now expose a `version` that participates in the key: empty for a real provider
(whose responses do not depend on our code), a hash of the module source for
anything simulated.

**Pipeline verification** (scripted mock agents — *not* results; they exist so
the harness and the analysis can be asserted on at zero cost):

| arm | U decision | U content | leak m1_draft | m1 | m2 | output |
|---|---|---|---|---|---|---|
| full | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 |
| swap | 1.000 | 1.000 | 0 | 0 | 0 | 0 |
| drop | 0.267 | 0.300 | 0 | 0 | 0 | 0 |
| b1_privacy | 1.000 | 0.600 | 0 | 0 | 0 | 0 |
| b4_restriction | 0.333 | 0.300 | 0 | 0 | 0 | 0 |
| b6_placebo | 1.000 | 0.300 | 1.000 | 0 | 0 | 0 |
| petal_text | 1.000 | 0.300 | 1.000 | 0 | 0 | 0 |
| decision_only | 1.000 | 0.600 | 0 | 0 | 0 | 0 |

The petal and placebo rows show the mechanism working on the channel: the draft
leaks, the relay does not. Measured δ lands exactly on each use type's designed
ceiling (decision 1.000, content 0.429), which is what we want from a harness
test — the real question is where a real model lands inside that range.

**Cost note.** Draft sharing plus the cache turns 1,500 logical calls into 1,234
paid ones per model (2.57 per run, not 3), so Experiment 1 should come in ~14%
under the Phase 1 projection. The dry runs will recalibrate from the ledger.
