"""Verify the plan's model ids against the live OpenRouter catalogue.

No API key, no cost: /api/v1/models is public. Writes:
  data/openrouter_models.json   full catalogue snapshot (pinned for the paper)
  config.json                   with resolved ids + measured prices
  results/model_check.md        a human-readable report

Run:  py -3.12 scripts/check_models.py            (verify + report)
      py -3.12 scripts/check_models.py --write     (also rewrite config.json)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import paths
from petal.client import fetch_catalogue, prices_from_catalogue
from petal.config import default_config


def fmt_price(p) -> str:
    # catalogue prices are USD per token; report per million for readability
    return "$%.3f / $%.3f per M tok" % (p.prompt * 1e6, p.completion * 1e6)


def candidates(cat: dict, needle: str, limit: int = 8) -> list[str]:
    needle = needle.lower()
    toks = [t for t in needle.replace("/", " ").replace("-", " ").split() if len(t) > 2]
    scored = []
    for m in cat.get("data", []):
        mid = m["id"].lower()
        score = sum(1 for t in toks if t in mid)
        if score:
            scored.append((score, -len(mid), m["id"]))
    scored.sort(reverse=True)
    return [s[2] for s in scored[:limit]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="rewrite config.json with resolved ids")
    args = ap.parse_args()

    paths.ensure_dirs()
    cat = fetch_catalogue()
    paths.MODEL_CATALOG.write_text(json.dumps(cat, indent=1), encoding="utf-8")
    ids = {m["id"] for m in cat.get("data", [])}
    prices = prices_from_catalogue(cat)
    print("catalogue: %d models" % len(ids))

    cfg = default_config()
    lines = ["# Model availability check", "",
             "Catalogue snapshot: `data/openrouter_models.json` (%d models)." % len(ids), ""]
    resolved: dict[str, str] = {}
    ok = True

    for role, spec in cfg.models.items():
        want = spec.model
        if want in ids:
            resolved[role] = want
            lines.append("## %s — OK" % role)
            lines.append("- requested `%s` is available, %s" % (want, fmt_price(prices[want])))
        else:
            ok = False
            lines.append("## %s — MISSING" % role)
            lines.append("- requested `%s` is **not in the catalogue**" % want)
            fb = spec.fallback_model
            if fb and fb in ids:
                resolved[role] = fb
                lines.append("- configured fallback `%s` is available, %s"
                             % (fb, fmt_price(prices[fb])))
            else:
                if fb:
                    lines.append("- configured fallback `%s` is also missing" % fb)
                cands = candidates(cat, want)
                lines.append("- nearest catalogue ids: " +
                             ", ".join("`%s`" % c for c in cands) if cands
                             else "- no near matches")
                resolved[role] = ""
        lines.append("")

    # cheapest sane options, for the reserve budget discussion
    lines.append("## Cheapest non-free instruct models (for reference)")
    cheap = sorted(
        ((p.prompt + p.completion, mid) for mid, p in prices.items()
         if p.prompt > 0 and p.completion > 0),
    )[:12]
    for tot, mid in cheap:
        lines.append("- `%s` — %s" % (mid, fmt_price(prices[mid])))

    report = paths.RESULTS / "model_check.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("report -> %s" % report)

    for role, mid in resolved.items():
        print("  %-9s %s" % (role, mid or "<UNRESOLVED>"))

    if args.write:
        for role, mid in resolved.items():
            if mid:
                cfg.models[role].model = mid
        cfg.save()
        print("config.json written")

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
