"""Project the paper-v1 spend from live catalogue prices; optionally recalibrate.

  py -3.12 scripts/budget_report.py              # projection from priors
  py -3.12 scripts/budget_report.py --ledger     # + observed per-call costs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import paths
from petal.budget import project, markdown_table, recalibrate_from_ledger
from petal.client import prices_from_catalogue
from petal.config import Config, default_config


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", action="store_true")
    args = ap.parse_args()

    paths.ensure_dirs()
    cfg = Config.load() if paths.CONFIG.exists() else default_config()
    if not paths.MODEL_CATALOG.exists():
        print("no catalogue snapshot; run scripts/check_models.py first")
        return 1
    cat = json.loads(paths.MODEL_CATALOG.read_text(encoding="utf-8"))
    prices = prices_from_catalogue(cat)

    proj = project(cfg, prices)
    md = ["# Projected spend (paper v1)", "",
          "Prices from the pinned catalogue snapshot; token counts are the plan's",
          "pre-dry-run priors (2000 in / 300 out per agent call).", "",
          markdown_table(proj), ""]

    if args.ledger:
        obs = recalibrate_from_ledger(paths.LEDGER)
        md += ["## Observed per-call cost (uncached ledger entries)", ""]
        if not obs:
            md.append("_ledger empty - no paid calls yet._")
        else:
            md.append("| role | calls | mean prompt tok | mean completion tok | mean $/call | observed $ |")
            md.append("|---|---|---|---|---|---|")
            for role, a in sorted(obs.items()):
                md.append("| %s | %d | %.1f | %.1f | %.7f | %.5f |" % (
                    role, a["calls"], a["mean_prompt_tokens"],
                    a["mean_completion_tokens"], a["mean_usd_per_call"],
                    a["observed_usd"]))
        md.append("")

    out = paths.RESULTS / "budget.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print("-> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
