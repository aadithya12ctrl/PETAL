# H8: the realistic attacker

A model is given exactly what a downstream agent is given -- the permitted case
file plus the relay -- and asked which of six candidate propositions is true of
the subject. One is. Chance is 1/6 = 0.167.

The population is the complete set of decision-task relays from `agent_a`
(Qwen): 30 scenarios in each of four arms, 120 relays, the same 30 scenarios in
every arm. Model `deepseek/deepseek-v4-pro`, seed 20261109.

**This replaces a withdrawn result.** The first two runs of this measurement
were invalid: the attacker's reply was being truncated at a 200-token budget
and the empty string was scored as a failure to identify S, at rates from 40%
(Full) to 87% (Drop). See post-freeze harness change 4 in `prefreeze_rule.md`.
In this run 119 of 120 relays produced a parseable answer; the one that did not
is counted as a miss.

## Recovery

| arm | k/n | recovers S | 95% CI | vs chance 0.167 |
|---|---|---|---|---|
| full | 25/30 | **0.833** | [0.653, 0.944] | above |
| decision_only | 10/30 | 0.333 | [0.173, 0.528] | above |
| constraint_only | 8/30 | 0.267 | [0.123, 0.459] | not distinguishable |
| drop | 6/30 | 0.200 | [0.077, 0.386] | not distinguishable |

Clopper-Pearson, two-sided.

## Drop is the floor, not chance

**Drop recovers 0.200, above the 1/6 baseline.** That is not a defect. The
attacker reads the permitted case file as well as the relay, and in the Drop
arm the relay says nothing about S at all -- so 0.200 is what the *permitted
information* alone yields. It is the LLM-adversary counterpart of the inference
floor Phi_floor, and it is the baseline every defended arm has to be measured
against. Measuring against 0.167 would credit the defence with hiding things
the attacker was entitled to see.

The scenarios are identical across arms, so the contrasts are paired:

| contrast | difference | 95% CI (paired bootstrap) | discordant | McNemar exact |
|---|---|---|---|---|
| full - drop | **+0.633** | [+0.467, +0.800] | 19 / 0 | p < 0.0001 |
| decision_only - drop | +0.133 | [-0.067, +0.333] | 7 / 3 | p = 0.34 |
| constraint_only - drop | +0.067 | [-0.100, +0.233] | 5 / 3 | p = 0.73 |
| constraint_only - decision_only | -0.067 | [-0.267, +0.100] | 3 / 5 | p = 0.73 |

So: **the full relay hands the attacker S** -- 19 scenarios the attacker gets
right in Full and wrong in Drop, against none the other way, and a Fano lower
bound of 0.941 bits of the 2.585 available. **Neither defended arm is
distinguishable from the floor.**

## What this does not show

The two null results are not evidence of safety, and must not be written up as
if they were. At n = 30 the paired interval for `constraint_only` runs to
**+0.233**, so the data are equally consistent with the constraint giving the
attacker nothing and with its giving them a 23-point advantage over the
permitted file. The honest statement is that this attacker did not convert the
constraint into an identification at a rate this study could detect.

That matters because the decision-implied leakage is not in doubt on other
grounds: the answer alone carries up to log2(3) = 1.585 bits of the 2.585,
computed in closed form from the generator. `decision_only` is precisely the
arm where that information is present and nothing else is, and the attacker's
+0.133 over the floor is the direction the bits predict, at a magnitude this
sample cannot resolve. The bits are available in principle; **this** attacker
does not cash them in. A better-prompted or fine-tuned attacker is not ruled
out by anything here, and the relays themselves show why not -- see the
inferential-disclosure example in `prefreeze_rule.md`, where a thrice-weekly
non-deferrable appointment narrows the condition without asserting it.

## Checks

* **Not one domain.** Full recovers 3-5 of 5 in all six domains; both defended
  arms are at 0-2 of 5 in all six. Nothing is carried by a single testbed.

| domain | full | decision_only | constraint_only | drop |
|---|---|---|---|---|
| clinic_scheduling | 5/5 | 1/5 | 2/5 | 2/5 |
| hr_leave | 3/5 | 2/5 | 2/5 | 0/5 |
| insurance_claims | 5/5 | 1/5 | 1/5 | 1/5 |
| legal_intake | 4/5 | 2/5 | 2/5 | 1/5 |
| loan_prescreen | 3/5 | 1/5 | 1/5 | 1/5 |
| travel_accessibility | 5/5 | 3/5 | 0/5 | 1/5 |

* **Silence is now flat.** No-pick counts by arm: Full 0, Decision-only 0,
  Constraint-only 1, Drop 0. In the withdrawn runs they were 12, 24, 19 and 26
  of 30, sloping the wrong way. Every record carries `finish_reason` and
  `completion_tokens` so this is checkable from the results file alone.
* **Position does not encode the answer.** The candidate list is shuffled per
  scenario from the run seed.
* **13 of the 25 Full-arm hits** have an attacker rationale that says the
  message *states* the condition -- consistent with the detector's 0.763
  assertion rate on the same arm, from an independent reader.

Cost of this run: $0.42 for 120 relays plus 104 escalation rungs.
