"""Freeze the testbed before paid runs. See petal/prereg.py for why.

  py -3.12 scripts/freeze.py --audit-model dev
  py -3.12 scripts/freeze.py --refreeze --why "fixed loan tier-A wording"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import paths, prereg
from petal.arms import ARMS, KEY_ARMS
from petal.config import Config, default_config


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-model", default="dev",
                    help="model role the pre-run audit was done on")
    ap.add_argument("--audit-problems", type=int, default=-1,
                    help="problems the audit still reports (-1 = not recorded)")
    ap.add_argument("--refreeze", action="store_true",
                    help="overwrite an existing freeze; requires --why")
    ap.add_argument("--why", default="")
    args = ap.parse_args()

    paths.ensure_dirs()
    old = prereg.load()
    if old is not None and not args.refreeze:
        raise SystemExit(
            "already frozen at %s (scenarios %s). Use --refreeze --why '...' "
            "to replace it." % (old.created_utc, old.scenarios_sha256[:12]))
    if args.refreeze and not args.why.strip():
        raise SystemExit("--refreeze needs --why: the reason goes in the paper")

    cfg = Config.load() if paths.CONFIG.exists() else default_config()
    sp = paths.SCENARIOS / "scenarios.json"
    if not sp.exists():
        raise SystemExit("no testbed; run scripts/build_scenarios.py first")
    scens = json.loads(sp.read_text(encoding="utf-8"))

    notes = list(old.notes) if (old and args.refreeze) else []
    if args.refreeze and old:
        notes.append("re-frozen %s, replacing %s: %s"
                     % (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                        old.scenarios_sha256[:12], args.why.strip()))

    pre = prereg.Preregistration(
        created_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        scenarios_sha256=prereg.current_scenarios_sha(),
        config_sha256=prereg.sha256_file(paths.CONFIG),
        n_scenarios=len(scens),
        git=prereg.git_head(),
        matrix={
            "experiment_1": {
                "arms": ARMS,
                "models": ["agent_a", "agent_b"],
                "seed": cfg.seed,
                "replication": {"arms": KEY_ARMS, "models": ["agent_a"],
                                "seed": cfg.second_seed},
                "primary_channel": "m1",
            },
            "experiment_2": {
                "schedules": ["none", "deterministic", "stochastic", "drop_at_3"],
                "hops": cfg.ladder_hops, "models": ["agent_a"], "seed": cfg.seed,
            },
            "decision_rule": {"kappa": cfg.kappa,
                              "kappa_sensitivity": list(cfg.kappa_sensitivity),
                              "lambda_length": cfg.lambda_length},
            "primary_endpoints": [
                "delta / ceiling on the petal_text arm, per use type",
                "Lambda = P(assert S | S) - P(assert S | S'), m1 channel",
                "H4: Fano lower bound vs the T3 product bound, per hop",
            ],
            "detector": {"se_sp_from": "200-item stratified hand-label set",
                         "correction": "Rogan-Gladen, bootstrapped over traces "
                                       "and validation set jointly"},
        },
        audit_model=args.audit_model,
        audit_problems=args.audit_problems,
        notes=notes,
    )
    prereg.path().write_text(json.dumps(pre.to_dict(), indent=1), encoding="utf-8")
    print(json.dumps(pre.to_dict(), indent=1))
    print("\n-> %s" % prereg.path())
    if pre.git.get("dirty"):
        print("\nWARNING: the working tree is dirty. Commit, then re-freeze, so "
              "the frozen testbed has a commit to point at.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
