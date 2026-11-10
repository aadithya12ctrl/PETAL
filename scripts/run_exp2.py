"""Experiment 2: ladder decay along a five-hop chain, against Theorem T3.

Four schedules over 20 scenarios: none / deterministic / stochastic /
random_dropout (plan §4). Restricted to the **medical** kind so that one ladder
alphabet, one eta product and one probe candidate set apply to every scenario --
eta depends on k, and mixing kinds would mean comparing decay against a bound
that differs per scenario.

  py -3.12 scripts/run_exp2.py                       # offline mock, zero cost
  py -3.12 scripts/run_exp2.py --paid --yes
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import paths
from petal.chain import run_chain
from petal.client import LLMClient, MockBackend, prices_from_catalogue
from petal.config import Config, api_key, default_config
from petal.ladder import SCHEDULES, build_ladder
from petal.mockagents import ScriptedAgents
from petal.scenarios.schema import Scenario

KIND = "medical"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paid", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--model", default="agent_a")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--schedules", default="all")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    paths.ensure_dirs()
    cfg = Config.load() if paths.CONFIG.exists() else default_config()
    allsc = [Scenario.from_dict(d) for d in json.loads(
        (paths.SCENARIOS / "scenarios.json").read_text(encoding="utf-8"))]

    pool = [s for s in allsc if s.S.kind == KIND]
    half = max(1, args.n // 2)
    chosen = ([s for s in pool if s.use_type == "decision"][:half]
              + [s for s in pool if s.use_type == "content"][:args.n - half])
    scheds = SCHEDULES if args.schedules == "all" else args.schedules.split(",")
    bad = [s for s in scheds if s not in SCHEDULES]
    if bad:
        raise SystemExit("unknown schedules: %s" % bad)

    ladder = build_ladder(KIND)
    print("ladder for kind %r:" % KIND)
    for r in ladder.summary():
        print("  rung %d %-12s k=%-3d p=%.2f eta=%.4f cumulative=%.5f"
              % (r["rung"], r["name"], r["k"], r["p"], r["eta"],
                 r["cumulative_eta"]))
    print("  eta product over the randomised rungs: %.4f" % ladder.eta_product())
    print("\n%d scenarios x %d schedules x %d hops = %d calls, backend %s"
          % (len(chosen), len(scheds), cfg.ladder_hops,
             len(chosen) * len(scheds) * cfg.ladder_hops,
             "openrouter" if args.paid else "mock"))

    prices = (prices_from_catalogue(json.loads(
        paths.MODEL_CATALOG.read_text(encoding="utf-8")))
        if paths.MODEL_CATALOG.exists() else {})
    if args.paid:
        if not api_key():
            raise SystemExit("--paid given but OPENROUTER_API_KEY is not set")
        if not args.yes:
            raise SystemExit("refusing a paid run without --yes")
        client = LLMClient(cfg, prices=prices)
    else:
        client = LLMClient(cfg, backend=MockBackend(responder=ScriptedAgents(allsc)),
                           prices=prices)

    runs = []
    t0 = time.time()
    for i, sc in enumerate(chosen, 1):
        for sched in scheds:
            runs.append(run_chain(client, sc, sched, ladder,
                                  model_role=args.model, seed=cfg.seed))
        if i % 5 == 0 or i == len(chosen):
            print("  %2d/%d scenarios, spend $%.4f" % (i, len(chosen),
                                                       client.meter.total))

    out = Path(args.out) if args.out else paths.RUNS / (
        "exp2_%s_%s_seed%d.jsonl" % ("paid" if args.paid else "mock",
                                     args.model, cfg.seed))
    with out.open("w", encoding="utf-8") as f:
        for r in runs:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")

    lad = paths.RESULTS / ("ladder_%s.json" % KIND)
    lad.write_text(json.dumps({"kind": KIND, "rungs": ladder.summary(),
                               "eta_product_randomised": ladder.eta_product()},
                              indent=2), encoding="utf-8")
    print("\n%d chain runs, %d calls (%d paid), %.0fs"
          % (len(runs), sum(r.calls for r in runs),
             sum(r.paid_calls for r in runs), time.time() - t0))
    print("spend: $%.4f | cache %s" % (client.meter.total, client.cache.stats()))
    print("-> %s\n-> %s" % (out, lad))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
