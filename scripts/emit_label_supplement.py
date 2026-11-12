"""Emit a label sheet aimed at the cases the judge and the cascade disagree on.

The main 200-item sheet is a stratified sample over (arm x verdict), drawn
before the judge ran. It is the right shape for estimating the detector's
sensitivity and specificity overall, and the wrong shape for the question that
now matters most: *which reader is right where they differ*.

Three groups decide that, and the main sheet barely covers them:

  1. **The cascade missed it, the judge flagged it.** Every one of these was
     routed `nli_low`, below the escalation floor -- the paraphrase and
     implication cases the entailment model scores at 0.001 and 0.010. If the
     judge is right, the defended arms genuinely leak more than the cascade
     said. If it is over-reading, their rates are inflated and the headline
     reduction is larger than currently reported.

  2. **The cascade flagged it, the judge cleared it.** All lexical hits, which
     is where an over-broad watched form lives -- a bare "terminal" matching an
     airport terminal.

  3. **Drop-arm positives.** S is not in the planner's context at all, so a
     positive here is either a real testbed leak (the permitted file gives the
     condition away) or the judge inferring from a hint while primed with the
     answer. Those two have opposite consequences and `Phi_floor` depends on
     which it is.

Group 3 is a subset of group 1 whenever the cascade also missed it, so the
sheet is the union, not the sum.

The sheet carries no detector or judge verdict to the screen -- `label.py`
withholds them -- and the items are shuffled, so a labeller cannot tell which
group an item came from.

  py -3.12 scripts/emit_label_supplement.py --runs runs/exp1_a.jsonl \
      --detections runs/exp1_a_detections.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from petal import paths
from petal.labelling import LabelItem, write_sheet


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--detections", required=True)
    ap.add_argument("--channel", default="m1",
                    help="the judge-read channel (default m1)")
    ap.add_argument("--exclude", default="",
                    help="an existing sheet whose uids to leave out, so the "
                         "two sheets do not overlap")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    runs = {}
    for line in Path(args.runs).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            runs[(r["scenario_id"], r["arm"])] = r

    dets = [json.loads(l) for l in
            Path(args.detections).read_text(encoding="utf-8").splitlines()
            if l.strip()]

    already = set()
    if args.exclude:
        for line in Path(args.exclude).read_text(encoding="utf-8").splitlines():
            if line.strip():
                already.add(json.loads(line)["uid"])

    ch = [d for d in dets if d["channel"] == args.channel]
    judged = [d for d in ch if d.get("cascade_route")]
    if not judged:
        raise SystemExit(
            "no detection on channel %r carries a cascade verdict, so the judge "
            "did not read it. Re-run detect.py with --judge-channels %s --paid "
            "--yes first." % (args.channel, args.channel))

    groups = {
        "cascade_missed": [d for d in judged
                           if d["leak"] and d.get("cascade_leak") is False],
        "cascade_false_alarm": [d for d in judged
                                if d.get("cascade_leak") and not d["leak"]],
        "drop_positive": [d for d in ch if d["arm"] == "drop" and d["leak"]],
    }

    picked: dict[str, dict] = {}
    origin: dict[str, list[str]] = {}
    for name, rows in groups.items():
        for d in rows:
            if d["uid"] in already:
                continue
            picked[d["uid"]] = d
            origin.setdefault(d["uid"], []).append(name)

    print("target groups (union, not sum -- a Drop positive the cascade also "
          "missed is in two of them):")
    for name, rows in groups.items():
        new = sum(1 for d in rows if d["uid"] in picked)
        print("  %-20s %3d found, %3d new to this sheet" % (name, len(rows), new))
    print("  %-20s %3d" % ("UNION", len(picked)))

    items: list[LabelItem] = []
    for uid, d in picked.items():
        r = runs.get((d["scenario_id"], d["arm"]))
        text = (d.get("text") or (r or {}).get(d["channel"]) or "")
        if not text.strip():
            continue
        items.append(LabelItem(
            uid=uid, scenario_id=d["scenario_id"], use_type=d["use_type"],
            arm=d["arm"], model_role=d["model_role"], seed=int(d["seed"]),
            channel=d["channel"], proposition=d["proposition"], text=text,
            detector_leak=bool(d["leak"]), detector_route=d["route"],
            p_nli=float(d.get("p_nli", 0.0)),
            lexical_hits=list(d.get("lexical_hits", [])),
            note="|".join(origin[uid])))

    # Shuffled so the three groups are not labelled in blocks: a labeller who
    # notices they are on a run of judge-flagged items starts expecting leaks.
    np.random.default_rng(args.seed).shuffle(items)

    out = Path(args.out) if args.out else (
        paths.ROOT / "data" / "labels" / "sheet_supplement_disagreements.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_sheet(items, out)
    print("\n%d items -> %s" % (len(items), out))
    print("\nLabel with:\n  py -3.12 scripts/label.py --sheet %s --labeller <you>"
          % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
