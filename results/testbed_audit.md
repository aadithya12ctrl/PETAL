# Testbed audit

Run file: `runs\exp1_mock_agent_a_seed20261109.jsonl`
Scenarios with runs: 60

This replaces the plan's human hand-check. It cannot judge whether a case file reads plausibly; it does settle every other hand-check question by measurement. See the module docstring.

- full           decision mean utility 1.000 (n=30)
- full           content  mean utility 1.000 (n=30)
- swap           decision mean utility 1.000 (n=30)
- swap           content  mean utility 1.000 (n=30)
- drop           decision mean utility 0.267 (n=30)
- drop           content  mean utility 0.300 (n=30)
- b4_restriction decision mean utility 0.333 (n=30)
- b4_restriction content  mean utility 0.300 (n=30)
- petal_text     decision mean utility 1.000 (n=30)
- petal_text     content  mean utility 0.300 (n=30)
- decision_only  decision mean utility 1.000 (n=30)
- decision_only  content  mean utility 0.600 (n=30)

## Is S needed?

- Drop arm, decision tasks: 8/30 correct = 0.267 against a 0.333 floor; one-sided p = 0.833

## No scenario problems found

Every scenario behaves as its construction claims: the annex forces the answer, the swap changes it, the Drop arm neither asserts the restricted fact nor solves the task without it.
