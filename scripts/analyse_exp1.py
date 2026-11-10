"""Experiment 1 analysis: writes results/exp1.md.

  py -3.12 scripts/analyse_exp1.py --runs runs/exp1_*.jsonl
  py -3.12 scripts/analyse_exp1.py --runs R --labels data/labels/sheet_X.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import analysis as A
from petal import paths
from petal.config import Config, default_config
from petal.labelling import read_sheet, validation_from_sheet

PAIRS = [("petal_text", "b6_placebo"), ("petal_text", "b1_privacy"),
         ("petal_text", "b4_restriction"), ("decision_only", "b4_restriction")]
DELTA_ARMS = ["petal_text", "decision_only", "b6_placebo", "b1_privacy",
              "b4_restriction"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--detections", nargs="*", default=None)
    ap.add_argument("--labels", default="", help="hand-label sheet for Rogan-Gladen")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cfg = Config.load() if paths.CONFIG.exists() else default_config()
    runs = [p for pat in args.runs for p in sorted(glob.glob(pat))] or args.runs
    dets = ([p for pat in args.detections for p in sorted(glob.glob(pat))]
            if args.detections else
            [str(r).replace(".jsonl", "") + "_detections.jsonl" for r in runs])

    panels, meta = A.load(runs, dets)
    val = None
    val_note = ("No hand-labelled validation set supplied, so leak rates are "
                "**observed, not corrected**. PETAL_v2 errata item 1: an observed "
                "rate is not a lower bound once the detector has false positives, "
                "and this one has them. Run `scripts/label.py` and pass `--labels`.")
    if args.labels:
        try:
            val = validation_from_sheet(read_sheet(Path(args.labels)))
            val_note = ("Validation set: n=%d, Se=%.3f, Sp=%.3f, Youden=%.3f."
                        % (val.n, val.sensitivity, val.specificity, val.youden))
        except (OSError, ValueError) as e:
            val_note = "Could not use %s: %s" % (args.labels, e)

    L = ["# Experiment 1: disclosure-use separability", "",
         "Runs: %s" % ", ".join("`%s`" % Path(r).name for r in runs),
         "%d runs, %d detections, models %s, seeds %s."
         % (meta["n_runs"], meta["n_detections"], meta["models"], meta["seeds"]),
         "", "Every comparison is scenario-paired; the bootstrap resamples "
         "scenarios, not runs.", "", "## Detector validation", "", val_note, ""]

    out_json: dict = {"meta": meta, "use_types": {}}

    for ut, p in panels.items():
        L += ["---", "", "## %s-type tasks (n = %d scenarios)"
              % (ut.capitalize(), len(p.scenarios)), ""]

        L += ["### Utility and leak by arm", "",
              "Leak is on the `%s` channel: the relay a defence is responsible "
              "for. `m1_draft` is the planner's pre-defence output, shown so the "
              "petal's effect on the channel is visible separately from any "
              "downstream dilution." % A.PRIMARY_CHANNEL, "",
              "| arm | utility | leak m1_draft | leak m1 | leak m2 | leak output |",
              "|---|---|---|---|---|---|"]
        for arm in p.arms():
            from petal.stats import bootstrap_mean
            u = bootstrap_mean(p.utility[arm])
            cells = []
            for ch in A.CHANNELS:
                r = A.leak_rate(p, arm, ch)
                cells.append("-" if r != r else "%.3f" % r)
            L.append("| %s | %s | %s |" % (arm, u, " | ".join(cells)))
        L.append("")

        lam = A.lambda_causal(p)
        flo = A.phi_floor(p)
        L += ["- **Causal leak** Lambda = leak(full) - leak(swap) = **%s**"
              % ("n/a" if lam != lam else "%.3f" % lam),
              "- **Inference floor** Phi_floor = leak(drop) = **%s**"
              % ("n/a" if flo != flo else "%.3f" % flo),
              "- *Positive control*: the Swap arm asserts **S'** at %s. If this "
              "were near zero the arm relayed nothing and its low rate on S "
              "would show specificity that was never tested."
              % ("n/a" if A.swap_control(p) != A.swap_control(p)
                 else "%.3f" % A.swap_control(p)),
              "", "Both terms of Lambda are the rate of asserting *S*. The second "
              "is measured where S is absent, so it is the rate of asserting S "
              "anyway -- detector false positives plus confabulation -- and "
              "subtracting it is what separates a causal leak from an artefact. "
              "Only Lambda is what a relay defence can act on; the floor is "
              "unavoidable by any relay design and is subtracted, not charged to "
              "the defence.", ""]

        # --- delta -------------------------------------------------------
        ceiling = None
        try:
            from petal.scenarios.schema import Scenario
            scens = {s.id: s for s in (Scenario.from_dict(d) for d in json.loads(
                (paths.SCENARIOS / "scenarios.json").read_text(encoding="utf-8")))}
            cs = [scens[s].delta_ceiling for s in p.scenarios if s in scens]
            ceiling = sum(cs) / len(cs) if cs else None
        except (OSError, KeyError, json.JSONDecodeError):
            pass

        dt = A.delta_table(p, DELTA_ARMS, n_boot=cfg.n_bootstrap, seed=cfg.seed)
        L += ["### Separability delta", "",
              "delta = (U_arm - U_drop) / (U_full - U_drop), as a ratio of means "
              "over scenario-paired bootstrap resamples. A ratio of means, not a "
              "mean of ratios: per scenario the denominator is often 0 and "
              "averaging per-scenario ratios would drop exactly the scenarios "
              "that carry no information about delta.", ""]
        if ceiling is not None:
            L.append("Design ceiling for this use type: **%.3f** -- the largest "
                     "delta any non-asserting defence could reach here. Read each "
                     "delta against it." % ceiling)
            L.append("")
        L += ["| arm | delta [95% CI] | fraction of ceiling |", "|---|---|---|"]
        for arm, iv in dt.items():
            frac = ("-" if not ceiling or iv.point != iv.point
                    else "%.2f" % (iv.point / ceiling))
            L.append("| %s | %s | %s |" % (arm, iv, frac))
        L.append("")

        # --- decision rule ----------------------------------------------
        L += ["### Decision rule (PETAL_v2 §4.2.4)", "",
              "Petal wins iff dU > kappa x dLeak + lambda x dLength, against the "
              "restriction-aware relay. Length is the relay's tokens as a "
              "fraction of the Full arm's, so lambda is dimensionless.", "",
              "| kappa | dU [95% CI] | dLeak | dLength | threshold | petal wins? "
              "| wins at CI low? |", "|---|---|---|---|---|---|---|"]
        for kap in [cfg.kappa] + list(cfg.kappa_sensitivity):
            d = A.decision_rule(p, kappa=kap, lam=cfg.lambda_length)
            if not d.get("available"):
                continue
            du = d["delta_utility"]
            L.append("| %.1f | %.3f [%.3f, %.3f] | %+.3f | %+.3f | %+.3f | %s | %s |"
                     % (kap, du["point"], du["lo"], du["hi"], d["delta_leak"],
                        d["delta_length_frac"], d["threshold"],
                        "yes" if d["petal_wins"] else "no",
                        "yes" if d["wins_at_ci_low"] else "no"))
        L.append("")

        # --- corrected rates --------------------------------------------
        if val is not None:
            L += ["### Corrected leak rates (Rogan-Gladen)", "",
                  "CIs resample the trace set *and* the validation set; holding "
                  "Se and Sp fixed gives intervals that are too narrow.", "",
                  "| arm | observed | corrected [95% CI] |", "|---|---|---|"]
            for arm, row in A.corrected_leaks(p, val, n_boot=cfg.n_bootstrap,
                                              seed=cfg.seed).items():
                if "corrected" in row:
                    L.append("| %s | %.3f | %.3f [%.3f, %.3f] |"
                             % (arm, row["observed"], row["corrected"],
                                row["lo"], row["hi"]))
                else:
                    L.append("| %s | %.3f | %s |"
                             % (arm, row["observed"],
                                row.get("corrected_error", "n/a")))
            L.append("")

        # --- tests -------------------------------------------------------
        t = A.paired_tests(p, PAIRS)
        L += ["### Paired tests, Holm-corrected", "",
              "One Holm family per use type, covering leak *and* utility tests "
              "together: the paper reads them as one claim about whether the petal "
              "helps, so correcting them separately would understate the "
              "correction.", "",
              "| test | p | p (Holm) | reject at 0.05 |", "|---|---|---|---|"]
        for name, r in sorted(t["holm"].items()):
            L.append("| %s | %s | %s | %s |"
                     % (name,
                        "n/a" if r["p"] is None or r["p"] != r["p"] else "%.4f" % r["p"],
                        "n/a" if r["p_adj"] != r["p_adj"] else "%.4f" % r["p_adj"],
                        "yes" if r["reject"] else "no"))
        L.append("")

        pw = A.power_note(p)
        if pw:
            L += ["### Power, stated honestly", "",
                  "- n = %d scenarios; sd of the paired difference = %.3f"
                  % (pw["n_scenarios"], pw["sd_paired_diff"]),
                  "- smallest delta gap detectable at 80%% power: **%.3f**"
                  % pw["mde_delta_80pct"],
                  "", "The plan asserts v1 can only detect a delta gap of about "
                  "0.25 or more. That number is this one, and it depends on a "
                  "variance that only a real run can supply -- so it is computed "
                  "here rather than quoted.", ""]

        out_json["use_types"][ut] = {
            "n_scenarios": len(p.scenarios),
            "utility": {a: A._mean(p.utility[a]) for a in p.arms()},
            "leak": {a: {ch: A.leak_rate(p, a, ch) for ch in A.CHANNELS}
                     for a in p.arms()},
            "lambda": lam, "phi_floor": flo,
            "delta": {a: iv.to_dict() for a, iv in dt.items()},
            "delta_ceiling": ceiling,
            "decision_rule": {str(k): A.decision_rule(p, kappa=k,
                                                      lam=cfg.lambda_length)
                              for k in [cfg.kappa] + list(cfg.kappa_sensitivity)},
            "tests": t["holm"], "power": pw,
        }

    out = Path(args.out) if args.out else paths.RESULTS / "exp1.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    (paths.RESULTS / "exp1.json").write_text(json.dumps(out_json, indent=1,
                                                        default=float),
                                             encoding="utf-8")
    print("\n".join(L))
    print("\n-> %s\n-> %s" % (out, paths.RESULTS / "exp1.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
