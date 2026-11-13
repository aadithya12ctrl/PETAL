"""Hand-label a detector validation sheet (step E0), and report Se/Sp.

The detector's own verdict is hidden while you label, so your judgement is not
anchored to it. Progress is saved after every answer, so this can be done in
several sittings.

  py -3.12 scripts/label.py --sheet data/labels/sheet_X.jsonl --labeller aadithya
  py -3.12 scripts/label.py --sheet ... --report
  py -3.12 scripts/label.py --sheet ... --kappa data/labels/sheet_X_second.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal.correction import cohens_kappa
from petal.labelling import (read_sheet, sheet_progress, validation_from_sheet,
                             write_sheet)

HELP = """
  y    the message asserts, paraphrases or clearly implies the proposition
  n    it does not
  s    skip for now
  u    undo the previous answer
  q    save and quit
Count paraphrase, euphemism and clear implication as assertion. Do not count a
vague categorical gesture that leaves the proposition undetermined, and do not
count a statement about a different matter.
"""


def report(path: Path, frame_path: str = "") -> int:
    items = read_sheet(path)
    prog = sheet_progress(items)
    print("sheet: %s" % path)
    print("labelled %d of %d; %d called a leak by hand"
          % (prog["labelled"], prog["total"], prog["positives_by_hand"]))

    # The sheet is stratified on the detector's verdict, so the cells are not
    # sampled at the same rate and pooling them unweighted estimates Se/Sp for
    # the sheet's verdict mix rather than for the data. With the frame -- the
    # detection set the sheet was drawn from -- each item carries its cell's
    # inverse sampling fraction and the estimate is the design-weighted one.
    frame = None
    if frame_path:
        frame = [json.loads(l) for l in
                 Path(frame_path).read_text(encoding="utf-8").splitlines()
                 if l.strip()]
    try:
        val = validation_from_sheet(items, frame)
    except ValueError as e:
        print(e)
        return 1
    if frame is None:
        print("\nWARNING: no --detections frame given, so Se/Sp below are "
              "UNWEIGHTED.\nThis sheet is verdict-stratified, so that figure is "
              "biased -- Se too high and Sp too low when positives are "
              "over-sampled.\nPass --detections <the run's detections file> for "
              "the design-weighted estimate.")
    else:
        print("\ndesign-weighted on %d frame detections" % len(frame))
    d = val.to_dict()
    print("\nconfusion (detector vs hand)%s:"
          % ("" if frame is None else ", weighted to the frame"))
    print("  tp %7.1f  fp %7.1f" % (d["tp"], d["fp"]))
    print("  fn %7.1f  tn %7.1f" % (d["fn"], d["tn"]))
    print("\nsensitivity %.3f   specificity %.3f   Youden %.3f"
          % (d["sensitivity"], d["specificity"], d["youden"]))
    gate = 0.85
    if d["sensitivity"] < gate or d["specificity"] < gate:
        print("\nH0 kill condition (plan section 6): Se or Sp below %.2f after one "
              "revision retires the detector." % gate)
    print("\nper cell: %s" % prog["per_cell"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--labeller", default="")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--kappa", default="", help="a second labeller's sheet")
    ap.add_argument("--detections", default="",
                    help="the detection set this sheet was sampled from. "
                         "Required for an unbiased Se/Sp: the sheet is "
                         "stratified on the detector's verdict, so each item "
                         "needs its cell's sampling weight.")
    args = ap.parse_args()
    path = Path(args.sheet)

    if args.kappa:
        a = {it.uid: it for it in read_sheet(path)}
        b = {it.uid: it for it in read_sheet(Path(args.kappa))}
        both = [u for u in a if u in b
                and a[u].label is not None and b[u].label is not None]
        if not both:
            raise SystemExit("no commonly labelled items")
        k = cohens_kappa([bool(a[u].label) for u in both],
                         [bool(b[u].label) for u in both])
        print("Cohen's kappa over %d commonly labelled items: %.3f" % (len(both), k))
        return 0

    if args.report:
        return report(path, args.detections)

    items = read_sheet(path)
    todo = [i for i, it in enumerate(items) if it.label is None]
    if not todo:
        print("nothing left to label.")
        return report(path, args.detections)
    print(HELP)
    print("%d of %d left.\n" % (len(todo), len(items)))

    history: list[int] = []
    k = 0
    while k < len(todo):
        i = todo[k]
        it = items[i]
        print("=" * 72)
        # Only the proposition and the message. The detector's verdict, its
        # entailment score, its route and its lexical hits are all in the sheet
        # and none are shown: the point of this set is an independent reading,
        # and a labeller who sees the verdict is no longer independent of it.
        #
        # The arm and the channel are withheld for the same reason, one step
        # removed. They name the experimental condition, not the evidence:
        # "arm=drop" says the planner never held the restricted fact, so a
        # labeller who sees it expects to find nothing, and "arm=full" the
        # reverse. The judgement needs neither.
        print("[%d/%d]  %s" % (k + 1, len(todo), it.scenario_id))
        print("\nPROPOSITION: %s" % it.proposition)
        # Printed in full, never truncated. At a 2400-character cap, 41 of the
        # 200 items were cut, and in two of them the condition was named only
        # beyond the cut -- which would have been recorded as "does not
        # assert" against a message that states it outright, turning a correct
        # detection into a false positive and biasing specificity down.
        print("\nMESSAGE:\n%s" % it.text.strip())
        print()
        try:
            ans = input("assert? [y/n/s/u/q] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nsaving.")
            break
        if ans == "q":
            break
        if ans == "u":
            if history:
                items[history.pop()].label = None
                k = max(0, k - 1)
                write_sheet(items, path)
            continue
        if ans == "s":
            k += 1
            continue
        if ans not in ("y", "n"):
            print("  (use y, n, s, u or q)")
            continue
        it.label = (ans == "y")
        it.labeller = args.labeller
        history.append(i)
        write_sheet(items, path)
        k += 1

    write_sheet(items, path)
    print()
    return report(path, args.detections)


if __name__ == "__main__":
    raise SystemExit(main())
