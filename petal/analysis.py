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
    #: per scenario, the utility a perfect non-asserting answer would earn
    #: (decision: 1.0; content: the permitted + abstract tiers). Aligned to
    #: `scenarios`. This is the numerator of the ceiling, and it is a property
    #: of the rubric, not of any run.
    u_max_no_s: list[float] = field(default_factory=list)
    #: channel -> did the judge read every span on it? A channel scored by the
    #: cascade alone yields a lower bound, because the entailment stage scores
    #: a plain paraphrase at 0.001. Set from the detections: a judge-read span
    #: carries the cascade's own verdict alongside the judge's.
    judge_read: dict[str, bool] = field(default_factory=dict)

    def arms(self) -> list[str]:
        return sorted(self.utility)


def scenario_index(path: str | Path | None = None) -> dict[str, Any]:
    """{scenario id: Scenario}, or {} if the testbed is not on disk."""
    from .scenarios.schema import Scenario
    from . import paths as _paths
    p = Path(path) if path else (_paths.SCENARIOS / "scenarios.json")
    try:
        return {s.id: s for s in (Scenario.from_dict(d)
                                  for d in json.loads(p.read_text(encoding="utf-8")))}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def load(runs_paths: Sequence[str | Path],
         detections_paths: Sequence[str | Path] | None = None,
         scenarios: dict[str, Any] | None = None
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
    #: A channel counts as judge-read only if *every* detection on it carries
    #: the cascade's verdict beside the judge's -- that is what the nominated
    #: channel does. Any span the judge did not read leaves the channel a
    #: cascade channel, because the rate is only as good as its weakest reader.
    judged: dict[str, list[bool]] = defaultdict(list)
    for d in dets:
        tgt = d.get("target", "S")
        l_acc[(d["use_type"], d["scenario_id"], d["arm"], d["channel"],
               tgt)].append(bool(d["leak"]))
        judged[d["channel"]].append(
            d.get("cascade_route") not in (None, "")
            or str(d.get("route", "")).startswith("judge"))
    judge_read = {ch: bool(v) and all(v) for ch, v in judged.items()}

    scens = scenario_index() if scenarios is None else scenarios

    panels: dict[str, Panel] = {}
    for ut in sorted({r["use_type"] for r in runs}):
        sids = sorted({s for s, u in use_of.items() if u == ut})
        arms = sorted({r["arm"] for r in runs if r["use_type"] == ut})
        p = Panel(use_type=ut, scenarios=sids)
        p.judge_read = dict(judge_read)
        p.u_max_no_s = [float(getattr(scens[s], "max_utility_without_asserting_S", 1.0))
                        if s in scens else float("nan") for s in sids]
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


def has_ceiling(p: Panel) -> bool:
    v = p.u_max_no_s
    return bool(v) and len(v) == len(p.scenarios) and all(x == x for x in v)


def ceiling(p: Panel, *, n_boot: int = 10000, seed: int = 0) -> Interval | None:
    """The delta a perfect non-asserting defence would score, in delta's units.

    This is the fix for a normalisation mismatch that would have made every
    "fraction of ceiling" number wrong. The scenario schema publishes a
    *design-intent* ceiling,

        (U_max_noS - U_chance) / (1 - U_chance),

    which is a statement about the rubric: U_chance is the floor the construction
    aims at, and 1.0 is a perfect score. But the measured delta is

        (U_arm - U_drop) / (U_full - U_drop),

    normalised by what the Drop and Full arms *actually* scored. The two agree
    only if U_drop == U_chance and U_full == 1.0, and neither holds: on the mock
    testbed the content arms gave U_drop = 0.30 against a 0.30 chance floor but
    U_full = 1.0, and the decision arms gave U_drop = 0.267 against a 0.333
    floor. Dividing a delta by a ceiling computed on a different scale is a
    category error, and it is why a content delta of 0.429 looked like it was
    sitting "exactly on" a 0.40 ceiling.

    So the ceiling is recomputed here on delta's own scale, by feeding the
    per-scenario `max_utility_without_asserting_S` through the identical
    estimator. It is a ratio of means over the same scenario-paired bootstrap,
    so it carries a CI and composes with delta exactly.
    """
    if not has_ceiling(p) or "full" not in p.utility or "drop" not in p.utility:
        return None
    return bootstrap_delta(p.u_max_no_s, p.utility["full"], p.utility["drop"],
                           n_boot=n_boot, seed=seed)


def delta_normalised_table(p: Panel, arms: Sequence[str], *, n_boot: int = 10000,
                           seed: int = 0) -> dict[str, Interval]:
    """delta / ceiling, resampled as one quantity rather than divided afterwards.

        delta / ceiling = (U_arm - U_drop) / (U_maxNoS - U_drop)

    because the (U_full - U_drop) in both denominators cancels. Estimating it
    directly, rather than dividing two point estimates, is what gives it an
    honest CI: the numerator and denominator share scenarios and are strongly
    correlated, so a ratio of two independently-bootstrapped intervals would be
    far too wide.

    1.0 means the arm reached everything a non-asserting defence could reach
    here. This is the headline number for Conjecture C1, because it is the only
    one comparable across use types -- a raw delta of 0.43 on content and 1.0 on
    decision describe the same achievement relative to what was available.
    """
    if not has_ceiling(p) or "drop" not in p.utility:
        return {}
    out: dict[str, Interval] = {}
    for arm in arms:
        if arm in p.utility:
            out[arm] = bootstrap_delta(p.utility[arm], p.u_max_no_s,
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


def subset(p: Panel, drop_ids: Iterable[str]) -> Panel:
    """A Panel with some scenarios removed, for the robustness check.

    Five restricted-category texts were reworded between the audit pilot and
    the freeze (see results/prefreeze_rule.md). The edits were to categories,
    so they touch 12 of the 60 scenarios, not only the five that failed. Every
    headline number is therefore reported twice -- on all 60, and with those 12
    dropped -- so that a reader can check the edits did not make the result.
    """
    drop = set(drop_ids)
    keep = [i for i, sid in enumerate(p.scenarios) if sid not in drop]
    out = Panel(use_type=p.use_type, scenarios=[p.scenarios[i] for i in keep])
    out.u_max_no_s = [p.u_max_no_s[i] for i in keep] if p.u_max_no_s else []
    for arm in p.utility:
        out.utility[arm] = [p.utility[arm][i] for i in keep]
        out.relay_tokens[arm] = [p.relay_tokens.get(arm, [])[i] for i in keep]             if p.relay_tokens.get(arm) else []
        out.leak[arm] = {ch: [v[i] for i in keep]
                         for ch, v in p.leak.get(arm, {}).items()}
        out.leak_control[arm] = {ch: [v[i] for i in keep]
                                 for ch, v in p.leak_control.get(arm, {}).items()}
    return out

def judge_coverage(p: "Panel") -> dict[str, bool]:
    """channel -> whether the judge read every span on it.

    Recorded per detection by the detector: a span the judge read on a
    nominated channel carries `cascade_route`, because the cascade's own
    verdict is kept beside the judge's. A channel where no detection carries
    one was scored by the cascade alone.
    """
    return {ch: bool(p.judge_read.get(ch)) for ch in CHANNELS}


def h5_verdict(p: "Panel", *, arm_full: str = "full",
               a: str = "constraint_only", b: str = "decision_only",
               channel: str = "m1") -> dict | None:
    """Did the pre-registered granularity ordering hold?

    H5, fixed before `constraint_only` ran: assertion should fall as the relay
    carries less, `full` > `constraint_only` >= `decision_only`. The second
    inequality is the interesting one, because it is the one a 'less is safer'
    intuition predicts and the one that can reverse: a relay instructed to
    carry only its conclusion can still volunteer the reason, and if it does
    the ordering flips.

    Reported with the paired test, because at n=30 a reversal of 4 against 1
    is not evidence of a real ordering in either direction.
    """
    lf = leak_rate(p, arm_full, channel)
    la = leak_rate(p, a, channel)
    lb = leak_rate(p, b, channel)
    if lf != lf or la != la or lb != lb:
        return None
    first = lf > la
    second = la <= lb
    parts = [("`%s` > `%s`" % (arm_full, a), "%.3f > %.3f" % (lf, la), first),
             ("`%s` <= `%s`" % (a, b), "%.3f vs %.3f" % (la, lb), second)]
    mc = mcnemar_leak(p, a, b, channel)
    if first and second:
        verdict = "supported"
        note = ("Both inequalities hold. The paired test on the second is "
                "%s, so the ordering is consistent with the data without "
                "being established by it." % mc)
    elif first and not second:
        verdict = "not supported"
        note = ("The first inequality holds and the second **reverses**: "
                "`%s` asserts S more often than `%s`, not less. The paired "
                "test is %s, so the reversal is not significant either -- the "
                "honest reading is that the ordering between the two "
                "abstracting arms is unresolved at this n, not that the "
                "coarser relay is safer. Worth reading the relays that "
                "assert: a planner told to carry only its conclusion can "
                "still volunteer the reason." % (b, a, mc))
    else:
        verdict = "not supported"
        note = ("The first inequality fails: the arm holding the full reason "
                "does not assert S more often than the abstracting one, which "
                "is the premise the rest of the comparison rests on. Paired "
                "test on the second: %s." % mc)
    return {"parts": parts, "verdict": verdict, "note": note}


def mcnemar_leak(p: "Panel", a: str, b: str, channel: str = "m1") -> str:
    """Exact McNemar on two arms' per-scenario leak flags, as a sentence."""
    xa = (p.leak.get(a) or {}).get(channel)
    xb = (p.leak.get(b) or {}).get(channel)
    if not xa or not xb or len(xa) != len(xb):
        return "not available"
    b01 = sum(1 for i, j in zip(xa, xb) if (not i) and j)
    b10 = sum(1 for i, j in zip(xa, xb) if i and (not j))
    n = b01 + b10
    if not n:
        return "no discordant pairs"
    try:
        from scipy.stats import binomtest
        pv = binomtest(b10, n, 0.5).pvalue
    except ImportError:
        return "%d vs %d discordant (scipy unavailable)" % (b10, b01)
    return ("%d vs %d discordant pairs, exact McNemar p = %.3f"
            % (b10, b01, pv))
