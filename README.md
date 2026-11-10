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
| 4 | NLI detector + judge escalation + Rogan–Gladen + human tooling | **done** |
| 5 | Exp 2 stochastic ladder + probes | **done** |
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

## Phase 4: the leak detector

A three-stage cascade in [petal/detector.py](petal/detector.py), in increasing
cost: a lexical gate on watched surface forms (free), a local MNLI cross-encoder
(free), then a paid LLM judge only where the first two leave the answer
uncertain or **disagree**.

**The hypothesis must be name-generic, and this is not cosmetic.** Relay
messages normally say "the patient" or "the subject", not the person's name.
Scored against a *named* hypothesis, an NLI model rates a verbatim unnamed
restatement at **0.000**, because the premise does not establish who it is
about — a detector with near-zero sensitivity on exactly the leaks that matter.
Measured on the testbed probes:

| premise | named hypothesis | generic hypothesis |
|---|---|---|
| verbatim, unnamed | 0.000 | **0.998** |
| paraphrase, unnamed | 0.002 | **0.996** |
| euphemism ("machine-based blood-filtering") | 0.299 | **0.989** |
| abstraction only | 0.000 | 0.000 |
| *different* restricted condition | 0.002 | 0.003 |

`Secret.proposition_generic` carries that form, and it is what the detector is
given.

**Entailment runs as a separate, resumable pass.** The plan already specifies
"DeBERTa-MNLI on Colab". That turned out to be necessary rather than
convenient: on this machine (8 GB, commit charge near its limit) loading a
255 MB weight file dies with a *process-level* access violation inside the
`safetensors` memory-map — not an exception, so it cannot be caught and retried
in process. So scoring is decoupled:

```
py -3.12 scripts/detect.py --runs R --emit-pairs   # unique (span, hypothesis) pairs
<notebooks/petal_nli_colab.ipynb on Colab GPU>     # -> R_nli.jsonl + meta
py -3.12 scripts/detect.py --runs R                # reads the cache, no torch
```

`scripts/nli_score.py` does the same locally when memory allows, chunked and
resumable. The notebook is generated by
[scripts/make_nli_notebook.py](scripts/make_nli_notebook.py) so that its
`pair_key` cannot drift from `petal.detector.pair_key` — it embeds a test vector
from the real function and asserts before scoring, because a key mismatch would
file every score under a key the detector never queries and the pass would look
like it never ran.

**Measured on the offline matrix** (1,920 texts, scored by
`DeBERTa-v3-large-mnli-fever-anli-ling-wanli` on a T4):

- the score distribution is strongly bimodal: 1,371 texts below 0.1, 515 above
  0.9, and **1.2%** between 0.25 and 0.75
- across 44 watched surface forms, median entailment where a form is present is
  **0.999** — the two independent signals agree
- judge escalation is **14 of 1,920 texts (0.7%)**, against the plan's assumed
  ~1.4 calls per run. That takes the judge line from $1.44 to roughly $0.01.
  Real relays will escalate more often, but the band is narrow.

**Two changes the measurement forced.**

1. *A lexical hit is no longer decisive on its own.* 18 texts carried a watched
   form while entailment said 0.003. Those are lexical false positives, and the
   cascade now escalates a disagreement rather than letting either signal win.
2. *Six surface forms were over-broad* and are the reason those false positives
   existed: a bare `terminal` (an airport terminal, in the travel domain),
   `sanctioned` (meaning approved), `expecting` (a delivery), `trauma`, `carer`.
   Tightened to `terminal prognosis`, `benefit sanctions`, `expecting a baby`,
   and so on. Disagreements fell from 18 to 14.

**Rogan–Gladen** is in [petal/correction.py](petal/correction.py), with a
bootstrap that resamples the trace set *and* the validation set — holding Se and
Sp fixed would give intervals that are too narrow. It refuses to invert a
detector whose Youden index is at or below 0.05 rather than returning a number
that explodes.

**Validation sampling** ([petal/labelling.py](petal/labelling.py)) stratifies on
(arm × detector verdict), because leaks are rare in the defended arms and a
simple random 200 would contain almost no positives — leaving sensitivity resting
on a handful of items. The consequence is recorded in the module: a
verdict-stratified sheet supplies Se and Sp only, never prevalence, which comes
from the full detection run.

**A second cache-staleness bug, same family as Phase 3's.** The cache key is the
request payload, which is right for a real provider — its reply depends on the
prompt and nothing else. A *scripted* agent's reply also depends on scenario data
that never appears in the prompt, so editing the surface-form lists left 1,500
cached replies looking valid while being stale. The mock's version now hashes its
own source **and** the scenario data.

## Phase 4 tooling for the human steps

```
py -3.12 scripts/check_key.py                  # verify the credential, zero spend
py -3.12 scripts/handcheck.py [--all|--report] # guided scenario hand-check
py -3.12 scripts/label.py --sheet S [--report] # E0 hand-labelling, resumable
py -3.12 scripts/label.py --sheet S --kappa S2 # two-rater agreement
```

### The hand-check gate, and what replaced it

The plan makes a human hand-check of the 60 scenarios a gate before any spend.
We are not doing one, and `scripts/audit_testbed.py` is the substitute. This
should be stated plainly in the paper's limitations, because the trade is real.

