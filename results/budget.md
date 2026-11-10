# Projected spend (paper v1)

Prices from the pinned catalogue snapshot; token counts are the plan's
pre-dry-run priors (2000 in / 300 out per agent call).

| block | model | runs | calls/run | $/run | $ total |
|---|---|---|---|---|---|
| exp1_primary_qwen | `qwen/qwen3.8-27b` | 720 | 3 | 0.00259 | 1.863 |
| exp1_secondary_llama | `meta-llama/llama-3.3-70b-instruct` | 480 | 3 | 0.00425 | 2.041 |
| exp2_ladder | `qwen/qwen3.8-27b` | 80 | 5 | 0.00431 | 0.345 |
| judge_escalations | `deepseek/deepseek-v4-pro` | 1792 | 1 | 0.00081 | 1.442 |
| dry_runs_primary | `qwen/qwen3.8-27b` | 10 | 3 | 0.00259 | 0.026 |
| dry_runs_secondary | `meta-llama/llama-3.3-70b-instruct` | 10 | 3 | 0.00425 | 0.043 |
| **subtotal** | | | | | **5.759** |

Limit $9.00, headroom $3.241, fits: True

## Observed per-call cost (uncached ledger entries)

| role | calls | mean prompt tok | mean completion tok | mean $/call | observed $ |
|---|---|---|---|---|---|
| agent_a | 6943 | 745.9 | 52.7 | 0.0000000 | 0.00000 |

