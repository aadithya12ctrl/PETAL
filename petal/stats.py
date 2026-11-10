"""Paired statistics for the arm comparisons, implemented against scipy only.

`statsmodels` is deliberately not a dependency: McNemar, Wilcoxon and Holm are a
few lines each, and writing them here means the exact variants are visible rather
than defaulted.

Two choices worth stating, because both change the numbers:

* **The bootstrap resamples scenarios, not runs.** Arms are compared on the same
  60 scenarios, so the scenario is the unit of pairing; resampling runs
  independently would break that pairing and understate the uncertainty in a
  difference between arms.
* **delta is a ratio of means, not a mean of ratios.** Per scenario the
  denominator U_full - U_drop is frequently 0 -- on any scenario where S made no
  difference -- and a mean of per-scenario ratios would either divide by zero or
  silently drop exactly the scenarios that carry no information about delta,
  biasing it. The ratio of resampled means is defined whenever the arm means
  differ at all, and its bootstrap distribution carries the uncertainty of both
  numerator and denominator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass
class Interval:
    point: float
    lo: float
    hi: float
    n: int

    def __str__(self) -> str:
        return "%.3f [%.3f, %.3f]" % (self.point, self.lo, self.hi)

    def to_dict(self) -> dict:
        return {"point": self.point, "lo": self.lo, "hi": self.hi, "n": self.n}


# ------------------------------------------------------------------ bootstrap
def bootstrap_mean(values: Sequence[float], *, n_boot: int = 10000,
                   alpha: float = 0.05, seed: int = 0) -> Interval:
    v = np.asarray(list(values), dtype=float)
    if v.size == 0:
        return Interval(float("nan"), float("nan"), float("nan"), 0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, v.size, size=(n_boot, v.size))
    draws = v[idx].mean(axis=1)
    return Interval(float(v.mean()), float(np.quantile(draws, alpha / 2)),
                    float(np.quantile(draws, 1 - alpha / 2)), int(v.size))


def bootstrap_paired_diff(a: Sequence[float], b: Sequence[float], *,
                          n_boot: int = 10000, alpha: float = 0.05,
                          seed: int = 0) -> Interval:
    """CI for mean(a) - mean(b) where a[i] and b[i] are the same scenario."""
    x = np.asarray(list(a), dtype=float)
    y = np.asarray(list(b), dtype=float)
    if x.size != y.size:
        raise ValueError("paired inputs differ in length")
    d = x - y
    return bootstrap_mean(d, n_boot=n_boot, alpha=alpha, seed=seed)


def bootstrap_delta(u_arm: Sequence[float], u_full: Sequence[float],
                    u_drop: Sequence[float], *, n_boot: int = 10000,
                    alpha: float = 0.05, seed: int = 0,
                    min_denominator: float = 1e-6) -> Interval:
    """delta = (mean U_arm - mean U_drop) / (mean U_full - mean U_drop).

    Scenario-paired: one resample of scenario indices is applied to all three
    arms, so the ratio is formed from means over the *same* resampled scenarios.
    """
    A = np.asarray(list(u_arm), dtype=float)
    F = np.asarray(list(u_full), dtype=float)
    D = np.asarray(list(u_drop), dtype=float)
    if not (A.size == F.size == D.size):
        raise ValueError("arms differ in scenario count")
    if A.size == 0:
        return Interval(float("nan"), float("nan"), float("nan"), 0)

    den = F.mean() - D.mean()
    point = ((A.mean() - D.mean()) / den if abs(den) > min_denominator
             else float("nan"))

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, A.size, size=(n_boot, A.size))
    da = A[idx].mean(axis=1)
    df = F[idx].mean(axis=1)
    dd = D[idx].mean(axis=1)
    dens = df - dd
    ok = np.abs(dens) > min_denominator
    if not ok.any():
        return Interval(point, float("nan"), float("nan"), int(A.size))
    draws = (da[ok] - dd[ok]) / dens[ok]
    return Interval(point, float(np.quantile(draws, alpha / 2)),
                    float(np.quantile(draws, 1 - alpha / 2)), int(A.size))


# ----------------------------------------------------------------- hypotheses
def mcnemar_exact(a: Sequence[bool], b: Sequence[bool]) -> dict:
    """Paired binary comparison, exact binomial on the discordant pairs.

    The exact form rather than the chi-square approximation because the
    defended arms produce few discordant pairs and the approximation is poor
    there -- which is precisely the comparison the paper rests on.
    """
    x = [bool(v) for v in a]
    y = [bool(v) for v in b]
    if len(x) != len(y):
        raise ValueError("paired inputs differ in length")
    b_only = sum(1 for p, q in zip(x, y) if p and not q)
    c_only = sum(1 for p, q in zip(x, y) if q and not p)
    n_disc = b_only + c_only
    if n_disc == 0:
        return {"b": 0, "c": 0, "n_discordant": 0, "p_value": 1.0,
                "note": "no discordant pairs"}
    try:
        from scipy.stats import binomtest
        p = float(binomtest(b_only, n_disc, 0.5).pvalue)
    except ImportError:
        z = (abs(b_only - c_only) - 1) / math.sqrt(n_disc)
        p = math.erfc(z / math.sqrt(2))
    return {"b": b_only, "c": c_only, "n_discordant": n_disc, "p_value": p}


def wilcoxon_paired(a: Sequence[float], b: Sequence[float]) -> dict:
    """Wilcoxon signed-rank on paired utilities."""
    x = np.asarray(list(a), dtype=float)
    y = np.asarray(list(b), dtype=float)
    d = x - y
    if np.allclose(d, 0):
        return {"n": int(x.size), "n_nonzero": 0, "statistic": float("nan"),
                "p_value": 1.0, "note": "all differences zero"}
    try:
        from scipy.stats import wilcoxon
        r = wilcoxon(x, y, zero_method="wilcox", alternative="two-sided")
        return {"n": int(x.size), "n_nonzero": int(np.count_nonzero(d)),
                "statistic": float(r.statistic), "p_value": float(r.pvalue)}
    except ImportError:
        return {"n": int(x.size), "n_nonzero": int(np.count_nonzero(d)),
                "statistic": float("nan"), "p_value": float("nan"),
                "note": "scipy unavailable"}


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, dict]:
    """Holm-Bonferroni step-down adjustment over a named family of tests."""
    items = sorted(pvalues.items(), key=lambda kv: (kv[1] is None, kv[1]))
    m = len(items)
    out: dict[str, dict] = {}
    running = 0.0
    for i, (name, p) in enumerate(items):
        if p is None or p != p:
            out[name] = {"p": p, "p_adj": float("nan"), "reject": False}
            continue
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)       # enforce monotonicity
        out[name] = {"p": p, "p_adj": running, "reject": running <= alpha}
    return out


# ---------------------------------------------------------------------- power
def mde_paired_mean(sd_diff: float, n: int, *, alpha: float = 0.05,
                    power: float = 0.80) -> float:
    """Smallest paired mean difference detectable at the given power."""
    if n <= 1 or sd_diff <= 0:
        return float("nan")
    try:
        from scipy.stats import norm
        z_a = norm.ppf(1 - alpha / 2)
        z_b = norm.ppf(power)
    except ImportError:
        z_a, z_b = 1.959964, 0.841621
    return (z_a + z_b) * sd_diff / math.sqrt(n)


def mde_delta(sd_diff: float, n: int, u_full: float, u_drop: float, **kw) -> float:
    """The same quantity expressed on the delta scale.

    delta divides a utility difference by (U_full - U_drop), so the smallest
    detectable delta gap is the smallest detectable utility difference divided by
    the same denominator. Reported rather than asserted, because the plan's claim
    that v1 can only detect "a delta gap of 0.25 or more" is exactly this number
    and it depends on a variance nobody has measured yet.
    """
    den = u_full - u_drop
    if abs(den) < 1e-9:
        return float("nan")
    return mde_paired_mean(sd_diff, n, **kw) / den
