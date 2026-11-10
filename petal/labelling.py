"""Stratified sampling and hand-labelling for detector validation (step E0).

The plan asks for 200 relay messages "stratified by arm and by the fast
detector's verdict". Stratifying on the verdict is the part that matters: leaks
are rare in the defended arms, so a simple random sample of 200 would contain
almost no positives and the sensitivity estimate would rest on a handful of
items. Allocating the sample across (arm x verdict) cells guarantees both error
directions are observable, and Rogan-Gladen needs both.

Note the consequence, which the analysis must respect: a verdict-stratified
sample is *not* representative of the trace population, so Se and Sp estimated
from it are valid (they are conditional on the true label within a cell only to
the extent cells are sampled proportionally) but the raw positive rate in the
sheet is not an estimate of prevalence. Prevalence comes from the full detection
run; the sheet only supplies Se and Sp.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .correction import Validation


@dataclass
class LabelItem:
    uid: str
    scenario_id: str
    use_type: str
    arm: str
    model_role: str
    seed: int
    channel: str
    proposition: str
    text: str
    detector_leak: bool
    detector_route: str
    p_nli: float
    lexical_hits: list[str]
    label: bool | None = None          # filled in by the human
    labeller: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cell(d: dict[str, Any]) -> tuple[str, str]:
    return (str(d.get("arm", "?")), "leak" if d.get("leak") else "clean")


def stratified_sample(detections: Iterable[dict[str, Any]], *, n: int = 200,
                      seed: int = 0, min_per_cell: int = 3) -> list[LabelItem]:
    """Allocate `n` items across (arm x verdict) cells, as evenly as possible.

    Cells get `min_per_cell` first (so no cell that exists is unrepresented),
    then the remainder is allocated largest-cell-first, capped by availability.
    """
    rows = [d for d in detections if (d.get("text") or "").strip()]
    if not rows:
        return []
    cells: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for d in rows:
        cells.setdefault(_cell(d), []).append(d)

    rng = np.random.default_rng(seed)
    quota = {k: min(min_per_cell, len(v)) for k, v in cells.items()}
    remaining = max(0, n - sum(quota.values()))
    # round-robin the remainder so big cells do not swallow it
    order = sorted(cells, key=lambda k: (-len(cells[k]), k))
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

    items: list[LabelItem] = []
    for k in order:
        pool = cells[k]
        take = quota[k]
        idx = rng.permutation(len(pool))[:take]
        for i in sorted(idx):
            d = pool[int(i)]
            items.append(LabelItem(
                uid=d["uid"], scenario_id=d["scenario_id"], use_type=d["use_type"],
                arm=d["arm"], model_role=d["model_role"], seed=int(d["seed"]),
                channel=d["channel"], proposition=d["proposition"], text=d["text"],
                detector_leak=bool(d["leak"]), detector_route=d["route"],
                p_nli=float(d.get("p_nli", 0.0)),
                lexical_hits=list(d.get("lexical_hits", []))))
    rng.shuffle(items)          # label in a blind order, not grouped by verdict
    return items


def write_sheet(items: list[LabelItem], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it.to_dict(), ensure_ascii=False) + "\n")


def read_sheet(path: Path) -> list[LabelItem]:
    out: list[LabelItem] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(LabelItem(**json.loads(line)))
    return out


def validation_from_sheet(items: list[LabelItem]) -> Validation:
    done = [it for it in items if it.label is not None]
    if not done:
        raise ValueError("no labelled items in the sheet")
    return Validation.from_labels([it.detector_leak for it in done],
                                  [bool(it.label) for it in done])


def sheet_progress(items: list[LabelItem]) -> dict[str, Any]:
    done = [it for it in items if it.label is not None]
    cells: dict[str, int] = {}
    for it in done:
        cells["%s/%s" % (it.arm, "leak" if it.detector_leak else "clean")] = \
            cells.get("%s/%s" % (it.arm, "leak" if it.detector_leak else "clean"), 0) + 1
    return {"total": len(items), "labelled": len(done),
            "positives_by_hand": sum(1 for it in done if it.label),
            "per_cell": cells}
