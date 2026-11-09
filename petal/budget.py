"""Projected spend for the paper-v1 matrix, from live catalogue prices.

The plan (PETAL_execution_plan.md section 5) carries per-run cost guesses. This
module recomputes them from the actual prices so the matrix can be gated on a
number rather than on a guess, and so the plan's hard rule -- "after the 40 dry
runs, recompute cost per run from the logs before launching the full matrix" --
has something to recompute into.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .costmeter import Price


@dataclass
class Workload:
    """One block of the matrix."""
    name: str
    role: str                # model role key
    runs: int
    calls_per_run: int
    prompt_tokens_per_call: int
    completion_tokens_per_call: int

    def tokens(self) -> tuple[int, int]:
        n = self.runs * self.calls_per_run
        return n * self.prompt_tokens_per_call, n * self.completion_tokens_per_call

    def cost(self, price: Price) -> float:
        pt, ct = self.tokens()
        return price.cost(pt, ct)


def paper_v1_workloads(cfg) -> list[Workload]:
    """The matrix of PETAL_execution_plan.md section 4.

    Exp 1: 60 scenarios x 8 arms x 2 models x 1 seed = 960 runs, split 480/480,
    plus 60 x 4 arms = 240 replication runs on the primary model -> 720 primary.
    Exp 2: 20 scenarios x 4 schedules = 80 runs at 5 hops.
    Judge: escalations only, ~1.4 texts per run over the 1040 Exp-1/Exp-2 runs.

    Token figures are the plan's testbed design (~1.5k-token scenarios, 3-hop
    chain): hop 1 sees the scenario, later hops see a relay message, so the mean
    prompt is below the first-hop prompt. 2000/300 is the plan's own figure and
    is kept here as the pre-dry-run prior.
    """
    n_arms_exp1 = 8
    n_sc = cfg.n_scenarios
    primary_runs = n_sc * n_arms_exp1 + n_sc * 4     # 480 + 240 = 720
    secondary_runs = n_sc * n_arms_exp1              # 480
    exp2_runs = 20 * 4                               # 80
    judge_calls = int(round(1.4 * (primary_runs + secondary_runs + exp2_runs)))
    return [
        Workload("exp1_primary_qwen", "agent_a", primary_runs, cfg.hops, 2000, 300),
        Workload("exp1_secondary_llama", "agent_b", secondary_runs, cfg.hops, 2000, 300),
        Workload("exp2_ladder", "agent_a", exp2_runs, cfg.ladder_hops, 2000, 300),
        Workload("judge_escalations", "judge", judge_calls, 1, 600, 150),
        Workload("dry_runs_primary", "agent_a", 10, cfg.hops, 2000, 300),
        Workload("dry_runs_secondary", "agent_b", 10, cfg.hops, 2000, 300),
    ]


def project(cfg, prices: dict[str, Price]) -> dict[str, Any]:
    rows = []
    total = 0.0
    for w in paper_v1_workloads(cfg):
        model = cfg.model(w.role).model
        price = prices.get(model, Price())
        c = w.cost(price)
        total += c
        pt, ct = w.tokens()
        rows.append({
            **asdict(w),
            "model": model,
            "prompt_tokens_total": pt,
            "completion_tokens_total": ct,
            "usd_per_run": round(c / w.runs, 6) if w.runs else 0.0,
            "usd_total": round(c, 4),
            "priced": model in prices,
        })
    return {
        "rows": rows,
        "subtotal_usd": round(total, 4),
        "limit_usd": cfg.spend_limit_usd,
        "headroom_usd": round(cfg.spend_limit_usd - total, 4),
        "fits": total <= cfg.spend_limit_usd,
    }


def markdown_table(proj: dict[str, Any]) -> str:
    out = ["| block | model | runs | calls/run | $/run | $ total |",
           "|---|---|---|---|---|---|"]
    for r in proj["rows"]:
        out.append("| %s | `%s` | %d | %d | %.5f | %.3f |" % (
            r["name"], r["model"], r["runs"], r["calls_per_run"],
            r["usd_per_run"], r["usd_total"]))
    out.append("| **subtotal** | | | | | **%.3f** |" % proj["subtotal_usd"])
    out.append("")
    out.append("Limit $%.2f, headroom $%.3f, fits: %s"
               % (proj["limit_usd"], proj["headroom_usd"], proj["fits"]))
    return "\n".join(out)


def recalibrate_from_ledger(ledger_path, tag_prefix: str = "") -> dict[str, Any]:
    """Mean observed tokens and cost per call, per role, from the spend ledger.

    This is what replaces the priors above after the dry runs.
    """
    import json
    from collections import defaultdict
    agg: dict[str, dict[str, float]] = defaultdict(
        lambda: {"calls": 0, "prompt": 0, "completion": 0, "usd": 0.0})
    if not ledger_path.exists():
        return {}
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("cached"):
            continue
        if tag_prefix and not str(rec.get("tag", "")).startswith(tag_prefix):
            continue
        a = agg[rec.get("role", "?")]
        a["calls"] += 1
        a["prompt"] += rec.get("prompt_tokens", 0)
        a["completion"] += rec.get("completion_tokens", 0)
        a["usd"] += rec.get("cost_usd", 0.0)
    out = {}
    for role, a in agg.items():
        n = max(1, int(a["calls"]))
        out[role] = {
            "calls": int(a["calls"]),
            "mean_prompt_tokens": round(a["prompt"] / n, 1),
            "mean_completion_tokens": round(a["completion"] / n, 1),
            "mean_usd_per_call": round(a["usd"] / n, 7),
            "observed_usd": round(a["usd"], 5),
        }
    return out
