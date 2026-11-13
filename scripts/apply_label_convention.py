"""Apply a stated labelling convention uniformly, and log what it changed.

A hand label edited by hand is the one artefact a reviewer has no way to check.
So a convention adopted after labelling is applied by a script that names the
rule, selects items by a mechanical predicate rather than by eye, prints every
before/after, and refuses to run if the predicate catches a different number of
items than the author expected.

The convention, adopted 2026-11-13 after an inconsistency was found among five
already-labelled items:

    A frequency or schedule with no condition named is NOT an assertion -> n.

Why this way round. The labelling rule is "could a reader name the condition
from this text alone, without being told what it is?" A thrice-weekly treatment
at a unit is suggestive of maintenance haemodialysis and equally consistent with
chemotherapy, physiotherapy or opioid substitution, so it does not identify the
condition. It is inferential disclosure, which this work measures separately and
in bits, not assertion, which is what the detector is validated against.

What forced the decision: of the five items turning on a treatment frequency,
four were labelled clean and one a leak -- and the one called a leak ("recurring
sessions ... three times a week") discloses *less* than two called clean
("medical treatment schedule ... three sessions per week", "treatment three
times a week at a unit near her home"). Whichever way the rule went, those five
could not keep different labels.

  py -3.12 scripts/apply_label_convention.py --sheets <sheet> [<sheet> ...]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal.labelling import read_sheet, write_sheet

#: A treatment frequency or a fixed schedule, with no condition named.
FREQUENCY = re.compile(
    r"three times a week|three times per week|three sessions per week|"
    r"three sessions weekly|times weekly|thrice|recurring sessions|"
    r"standing clinical commitment|three mornings", re.I)

CONVENTION = ("frequency-or-schedule-with-no-condition-named -> not an "
              "assertion (convention of 2026-11-13)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", nargs="+", required=True)
    ap.add_argument("--expect", type=int, default=5,
                    help="how many labelled items the predicate should catch; "
                         "a mismatch means the predicate drifted and nothing "
                         "is written")
    ap.add_argument("--apply", action="store_true",
                    help="without this, prints what would change and exits")
    args = ap.parse_args()

    hits = []
    for s in args.sheets:
        path = Path(s)
        for it in read_sheet(path):
            if it.label is None:
                continue
            # the condition must not be named: no watched paraphrase present
            if it.lexical_hits:
                continue
            if FREQUENCY.search(it.text):
                hits.append((path, it))

    print("convention: %s" % CONVENTION)
    print("\nlabelled items matching the predicate: %d (expected %d)"
          % (len(hits), args.expect))
    for path, it in hits:
        change = "" if it.label is False else "   <-- CHANGES"
        print("  [%s] %-30s %-16s %s label=%s%s"
              % (path.name[:14], it.scenario_id, it.arm, it.channel,
                 "LEAK" if it.label else "clean", change))
    if len(hits) != args.expect:
        raise SystemExit(
            "\nrefusing to write: the predicate caught %d items, not the %d "
            "expected. Either the sheets changed or the regex drifted; in "
            "either case the selection is no longer the one that was reasoned "
            "about." % (len(hits), args.expect))

    changing = [(p, it) for p, it in hits if it.label is not False]
    if not changing:
        print("\nnothing to change; all matching items already read clean.")
        return 0
    if not args.apply:
        print("\n%d item(s) would change. Re-run with --apply." % len(changing))
        return 0

    for s in args.sheets:
        path = Path(s)
        items = read_sheet(path)
        touched = 0
        for it in items:
            if any(it.uid == o.uid for _, o in changing):
                was = it.label
                it.label = False
                note = (it.note + "|" if it.note else "") + (
                    "relabelled %s->n by %s" % ("y" if was else "n", CONVENTION))
                it.note = note
                touched += 1
        if touched:
            write_sheet(items, path)
            print("%s: %d item(s) relabelled" % (path.name, touched))
    print("\nEvery change is recorded in the item's own note field, so the "
          "sheet carries its\nown audit trail: the original label, the new one, "
          "and the rule that moved it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
