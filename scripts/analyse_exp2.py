"""Experiment 2 analysis: measured decay of information about S vs Theorem T3.

The comparison, and why it is the right one:

* **T3 gives an upper bound.** I(S; M_h) <= (prod_{r<h} eta_r) * I(S; M_0). We do
  not know I(S; M_0) exactly, so we use its largest possible value, log2(k) for a
  near-uniform S over k categories. That makes the bound as *loose* as it can
  honestly be, so exceeding it is strong evidence rather than an artefact of a
  tight assumption.
* **The probe gives a lower bound.** Fano applied to any estimator's error rate
  (see petal/probe.py).
* **H4 fires when the lower bound exceeds the upper bound.** That would mean more
  information about S is reaching hop h than the ladder can account for -- a side
  channel, or re-derivation from elsewhere in the note. PETAL_v2 §4.3 is explicit
  that T3 covers the slot and not that, so H4 is a check on the scope claim, not
  on the algebra.

  py -3.12 scripts/analyse_exp2.py --runs runs/exp2_mock_agent_a_seed20261109.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import paths
from petal.ladder import SCHEDULES, build_ladder, true_value_at
from petal.probe import MatchProbe, chance_error, fano_mi_lower, logreg_probe_cv

KIND = "medical"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--logreg", action="store_true",
                    help="also run the plan's logistic-regression probe")
    args = ap.parse_args()

    runs = [json.loads(l) for l in Path(args.runs).read_text(encoding="utf-8").splitlines()
            if l.strip()]
    ladder = build_ladder(KIND)
    cands = ladder.rungs[0].alphabet
    probe = MatchProbe(cands)
    k = probe.k
    idx_of = {v: i for i, v in enumerate(cands)}

    from petal.ladder import all_categories
    cats = all_categories()

    # schedule -> hop -> (texts, truth indices)
    data: dict[str, dict[int, tuple[list[str], list[int]]]] = defaultdict(
        lambda: defaultdict(lambda: ([], [])))
    util: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        cat = cats[r["category"]]
        truth = idx_of.get(true_value_at(cat, ladder.rungs[0]))
        if truth is None:
            continue
        util[r["schedule"]].append(r["utility"])
        for hp in r["hops"]:
            if hp["hop"] == len(r["hops"]):
                continue                      # final output, no slot was rewritten
            ts, ys = data[r["schedule"]][hp["hop"]]
            ts.append(hp["sent"])
            ys.append(truth)

    L = ["# Experiment 2: ladder decay against Theorem T3", "",
         "Run file: `%s`" % args.runs,
         "Kind: `%s`; probe over k = %d candidate propositions; "
         "I(S;M_0) assumed at its maximum log2(k) = %.2f bits."
         % (KIND, k, math.log2(k)), "",
         "## The ladder actually used", "",
         "| rung | name | k | p | eta | cumulative eta |", "|---|---|---|---|---|---|"]
    for s in ladder.summary():
        L.append("| %d | %s | %d | %.2f | %.4f | %.5f |"
                 % (s["rung"], s["name"], s["k"], s["p"], s["eta"],
                    s["cumulative_eta"]))
    L += ["",
          "Product over the randomised rungs: **%.4f**. PETAL_v2 §4.3 quotes 0.039 "
          "for an illustrative (20, 5, 3, 2) alphabet; the testbed's real alphabets "
          "are larger, and a larger k raises eta for a fixed p, so the real ladder "
          "contracts slightly less than the paper's example."
          % ladder.eta_product(), ""]

    L += ["## Measured decay", "",
          "`probe LB` is the Fano lower bound on I(S; M_h) in bits from the "
          "matcher's error rate; `LB (cons.)` evaluates Fano at the one-sided "
          "95% Clopper-Pearson upper limit of that error rate. `T3 UB` is "
          "(prod eta) x log2(k). **H4 fires on the conservative bound**, because at "
          "n = 20 the noise on an error rate is about +/- 0.09 and the point "
          "estimate alone breaches the bound by chance.", "",
          "| schedule | hop | n | probe error | probe LB | LB (cons.) | T3 UB | "
          "H4 |", "|---|---|---|---|---|---|---|---|"]

    fired: list[str] = []
    rows: list[dict] = []
    for sched in SCHEDULES:
        if sched not in data:
            continue
        for hop in sorted(data[sched]):
            texts, truth = data[sched][hop]
            res = probe.evaluate(texts, truth, hop=hop, schedule=sched)
            if sched == "stochastic":
                ub = ladder.bound_at_hop(hop) * math.log2(k)
            elif sched == "deterministic":
                # every rung is a deterministic map: coefficient 1 until the
                # slot is dropped, which is precisely errata item 5
                ub = (0.0 if ladder.rung_for_hop(hop).k <= 1 else math.log2(k))
            else:
                ub = math.log2(k)
            flag = ""
            if res.mi_lower_bits_conservative > ub + 1e-9:
                flag = "**FIRES**"
                fired.append("%s hop %d: conservative LB %.2f > UB %.2f"
                             % (sched, hop, res.mi_lower_bits_conservative, ub))
            elif res.mi_lower_bits > ub + 1e-9:
                flag = "point est. only"
            L.append("| %s | %d | %d | %.3f | %.3f | %.3f | %.3f | %s |"
                     % (sched, hop, res.n, res.error_rate, res.mi_lower_bits,
                        res.mi_lower_bits_conservative, ub, flag))
            rows.append({**res.to_dict(), "t3_upper_bits": ub})
    L.append("")
    L.append("Chance error for this probe is %.3f, i.e. %.3f bits."
             % (chance_error(k), fano_mi_lower(chance_error(k), k)))
    L.append("")

    L += ["## Task utility by schedule", ""]
    for sched in SCHEDULES:
        if util.get(sched):
            L.append("- %-14s mean utility %.3f (n=%d)"
                     % (sched, st.mean(util[sched]), len(util[sched])))
    L.append("")

    if args.logreg:
        L += ["## The plan's logistic-regression probe (secondary)", "",
              "Over the four kinds rather than the %d categories: with 20 texts per "
              "hop, 20 of which carry different categories, a %d-class classifier "
              "measures the classifier and not the channel." % (k, k), "",
              "| schedule | hop | n | k | error | LB (bits) |", "|---|---|---|---|---|---|"]
        for sched in SCHEDULES:
            if sched not in data:
                continue
            for hop in sorted(data[sched]):
                texts, truth = data[sched][hop]
                labels = [cands[t].split()[-1] for t in truth]
                r = logreg_probe_cv(texts, labels)
                L.append("| %s | %d | %s | %s | %s | %s |" % (
                    sched, hop, r.get("n"), r.get("k"),
                    ("%.3f" % r["error_rate"]) if r.get("error_rate") == r.get("error_rate") else "n/a",
                    ("%.3f" % r["mi_lower_bits"]) if r.get("mi_lower_bits") == r.get("mi_lower_bits") else "n/a"))
        L.append("")

    L += ["## H4 verdict", ""]
    if fired:
        L.append("**H4 fires.** Measured information exceeds the T3 bound at:")
        for f in fired:
            L.append("- %s" % f)
        L.append("")
        L.append("That is a finding, not a bug in the algebra: it means S reaches the "
                 "hop by a route the ladder does not control. The note's free text, "
                 "written by the agent around the slot, is the first place to look.")
    else:
        L.append("Measured information stays at or below the T3 bound at every hop of "
                 "every schedule, so there is no evidence of a channel the ladder does "
                 "not control. Note this is the weaker direction of the test: a bound "
                 "that holds is consistent with the ladder working and with the probe "
                 "being weak, which is why the `none` schedule is reported alongside "
                 "as the no-decay reference.")

    out = Path(args.out) if args.out else paths.RESULTS / "exp2_ladder.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    (paths.RESULTS / "exp2_probe_rows.json").write_text(
        json.dumps(rows, indent=1), encoding="utf-8")
    print("\n".join(L))
    print("\n-> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
