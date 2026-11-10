"""The stochastic abstraction ladder, and Theorem T3's contraction coefficient.

PETAL_v2 §4.3 replaces v1's unproven "deterministic coarsening gives geometric
decay" with a ladder whose rungs are k-ary randomised response. The reason is
errata item 5: data processing says information cannot increase, but a
non-constant *deterministic* map has input-independent contraction coefficient
**1**, so a deterministic ladder gives step-wise decay that hits zero at the
"dropped" rung, not geometric decay. Randomising each rung buys a strict
contraction that can be computed in closed form.

For a k-ary symmetric channel that keeps the true symbol with probability p and
spreads 1 - p uniformly over the other k - 1:

    eta_r   = | p_r - (1 - p_r) / (k_r - 1) |          (Dobrushin / TV coefficient)
    eps_r   = ln( p_r (k_r - 1) / (1 - p_r) )          (local DP level of the rung)
    I(S; M_t) <= ( prod_{r<=t} eta_r ) * I(S; M_0)     (Theorem T3)

The alphabets here are **derived from the testbed rather than assumed**, which
matters: eta depends on k, so quoting a contraction factor against an invented k
would be quoting a bound the experiment never runs under. Rung 0's alphabet is
every restricted condition of the same kind in the testbed, rung 1's is the
distinct clinical/financial areas within that kind, rung 2's is the kinds
themselves, and rung 3 is the binary "an annex applies".

The final rung is "dropped", which carries nothing. It is kept out of the eta
product for the same reason the paper quotes 0.039 "before the final dropped
rung": a coefficient of 0 would make the product trivially 0 and hide whether the
randomised rungs are doing any work.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from .scenarios.templates import ABSTRACTION_FORMS, DOMAINS

# ---------------------------------------------------------------- rung 1 values
# One short phrase per restricted category: the clinical, financial or legal
# *area* it belongs to. This is the second rung of the ladder -- coarser than the
# condition, finer than its kind. Authored here rather than in templates.py so
# the ladder is self-contained and the testbed stays usable without it.
AREA_OF: dict[str, str] = {
    # clinic_scheduling
    "dialysis": "a kidney condition",
    "chemo": "a cancer condition",
    "oat": "a substance-use condition",
    "psych_day": "a mental health condition",
    "fertility": "a reproductive health matter",
    "dot_tb": "an infectious disease",
    # insurance_claims
    "psych_inpatient": "a mental health condition",
    "alcohol_detox": "a substance-use condition",
    "hiv": "an infectious disease",
    "termination": "a reproductive health matter",
    "self_harm": "a mental health condition",
    "genetic": "an inherited risk factor",
    # hr_leave
    "partner_terminal": "a bereavement or caring matter",
    "pregnancy": "a reproductive health matter",
    "cancer_tx": "a cancer condition",
    "psych_admission": "a mental health condition",
    "gender_care": "a gender-related health matter",
    "domestic_abuse": "a personal safety matter",
    # legal_intake
    "undocumented": "an immigration matter",
    "asylum_torture": "an immigration matter",
    "criminal_record": "a criminal justice matter",
    "hiv_status": "an infectious disease",
    "dv_order": "a personal safety matter",
    "injecting_use": "a substance-use condition",
    "mental_capacity": "a mental health condition",
    # loan_prescreen
    "debt_counselling": "a problem-debt matter",
    "gambling": "a substance-use condition",
    "bankruptcy": "an insolvency matter",
    "benefit_sanction": "a welfare income matter",
    "carer_illness": "a bereavement or caring matter",
    "coerced_debt": "a personal safety matter",
    # travel_accessibility
    "oxygen": "a respiratory condition",
    "ptsd_dog": "a mental health condition",
    "dialysis_travel": "a kidney condition",
    "epilepsy": "a neurological condition",
    "pregnancy_travel": "a reproductive health matter",
    "stoma": "a digestive condition",
}

# The second condition per bar-pair (petal/scenarios/confusable.py). Several
# map to an area an existing key already uses: two categories that bar the same
# options and coarsen to the same area are indistinguishable at rung 1, which is
# the ladder working rather than a collision.
from .scenarios.confusable import AREAS as _SIBLING_AREAS  # noqa: E402

AREA_OF.update(_SIBLING_AREAS)

PLACEHOLDER_TRUE = "a restricted annex applies to this file"
PLACEHOLDER_FALSE = "no restricted annex applies to this file"
DROPPED = ""


def all_categories() -> dict[str, dict[str, Any]]:
    """Every restricted category in the testbed, by key."""
    out: dict[str, dict[str, Any]] = {}
    for dom in DOMAINS.values():
        for cat in dom["categories"]:
            out[cat["key"]] = cat
    return out


def _missing_areas() -> list[str]:
    return sorted(set(all_categories()) - set(AREA_OF))


# --------------------------------------------------------------------- rungs
@dataclass
class Rung:
    """One rung: a coarsening, plus the k-ary randomised response over it."""
    name: str
    k: int                       # alphabet size at this rung
    p: float                     # probability the true (coarsened) symbol survives
    alphabet: list[str] = field(default_factory=list)

    @property
    def eta(self) -> float:
        """Dobrushin coefficient. 0 for a rung that transmits nothing."""
        if self.k <= 1:
            return 0.0
        return abs(self.p - (1.0 - self.p) / (self.k - 1))

    @property
    def epsilon(self) -> float:
        """Local differential privacy level of this rung."""
        if self.k <= 1:
            return 0.0
        if self.p >= 1.0:
            return float("inf")
        if self.p <= 0.0:
            return 0.0
        return math.log(self.p * (self.k - 1) / (1.0 - self.p))

    def transmit(self, true_value: str, rng: random.Random) -> tuple[str, bool]:
        """k-ary randomised response. Returns (emitted, was_truthful)."""
        if self.k <= 1 or not self.alphabet:
            return DROPPED, False
        if self.p >= 1.0 or rng.random() < self.p:
            return true_value, True
        others = [v for v in self.alphabet if v != true_value]
        if not others:
            return true_value, True
        return rng.choice(others), False


@dataclass
class Ladder:
    rungs: list[Rung]

    @property
    def etas(self) -> list[float]:
        return [r.eta for r in self.rungs]

    def eta_product(self, upto: int | None = None, include_dropped: bool = False) -> float:
        """Product of eta over the first `upto` rungs.

        `include_dropped` is off by default: a rung that transmits nothing has
        eta 0 and would drive the product to 0 regardless of the randomised
        rungs, which is exactly the thing we want to be able to see.
        """
        rs = self.rungs[:upto] if upto is not None else self.rungs
        vals = [r.eta for r in rs if include_dropped or r.k > 1]
        out = 1.0
        for v in vals:
            out *= v
        return out

    def bound_at_hop(self, hop: int) -> float:
        """The T3 factor applying to a message emitted at hop `hop` (1-based).

        Hop 1 carries rung 0 having passed through rung 0's channel, so the
        factor after h hops is the product of the first h rungs' coefficients.
        """
        return self.eta_product(upto=max(0, hop), include_dropped=True)

    def rung_for_hop(self, hop: int) -> Rung:
        """Hop 1 -> rung 0, and the last rung repeats once the ladder runs out."""
        return self.rungs[min(max(0, hop - 1), len(self.rungs) - 1)]

    def summary(self) -> list[dict[str, Any]]:
        out = []
        cum = 1.0
        for i, r in enumerate(self.rungs):
            cum *= r.eta
            out.append({"rung": i, "name": r.name, "k": r.k, "p": r.p,
                        "eta": round(r.eta, 4),
                        "epsilon": (None if math.isinf(r.epsilon)
                                    else round(r.epsilon, 3)),
                        "cumulative_eta": round(cum, 6)})
        return out


# -------------------------------------------------------- building the ladder
def build_ladder(kind: str, *, keep_probs: tuple[float, ...] = (0.8, 0.7, 0.6, 0.6),
                 strict: bool = True) -> Ladder:
    """The ladder for restricted content of a given kind.

    Alphabet sizes come from the testbed, so eta is the coefficient the
    experiment actually runs under rather than a quoted example.
    """
    if strict:
        miss = _missing_areas()
        if miss:
            raise AssertionError("no area defined for categories: %s" % miss)

    cats = all_categories()
    same_kind = [c for c in cats.values() if c["kind"] == kind]
    if not same_kind:
        raise ValueError("no categories of kind %r" % kind)

    exact = sorted({c["proposition"].format(name="The subject") for c in same_kind})
    areas = sorted({AREA_OF[c["key"]] for c in same_kind})
    kinds = sorted({ABSTRACTION_FORMS[k][0] for k in ABSTRACTION_FORMS})

    p0, p1, p2, p3 = keep_probs
    return Ladder([
        Rung("exact", len(exact), p0, exact),
        Rung("area", len(areas), p1, areas),
        Rung("kind", len(kinds), p2, kinds),
        Rung("placeholder", 2, p3, [PLACEHOLDER_TRUE, PLACEHOLDER_FALSE]),
        Rung("dropped", 1, 1.0, []),
    ])


def true_value_at(cat: dict[str, Any], rung: Rung) -> str:
    """The honest symbol for this category at this rung."""
    if rung.name == "exact":
        return cat["proposition"].format(name="The subject")
    if rung.name == "area":
        return AREA_OF[cat["key"]]
    if rung.name == "kind":
        return ABSTRACTION_FORMS[cat["kind"]][0]
    if rung.name == "placeholder":
        return PLACEHOLDER_TRUE
    return DROPPED


def coarsen(prev_value: str, rung: Rung, kind: str) -> str:
    """Map the previous rung's symbol to this rung's, *from the symbol itself*.

    This is the whole reason Theorem T3's product bound applies. T3 composes
    contraction coefficients along S -> M_1 -> M_2 -> ..., which requires each
    hop's content to be derived from the previous hop's content. Re-coarsening
    the original S at every hop would make the hops conditionally independent
    given S rather than a Markov chain, and then the only valid factor is the
    single rung's eta, not the product -- the bound the experiment is testing
    would not be the bound the experiment runs under.

    So when the randomised response at rung 0 emits the *wrong* condition, rung 1
    reports the area of that wrong condition. The error propagates, which is
    exactly what makes the composition contract.
    """
    if not (prev_value or "").strip():
        return DROPPED
    if rung.name == "exact":
        return prev_value
    if rung.name == "area":
        return _PROP_TO_AREA.get(prev_value, prev_value)
    if rung.name == "kind":
        # within a kind-specific ladder every area maps to the same kind symbol
        return ABSTRACTION_FORMS[kind][0]
    if rung.name == "placeholder":
        return PLACEHOLDER_TRUE
    return DROPPED


#: name-generic proposition -> area, built once from the testbed
_PROP_TO_AREA: dict[str, str] = {
    cat["proposition"].format(name="The subject"): AREA_OF[key]
    for key, cat in all_categories().items() if key in AREA_OF
}


# ------------------------------------------------------------------ schedules
SCHEDULES = ["none", "deterministic", "stochastic", "random_dropout"]


@dataclass
class Emission:
    hop: int
    schedule: str
    rung: str
    k: int
    p: float
    value: str
    truthful: bool
    eta_bound: float

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def emit(schedule: str, ladder: Ladder, cat: dict[str, Any], hop: int,
         rng: random.Random, prev_value: str | None = None,
         kind: str = "medical") -> Emission:
    """What the relay's S slot carries at `hop`, given what it carried before.

    * `none`            the exact value, every hop. No decay; the reference arm.
    * `deterministic`   coarsen one rung per hop, transmitted truthfully. Decay
                        happens only by reaching "dropped", which is errata item
                        5's point: a non-constant deterministic map has
                        input-independent contraction coefficient 1.
    * `stochastic`      coarsen one rung per hop, then k-ary randomised response.
    * `random_dropout`  the matched control. It keeps the previous value
                        unchanged with the same probability p_r that the
                        stochastic arm keeps its coarsened one, and otherwise
                        drops the slot for good. The two arms therefore agree on
                        how often the slot stays truthful and differ only in
                        whether the alternative is a vaguer statement or
                        silence, which is what isolates abstraction from
                        omission.
    """
    if schedule not in SCHEDULES:
        raise ValueError("unknown schedule %r" % schedule)
    rung = ladder.rung_for_hop(hop)
    exact_rung = ladder.rungs[0]
    exact = true_value_at(cat, exact_rung)
    prev = exact if prev_value is None else prev_value

    if schedule == "none":
        return Emission(hop, schedule, "exact", exact_rung.k, 1.0, exact, True, 1.0)

    if schedule == "deterministic":
        v = coarsen(prev, rung, kind)
        return Emission(hop, schedule, rung.name, rung.k, 1.0, v,
                        v == true_value_at(cat, rung),
                        0.0 if rung.k <= 1 else 1.0)

    if schedule == "stochastic":
        honest = coarsen(prev, rung, kind)
        v, kept = rung.transmit(honest, rng)
        return Emission(hop, schedule, rung.name, rung.k, rung.p, v,
                        kept and v == true_value_at(cat, rung),
                        ladder.bound_at_hop(hop))

    keep = rung.p if rung.k > 1 else 0.0
    if prev and rng.random() < keep:
        return Emission(hop, schedule, "kept", exact_rung.k, keep, prev,
                        prev == exact, 1.0)
    return Emission(hop, schedule, "silent", 1, keep, DROPPED, False, 1.0)


def category_for(proposition_generic: str,
                 kind: str | None = None) -> dict[str, Any] | None:
    """Recover the category a scenario's restricted content came from.

    Scenarios store the proposition, not the category key, so the ladder matches
    on the name-generic proposition -- the same string the detector uses as its
    hypothesis, so the two cannot drift apart.

    Three propositions are shared by two categories each, because the same
    restricted fact appears in two domains: `hiv`/`hiv_status`,
    `dialysis`/`dialysis_travel` and `pregnancy`/`pregnancy_travel`. The
    ambiguity is benign for the ladder and is checked to stay that way by
    `shared_proposition_groups`: each pair agrees on kind and on area, so every
    rung coarsens them identically. The first match is returned deterministically
    because `all_categories` iterates the domains in declaration order.
    """
    hits = [c for c in all_categories().values()
            if c["proposition"].format(name="The subject") == proposition_generic]
    if kind is not None:
        # prefer a category of the expected kind: the ladder's rung-2 alphabet is
        # kind-specific, so resolving to the wrong kind would emit a symbol the
        # rung does not contain
        same = [c for c in hits if c["kind"] == kind]
        if same:
            return same[0]
    return hits[0] if hits else None


def shared_proposition_groups() -> dict[str, list[str]]:
    """Propositions claimed by more than one category, with their keys."""
    groups: dict[str, list[str]] = {}
    for key, cat in all_categories().items():
        groups.setdefault(cat["proposition"].format(name="The subject"),
                          []).append(key)
    return {p: ks for p, ks in groups.items() if len(ks) > 1}


def watched_forms(ladder: Ladder, extra: list[str] | None = None) -> list[str]:
    """Every string the ladder might have put in the slot, at any rung.

    Needed because the slot has to be found and rewritten at each hop, and by
    hop 3 it no longer holds a surface form of S -- it holds the previous rung's
    coarsening.
    """
    out: list[str] = list(extra or [])
    for r in ladder.rungs:
        out.extend(r.alphabet)
    return [f for f in dict.fromkeys(out) if f.strip()]
