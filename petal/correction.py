"""Rogan-Gladen correction for an imperfect leak detector.

PETAL_v2 errata item 1: v1 claimed every reported leak rate was a lower bound,
which is false as soon as the detector has false positives. With sensitivity Se
and specificity Sp estimated on hand labels, the corrected prevalence is

    p_true = (p_obs + Sp - 1) / (Se + Sp - 1)

clipped to [0, 1]. The paper's CI "resamples both the trace set and the
validation set", which is what `bootstrap_corrected` does: the uncertainty in Se
and Sp is a real part of the uncertainty in the corrected rate, and holding them
fixed produces intervals that are too narrow.

The denominator is the Youden index Se + Sp - 1. As it approaches zero the
correction explodes, so `corrected_rate` reports it and refuses to invert a
detector that is no better than chance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass
class Validation:
    """Counts from the hand-labelled validation set."""
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def sensitivity(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else float("nan")

    @property
    def specificity(self) -> float:
        d = self.tn + self.fp
        return self.tn / d if d else float("nan")

    @property
    def youden(self) -> float:
        return self.sensitivity + self.specificity - 1.0

    @classmethod
    def from_labels(cls, predicted: Sequence[bool], truth: Sequence[bool]) -> "Validation":
        if len(predicted) != len(truth):
            raise ValueError("predicted and truth differ in length")
        tp = sum(1 for p, t in zip(predicted, truth) if p and t)
        fp = sum(1 for p, t in zip(predicted, truth) if p and not t)
        fn = sum(1 for p, t in zip(predicted, truth) if not p and t)
        tn = sum(1 for p, t in zip(predicted, truth) if not p and not t)
        return cls(tp=tp, fp=fp, fn=fn, tn=tn)

    @classmethod
    def from_weighted_labels(cls, predicted: Sequence[bool],
                            truth: Sequence[bool],
                            weights: Sequence[float]) -> "Validation":
        """Se/Sp from a sample stratified on the detector's own verdict.

        The validation sheet is drawn stratified by (arm x detector verdict).
        That makes an item's sampling probability depend on the detector's
        verdict -- which is exactly what Se and Sp condition on -- so pooling
        the sampled items unweighted estimates the wrong quantity. With a
        design that over-samples the detector's positives, unweighted Se is
        biased up and unweighted Sp biased down.

        The fix is the usual one for a stratified design: weight each item by
        the inverse of its sampling fraction, so the weighted counts estimate
        the counts in the population the sheet was drawn from.

        Counts come back as floats, because weighted counts are not integers.
        """
        if not (len(predicted) == len(truth) == len(weights)):
            raise ValueError("predicted, truth and weights differ in length")
        z = zip(predicted, truth, weights)
        tp = fp = fn = tn = 0.0
        for pr, t, w in z:
            if pr and t:
                tp += w
            elif pr and not t:
                fp += w
            elif t:
                fn += w
            else:
                tn += w
        return cls(tp=tp, fp=fp, fn=fn, tn=tn)

    def to_dict(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
                "n": self.n, "sensitivity": self.sensitivity,
                "specificity": self.specificity, "youden": self.youden}


class UninvertibleDetector(RuntimeError):
    pass


def corrected_rate(p_obs: float, se: float, sp: float, *,
                   min_youden: float = 0.05) -> float:
    """Rogan-Gladen point estimate, clipped to [0, 1]."""
    y = se + sp - 1.0
    if not math.isfinite(y) or y <= min_youden:
        raise UninvertibleDetector(
            "Youden index %.3f <= %.3f: this detector cannot be inverted"
            % (y, min_youden))
    return min(1.0, max(0.0, (p_obs + sp - 1.0) / y))


@dataclass
class CorrectedRate:
    observed: float
    corrected: float
    lo: float
    hi: float
    se: float
    sp: float
    youden: float
    n_traces: int
    n_validation: int
    n_degenerate: int           # bootstrap draws where the detector was uninvertible

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        return d


def bootstrap_corrected(flags: Sequence[bool], val: Validation, *,
                        n_boot: int = 10000, alpha: float = 0.05,
                        seed: int = 0, min_youden: float = 0.05) -> CorrectedRate:
    """Corrected rate with a percentile CI over traces *and* validation set.

    Each draw resamples the trace flags (giving p_obs) and resamples the
    validation set's four cells from a multinomial (giving Se and Sp), so the
    interval carries the detector's own uncertainty. Draws in which the
    resampled detector is uninvertible are counted and excluded rather than
    clipped, because clipping them would pull the interval towards whichever
    bound the degenerate draw happened to hit.
    """
    flags = np.asarray(list(flags), dtype=bool)
    if flags.size == 0:
        raise ValueError("no traces")
    rng = np.random.default_rng(seed)
    p_obs = float(flags.mean())
    point = corrected_rate(p_obs, val.sensitivity, val.specificity,
                           min_youden=min_youden)

    cells = np.array([val.tp, val.fn, val.fp, val.tn], dtype=float)
    probs = cells / cells.sum()
    draws = rng.multinomial(val.n, probs, size=n_boot)
    idx = rng.integers(0, flags.size, size=(n_boot, flags.size))
    p_boot = flags[idx].mean(axis=1)

    out = []
    degenerate = 0
    for k in range(n_boot):
        tp, fn, fp, tn = draws[k]
        se = tp / (tp + fn) if (tp + fn) else np.nan
        sp = tn / (tn + fp) if (tn + fp) else np.nan
        y = se + sp - 1.0
        if not np.isfinite(y) or y <= min_youden:
            degenerate += 1
            continue
        out.append(min(1.0, max(0.0, (p_boot[k] + sp - 1.0) / y)))
    if not out:
        raise UninvertibleDetector("every bootstrap draw was uninvertible")
    arr = np.sort(np.asarray(out))
    lo = float(np.quantile(arr, alpha / 2))
    hi = float(np.quantile(arr, 1 - alpha / 2))
    return CorrectedRate(observed=p_obs, corrected=point, lo=lo, hi=hi,
                         se=val.sensitivity, sp=val.specificity, youden=val.youden,
                         n_traces=int(flags.size), n_validation=val.n,
                         n_degenerate=degenerate)


# ------------------------------------------------------------- agreement
def cohens_kappa(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Two-rater agreement on a binary label, chance-corrected."""
    if len(a) != len(b) or not a:
        raise ValueError("need two equal, non-empty label sequences")
    n = len(a)
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(a) / n
    pb = sum(b) / n
    chance = pa * pb + (1 - pa) * (1 - pb)
    if abs(1 - chance) < 1e-12:
        return float("nan")
    return (agree - chance) / (1 - chance)
