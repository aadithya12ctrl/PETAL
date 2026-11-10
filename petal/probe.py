"""Probes that try to recover S from a relay message, and the MI bound they give.

Experiment 2 asks whether measured information about S decays at least as fast as
Theorem T3's bound. That needs a number per hop, and the plan proposes "a small
probe (logistic regression on embeddings)".

**Why the primary probe is training-free.** The plan's design gives 20 scenarios
x 5 hops, so one hop of one schedule supplies 20 texts carrying 20 *different*
restricted categories. Training a 23-class classifier on 20 examples measures the
classifier, not the channel. The primary probe is therefore a matcher: rank all
candidate propositions against the message and see whether the true one comes
first. It needs no training data, it is exactly "the adversary's best guess given
the message", and its error rate feeds Fano directly.

**Fano with a suboptimal probe is still valid.** Fano's inequality
H(S|M) <= H_b(P_e) + P_e log2(k-1) holds for *any* estimator of S from M, not
only the Bayes-optimal one. A weak probe has larger P_e, hence a larger
right-hand side, hence a weaker but still correct upper bound on H(S|M) -- so

    I(S; M) >= log2(k) - H_b(P_e) - P_e log2(k - 1)

is a genuine lower bound. That direction is what H4 needs: T3 supplies an upper
bound on I, the probe supplies a lower bound, and the kill condition fires if the
lower bound ever exceeds the upper one, which would mean S is reaching the
downstream agent by a route the ladder does not control.

The plan's logistic-regression probe is kept as a secondary over the four *kinds*
rather than the 23 categories, where n = 20 is merely thin instead of hopeless.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np


# ------------------------------------------------------------------ MI bounds
def binary_entropy(e: float) -> float:
    if e <= 0.0 or e >= 1.0:
        return 0.0
    return -(e * math.log2(e) + (1 - e) * math.log2(1 - e))


def chance_error(k: int) -> float:
    return 1.0 - 1.0 / k if k > 1 else 0.0


def fano_mi_lower(error_rate: float, k: int) -> float:
    """Lower bound on I(S; M) in bits, from an estimator's error rate.

    Two guards, both of which matter in practice:

    * Clipped at 0, since a negative lower bound on a non-negative quantity is
      just 0.
    * Returns 0 once the error rate reaches chance, 1 - 1/k. The algebra does
      not: at e = 1 with k = 23 it returns 0.065 bits, because an estimator that
      is reliably *wrong* is informative and could be inverted. That is true in
      general but it is not what an error rate at or above chance means here --
      it means the message carried nothing and the probe guessed. Reporting
      0.065 bits for an empty slot would put a floor under every decay curve and
      make the ladder look leakier than it is.
    """
    if k <= 1:
        return 0.0
    e = min(max(float(error_rate), 0.0), 1.0)
    if e >= chance_error(k):
        return 0.0
    val = math.log2(k) - binary_entropy(e) - e * math.log2(k - 1)
    return max(0.0, val)


def error_upper_ci(n_errors: int, n: int, alpha: float = 0.05) -> float:
    """One-sided Clopper-Pearson upper limit on the error rate.

    Needed because H4 compares a *measured* lower bound against a *theoretical*
    upper bound, and at n = 20 the sampling noise on an error rate is about
    +/- 0.09. Without this, a rung whose true keep probability is 0.8 can show
    2 errors instead of 4 by chance and appear to breach the bound. Evaluating
    Fano at the upper confidence limit of the error gives a conservative lower
    bound on the information, so H4 fires on evidence rather than on noise.
    """
    if n <= 0:
        return 1.0
    if n_errors >= n:
        return 1.0
    try:
        from scipy.stats import beta
        return float(beta.ppf(1 - alpha, n_errors + 1, n - n_errors))
    except ImportError:
        # normal approximation, widened, if scipy is unavailable
        p = n_errors / n
        return min(1.0, p + 1.96 * math.sqrt(max(p * (1 - p), 0.01) / n))


# -------------------------------------------------------------- match probe
@dataclass
class ProbeResult:
    hop: int
    schedule: str
    n: int
    k: int
    top1_correct: int
    error_rate: float
    mi_lower_bits: float
    mi_at_chance_bits: float
    error_rate_ci_hi: float = 1.0      # Clopper-Pearson upper limit
    mi_lower_bits_conservative: float = 0.0   # Fano at that limit; use this for H4
    per_item: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d.pop("per_item", None)
        return d


class MatchProbe:
    """Rank candidate propositions against a message by TF-IDF cosine.

    Appropriate here because Experiment 2's restricted slot carries strings the
    defender chose from a known alphabet, so the adversary's task really is to
    match the message against that alphabet. It is *not* appropriate for
    detecting paraphrase in free model text -- that is what the entailment
    detector in `petal/detector.py` is for, and the limitation is stated in the
    Experiment 2 analysis.
    """

    def __init__(self, candidates: Sequence[str]):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.candidates = list(candidates)
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                   sublinear_tf=True, min_df=1)
        self._C = self.vec.fit_transform(self.candidates)
        # row-normalised already by TfidfVectorizer, so a dot product is cosine

    @property
    def k(self) -> int:
        return len(self.candidates)

    def rank(self, text: str) -> list[int]:
        if not (text or "").strip():
            return list(range(self.k))        # no information: arbitrary order
        q = self.vec.transform([text])
        sims = (self._C @ q.T).toarray().ravel()
        return list(np.argsort(-sims))

    def top1(self, text: str) -> int:
        return self.rank(text)[0]

    def evaluate(self, texts: Sequence[str], truth_idx: Sequence[int], *,
                 hop: int = 0, schedule: str = "") -> ProbeResult:
        if len(texts) != len(truth_idx):
            raise ValueError("texts and truth_idx differ in length")
        per = []
        correct = 0
        for t, gi in zip(texts, truth_idx):
            # A message with nothing in the slot carries no signal; counting a
            # lucky tie-break as a hit would understate the decay.
            if not (t or "").strip():
                pred = -1
                hit = False
            else:
                pred = self.top1(t)
                hit = (pred == gi)
            correct += int(hit)
            per.append({"pred": pred, "truth": int(gi), "hit": hit})
        n = max(1, len(texts))
        n_err = len(texts) - correct
        e = 1.0 - correct / n
        e_hi = error_upper_ci(n_err, len(texts))
        return ProbeResult(hop=hop, schedule=schedule, n=len(texts), k=self.k,
                           top1_correct=correct, error_rate=e,
                           mi_lower_bits=fano_mi_lower(e, self.k),
                           mi_at_chance_bits=fano_mi_lower(chance_error(self.k), self.k),
                           error_rate_ci_hi=e_hi,
                           mi_lower_bits_conservative=fano_mi_lower(e_hi, self.k),
                           per_item=per)


# ------------------------------------------------- the plan's logreg variant
def logreg_probe_cv(texts: Sequence[str], labels: Sequence[str], *,
                    seed: int = 0) -> dict[str, Any]:
    """Leave-one-out logistic regression over coarse labels.

    This is the plan's probe. It is reported as a secondary because with 20
    texts per hop it is thin even over four classes; it is here so the
    comparison the plan asks for can be made rather than asserted.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import LeaveOneOut
    from sklearn.pipeline import make_pipeline

    y = np.asarray(list(labels))
    X = list(texts)
    classes = sorted(set(y.tolist()))
    k = len(classes)
    if k < 2 or len(X) < 4:
        return {"n": len(X), "k": k, "error_rate": float("nan"),
                "mi_lower_bits": float("nan"), "note": "too few samples or classes"}

    correct = 0
    for tr, te in LeaveOneOut().split(X):
        y_tr = y[tr]
        if len(set(y_tr.tolist())) < 2:
            continue
        pipe = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1),
            LogisticRegression(max_iter=2000, random_state=seed))
        pipe.fit([X[i] for i in tr], y_tr)
        correct += int(pipe.predict([X[te[0]]])[0] == y[te[0]])
    n = len(X)
    e = 1.0 - correct / n
    return {"n": n, "k": k, "classes": classes, "correct": correct,
            "error_rate": e, "mi_lower_bits": fano_mi_lower(e, k),
            "mi_at_chance_bits": fano_mi_lower(chance_error(k), k)}
