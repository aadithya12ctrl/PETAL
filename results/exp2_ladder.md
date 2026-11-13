# Experiment 2: ladder decay against Theorem T3

Run file: `runs/exp2_paid_agent_a_seed20261109.jsonl`
Kind: `medical`; probe over k = 47 candidate propositions; I(S;M_0) assumed at its maximum log2(k) = 5.55 bits.

## The ladder actually used

| rung | name | k | p | eta | cumulative eta |
|---|---|---|---|---|---|
| 0 | exact | 47 | 0.80 | 0.7957 | 0.79565 |
| 1 | area | 18 | 0.70 | 0.6824 | 0.54292 |
| 2 | kind | 4 | 0.60 | 0.4667 | 0.25336 |
| 3 | placeholder | 2 | 0.60 | 0.2000 | 0.05067 |
| 4 | dropped | 1 | 1.00 | 0.0000 | 0.00000 |

Product over the randomised rungs: **0.0507**. PETAL_v2 §4.3 quotes 0.039 for an illustrative (20, 5, 3, 2) alphabet; the testbed's real alphabets are larger, and a larger k raises eta for a fixed p, so the real ladder contracts slightly less than the paper's example.

## Measured decay

`probe LB` is the Fano lower bound on I(S; M_h) in bits from the matcher's error rate; `LB (cons.)` evaluates Fano at the one-sided 95% Clopper-Pearson upper limit of that error rate. `T3 UB` is (prod eta) x log2(k). **H4 fires on the conservative bound**, because at n = 20 the noise on an error rate is about +/- 0.09 and the point estimate alone breaches the bound by chance.

| schedule | hop | n | probe error | probe LB | LB (cons.) | T3 UB | H4 |
|---|---|---|---|---|---|---|---|
| none | 1 | 20 | 0.550 | 1.524 | 0.635 | 5.555 |  |
| none | 2 | 20 | 0.550 | 1.524 | 0.635 | 5.555 |  |
| none | 3 | 20 | 0.450 | 2.076 | 1.016 | 5.555 |  |
| none | 4 | 20 | 0.350 | 2.687 | 1.482 | 5.555 |  |
| deterministic | 1 | 20 | 0.550 | 1.524 | 0.635 | 5.555 |  |
| deterministic | 2 | 20 | 1.000 | 0.000 | 0.000 | 5.555 |  |
| deterministic | 3 | 20 | 1.000 | 0.000 | 0.000 | 5.555 |  |
| deterministic | 4 | 20 | 1.000 | 0.000 | 0.000 | 5.555 |  |
| stochastic | 1 | 20 | 0.550 | 1.524 | 0.635 | 4.420 |  |
| stochastic | 2 | 20 | 0.950 | 0.021 | 0.000 | 3.016 |  |
| stochastic | 3 | 20 | 1.000 | 0.000 | 0.000 | 1.407 |  |
| stochastic | 4 | 20 | 1.000 | 0.000 | 0.000 | 0.281 |  |
| random_dropout | 1 | 20 | 0.750 | 0.601 | 0.124 | 5.555 |  |
| random_dropout | 2 | 20 | 0.900 | 0.114 | 0.000 | 5.555 |  |
| random_dropout | 3 | 20 | 0.900 | 0.114 | 0.000 | 5.555 |  |
| random_dropout | 4 | 20 | 0.950 | 0.021 | 0.000 | 5.555 |  |

Chance error for this probe is 0.979, i.e. 0.000 bits.

## Outside the slot: what the agents carry on their own

Everything above is a probe of a channel *this code writes*. `petal.chain.rewrite_slot` applies the randomised response itself, so the symbol in the slot was drawn from the rung's alphabet by `petal.ladder.emit`: it satisfies T3 by construction, and H4 cannot fail there however the agents behave. A decay curve that tracks the bound is a test of this repository, not a result about relays.

The question that is about the agents is whether they carry S *around* the slot -- restating the condition in their own prose, or re-deriving it from the coarsened symbol and spelling it out again downstream. So the probe is re-run on each note with the ladder's line cut out. PETAL_v2 §4.3 puts exactly this outside T3's scope, and information found here above the ladder's bound is the side channel H4 was written to catch.

| schedule | hop | n | probe error | LB (cons.) | T3 UB | H4 (side) |
|---|---|---|---|---|---|---|
| none | 1 | 20 | 0.950 | 0.000 | 5.555 |  |
| none | 2 | 20 | 0.950 | 0.000 | 5.555 |  |
| none | 3 | 20 | 1.000 | 0.000 | 5.555 |  |
| none | 4 | 20 | 0.950 | 0.000 | 5.555 |  |
| deterministic | 1 | 20 | 0.950 | 0.000 | 5.555 |  |
| deterministic | 2 | 20 | 0.950 | 0.000 | 5.555 |  |
| deterministic | 3 | 20 | 1.000 | 0.000 | 5.555 |  |
| deterministic | 4 | 20 | 1.000 | 0.000 | 5.555 |  |
| stochastic | 1 | 20 | 0.950 | 0.000 | 4.420 |  |
| stochastic | 2 | 20 | 0.950 | 0.000 | 3.016 |  |
| stochastic | 3 | 20 | 1.000 | 0.000 | 1.407 |  |
| stochastic | 4 | 20 | 1.000 | 0.000 | 0.281 |  |
| random_dropout | 1 | 20 | 0.950 | 0.000 | 5.555 |  |
| random_dropout | 2 | 20 | 0.950 | 0.000 | 5.555 |  |
| random_dropout | 3 | 20 | 1.000 | 0.000 | 5.555 |  |
| random_dropout | 4 | 20 | 1.000 | 0.000 | 5.555 |  |

The `none` schedule is the reference: it writes no slot, so its no-slot column is the whole note and its numbers should match the table above. Where a defended schedule's no-slot row is near the `none` row, the ladder is coarsening a symbol while the prose around it carries S regardless.

## Task utility by schedule

- none           mean utility 0.595 (n=20)
- deterministic  mean utility 0.595 (n=20)
- stochastic     mean utility 0.590 (n=20)
- random_dropout mean utility 0.605 (n=20)

## H4 verdict

Measured information stays at or below the T3 bound at every hop of every schedule, so there is no evidence of a channel the ladder does not control. Note this is the weaker direction of the test: a bound that holds is consistent with the ladder working and with the probe being weak, which is why the `none` schedule is reported alongside as the no-decay reference.
