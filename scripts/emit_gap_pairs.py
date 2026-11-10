"""Pass 1 for the entailment-backed petal: the pairs its gap scan will need.

The petal has to decide which spans of the planner's draft assert S *before* it
regenerates them, and we want that decision made by the same entailment signal
that later grades the relay (see `petal.arms.make_gap_scorer`). The entailment
model does not fit in this machine's memory, so the scan cannot call it inline.
It is split in two instead:

    1. run the arms that do not need the petal -- their planner call IS the
       petal's planner call, because `full`, `b6_placebo` and `petal_text`
       share a draft and the LLM cache serves it once;
    2. this script, which reads those drafts and writes every
       (span, hypothesis) pair the gap scan will look up;
    3. scripts/nli_score.py (Colab) scores them into a cache;
    4. re-run the petal arms with --gap-nli <cache>. The planner call is served
       from cache and costs nothing; only the fill call is new.

Spans are enumerated with `detector.span_candidates`, the same function the leak
pass uses, so one cache serves both and a pair can never be scored under one
spelling and looked up under another.

  py -3.12 scripts/emit_gap_pairs.py --runs runs/exp1_paid_agent_a_seed20261109.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import paths
from petal.arms import read_runs
from petal.detector import span_candidates
from petal.scenarios.schema import Scenario


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    scens = {s.id: s for s in (Scenario.from_dict(d) for d in json.loads(
        (paths.SCENARIOS / "scenarios.json").read_text(encoding="utf-8")))}

    seen: set[tuple[str, str]] = set()
    n_drafts = 0
    out = Path(args.out) if args.out else Path(
        str(args.runs[0]).replace(".jsonl", "") + "_gappairs.jsonl")
    with out.open("w", encoding="utf-8") as f:
        for rp in args.runs:
            for r in read_runs(rp):
                draft = r.get("m1_draft") or ""
                if not draft.strip():
                    continue
                sc = scens[r["scenario_id"]]
                hyp = sc.S.proposition_generic or sc.S.proposition
                n_drafts += 1
                for prem in span_candidates(draft):
                    if (prem, hyp) in seen:
                        continue
                    seen.add((prem, hyp))
                    f.write(json.dumps({"premise": prem, "hypothesis": hyp},
                                       ensure_ascii=False) + "\n")
    print("%d drafts -> %d unique (span, hypothesis) pairs -> %s"
          % (n_drafts, len(seen), out))
    print("next: py -3.12 scripts/nli_score.py --pairs %s" % out)
    print("then: py -3.12 scripts/run_exp1.py --arms petal_text,b6_placebo "
          "--gap-nli <scores file>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
