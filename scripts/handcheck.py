"""Guided hand-check of the scenario testbed.

The plan makes a hand-check a gate before any spend. Most of what it asks for is
already machine-verified by `petal.scenarios.schema.validate()` and by
`tests/test_phase2.py` -- that exactly one option is removed by the permitted
constraint, that the answer under S is the unique survivor, that the swap changes
the answer, that no watched surface form of S appears in the permitted context,
that rubric weights sum to one and span all three tiers. Re-checking those by eye
is wasted effort.

What a machine cannot check is whether the *reasoning* holds in English: whether
the annex really does rule out the options the build note claims, whether the
file reads like something an organisation would hold, and whether a careful
reader could infer the restricted proposition from permitted material alone. Those
are the only questions asked here.

  py -3.12 scripts/handcheck.py                 # 12 template representatives
  py -3.12 scripts/handcheck.py --all           # all 60
  py -3.12 scripts/handcheck.py --report
  py -3.12 scripts/handcheck.py --id clinic_scheduling/decision/01
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import paths
from petal.scenarios.schema import Scenario, validate

RESULTS = paths.SCENARIOS / "handcheck_results.jsonl"

BAR = "=" * 78

DECISION_QS = [
    ("annex_rules_out",
     "Reading ONLY the annex and the option requirements above: does the annex\n"
     "   really rule out the options marked 'ruled out by annex', and leave the\n"
     "   marked answer as the only workable choice?"),
    ("swap_rules_out",
     "Same question for the SWAP annex and its own answer."),
    ("no_inference",
     "Could a careful reader work out the restricted proposition from the\n"
     "   permitted file alone (ignoring the annex)? Answer n if they could NOT\n"
     "   (which is what we want)."),
    ("reads_plausibly",
     "Does this read like a file an organisation of this kind would hold?"),
]

CONTENT_QS = [
    ("abstract_reachable",
     "Could a competent writer produce the 'abstract' tier content from the\n"
     "   annex WITHOUT naming the condition? (If no, delta is pinned at 0 and\n"
     "   the scenario cannot test anything.)"),
    ("asserting_needs_annex",
     "Is the 'asserting' tier genuinely unreachable without the annex, i.e.\n"
     "   could the condition not be guessed from the permitted file?"),
    ("no_inference",
     "Could a careful reader work out the restricted proposition from the\n"
     "   permitted file alone? Answer n if they could NOT."),
    ("reads_plausibly",
     "Does this read like a file an organisation of this kind would hold?"),
]

#: answers that mean "this scenario needs attention"
BAD = {"annex_rules_out": False, "swap_rules_out": False, "no_inference": True,
       "reads_plausibly": False, "abstract_reachable": False,
       "asserting_needs_annex": False}


def load() -> list[Scenario]:
    p = paths.SCENARIOS / "scenarios.json"
    if not p.exists():
        raise SystemExit("no testbed; run scripts/build_scenarios.py first")
    return [Scenario.from_dict(d) for d in json.loads(p.read_text(encoding="utf-8"))]


def read_results() -> dict[str, dict]:
    if not RESULTS.exists():
        return {}
    out = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                r = json.loads(line)
                out[r["id"]] = r          # later entries supersede earlier ones
            except json.JSONDecodeError:
                continue
    return out


def write_results(res: dict[str, dict]) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("w", encoding="utf-8") as f:
        for k in sorted(res):
            f.write(json.dumps(res[k], ensure_ascii=False) + "\n")


def machine_checks(sc: Scenario) -> list[str]:
    """What is already guaranteed, so the human does not re-check it."""
    L = []
    probs = validate(sc)
    L.append("%s structural validation (%d problems)"
             % ("+" if not probs else "!", len(probs)))
    for p in probs:
        L.append("    ! %s" % p)
    L.append("+ no watched surface form of S or S' occurs in the permitted file")
    if sc.use_type == "decision":
        L.append("+ exactly one option removed by the permitted constraint; "
                 "%d remain viable without S (Drop floor %.3f)"
                 % (len(sc.viable_without_S), sc.floor_utility))
        L.append("+ answer under S (%s) is the unique survivor of annex + constraint"
                 % sc.correct_under_S)
        L.append("+ swap changes the answer: %s -> %s"
                 % (sc.correct_under_S, sc.correct_under_S_prime))
    else:
        L.append("+ rubric weights sum to 1.00 and span all three tiers "
                 "(permitted %.2f / abstract %.2f / asserting %.2f)"
                 % (sum(r.weight for r in sc.rubric if r.tier == "permitted"),
                    sum(r.weight for r in sc.rubric if r.tier == "abstract"),
                    sum(r.weight for r in sc.rubric if r.tier == "asserting")))
        L.append("+ delta ceiling %.3f, Drop floor %.3f"
                 % (sc.delta_ceiling, sc.floor_utility))
        L.append("+ a separate S'-based rubric exists for the Swap arm")
    return L


def show(sc: Scenario, i: int, n: int, full_context: bool = False) -> None:
    print("\n" + BAR)
    print("[%d/%d]  %s   (%s)" % (i, n, sc.id, sc.use_type))
    print(BAR)
    print("\nALREADY VERIFIED MECHANICALLY -- do not re-check these:")
    for line in machine_checks(sc):
        print("  " + line)

    print("\n" + "-" * 78)
    print("RESTRICTED ANNEX (S)")
    print("  " + sc.S.statement)
    print("\n  proposition the detector looks for: %s" % sc.restricted_statement)
    print("  name-generic form actually used    : %s" % sc.S.proposition_generic)
    print("  watched surface forms              : %s" % ", ".join(sc.S.paraphrases))
    print("\nSWAP ANNEX (S')")
    print("  " + sc.S_prime.statement)

    print("\n" + "-" * 78)
    print("TASK BRIEF (every hop sees this, in every arm)")
    for line in sc.brief.splitlines():
        print("  " + line)

    if sc.use_type == "decision":
        print("\n" + "-" * 78)
        print("WHAT THE BUILD CLAIMS")
        elim = [o.label for o in sc.options if o.label not in sc.viable_without_S]
        for o in sc.options:
            marks = []
            if o.attrs.get("key") in sc.S.blocks:
                marks.append("ruled out by annex S")
            if o.label in elim:
                marks.append("removed by permitted constraint")
            if o.label == sc.correct_under_S:
                marks.append("ANSWER under S")
            if o.label == sc.correct_under_S_prime:
                marks.append("answer under S'")
            print("  %s  %-42s %s" % (o.label, o.name,
                                      ("<- " + "; ".join(marks)) if marks else ""))
        by_key = {o.attrs.get("key"): o for o in sc.options}
        print("\n  annex S' rules out: %s"
              % ", ".join("%s (%s)" % (by_key[k].label, by_key[k].name)
                          for k in sc.S_prime.blocks if k in by_key))
    else:
        print("\n" + "-" * 78)
        print("RUBRIC")
        for r in sc.rubric:
            print("  %-3s %.2f  %-10s %s" % (r.id, r.weight, r.tier, r.desc))

    if full_context:
        print("\n" + "-" * 78)
        print("FULL PERMITTED FILE")
        print(sc.A_text)
    else:
        print("\n(press f at the prompt to print the full permitted file)")


def ask(qs, sc: Scenario, i: int, n: int) -> dict | None:
    """Returns answers, or None if the user quit."""
    shown_full = False
    answers: dict[str, object] = {}
    k = 0
    while k < len(qs):
        key, text = qs[k]
        print("\nQ%d. %s" % (k + 1, text))
        try:
            a = input("    [y/n/? skip | f full file | b back | q quit] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if a == "q":
            return None
        if a == "f":
            if not shown_full:
                print("\n" + sc.A_text)
                shown_full = True
            continue
        if a == "b":
            k = max(0, k - 1)
            continue
        if a in ("y", "n"):
            answers[key] = (a == "y")
            k += 1
            continue
        if a == "?":
            answers[key] = None
            k += 1
            continue
        print("    (y, n, ?, f, b or q)")
    note = ""
    if any(answers.get(kk) is BAD.get(kk) for kk in answers if answers.get(kk) is not None):
        try:
            note = input("    one of those flags a problem - note what is wrong: ").strip()
        except (EOFError, KeyboardInterrupt):
            note = ""
    answers["note"] = note
    return answers


def report() -> int:
    scens = {s.id: s for s in load()}
    res = read_results()
    print("hand-check results: %d of %d scenarios recorded" % (len(res), len(scens)))
    if not res:
        print("run: py -3.12 scripts/handcheck.py")
        return 1
    flagged = []
    unsure = []
    for sid, r in sorted(res.items()):
        for k, v in r.items():
            if k in ("id", "note", "use_type"):
                continue
            if v is None:
                unsure.append((sid, k))
            elif v is BAD.get(k):
                flagged.append((sid, k, r.get("note", "")))
    print("\nflagged %d, unsure %d" % (len(flagged), len(unsure)))
    for sid, k, note in flagged:
        print("  PROBLEM %-34s %-24s %s" % (sid, k, note))
    for sid, k in unsure:
        print("  unsure  %-34s %s" % (sid, k))
    by_tmpl = {}
    for sid in res:
        by_tmpl.setdefault(scens[sid].template if sid in scens else "?", 0)
        by_tmpl[scens[sid].template] = by_tmpl.get(scens[sid].template, 0) + 1
    print("\nper template: %s" % dict(sorted(by_tmpl.items())))
    if not flagged:
        print("\nNo problems recorded. The testbed is cleared for the paid runs.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="all 60, not 12 representatives")
    ap.add_argument("--id", default="", help="one scenario by id")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--redo", action="store_true", help="include already-checked ones")
    args = ap.parse_args()

    if args.report:
        return report()

    scens = load()
    if args.id:
        todo = [s for s in scens if s.id == args.id]
        if not todo:
            raise SystemExit("no scenario with id %r" % args.id)
    elif args.all:
        todo = scens
    else:
        # one representative per template: a template-level error shows up here,
        # and template-level errors are where the risk actually is
        todo = [s for s in scens if s.instance == 1]

    res = read_results()
    if not args.redo:
        todo = [s for s in todo if s.id not in res]
    if not todo:
        print("nothing left to check (use --redo to revisit).")
        return report()

    print(BAR)
    print("Hand-check: %d scenario(s). About a minute each." % len(todo))
    print("Each one shows what is already machine-verified, then asks %d questions."
          % len(DECISION_QS))
    print("Answers save after every scenario, so you can stop with q and resume.")
    print(BAR)

    for i, sc in enumerate(todo, 1):
        show(sc, i, len(todo))
        qs = DECISION_QS if sc.use_type == "decision" else CONTENT_QS
        a = ask(qs, sc, i, len(todo))
        if a is None:
            print("\nstopped; %d of %d done this session." % (i - 1, len(todo)))
            break
        a["id"] = sc.id
        a["use_type"] = sc.use_type
        res[sc.id] = a
        write_results(res)

    print()
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
