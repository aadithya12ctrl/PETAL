"""Cut the 200-item validation sheet to a pre-registered subset.

200 items was sized for tight error bars on the Rogan-Gladen correction, not
for a person's afternoon. The subset is smaller and the intervals get wider;
what must not happen is the subset being chosen *as the labelling goes*, because
"I stopped when the numbers looked right" and "I stopped when I got tired" are
indistinguishable afterwards.

So the selection is fixed in advance and mechanically reproducible:

  * a fixed seed, recorded in the pre-registration;
  * stratified by **arm x detector verdict**, the same frame the 200 were drawn
    on, so no (arm, verdict) cell that exists in the data is unrepresented;
  * items already labelled are **carried in first** -- they were drawn blind
    from the same frame, so keeping them is not selection on their content, and
    discarding work already done would be worse;
  * the remainder allocated round-robin over cells, largest cell first, capped
    by availability.

Anyone can re-run this and get the same 50 ids. That is the whole point.

  py -3.12 scripts/emit_label_subset.py --sheet data/labels/sheet_exp1_a_detections.jsonl -n 50
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from petal.labelling import read_sheet, write_sheet


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20261113)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    src = Path(args.sheet)
    items = read_sheet(src)

    cells: dict[tuple[str, bool], list] = defaultdict(list)
    for it in items:
        cells[(it.arm, bool(it.detector_leak))].append(it)

    # Already-labelled items come in regardless. They were drawn blind from the
    # same frame before any of this was decided, so including them is not a
    # choice about their content; dropping them would throw away real work and
    # would itself be a selection.
    keep = {id(it) for it in items if it.label is not None}
    print("already labelled, carried in: %d" % len(keep))

    rng = np.random.default_rng(args.seed)
    order = sorted(cells, key=lambda k: (-len(cells[k]), str(k)))
    # deterministic within-cell order, independent of the file's line order
    for k in order:
        cells[k].sort(key=lambda it: hashlib.sha256(it.uid.encode()).hexdigest())
        idx = rng.permutation(len(cells[k]))
        cells[k] = [cells[k][int(i)] for i in idx]

    quota = {k: sum(1 for it in cells[k] if id(it) in keep) for k in order}
    # one unlabelled item per existing cell before any cell gets a second
    for k in order:
        if quota[k] == 0 and len(cells[k]) > 0:
            quota[k] = 1
    remaining = args.n - sum(quota.values())
    while remaining > 0:
        progressed = False
        for k in order:
            if remaining <= 0:
                break
            if quota[k] < len(cells[k]):
                quota[k] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    if remaining < 0:
        print("note: %d items already labelled across cells exceeds the per-cell "
              "floor; keeping all of them, so the subset is %d rather than %d"
              % (-remaining, sum(quota.values()), args.n))

    chosen = []
    for k in order:
        pool = cells[k]
        labelled = [it for it in pool if id(it) in keep]
        rest = [it for it in pool if id(it) not in keep]
        take = labelled + rest[:max(0, quota[k] - len(labelled))]
        chosen.extend(take)

    print("\n%-18s %-6s %5s %5s" % ("arm", "verdict", "avail", "taken"))
    for k in order:
        t = sum(1 for it in chosen if (it.arm, bool(it.detector_leak)) == k)
        print("%-18s %-6s %5d %5d"
              % (k[0], "leak" if k[1] else "clean", len(cells[k]), t))

    rng.shuffle(chosen)
    out = Path(args.out) if args.out else src.with_name(
        src.stem + "_subset%d.jsonl" % args.n)
    write_sheet(chosen, out)

    ids = sorted(it.uid for it in chosen)
    digest = hashlib.sha256("\n".join(ids).encode()).hexdigest()[:16]
    print("\n%d items -> %s" % (len(chosen), out))
    print("selection sha256(ids)[:16] = %s   (seed %d)" % (digest, args.seed))
    print("\nThe frame stays on disk: %s. Keep it -- the subset is a *sample of\n"
          "the detector's verdicts*, so correcting the leak rates needs each\n"
          "item's sampling weight, which only the full frame gives." % src)
    print("\nLabel with:\n  py -3.12 scripts/label.py --sheet %s --labeller <you>"
          % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
