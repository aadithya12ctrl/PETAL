# The entailment gap scan changed 2 gaps in 101

The petal masks spans of the planner's draft that disclose S, then regenerates
them from the permitted context alone. Which spans get masked is decided by a
*gap scorer*, and the scorer can be either a surface-form (lexical) gate or an
entailment model. `PETAL_v2` 3.2 requires assertion to be detected "by
entailment against the restricted statement, not verbatim match", so the petal
is run twice: once with the lexical gate, then again with entailment scores
from a GPU pass, keyed by `sha256(premise || hypothesis)`.

The second pass exists because a petal scored by a detector stronger than the
one it used to find its gaps yields only an upper bound on its leak rate and a
lower bound on its delta. This file reports what the second pass actually
changed, which is almost nothing -- and why that is a result rather than a
disappointment.

## What changed

| quantity | lexical | entailment |
|---|---|---|
| gaps found, `petal_text`, 60 scenarios | 99 | **101** |
| gaps in both sets | | **99** |
| added by entailment | | **2** |
| removed by entailment | | **0** |
| scenarios with an identical gap set | | **58 of 60** |
| Jaccard of the two gap sets | | **0.980** |
| mean gaps per draft | 1.65 | 1.68 |
| drafts with no gaps at all | 12 / 60 | 11 / 60 |

Gap sets were compared on character offsets within the same run record, not on
span text. The entailment set is a **strict superset**: every span the lexical
gate flagged stayed flagged, and two were added.

The two additions, with their entailment scores:

| scenario | score |
|---|---|
| `legal_intake/content/04` | 0.994 |
| `loan_prescreen/content/04` | 0.874 |

Both are genuine entailments of the restricted proposition that contain none of
its surface forms -- exactly the case the second pass was built for. There are
two of them.

## Why so few

Of the 101 gaps in the entailment pass, **99 carry a score of exactly 1.0**,
which is the lexical gate firing; only 2 come from the entailment model alone.
And of the 97 spans the entailment model scores above the threshold
(tau = 0.15), **97 ended up inside a gap**. The two scorers do not disagree
about anything: they agree on every span entailment flags, and entailment finds
two more.

The reason is a property of the **draft**, not of the detector. When the planner
discloses S in `m1_draft`, it does so by naming it -- "psychiatric day
programme", "maintenance haemodialysis", "non-molestation order". Naming is
precisely what a surface-form gate catches. The euphemistic and
schedule-shaped phrasings that need an entailment model to catch barely occur
in the undefended draft; they occur in the *defended relays*, which is a
different measurement (the leak rates in `exp1.md`, scored by the full
three-stage cascade).

So the honest statement is: **on these drafts a surface-form gate is within 2%
of an entailment model.** That is measured, not assumed, and it took the second
pass to establish it.

## What this licenses, and what it does not

**Licensed.** The petal may be reported as entailment-backed, because it is:
the gap scan ran against 2029 cached entailment scores with zero unscored
spans, and the paper can state that the entailment stage changed 2 of 101 gaps.
The upper-bound/lower-bound caveat that applies to a lexical-gap petal does not
apply here.

**Not licensed.** Nothing here says an entailment gap scorer is unnecessary in
general. It says it was nearly redundant *for these 60 drafts from this
planner*. A planner that hedged -- that wrote "a standing clinical commitment"
where this one wrote "psychiatric day programme" -- would invert the result, and
the paper should say so rather than generalise from one model's directness.

**Still to be stated plainly.** **11 of 60 drafts have no gaps at all.** On
those the petal is a literal no-op: the relay it emits is the Full arm's draft,
unmodified. That is not a detector failure -- there was nothing in those drafts
for either scorer to find -- but it dilutes the arm's measured effect toward
Full, and the petal's leak rate and delta must be reported with that count
beside them rather than averaged over 60 as though all 60 were defended.
