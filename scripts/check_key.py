"""Verify the OpenRouter credential without spending anything.

GET /api/v1/key returns the key's own usage and limit. It generates no tokens,
so this costs nothing, and it answers the question the plan's hard rules care
about: is a spending limit actually set on the key, and how much is left.

The key itself is never printed, logged or written anywhere.

  py -3.12 scripts/check_key.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import paths
from petal.config import Config, api_key, default_config

KEY_URL = "https://openrouter.ai/api/v1/key"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"


def mask(k: str) -> str:
    return "%s…%s (%d chars)" % (k[:7], k[-4:], len(k)) if len(k) > 14 else "(too short)"


def gitignored(rel: str) -> bool:
    try:
        r = subprocess.run(["git", "check-ignore", "-q", rel],
                           cwd=str(paths.ROOT), capture_output=True)
        return r.returncode == 0
    except OSError:
        return False


def main() -> int:
    k = api_key()
    if not k:
        print("no key found. Create %s containing:\n  OPENROUTER_API_KEY=sk-or-..."
              % (paths.ROOT / ".env"))
        return 1

    print("key source   : %s" % ("environment" if "OPENROUTER_API_KEY" in __import__("os").environ
                                 else str(paths.ROOT / ".env")))
    print("key          : %s" % mask(k))
    if not k.startswith("sk-or-"):
        print("  note: OpenRouter keys normally begin 'sk-or-'. If this is a key for "
              "another provider it will fail at the first call.")
    print(".env ignored : %s" % ("yes" if gitignored(".env") else "NO - fix .gitignore"))

    try:
        r = requests.get(KEY_URL, headers={"Authorization": "Bearer " + k,
                                           "X-Title": "PETAL-research"}, timeout=60)
    except requests.RequestException as e:
        print("could not reach OpenRouter: %s" % e)
        return 2

    if r.status_code == 401:
        print("\nREJECTED (401): the key is not valid. Check for a stray quote, a "
              "trailing space, or a copy that lost characters.")
        return 3
    if r.status_code != 200:
        print("\nHTTP %d: %s" % (r.status_code, r.text[:300]))
        return 4

    d = (r.json() or {}).get("data", {})
    print("\naccepted by OpenRouter.")
    print("  label              : %s" % d.get("label"))
    print("  usage so far       : $%s" % d.get("usage"))
    lim = d.get("limit")
    print("  key spending limit : %s" % ("$%s" % lim if lim is not None else
                                         "none set on the key itself"))
    rem = d.get("limit_remaining")
    if rem is not None:
        print("  remaining          : $%s" % rem)
    print("  free tier          : %s" % d.get("is_free_tier"))
    rl = d.get("rate_limit")
    if rl:
        print("  rate limit         : %s" % json.dumps(rl))

    # account balance: the key's own limit caps what this key may spend, but the
    # balance is what actually exists to be spent
    try:
        c = requests.get(CREDITS_URL, headers={"Authorization": "Bearer " + k,
                                               "X-Title": "PETAL-research"}, timeout=60)
        if c.status_code == 200:
            cd = (c.json() or {}).get("data", {})
            total = cd.get("total_credits")
            used = cd.get("total_usage")
            if total is not None and used is not None:
                print("\naccount balance    : $%.2f purchased - $%.2f used = $%.2f left"
                      % (float(total), float(used), float(total) - float(used)))
    except (requests.RequestException, ValueError, TypeError):
        pass

    cfg = Config.load() if paths.CONFIG.exists() else default_config()
    print("\nlocal ceiling      : $%.2f (petal/costmeter.py, enforced per call)"
          % cfg.spend_limit_usd)
    if lim is None:
        print("\nThe plan's hard rule is a $9 limit *on the key*. Nothing here can stop a "
              "bug in code I have not written; setting the limit in the OpenRouter "
              "dashboard is the only guard that does not depend on this repo.")
    elif float(lim) > cfg.spend_limit_usd:
        print("\nThe key's limit ($%s) is above the local ceiling ($%.2f). The local one "
              "binds first in normal use." % (lim, cfg.spend_limit_usd))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
