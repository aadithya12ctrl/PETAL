"""Pre-registration: freeze the testbed before any paid run, and check it after.

The problem this closes
-----------------------
`scripts/audit_testbed.py` flags a scenario using real run output -- Full-arm
accuracy below 0.5, a swap that did not change the answer, a Drop arm that
scored too well. Those are the right checks. But if they run on the *reported*
data and we then fix or drop what they flag, the fix is selection on the
outcome: drop the scenarios the strong model fumbled and U_full rises, which
moves the denominator of every delta in the paper's favour, with no step along
the way that looks dishonest.

The separation that fixes it is cheap, because the audit does not need the
reported model:

    1. run the full 60 x 8 matrix on the cheap dev model (`--models dev`);
    2. audit that, and fix whatever it flags;
    3. freeze -- this module -- recording a hash of the frozen testbed, the
       matrix to be run, and the exclusion rule, before a single paid call;
    4. run the reported matrix. `scripts/run_exp1.py --paid` refuses to start
       if `scenarios.json` no longer hashes to the frozen value.

After step 3 the testbed is not edited again. If a scenario still misbehaves,
it is reported as misbehaving; if it is excluded, it is excluded by the rule
written down at step 3 and the exclusion is reported with its count.

This is a lock, not a proof: anyone can delete the file and re-freeze. Its
value is that re-freezing is a visible act with a git commit attached, which is
exactly what an unrecorded edit is not.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from . import paths

#: the rule exclusions must follow, fixed at freeze time
DEFAULT_EXCLUSION_RULE = (
    "No scenario is excluded from the reported analysis. Scenarios that fail an "
    "audit check on the reported run are reported as failing, with the check and "
    "the count, and are kept in every aggregate. The only admissible exclusion is "
    "a run that produced no parseable FINAL line, which is a harness failure "
    "rather than a result; those are counted and reported separately.")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def git_head() -> dict[str, Any]:
    def run(*a):
        try:
            return subprocess.run(a, cwd=str(paths.ROOT), capture_output=True,
                                  text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"commit": run("git", "rev-parse", "HEAD"),
            "dirty": bool(run("git", "status", "--porcelain"))}


@dataclass
class Preregistration:
    created_utc: str
    scenarios_sha256: str
    config_sha256: str
    n_scenarios: int
    git: dict[str, Any]
    matrix: dict[str, Any]
    exclusion_rule: str = DEFAULT_EXCLUSION_RULE
    audit_model: str = ""
    audit_problems: int = -1
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def path() -> Path:
    return paths.RESULTS / "preregistration.json"


def load() -> "Preregistration | None":
    p = path()
    if not p.exists():
        return None
    try:
        return Preregistration(**json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def current_scenarios_sha() -> str:
    return sha256_file(paths.SCENARIOS / "scenarios.json")


def check() -> tuple[bool, str]:
    """(ok, message). False means a paid run must not start."""
    pre = load()
    if pre is None:
        return False, (
            "no pre-registration at %s. The testbed must be frozen before paid "
            "runs, or scenario fixes made afterwards become selection on the "
            "outcome. Run:\n"
            "  py -3.12 scripts/run_exp1.py --paid --yes --models dev\n"
            "  py -3.12 scripts/audit_testbed.py --runs runs/exp1_paid_dev_*.jsonl\n"
            "  <fix whatever it flags, rebuild, commit>\n"
            "  py -3.12 scripts/freeze.py --audit-model dev" % path())
    now = current_scenarios_sha()
    if now != pre.scenarios_sha256:
        return False, (
            "scenarios.json has changed since the pre-registration.\n"
            "  frozen:  %s\n  current: %s\n"
            "Either restore the frozen testbed, or re-freeze deliberately with\n"
            "  py -3.12 scripts/freeze.py --refreeze --why '<reason>'\n"
            "which records the reason and the previous hash, so the change is "
            "visible in the paper." % (pre.scenarios_sha256[:16], now[:16]))
    return True, "pre-registration ok (frozen %s, scenarios %s)" % (
        pre.created_utc, pre.scenarios_sha256[:12])
