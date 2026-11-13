"""Se/Sp with an interval, combining both label sheets as disjoint strata.

Reporting Se = 1.000 from the 50-item subset was too strong, and the
supplement is why we know: the cascade missed 1 of the 27 hard items, and the
subset could not have seen that -- 33 such items sat in a cascade-negative
population of ~1459, so 27 cascade-negative draws expected 0.6 of them. A point
estimate of 1.000 from a sample with no power over the stratum where the misses
live is an artefact of where we looked.

The fix is to use both sheets together, which needs strata that do not overlap.
The main sheet is allocated over (arm x cascade verdict); the supplement is
drawn from the items where the cascade and the judge disagree, which cuts across
those cells. So the population is split three ways:

    stratum = (arm, cascade verdict, whether the judge disagreed)

Every labelled item falls in exactly one, both sheets contribute, and each
item's weight is its stratum's population size over the number labelled from
it. The interval is a stratified bootstrap: resample labelled items within each
stratum, recompute the weighted Se and Sp, and take percentiles. A stratum
sampled 0/27 then produces the wide upper tail it deserves, instead of a
confident 1.000.

  py -3.12 scripts/validation_report.py \\
      --sheets data/labels/sheet_exp1_a_detections_subset50.jsonl \\
               data/labels/sheet_supplement_disagreements.jsonl \\
      --cascade runs/exp1_a_detections_cascade.jsonl \\
      --judge runs/exp1_a_detections.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from petal.labelling import read_sheet


def load(p: str) -> dict[str, dict]:
    return {d["uid"]: d for d in
            (json.loads(l) for l in
             Path(p).read_text(encoding="utf-8").splitlines() if l.strip())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", nargs="+", required=True)
    ap.add_argument("--cascade", required=True,
                    help="detections from the reader being validated")
    ap.add_argument("--judge", default="",
                    help="detections from the other reader, to define the "
                         "disagreement stratum the supplement was drawn from")
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    casc = load(args.cascade)
    judge = load(args.judge) if args.judge else {}

    def stratum(uid: str, arm: str) -> tuple:
        cl = bool(casc[uid]["leak"]) if uid in casc else None
        dis = (bool(judge[uid]["leak"]) != cl) if (judge and uid in judge) else False
        return (arm, cl, dis)

    pop: Counter = Counter()
    for uid, d in casc.items():
        pop[stratum(uid, str(d.get("arm")))] += 1

    items = []
    for s in args.sheets:
        for it in read_sheet(Path(s)):
            if it.label is not None and it.uid in casc:
                items.append(it)
    # a uid labelled in both sheets is one observation, not two
    seen: set[str] = set()
    uniq = []
    for it in items:
        if it.uid not in seen:
            seen.add(it.uid)
            uniq.append(it)
    items = uniq

    by: dict[tuple, list] = defaultdict(list)
    for it in items:
        by[stratum(it.uid, it.arm)].append(it)

    print("labelled items: %d across %d strata (of %d strata in the frame)"
          % (len(items), len(by), len(pop)))
    print("\n%-34s %6s %6s %8s" % ("stratum (arm, cascade, judge-differs)",
                                   "pop", "drawn", "weight"))
    for k in sorted(by, key=str):
        print("%-34s %6d %6d %8.1f"
              % ("(%s, %s, %s)" % (k[0], "leak" if k[1] else "clean",
                                   "yes" if k[2] else "no"),
                 pop[k], len(by[k]), pop[k] / len(by[k])))
    uncovered = [k for k in pop if k not in by and pop[k] > 0]
    if uncovered:
        print("\n%d stratum/strata in the frame with no labelled item; their "
              "items are excluded from the estimate, which is what makes it an\n"
              "estimate for the covered part of the frame rather than all of it:"
              % len(uncovered))
        for k in sorted(uncovered, key=str)[:8]:
            print("   (%s, %s, %s)  pop %d"
                  % (k[0], "leak" if k[1] else "clean",
                     "yes" if k[2] else "no", pop[k]))

    def se_sp(sample: dict[tuple, list]) -> tuple[float, float]:
        tp = fp = fn = tn = 0.0
        for k, its in sample.items():
            w = pop[k] / len(by[k])          # weight from the real draw count
            for it in its:
                pred = bool(casc[it.uid]["leak"])
                t = bool(it.label)
                if pred and t:
                    tp += w
                elif pred and not t:
                    fp += w
                elif t:
                    fn += w
                else:
                    tn += w
        se = tp / (tp + fn) if (tp + fn) else float("nan")
        sp = tn / (tn + fp) if (tn + fp) else float("nan")
        return se, sp

    pt_se, pt_sp = se_sp(by)
    rng = np.random.default_rng(args.seed)
    ses, sps = [], []
    for _ in range(args.n_boot):
        draw = {k: [v[int(i)] for i in rng.integers(0, len(v), len(v))]
                for k, v in by.items()}
        a, b = se_sp(draw)
        if a == a:
            ses.append(a)
        if b == b:
            sps.append(b)
    q = lambda xs: (float(np.percentile(xs, 2.5)), float(np.percentile(xs, 97.5)))
    se_lo, se_hi = q(ses)
    sp_lo, sp_hi = q(sps)

    print("\nreader validated: %s" % Path(args.cascade).name)
    print("  sensitivity %.3f  [%.3f, %.3f]" % (pt_se, se_lo, se_hi))
    print("  specificity %.3f  [%.3f, %.3f]" % (pt_sp, sp_lo, sp_hi))
    print("  Youden      %.3f  [%.3f, %.3f]"
          % (pt_se + pt_sp - 1, se_lo + sp_lo - 1, se_hi + sp_hi - 1))
    print("\nstratified bootstrap, %d draws, seed %d." % (args.n_boot, args.seed))

    # The bootstrap cannot resample an event it never observed, so a stratum
    # labelled 0-for-3 contributes a confident zero and the interval above is
    # too narrow in exactly the place that matters: the large cascade-negative
    # strata, where an undetected leak would be a miss. A Clopper-Pearson
    # upper limit on each such stratum's miss prevalence gives the worst case
    # the labels do not rule out. This is the figure to quote as a bound.
    try:
        from scipy.stats import beta
    except ImportError:
        print("\n(scipy unavailable: skipping the Clopper-Pearson bound)")
        return 0

    tp_w = 0.0
    for k, its in by.items():
        if k[1]:                      # cascade said leak: contributes TP/FP
            tp_w += (pop[k] / len(its)) * sum(1 for it in its if it.label)

    # Bounding each (arm, clean, differs) cell separately and summing the worst
    # cases assumes every cell sits at its own upper limit at once, which with
    # 3-4 labels per cell bounds nothing useful -- it returns Se >= 0.32. The
    # misses are a property of the *reader*, not of the arm: the cascade's blind
    # spot is paraphrase, and nothing about `swap` versus `drop` changes that.
    # So the cascade-negative population is pooled into the two groups that do
    # differ in mechanism -- the items the judge also passed, and the items the
    # judge flagged -- and bounded once each.
    groups = {False: [0, 0, 0], True: [0, 0, 0]}      # differs -> [pop, n, k]
    for k, its in by.items():
        if k[1]:
            continue
        g = groups[k[2]]
        g[0] += pop[k]
        g[1] += len(its)
        g[2] += sum(1 for it in its if it.label)

    fn_max = 0.0
    print("\nWorst case the labels do not rule out (Clopper-Pearson, 97.5% "
          "one-sided,\npooled across arms because the blind spot is the "
          "reader's, not the arm's):")
    print("  %-26s %6s %6s %7s %9s %9s"
          % ("cascade-negative group", "pop", "labels", "misses", "prev<=",
             "misses<="))
    for differs, (P, n, kk) in groups.items():
        if not n:
            continue
        p_hi = 1.0 if kk == n else float(beta.ppf(0.975, kk + 1, n - kk))
        fn_max += P * p_hi
        print("  %-26s %6d %6d %7d %9.3f %9.0f"
              % ("judge flagged it too" if differs else "judge passed it too",
                 P, n, kk, p_hi, P * p_hi))

    se_bound = tp_w / (tp_w + fn_max) if (tp_w + fn_max) else float("nan")
    print("\n  weighted true positives      %8.0f" % tp_w)
    print("  upper bound on missed leaks  %8.0f" % fn_max)
    print("  => sensitivity at least      %8.3f" % se_bound)
    print("\nSo the defensible statement is a sensitivity *interval*, not a "
          "point:\nthe labels put it between %.2f and 1.00, and the bootstrap's "
          "%.3f is the\noptimistic end because 80 labels cannot see a rare miss "
          "in a 1920-item frame." % (se_bound, se_lo))

    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parent.parent / "results" / "validation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "reader": Path(args.cascade).name,
        "n_labelled": len(items),
        "n_strata_covered": len(by),
        "n_strata_in_frame": len(pop),
        "sensitivity": pt_se,
        "sensitivity_boot_lo": se_lo,
        "sensitivity_boot_hi": se_hi,
        "sensitivity_lower_bound": se_bound,
        "specificity": pt_sp,
        "specificity_boot_lo": sp_lo,
        "specificity_boot_hi": sp_hi,
        "n_boot": args.n_boot,
        "seed": args.seed,
        "note": ("The bootstrap interval cannot express a miss that was never "
                 "observed, so sensitivity_lower_bound -- the Clopper-Pearson "
                 "worst case the labels do not rule out -- is the figure to "
                 "quote as a bound."),
    }, indent=2) + chr(10), encoding="utf-8")
    print("-> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
