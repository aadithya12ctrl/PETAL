"""Run Experiment 1: the eight arms over the testbed.

Defaults to the free mock backend. A paid run needs BOTH `--paid` and `--yes`,
prints the projected cost first, and is still protected by the cost meter's hard
ceiling, so a mistake here costs nothing.

  # offline, full matrix, zero cost
  py -3.12 scripts/run_exp1.py

  # the plan's 10-scenario dry run on the primary model, for real
  py -3.12 scripts/run_exp1.py --paid --yes --limit 10 --out runs/dry_a.jsonl

  # the reported matrix
  py -3.12 scripts/run_exp1.py --paid --yes --models agent_a,agent_b
  py -3.12 scripts/run_exp1.py --paid --yes --models agent_a --seed2 --arms key
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import paths, prereg
from petal.arms import ARMS, KEY_ARMS, RunRecord, run_arm, write_runs
from petal.client import LLMClient, MockBackend, count_messages, prices_from_catalogue
from petal.config import Config, api_key, default_config
from petal.mockagents import ScriptedAgents
from petal.scenarios.schema import Scenario


def load_scenarios() -> list[Scenario]:
    p = paths.SCENARIOS / "scenarios.json"
    if not p.exists():
        raise SystemExit("no testbed; run scripts/build_scenarios.py first")
    return [Scenario.from_dict(d) for d in json.loads(p.read_text(encoding="utf-8"))]


def make_client(cfg: Config, scens: list[Scenario], paid: bool) -> LLMClient:
    prices = {}
    if paths.MODEL_CATALOG.exists():
        prices = prices_from_catalogue(
            json.loads(paths.MODEL_CATALOG.read_text(encoding="utf-8")))
    if paid:
        if not api_key():
            raise SystemExit("--paid given but OPENROUTER_API_KEY is not set "
                             "(environment or .env)")
        return LLMClient(cfg, prices=prices)
    return LLMClient(cfg, backend=MockBackend(responder=ScriptedAgents(scens)),
                     prices=prices)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paid", action="store_true", help="use OpenRouter instead of the mock")
    ap.add_argument("--yes", action="store_true", help="confirm a paid run")
    ap.add_argument("--models", default="agent_a", help="comma-separated role keys")
    ap.add_argument("--arms", default="all", help="'all', 'key', or a comma-separated list")
    ap.add_argument("--limit", type=int, default=0, help="first N scenarios only")
    ap.add_argument("--use-type", default="", choices=["", "decision", "content"])
    ap.add_argument("--seed2", action="store_true", help="use the replication seed")
    ap.add_argument("--gap-nli", default="",
                    help="entailment score cache for the petal's gap scan; "
                         "without it the petal is lexical-gap only (see "
                         "petal.arms.make_gap_scorer)")
    ap.add_argument("--allow-missing-nli", action="store_true",
                    help="do not fail when --gap-nli has no score for a span")
    ap.add_argument("--no-prereg", action="store_true",
                    help="paid run without a frozen testbed; records why in the "
                         "run file name and is not reportable")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    paths.ensure_dirs()
    cfg = Config.load() if paths.CONFIG.exists() else default_config()
    scens = load_scenarios()
    if args.use_type:
        scens = [s for s in scens if s.use_type == args.use_type]
    if args.limit:
        # take from the front of each use type so both are represented
        d = [s for s in scens if s.use_type == "decision"][:max(1, args.limit // 2)]
        c = [s for s in scens if s.use_type == "content"][:max(1, args.limit // 2)]
        scens = d + c

    arms = ARMS if args.arms == "all" else (
        KEY_ARMS if args.arms == "key" else args.arms.split(","))
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        raise SystemExit("unknown arms: %s" % unknown)
    models = args.models.split(",")
    seed = cfg.second_seed if args.seed2 else cfg.seed

    n_runs = len(scens) * len(arms) * len(models)
    print("scenarios %d x arms %d x models %d = %d runs, seed %d, backend %s"
          % (len(scens), len(arms), len(models), n_runs, seed,
             "openrouter" if args.paid else "mock"))

    if args.paid and not args.no_prereg:
        ok, msg = prereg.check()
        print("pre-registration: %s" % msg)
        if not ok:
            raise SystemExit(
                "refusing a paid run against an unfrozen testbed.\n\n%s\n\n"
                "Pass --no-prereg to run anyway; such a run is a pilot, not "
                "reportable data." % msg)

    if args.paid:
        # rough upper bound from the first scenario's actual prompt sizes
        from petal import prompts as P
        probe = count_messages(P.planner_messages(scens[0])) + 2 * 900
        est = 0.0
        for role in models:
            pr = prices_from_catalogue(json.loads(
                paths.MODEL_CATALOG.read_text(encoding="utf-8")))
            price = pr.get(cfg.model(role).model)
            if price:
                per_run = price.cost(probe, 3 * cfg.model(role).max_tokens)
                est += per_run * len(scens) * len(arms)
        print("projected upper bound for this invocation: $%.3f" % est)
        if not args.yes:
            raise SystemExit("refusing a paid run without --yes")

    nli_cache = None
    if args.gap_nli:
        from petal.detector import CachedNliScorer, NliScoreCache
        cache = NliScoreCache(Path(args.gap_nli))
        if not len(cache):
            raise SystemExit("--gap-nli %s holds no scores" % args.gap_nli)
        nli_cache = CachedNliScorer(cache)
        print("gap scan: entailment-backed, %d cached pairs" % len(cache))
    elif set(arms) & {"petal_text", "b6_placebo"}:
        print("gap scan: LEXICAL ONLY. The petal will be scored by a detector "
              "stronger than the one it used to find its gaps, so its leak rate "
              "is an upper bound and its delta a lower bound. Report this arm as "
              "the 'lexical-gap petal'. See scripts/emit_gap_pairs.py for the "
              "entailment-backed pass.")

    client = make_client(cfg, scens, args.paid)
    print("spend before: $%.4f of $%.2f" % (client.meter.total, client.meter.limit))

    records: list[RunRecord] = []
    t0 = time.time()
    for role in models:
        for i, sc in enumerate(scens, 1):
            for arm in arms:
                records.append(run_arm(client, sc, arm, model_role=role, seed=seed,
                                       nli_cache=nli_cache))
            if i % 10 == 0 or i == len(scens):
                print("  %s %3d/%d  spend $%.4f  cache %s"
                      % (role, i, len(scens), client.meter.total, client.cache.stats()))

    out = Path(args.out) if args.out else (
        paths.RUNS / ("exp1_%s_%s_seed%d.jsonl"
                      % ("paid" if args.paid else "mock", "-".join(models), seed)))
    out.parent.mkdir(parents=True, exist_ok=True)
    write_runs(out, records)

    # An empty completion is scored as a wrong answer, so a model that returns
    # nothing produces a tidy dataset of zeros with no error anywhere. Check the
    # rate before letting the run stand.
    rep = client.empty_report(sum(r.calls for r in records))
    if rep["n_empty"]:
        print("\nEMPTY COMPLETIONS: %d of %d calls (%.1f%%)%s"
              % (rep["n_empty"], rep["n_calls"], 100 * rep["rate"],
                 "; %d exhausted max_tokens on reasoning" % rep["budget_starved"]
                 if rep["budget_starved"] else ""))
        for k, v in sorted(rep["by"].items()):
            print("   %-60s %d" % (k, v))
        if rep["rate"] > 0.02:
            raise SystemExit(
                "\nrefusing to report this run: %.1f%% of calls returned no text.\n"
                "A completion with no content scores as a wrong answer, so these "
                "would be indistinguishable from genuine failures.\n"
                "If finish_reason is 'length' with reasoning_tokens at max_tokens, "
                "the model is a reasoning model whose budget is too small: raise "
                "max_tokens, set reasoning_effort, or pin an instruct variant."
                % (100 * rep["rate"]))

    missing = sum(r.gap_scores_missing for r in records)
    if missing:
        msg = ("%d draft spans had no cached entailment score, so the gap scan "
               "treated them as clean. Re-emit the pairs and rescore:\n"
               "  py -3.12 scripts/emit_gap_pairs.py --runs %s\n"
               "  py -3.12 scripts/nli_score.py --pairs ..." % (missing, out))
        if args.allow_missing_nli:
            print("\nWARNING: " + msg)
        else:
            raise SystemExit("\n" + msg + "\n\n(--allow-missing-nli to proceed "
                             "anyway; the petal arm is then lexical-gap in part, "
                             "which must be said in the paper.)")

    scorers = sorted({r.gap_scorer for r in records if r.gap_scorer})
    if scorers:
        print("gap scorer(s) used: %s" % ", ".join(scorers))

    paid_calls = sum(r.paid_calls for r in records)
    print("\n%d runs, %d calls (%d paid), %.1fs" % (
        len(records), sum(r.calls for r in records), paid_calls, time.time() - t0))
    print("spend after: $%.4f" % client.meter.total)
    print("cache: %s" % client.cache.stats())
    print("-> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
