"""Build, validate and write the 60-scenario testbed, plus the hand-check export.

  py -3.12 scripts/build_scenarios.py
  py -3.12 scripts/build_scenarios.py --strict   # non-zero exit if anything invalid

Writes:
  data/scenarios/scenarios.json     machine-readable testbed
  data/scenarios/handcheck.md       one block per scenario for the hand-check
  results/testbed_summary.md        counts, token lengths, delta ceilings
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import paths
from petal.client import count_tokens
from petal.scenarios.build import build_all, validate_all


def handcheck_block(sc) -> str:
    L = [
        "## %s" % sc.id,
        "",
        "- **use type**: %s   **domain**: %s   **instance**: %d" % (
            sc.use_type, sc.domain, sc.instance),
        "- **delta ceiling**: %.3f   **floor utility (Drop, by design)**: %.3f" % (
            sc.delta_ceiling, sc.floor_utility),
        "- **build note**: %s" % sc.notes,
        "",
        "**Task (Y)**: %s" % sc.Y,
        "",
        "**Restricted annex (S)**", "", "> " + sc.S.statement, "",
        "**Restricted proposition** (NLI hypothesis): `%s`" % sc.restricted_statement, "",
        "**Swap annex (S')**", "", "> " + sc.S_prime.statement, "",
        "**Swap proposition**: `%s`" % sc.S_prime.proposition, "",
        "**Surface forms watched for**: %s" % ", ".join("`%s`" % p for p in sc.S.paraphrases),
        "",
    ]
    if sc.use_type == "decision":
        L.append("**Options**")
        L.append("")
        for o in sc.options:
            mark = []
            if o.label == sc.correct_under_S:
                mark.append("correct under S")
            if o.label == sc.correct_under_S_prime:
                mark.append("correct under S'")
            if o.label not in sc.viable_without_S:
                mark.append("removed by permitted constraint")
            L.append("- **%s** %s%s" % (o.label, o.name,
                                        ("  <- " + "; ".join(mark)) if mark else ""))
        L.append("")
    else:
        L.append("**Rubric** (weights sum to 1.00). Tier `permitted` = earnable with "
                 "no annex; `abstract` = needs the annex but asserts nothing; "
                 "`asserting` = earning it asserts the restricted proposition.")
        L.append("")
        L.append("| id | weight | tier | what it checks |")
        L.append("|---|---|---|---|")
        for r in sc.rubric:
            L.append("| %s | %.2f | %s | %s |" % (r.id, r.weight, r.tier, r.desc))
        L.append("")
    L.append("**Permitted context (A), %d tokens**" % count_tokens(sc.A_text))
    L.append("")
    L.append("```")
    L.append(sc.A_text)
    L.append("```")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    paths.ensure_dirs()
    scens = build_all()
    problems = validate_all(scens)

    out = paths.SCENARIOS / "scenarios.json"
    out.write_text(json.dumps([s.to_dict() for s in scens], indent=1),
                   encoding="utf-8")

    hc = ["# Scenario hand-check sheet",
          "",
          "%d scenarios. For each one, check that (a) the annex really does rule out "
          "the options the build note claims, (b) the answer under S is the only one "
          "left, (c) the swap genuinely changes the answer, and (d) nothing in the "
          "permitted context gives the restricted proposition away." % len(scens),
          ""]
    for sc in scens:
        hc.append(handcheck_block(sc))
    (paths.SCENARIOS / "handcheck.md").write_text("\n".join(hc), encoding="utf-8")

    # ------------------------------------------------------------- summary
    toks = [count_tokens(s.A_text) for s in scens]
    dec = [s for s in scens if s.use_type == "decision"]
    con = [s for s in scens if s.use_type == "content"]
    S = ["# Testbed summary", "",
         "- scenarios: **%d** (%d decision, %d content) across %d domains"
         % (len(scens), len(dec), len(con), len({s.domain for s in scens})),
         "- permitted context: %d-%d tokens, mean %.0f"
         % (min(toks), max(toks), sum(toks) / len(toks)),
         "- delta ceiling: decision %.3f, content %.3f"
         % (dec[0].delta_ceiling, con[0].delta_ceiling),
         "- floor utility (what Drop earns by design): decision %.3f, content %.3f"
         % (dec[0].floor_utility, con[0].floor_utility),
         "", "## Distinct answers per domain (guessability check)", "",
         "| domain | answers under S | answers under S' |", "|---|---|---|"]
    for d in sorted({s.domain for s in dec}):
        ds = [s for s in dec if s.domain == d]
        S.append("| %s | %s | %s |" % (
            d, " ".join(sorted(s.correct_under_S for s in ds)),
            " ".join(sorted(s.correct_under_S_prime for s in ds))))
    S += ["", "## Validation", ""]
    if problems:
        S.append("**%d scenarios/groups with problems:**" % len(problems))
        for k, v in problems.items():
            S.append("- `%s`" % k)
            for x in v:
                S.append("  - %s" % x)
    else:
        S.append("All %d scenarios pass structural validation." % len(scens))
    (paths.RESULTS / "testbed_summary.md").write_text("\n".join(S) + "\n", encoding="utf-8")

    print("\n".join(S))
    print()
    print("-> %s" % out)
    print("-> %s" % (paths.SCENARIOS / "handcheck.md"))
    return 1 if (problems and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