**What is lost**: nobody has judged whether a case file reads like something an
organisation would really hold. If the files are transparently synthetic in a way
that changes how a model behaves, no automated check can see it.

**What is gained**: every *other* question a hand-check would ask is a claim
about model behaviour, and such claims are better settled by measurement than by
introspection -- including the author's. The audit reads real run output and maps
each hand-check question onto a measurement:

| hand-check question | measurement |
|---|---|
| does the annex force the answer? | Full-arm accuracy ~ 1.0 |
| does the swap change the answer? | Swap arm reaches the S' key, and chooses differently |
| is the restricted fact unguessable from permitted context? | Drop-arm leak rate ~ 0, i.e. Phi_floor |
| is the restricted fact actually needed? | Drop-arm accuracy sits at the 1/3 floor |
| do the content tiers behave? | Drop earns the permitted tier and nothing above it |

A scenario that fails is a scenario bug, listed by id, to be fixed before the
reported run.

**The audit caught a flaw in its own first version**, which is worth recording
because it is the same mistake a human reviewer would have made. It flagged 8 of
30 decision scenarios as "solvable without S" on the strength of the Drop arm
scoring 1.00 — but the Drop arm guesses among three viable options, so one run in
three is a lucky guess, and 8/30 = 0.267 *is* chance. Per-scenario the two are
indistinguishable without replicates. The check now requires three or more runs
per scenario, and the real evidence is a population-level one-sided binomial test
of Drop-arm accuracy against the 1/3 floor (offline: 8/30, p = 0.83, i.e. no
evidence the files carry the answer).

## Phase 5: the stochastic ladder (Experiment 2)

Five-hop chain, four schedules, 20 scenarios. The ladder lives in
[petal/ladder.py](petal/ladder.py), the chain in [petal/chain.py](petal/chain.py),
the probes in [petal/probe.py](petal/probe.py).

**Alphabets come from the testbed, not from the paper's example.** Eta depends on
k, so quoting a contraction factor against an invented alphabet would be quoting a
bound the experiment never runs under. The medical-kind ladder is
k = (23, 12, 4, 2) with p = (0.8, 0.7, 0.6, 0.6), giving

| rung | k | p | eta |
|---|---|---|---|
| exact proposition | 23 | 0.80 | 0.7909 |
| clinical area | 12 | 0.70 | 0.6727 |
| kind | 4 | 0.60 | 0.4667 |
| placeholder | 2 | 0.60 | 0.2000 |

Product **0.0497**, against the 0.039 PETAL_v2 §4.3 quotes for an illustrative
(20, 5, 3, 2). A larger k raises eta for fixed p, so the real ladder contracts
slightly *less* than the paper's example — worth stating rather than quoting the
nicer number.

**The composition bug, which was the crux of this phase.** The first version
re-coarsened the *original* S at every hop. That makes the hops conditionally
independent given S rather than a Markov chain, and T3's product bound does not
apply to it — only the single rung's eta does. So the experiment would have been
testing a bound it was not running under. `ladder.coarsen` now maps the previous
*emitted* symbol to the next rung, so when rung 0's randomised response emits the
wrong condition, rung 1 reports *that* condition's area. The error propagates,
which is what makes the composition contract.

**Scope, which the paper insists on.** T3 bounds the slot that carries S. The
chain therefore keeps the slot explicit (`CARRIED NOTE`), so the probe measures
the slot and the detector measures the free text the agent wrote around it,
instead of conflating them. `rewrite_slot` appends the note when an agent dropped
it rather than treating that hop as having transmitted nothing — which would
flatter the decay.

**Two probe corrections.** H4 compares a measured lower bound against a
theoretical upper bound, and both sides needed care:

1. *Fano returns 0.065 bits for an error rate of 1.0 at k = 23*, because an
   estimator that is reliably wrong is informative. True in general, but here an
   error at or above chance means the slot was empty and the probe guessed —
   reporting 0.065 bits would put a floor under every decay curve. Clamped to 0
   at chance.
2. *At n = 20 the noise on an error rate is about ±0.09.* The point estimate
   breached the bound at stochastic hop 1 (LB 3.609 vs UB 3.578) purely because
   2 errors came up instead of the expected 4. H4 now fires on Fano evaluated at
   the one-sided 95% Clopper-Pearson upper limit of the error rate, and that row
   is reported as "point est. only".

**A data bug the tests caught**, with a silent consequence: `pregnancy` (HR) was
kind `personal` while `pregnancy_travel` was `medical`, though both assert "the
subject is pregnant". Exp 2 selects medical-kind scenarios, the proposition
lookup resolved to the `personal` category, and the ladder then emitted a rung-2
symbol outside the alphabet of the rung it was built for. `pregnancy` is now
medical, `category_for` takes the expected kind, and a test asserts that every
shared proposition's categories agree on kind *and* area.

Offline decay (mock agents, so the numbers demonstrate the instrument, not a
result): the `none` schedule holds at 4.52 bits across all four hops; the
stochastic ladder falls to 0 by hop 2 and its bound falls 3.58 → 2.41 → 1.12 →
0.23; `random_dropout`, matched on per-hop truthfulness, decays more slowly
(1.77 → 0.88 → 0.52 → 0.12) because silence preserves category identity when it
does speak, whereas coarsening destroys it immediately. That contrast is the
control the plan asked for.
