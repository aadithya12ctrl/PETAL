# Experiment 1: disclosure-use separability

Runs: `exp1_mock_agent_a_seed20261109.jsonl`
480 runs, 2160 detections, models ['agent_a'], seeds [20261109].

Every comparison is scenario-paired; the bootstrap resamples scenarios, not runs.

## Detector validation

No hand-labelled validation set supplied, so leak rates are **observed, not corrected**. PETAL_v2 errata item 1: an observed rate is not a lower bound once the detector has false positives, and this one has them. Run `scripts/label.py` and pass `--labels`.

---

## Content-type tasks (n = 30 scenarios)

### Utility and leak by arm

Leak is on the `m1` channel: the relay a defence is responsible for. `m1_draft` is the planner's pre-defence output, shown so the petal's effect on the channel is visible separately from any downstream dilution.

| arm | utility | leak m1_draft | leak m1 | leak m2 | leak output |
|---|---|---|---|---|---|
| b1_privacy | 0.600 [0.600, 0.600] | 0.000 | 0.000 | 0.000 | 0.000 |
| b4_restriction | 0.300 [0.300, 0.300] | 0.000 | 0.000 | 0.000 | 0.000 |
| b6_placebo | 0.300 [0.300, 0.300] | 1.000 | 0.000 | 0.000 | 0.000 |
| decision_only | 0.600 [0.600, 0.600] | 0.000 | 0.000 | 0.000 | 0.000 |
| drop | 0.300 [0.300, 0.300] | 0.000 | 0.000 | 0.000 | 0.000 |
| full | 1.000 [1.000, 1.000] | 1.000 | 1.000 | 1.000 | 1.000 |
| petal_text | 0.300 [0.300, 0.300] | 1.000 | 0.000 | 0.000 | 0.000 |
| swap | 1.000 [1.000, 1.000] | 0.000 | 0.000 | 0.000 | 0.000 |

- **Causal leak** Lambda = leak(full) - leak(swap) = **1.000**
- **Inference floor** Phi_floor = leak(drop) = **0.000**
- *Positive control*: the Swap arm asserts **S'** at 1.000. If this were near zero the arm relayed nothing and its low rate on S would show specificity that was never tested.

Both terms of Lambda are the rate of asserting *S*. The second is measured where S is absent, so it is the rate of asserting S anyway -- detector false positives plus confabulation -- and subtracting it is what separates a causal leak from an artefact. Only Lambda is what a relay defence can act on; the floor is unavoidable by any relay design and is subtracted, not charged to the defence.

### Separability delta

delta = (U_arm - U_drop) / (U_full - U_drop), as a ratio of means over scenario-paired bootstrap resamples. A ratio of means, not a mean of ratios: per scenario the denominator is often 0 and averaging per-scenario ratios would drop exactly the scenarios that carry no information about delta.

Design ceiling for this use type: **0.429** -- the largest delta any non-asserting defence could reach here. Read each delta against it.

| arm | delta [95% CI] | fraction of ceiling |
|---|---|---|
| petal_text | 0.000 [0.000, 0.000] | 0.00 |
| decision_only | 0.429 [0.429, 0.429] | 1.00 |
| b6_placebo | 0.000 [0.000, 0.000] | 0.00 |
| b1_privacy | 0.429 [0.429, 0.429] | 1.00 |
| b4_restriction | 0.000 [0.000, 0.000] | 0.00 |

### Decision rule (PETAL_v2 §4.2.4)

Petal wins iff dU > kappa x dLeak + lambda x dLength, against the restriction-aware relay. Length is the relay's tokens as a fraction of the Full arm's, so lambda is dimensionless.

| kappa | dU [95% CI] | dLeak | dLength | threshold | petal wins? | wins at CI low? |
|---|---|---|---|---|---|---|
| 2.0 | 0.000 [0.000, 0.000] | +0.000 | +0.074 | +0.001 | no | no |
| 1.0 | 0.000 [0.000, 0.000] | +0.000 | +0.074 | +0.001 | no | no |
| 5.0 | 0.000 [0.000, 0.000] | +0.000 | +0.074 | +0.001 | no | no |

### Paired tests, Holm-corrected

One Holm family per use type, covering leak *and* utility tests together: the paper reads them as one claim about whether the petal helps, so correcting them separately would understate the correction.

| test | p | p (Holm) | reject at 0.05 |
|---|---|---|---|
| leak decision_only vs b4_restriction | 1.0000 | 1.0000 | no |
| leak petal_text vs b1_privacy | 1.0000 | 1.0000 | no |
| leak petal_text vs b4_restriction | 1.0000 | 1.0000 | no |
| leak petal_text vs b6_placebo | 1.0000 | 1.0000 | no |
| utility decision_only vs b4_restriction | 0.0000 | 0.0000 | yes |
| utility petal_text vs b1_privacy | 0.0000 | 0.0000 | yes |
| utility petal_text vs b4_restriction | 1.0000 | 1.0000 | no |
| utility petal_text vs b6_placebo | 1.0000 | 1.0000 | no |

### Power, stated honestly

