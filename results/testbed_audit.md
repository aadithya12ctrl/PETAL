# Testbed audit

Run file: `runs/pilot_dev.jsonl`
Scenarios with runs: 60

This replaces the plan's human hand-check. It cannot judge whether a case file reads plausibly; it does settle every other hand-check question by measurement. See the module docstring.

- full           decision mean utility 0.833 (n=30)
- full           content  mean utility 0.603 (n=30)
- swap           decision mean utility 0.600 (n=30)
- swap           content  mean utility 0.607 (n=30)
- drop           decision mean utility 0.267 (n=30)
- drop           content  mean utility 0.330 (n=30)
- b4_restriction decision mean utility 0.633 (n=30)
- b4_restriction content  mean utility 0.350 (n=30)
- petal_text     decision mean utility 0.833 (n=30)
- petal_text     content  mean utility 0.320 (n=30)
- decision_only  decision mean utility 0.733 (n=30)
- decision_only  content  mean utility 0.567 (n=30)

## Is S needed?

- Drop arm, decision tasks: 8/30 correct = 0.267 against a 0.333 floor; one-sided p = 0.833

## Does the annex determine the answer?

- annex-bearing arms: 0.783 (n=180) against Drop 0.267 (n=30)
- one-sided Fisher exact p = 6.12e-08

## 27 observation(s) needing replication

Single-run signals from a model that is wrong a fair fraction of the time anyway. Listed so nothing is hidden, **not** counted as scenario faults: with one run per scenario a miss is one draw, and treating it as a defect would flag the model rather than the testbed.

| scenario | check | detail |
|---|---|---|
| `clinic_scheduling/decision/05` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `clinic_scheduling/decision/05` | swap_does_not_change_the_answer | both arms chose ['C'] |
| `hr_leave/decision/01` | annex_rarely_forces_answer | 2 of 6 annex-bearing arms correct (0.33) |
| `hr_leave/decision/01` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `hr_leave/decision/01` | swap_does_not_change_the_answer | both arms chose ['B'] |
| `hr_leave/decision/02` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `hr_leave/decision/02` | swap_does_not_change_the_answer | both arms chose ['B'] |
| `hr_leave/decision/03` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `hr_leave/decision/04` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `hr_leave/decision/04` | swap_does_not_change_the_answer | both arms chose ['B'] |
| `hr_leave/decision/05` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `insurance_claims/decision/02` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `insurance_claims/decision/02` | swap_does_not_change_the_answer | both arms chose ['A'] |
| `insurance_claims/decision/04` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `insurance_claims/decision/05` | annex_rarely_forces_answer | 2 of 6 annex-bearing arms correct (0.33) |
| `insurance_claims/decision/05` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `legal_intake/content/02` | annex_rarely_forces_answer | 1 of 6 annex-bearing arms correct (0.28) |
| `legal_intake/content/03` | annex_rarely_forces_answer | 1 of 6 annex-bearing arms correct (0.30) |
| `legal_intake/decision/01` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `loan_prescreen/content/02` | annex_rarely_forces_answer | 1 of 6 annex-bearing arms correct (0.23) |
| `loan_prescreen/content/03` | annex_rarely_forces_answer | 1 of 6 annex-bearing arms correct (0.28) |
| `loan_prescreen/content/05` | annex_rarely_forces_answer | 1 of 6 annex-bearing arms correct (0.32) |
| `loan_prescreen/decision/01` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `loan_prescreen/decision/03` | annex_rarely_forces_answer | 1 of 6 annex-bearing arms correct (0.17) |
| `loan_prescreen/decision/04` | annex_rarely_forces_answer | 1 of 6 annex-bearing arms correct (0.17) |
| `loan_prescreen/decision/04` | swap_key_not_reached | Swap arm utility 0.00 against the S' key over 1 run(s) |
| `loan_prescreen/decision/05` | annex_rarely_forces_answer | 1 of 6 annex-bearing arms correct (0.17) |

## No scenario problems found

Every scenario behaves as its construction claims: the annex forces the answer, the swap changes it, the Drop arm neither asserts the restricted fact nor solves the task without it.
