"""The eight arms of Experiment 1, and the three-hop runner that executes them.

Arms (PETAL_execution_plan.md section 4):

    full            S present, no defence                       -> U_full, q_0
    swap            S' in place of S                            -> Lambda = leak(full) - leak(swap)
    drop            no annex                                    -> U_drop, Phi_floor
    b1_privacy      S present + prompt-level privacy instruction
    b4_restriction  planner told to omit anything annex-derived  -> U_restr
    b6_placebo      same gaps as the petal, filled with matched irrelevant text
    petal_text      same gaps, regenerated from the permitted context alone
    constraint_only planner relays the operative constraint, not the reason
    decision_only   planner relays its annex-derived conclusion, not the annex

`tau_gap` is a threshold on the gap scorer's output. The lexical scorer returns
0 or 1, so any tau in (0, 1] behaves identically; once the entailment scorer is
supplied (`nli_cache`), tau is a real probability cut and the configured 0.15 is
deliberately far below the detector's own leak threshold of 0.75 -- the petal
should mask a span it only suspects, because masking a clean span costs a little
utility while missing a leaky one costs the whole defence.

The three relay-granularity arms
--------------------------------
`full`, `constraint_only` and `decision_only` form a gradient in *what* is
relayed rather than in how it is defended:

    full             the reason           "the patient has dialysis Tue/Thu AM"
    constraint_only  the constraint       "unavailable Tue/Thu mornings"
    decision_only    the conclusion       "book option B"

Only the middle one leaves the decision to the Worker while still carrying what
the Worker needs, which is the realistic form of using S without saying it. It
is also the one where inferential leakage and assertion leakage come apart
most sharply: the constraint asserts nothing about any condition, and under an
adversary who knows the scenario generator it nonetheless identifies S's
barred pair exactly. `petal.implied.analyse(..., observable="constraint")`
computes that exactly, as it does for the answer.

Why full, b6_placebo and petal_text share a planner call
--------------------------------------------------------
All three send the planner an identical prompt at an identical seed, so the
draft is the same object; the cache serves it once and the two defences are
applied to that same draft afterwards. This is not only cheaper, it is what makes
B6 a true matched placebo -- it fills the *same spans of the same text* as the
petal, so a difference between the arms is attributable to what fills the slot
rather than to the draft differing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

from . import gaps as G
from . import prompts as P
from .client import LLMClient, LLMResponse
from .config import Config
from .scenarios.schema import Scenario
from .scenarios.scorer import ScoreResult, score
from .scenarios.templates import STANDING_NOTICES

ARMS = ["full", "swap", "drop", "b1_privacy", "b4_restriction",
        "b6_placebo", "petal_text", "constraint_only", "decision_only"]

#: the four arms the plan replicates on a second seed
KEY_ARMS = ["full", "drop", "petal_text", "decision_only"]

#: arms whose planner prompt is identical to `full` (so the draft is shared)
SHARED_DRAFT_ARMS = {"full", "b6_placebo", "petal_text"}

ANNEX_OF = {"swap": "S_prime", "drop": "none"}


@dataclass
class Hop:
    role: str          # planner | fill | worker | reporter
    model: str
    provider: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    cached: bool
    text: str


@dataclass
class RunRecord:
    scenario_id: str
    domain: str
    use_type: str
    arm: str
    model_role: str
    seed: int
    # --- the relay, as the detector will see it ----------------------
    m1_draft: str = ""      # planner output before any defence
    m1: str = ""            # relay actually sent onward
    m2: str = ""            # worker handover
    output: str = ""        # reporter final output
    # --- defence bookkeeping -----------------------------------------
    gap_scan: dict[str, Any] = field(default_factory=dict)
    gap_scorer: str = ""        # "lexical" or "lexical+nli" -- see run_arm
    gap_scores_missing: int = 0
    n_gaps: int = 0
    markers_left: int = 0
    petal_residual_forms: list[str] = field(default_factory=list)
    # --- scoring ------------------------------------------------------
    utility: float = 0.0
    chosen: str | None = None
    found_final: bool = True
    rubric_hits: dict[str, float] = field(default_factory=dict)
    utility_nonentailing: float = 0.0
    # --- cost ---------------------------------------------------------
    hops: list[Hop] = field(default_factory=list)
    calls: int = 0
    paid_calls: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def add(self, role: str, r: LLMResponse) -> None:
        self.hops.append(Hop(role=role, model=r.model_served or r.model,
                             provider=r.provider, prompt_tokens=r.prompt_tokens,
                             completion_tokens=r.completion_tokens,
                             cost_usd=r.cost_usd, cached=r.cached, text=r.text))
        self.calls += 1
        if not r.cached:
            self.paid_calls += 1
        self.cost_usd += r.cost_usd


# ----------------------------------------------------------------- the runner
def make_gap_scorer(sc: Scenario, nli_cache=None):
    """The scorer the petal uses to find its gaps.

    With `nli_cache` (a `detector.CachedNliScorer`) this is max(lexical,
    entailment) -- the same signal the leak detector uses to grade the result.
    Without it, lexical only, which is a strictly weaker detector than the one
    that scores the arm: it will miss paraphrases, those paraphrases will
    survive into the relay, and the petal will be charged for them. A run made
    this way is reported as the **lexical-gap petal** and read as a lower bound
    on what the mechanism can do, never as the mechanism's performance.
    """
    lex = G.LexicalScorer(sc.S.paraphrases)
    if nli_cache is None:
        return lex
    hyp = sc.S.proposition_generic or sc.S.proposition
    return G.MaxSpanScorer(lex, G.CachedNliSpanScorer(nli_cache, hyp))


def run_arm(client: LLMClient, sc: Scenario, arm: str, *, model_role: str = "agent_a",
            seed: int | None = None, tau: float | None = None,
            nli_cache=None) -> RunRecord:
    if arm not in ARMS:
        raise ValueError("unknown arm %r" % arm)
    cfg: Config = client.cfg
    seed = cfg.seed if seed is None else seed
    tau = cfg.tau_gap if tau is None else tau
    rec = RunRecord(scenario_id=sc.id, domain=sc.domain, use_type=sc.use_type,
                    arm=arm, model_role=model_role, seed=seed)
    privacy = (arm == "b1_privacy")
    tag = "exp1:%s:%s:%s:%d" % (sc.id, arm, model_role, seed)

    # ---- hop 1: planner ------------------------------------------------
    annex = ANNEX_OF.get(arm, "S")
    msgs = P.planner_messages(sc, annex=annex, privacy=privacy,
                              relay_instruction=P.RELAY_INSTRUCTION.get(arm, ""))
    r1 = client.chat(model_role, msgs, seed=seed, tag=tag + ":planner")
    rec.add("planner", r1)
    rec.m1_draft = r1.text
    rec.m1 = r1.text

    # ---- defences applied to the draft ---------------------------------
    if arm in ("petal_text", "b6_placebo"):
        scorer = make_gap_scorer(sc, nli_cache)
        gs = G.scan(rec.m1_draft, scorer, tau)
        rec.gap_scan = gs.to_dict()
        rec.gap_scorer = gs.scorer
        rec.gap_scores_missing = gs.n_missing_scores
        rec.n_gaps = gs.n_gaps
        if gs.n_gaps:
            if arm == "petal_text":
                masked = G.mask(rec.m1_draft, gs.gaps)
                rf = client.chat(model_role,
                                 P.fill_messages(sc, masked, gs.n_gaps),
                                 seed=seed, tag=tag + ":fill")
                rec.add("fill", rf)
                filled, left = G.strip_unfilled_markers(rf.text or masked)
                rec.markers_left = left
                rec.m1 = filled
                rec.petal_residual_forms = (scorer.hits(filled)
                                            if hasattr(scorer, "hits") else [])
            else:
                rec.m1 = G.placebo_fill(rec.m1_draft, gs.gaps, STANDING_NOTICES,
                                        seed_key="%s|%s|%d" % (sc.id, model_role, seed))

    # ---- hop 2: worker --------------------------------------------------
    r2 = client.chat(model_role, P.worker_messages(sc, rec.m1, privacy=privacy),
                     seed=seed, tag=tag + ":worker")
    rec.add("worker", r2)
    rec.m2 = r2.text

    # ---- hop 3: reporter ------------------------------------------------
    r3 = client.chat(model_role, P.reporter_messages(sc, rec.m2, privacy=privacy),
                     seed=seed, tag=tag + ":reporter")
    rec.add("reporter", r3)
    rec.output = r3.text

    # ---- score ----------------------------------------------------------
    sr: ScoreResult = score(sc, rec.output, under_swap=(arm == "swap"))
    rec.utility = sr.utility
    rec.chosen = sr.chosen
    rec.found_final = sr.found_final
    rec.rubric_hits = sr.rubric_hits
    rec.utility_nonentailing = sr.utility_nonentailing
    return rec


def relay_texts(rec: RunRecord) -> dict[str, str]:
    """The channels the detector scores: both relay messages and the output.

    `m1_draft` is included separately because it is the *pre-defence* relay: the
    difference between leak(m1_draft) and leak(m1) is the petal's effect on the
    channel, before any downstream dilution.
    """
    return {"m1_draft": rec.m1_draft, "m1": rec.m1, "m2": rec.m2, "output": rec.output}


def write_runs(path, records: list[RunRecord]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")


def read_runs(path) -> list[dict[str, Any]]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