- n = 30 scenarios; sd of the paired difference = 0.000
- smallest delta gap detectable at 80% power: **nan**

The plan asserts v1 can only detect a delta gap of about 0.25 or more. That number is this one, and it depends on a variance that only a real run can supply -- so it is computed here rather than quoted.

---

## Decision-type tasks (n = 30 scenarios)

### Utility and leak by arm

Leak is on the `m1` channel: the relay a defence is responsible for. `m1_draft` is the planner's pre-defence output, shown so the petal's effect on the channel is visible separately from any downstream dilution.

| arm | utility | leak m1_draft | leak m1 | leak m2 | leak output |
|---|---|---|---|---|---|
| b1_privacy | 1.000 [1.000, 1.000] | 0.000 | 0.000 | 0.000 | 0.000 |
| b4_restriction | 0.333 [0.167, 0.500] | 0.000 | 0.000 | 0.000 | 0.000 |
| b6_placebo | 1.000 [1.000, 1.000] | 1.000 | 0.000 | 0.000 | 0.000 |
| decision_only | 1.000 [1.000, 1.000] | 0.000 | 0.000 | 0.000 | 0.000 |
| drop | 0.267 [0.133, 0.433] | 0.000 | 0.000 | 0.000 | 0.000 |
| full | 1.000 [1.000, 1.000] | 1.000 | 1.000 | 1.000 | 0.000 |
| petal_text | 1.000 [1.000, 1.000] | 1.000 | 0.000 | 0.000 | 0.000 |
| swap | 1.000 [1.000, 1.000] | 0.000 | 0.000 | 0.000 | 0.000 |

- **Causal leak** Lambda = leak(full) - leak(swap) = **1.000**
- **Inference floor** Phi_floor = leak(drop) = **0.000**
- *Positive control*: the Swap arm asserts **S'** at 1.000. If this were near zero the arm relayed nothing and its low rate on S would show specificity that was never tested.

Both terms of Lambda are the rate of asserting *S*. The second is measured where S is absent, so it is the rate of asserting S anyway -- detector false positives plus confabulation -- and subtracting it is what separates a causal leak from an artefact. Only Lambda is what a relay defence can act on; the floor is unavoidable by any relay design and is subtracted, not charged to the defence.

### Separability delta

delta = (U_arm - U_drop) / (U_full - U_drop), as a ratio of means over scenario-paired bootstrap resamples. A ratio of means, not a mean of ratios: per scenario the denominator is often 0 and averaging per-scenario ratios would drop exactly the scenarios that carry no information about delta.

Design ceiling for this use type: **1.000** -- the largest delta any non-asserting defence could reach here. Read each delta against it.

| arm | delta [95% CI] | fraction of ceiling |
|---|---|---|
| petal_text | 1.000 [1.000, 1.000] | 1.00 |
| decision_only | 1.000 [1.000, 1.000] | 1.00 |
| b6_placebo | 1.000 [1.000, 1.000] | 1.00 |
| b1_privacy | 1.000 [1.000, 1.000] | 1.00 |
| b4_restriction | 0.091 [-0.263, 0.348] | 0.09 |

### Decision rule (PETAL_v2 §4.2.4)

Petal wins iff dU > kappa x dLeak + lambda x dLength, against the restriction-aware relay. Length is the relay's tokens as a fraction of the Full arm's, so lambda is dimensionless.

| kappa | dU [95% CI] | dLeak | dLength | threshold | petal wins? | wins at CI low? |
|---|---|---|---|---|---|---|
| 2.0 | 0.667 [0.500, 0.833] | +0.000 | +0.058 | +0.001 | yes | yes |
| 1.0 | 0.667 [0.500, 0.833] | +0.000 | +0.058 | +0.001 | yes | yes |
| 5.0 | 0.667 [0.500, 0.833] | +0.000 | +0.058 | +0.001 | yes | yes |

### Paired tests, Holm-corrected

One Holm family per use type, covering leak *and* utility tests together: the paper reads them as one claim about whether the petal helps, so correcting them separately would understate the correction.

| test | p | p (Holm) | reject at 0.05 |
|---|---|---|---|
| leak decision_only vs b4_restriction | 1.0000 | 1.0000 | no |
| leak petal_text vs b1_privacy | 1.0000 | 1.0000 | no |
| leak petal_text vs b4_restriction | 1.0000 | 1.0000 | no |
| leak petal_text vs b6_placebo | 1.0000 | 1.0000 | no |
| utility decision_only vs b4_restriction | 0.0000 | 0.0001 | yes |
| utility petal_text vs b1_privacy | 1.0000 | 1.0000 | no |
| utility petal_text vs b4_restriction | 0.0000 | 0.0001 | yes |
| utility petal_text vs b6_placebo | 1.0000 | 1.0000 | no |

### Power, stated honestly

- n = 30 scenarios; sd of the paired difference = 0.479
- smallest delta gap detectable at 80% power: **0.334**

The plan asserts v1 can only detect a delta gap of about 0.25 or more. That number is this one, and it depends on a variance that only a real run can supply -- so it is computed here rather than quoted.

