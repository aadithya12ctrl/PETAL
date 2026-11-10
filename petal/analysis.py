"""Experiment 1 analysis: delta, leak rates, the decision rule, and the tests.

Everything here is scenario-paired. A scenario is the unit: each arm ran on the
same 60, so differences between arms are paired differences and the bootstrap
resamples scenarios.

Leak rates are reported three ways, and the distinction matters:

* **observed** -- what the detector flagged.
* **corrected** -- Rogan-Gladen, once a hand-labelled validation set exists.
  PETAL_v2 errata item 1: calling observed rates "lower bounds" is false as soon
  as the detector has false positives, and this detector demonstrably does.
* **causal leak** Lambda = leak(Full) - leak(Swap), and the **inference floor**
  Phi_floor = leak(Drop). Only Lambda is the quantity a relay defence can act
  on; the floor is unavoidable by any relay design (PETAL_v2 limitation 7) and
  must be subtracted rather than charged to the defence.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .correction import Validation, bootstrap_corrected, UninvertibleDetector
from .stats import (Interval, bootstrap_delta, bootstrap_paired_diff,
                    holm, mcnemar_exact, mde_delta, wilcoxon_paired)

#: the channel a relay-level defence is responsible for
PRIMARY_CHANNEL = "m1"
#: every channel the detector scores, in transmission order
CHANNELS = ["m1_draft", "m1", "m2", "output"]


@dataclass
class Panel:
    """Scenario-aligned measurements for one use type."""
    use_type: str
    scenarios: list[str]
    utility: dict[str, list[float]] = field(default_factory=dict)
    #: assertion of S, per arm per channel -- the quantity Lambda is built from
    leak: dict[str, dict[str, list[bool]]] = field(default_factory=dict)
    #: assertion of S', scored only on the Swap arm, as a positive control
    leak_control: dict[str, dict[str, list[bool]]] = field(default_factory=dict)
    relay_tokens: dict[str, list[float]] = field(default_factory=dict)

    def arms(self) -> list[str]:
        return sorted(self.utility)


def load(runs_paths: Sequence[str | Path],
         detections_paths: Sequence[str | Path] | None = None
         ) -> tuple[dict[str, Panel], dict[str, Any]]:
    """Build one Panel per use type from run and detection files.

    Runs are keyed by (scenario, arm) and averaged over models and seeds, so a
    scenario contributes one number per arm. Averaging before pairing is
    deliberate: it keeps the pairing intact and makes the replication seed a
    variance reduction rather than a doubling of the sample.
    """
    runs: list[dict] = []
    for p in runs_paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                runs.append(json.loads(line))

    dets: list[dict] = []
    for p in (detections_paths or []):
        pp = Path(p)
        if pp.exists():
            for line in pp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    dets.append(json.loads(line))

    u_acc: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    t_acc: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    use_of: dict[str, str] = {}
    for r in runs:
        key = (r["use_type"], r["scenario_id"], r["arm"])
        u_acc[key].append(float(r["utility"]))
        hops = r.get("hops") or []
        relay = next((h for h in hops if h.get("role") == "worker"), None)
        t_acc[key].append(float((relay or {}).get("prompt_tokens", 0)))
        use_of[r["scenario_id"]] = r["use_type"]

    # Detections are keyed by target as well as channel. Every arm is scored
    # against S -- that is what Lambda needs -- and the Swap arm is additionally
    # scored against S' as a positive control.
    l_acc: dict[tuple[str, str, str, str, str], list[bool]] = defaultdict(list)
    for d in dets:
        tgt = d.get("target", "S")
        l_acc[(d["use_type"], d["scenario_id"], d["arm"], d["channel"],
               tgt)].append(bool(d["leak"]))

    panels: dict[str, Panel] = {}
    for ut in sorted({r["use_type"] for r in runs}):
        sids = sorted({s for s, u in use_of.items() if u == ut})
        arms = sorted({r["arm"] for r in runs if r["use_type"] == ut})
        p = Panel(use_type=ut, scenarios=sids)
        for arm in arms:
            p.utility[arm] = [_mean(u_acc.get((ut, s, arm), [])) for s in sids]
            p.relay_tokens[arm] = [_mean(t_acc.get((ut, s, arm), [])) for s in sids]
            p.leak[arm] = {}
            p.leak_control[arm] = {}
            for ch in CHANNELS:
                vals = [l_acc.get((ut, s, arm, ch, "S")) for s in sids]
                if any(v is not None for v in vals):
                    p.leak[arm][ch] = [bool(v and any(v)) for v in vals]
                cvals = [l_acc.get((ut, s, arm, ch, "S_prime")) for s in sids]
                if any(v is not None for v in cvals):
                    p.leak_control[arm][ch] = [bool(v and any(v)) for v in cvals]
        panels[ut] = p

    meta = {"n_runs": len(runs), "n_detections": len(dets),
            "models": sorted({r["model_role"] for r in runs}),
            "seeds": sorted({r["seed"] for r in runs}),
            "arms": sorted({r["arm"] for r in runs})}
    return panels, meta


def _mean(xs: Iterable[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


# --------------------------------------------------------------- separability
def delta_table(p: Panel, arms: Sequence[str], *, n_boot: int = 10000,
                seed: int = 0) -> dict[str, Interval]:
    if "full" not in p.utility or "drop" not in p.utility:
        return {}
    out: dict[str, Interval] = {}
    for arm in arms:
        if arm in p.utility:
            out[arm] = bootstrap_delta(p.utility[arm], p.utility["full"],
                                       p.utility["drop"], n_boot=n_boot, seed=seed)
    return out


# -------------------------------------------------------------- leak measures
def leak_rate(p: Panel, arm: str, channel: str = PRIMARY_CHANNEL) -> float:
    v = p.leak.get(arm, {}).get(channel)
    return _mean([1.0 if x else 0.0 for x in v]) if v else float("nan")


def lambda_causal(p: Panel, channel: str = PRIMARY_CHANNEL) -> float:
    """Lambda = P(assert S | S) - P(assert S | S'). The causal leak.

    Both terms are the rate of asserting *S*. The second is measured on the Swap
    arm, where S is absent, so it is the rate at which S is asserted anyway --
    detector false positives plus genuine confabulation. Subtracting it is what
    separates a causal leak from an artefact.
    """
    return leak_rate(p, "full", channel) - leak_rate(p, "swap", channel)


def swap_control(p: Panel, channel: str = PRIMARY_CHANNEL) -> float:
    """Rate at which the Swap arm asserts S'. A positive control.

    If this is near zero the Swap arm relayed nothing, and its low rate on S is
    then uninformative -- it would show specificity that was never tested.
    """
    v = p.leak_control.get("swap", {}).get(channel)
    return _mean([1.0 if x else 0.0 for x in v]) if v else float("nan")


def phi_floor(p: Panel, channel: str = PRIMARY_CHANNEL) -> float:
    return leak_rate(p, "drop", channel)


def corrected_leaks(p: Panel, val: Validation | None, *, channel: str = PRIMARY_CHANNEL,
                    n_boot: int = 10000, seed: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in p.arms():
        flags = p.leak.get(arm, {}).get(channel)
        if not flags:
            continue
        row: dict[str, Any] = {"observed": _mean([1.0 if f else 0.0 for f in flags])}
        if val is not None:
            try:
                cr = bootstrap_corrected(flags, val, n_boot=n_boot, seed=seed)
                row.update({"corrected": cr.corrected, "lo": cr.lo, "hi": cr.hi,
                            "degenerate_draws": cr.n_degenerate})
            except (UninvertibleDetector, ValueError) as e:
                row["corrected_error"] = str(e)
        out[arm] = row
    return out


# ------------------------------------------------------------- decision rule
def decision_rule(p: Panel, *, kappa: float, lam: float,
                  petal_arm: str = "petal_text", baseline: str = "b4_restriction",
                  channel: str = PRIMARY_CHANNEL) -> dict[str, Any]:
    """PETAL_v2 §4.2.4: petal wins iff dU > kappa * dLeak + lambda * dLength.

    Length is the relay's token count, expressed as a fraction of the Full arm's
    relay so that `lambda` is dimensionless. PETAL_v2 errata item 11 is the
    reason for being explicit here: token slack is a proxy for bit slack, not the
    same thing, so a length penalty measured in tokens is a stated convention and
    not a derived quantity.
    """
    if petal_arm not in p.utility or baseline not in p.utility:
        return {"available": False}
    du = bootstrap_paired_diff(p.utility[petal_arm], p.utility[baseline])
    lk_p, lk_b = leak_rate(p, petal_arm, channel), leak_rate(p, baseline, channel)
    base_len = _mean(p.relay_tokens.get("full", [])) or 1.0
    dlen = (_mean(p.relay_tokens.get(petal_arm, []))
            - _mean(p.relay_tokens.get(baseline, []))) / base_len
    cost = kappa * (lk_p - lk_b) + lam * dlen
    return {"available": True, "delta_utility": du.to_dict(),
            "leak_petal": lk_p, "leak_baseline": lk_b,
            "delta_leak": lk_p - lk_b, "delta_length_frac": dlen,
            "threshold": cost, "petal_wins": du.point > cost,
            "margin": du.point - cost,
            "wins_at_ci_low": du.lo > cost}


# -------------------------------------------------------------------- testing
def paired_tests(p: Panel, pairs: Sequence[tuple[str, str]], *,
                 channel: str = PRIMARY_CHANNEL) -> dict[str, Any]:
    """McNemar on leaks and Wilcoxon on utility, with one Holm family.

    The family is every test reported for this use type. Correcting leak tests
    and utility tests separately would understate the correction: the paper reads
    them together as one claim about whether the petal helps.
    """
    raw: dict[str, float] = {}
    detail: dict[str, Any] = {}
    for a, b in pairs:
        if a not in p.utility or b not in p.utility:
            continue
        w = wilcoxon_paired(p.utility[a], p.utility[b])
        detail["utility %s vs %s" % (a, b)] = w
        raw["utility %s vs %s" % (a, b)] = w["p_value"]
        la = p.leak.get(a, {}).get(channel)
        lb = p.leak.get(b, {}).get(channel)
        if la and lb:
            m = mcnemar_exact(la, lb)
            detail["leak %s vs %s" % (a, b)] = m
            raw["leak %s vs %s" % (a, b)] = m["p_value"]
    return {"detail": detail, "holm": holm(raw)}


def power_note(p: Panel) -> dict[str, Any]:
    """The MDE on the delta scale, from the observed paired variance."""
    import numpy as np
    if not {"full", "drop", "petal_text"} <= set(p.utility):
        return {}
    d = np.asarray(p.utility["petal_text"]) - np.asarray(p.utility["b4_restriction"]) \
        if "b4_restriction" in p.utility else \
        np.asarray(p.utility["petal_text"]) - np.asarray(p.utility["drop"])
    sd = float(np.std(d, ddof=1)) if d.size > 1 else float("nan")
    u_full, u_drop = _mean(p.utility["full"]), _mean(p.utility["drop"])
    return {"n_scenarios": len(p.scenarios), "sd_paired_diff": sd,
            "u_full": u_full, "u_drop": u_drop,
            "mde_delta_80pct": mde_delta(sd, len(p.scenarios), u_full, u_drop)}
