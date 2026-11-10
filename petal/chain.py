"""Experiment 2: the five-hop chain with an abstraction ladder on the S slot.

One run = one scenario under one schedule. At each hop the agent writes a
handover note; the defender then rewrites the note's restricted slot to the value
the schedule prescribes for that hop, and the rewritten note is what the next
agent sees. So the agent at hop t sees content at rung t-2 and its output is
coarsened to rung t-1 -- monotone coarsening along the chain.

The slot has to be *found* before it can be rewritten, and by hop 3 it no longer
holds a surface form of S: it holds the previous rung's coarsening. The scan
therefore watches every string any rung could have emitted, which is what
`ladder.watched_forms` supplies.

Scope, stated because PETAL_v2 §4.3 insists on it: T3 bounds the slot. If an
agent re-derives S from something else in the note, that is outside the
guarantee, and it shows up as the probe beating the bound -- which is H4's kill
condition and a finding rather than a bug.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict
from typing import Any

from . import gaps as G
from . import prompts as P
from .client import LLMClient
from .ladder import Emission, Ladder, category_for, emit, watched_forms
from .scenarios.schema import Scenario
from .scenarios.scorer import score


@dataclass
class ChainHop:
    hop: int
    raw: str                 # what the agent wrote
    sent: str                # what the next agent sees, after the ladder
    emission: dict[str, Any]
    n_slots_found: int
    cost_usd: float
    cached: bool


@dataclass
class ChainRun:
    scenario_id: str
    use_type: str
    domain: str
    schedule: str
    model_role: str
    seed: int
    category: str
    hops: list[ChainHop] = field(default_factory=list)
    output: str = ""
    utility: float = 0.0
    calls: int = 0
    paid_calls: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rewrite_slot(text: str, forms: list[str], value: str) -> tuple[str, int]:
    """Replace the restricted slot with `value`; drop any further occurrences.

    Returns (text, number of spans found). If nothing matched and `value` is
    non-empty, the slot is appended: the ladder is the defender's channel, and a
    hop that simply forgot to carry the note must not silently become a hop that
    transmitted nothing -- that would flatter the decay.
    """
    scorer = G.LexicalScorer(forms)
    scan = G.scan(text or "", scorer, 0.5)
    note = P.carried_note(value)
    if not scan.gaps:
        if note:
            return ((text or "").rstrip() + "\n" + note).strip(), 0
        return (text or "").strip(), 0
    out: list[str] = []
    pos = 0
    for i, g in enumerate(sorted(scan.gaps, key=lambda s: s.start)):
        out.append(text[pos:g.start])
        if i == 0 and note:
            out.append(note)
        pos = g.end
    out.append(text[pos:])
    joined = "".join(out)
    # tidy the holes left where later occurrences were removed
    return "\n".join(ln.rstrip() for ln in joined.splitlines()
                     if ln.strip()), len(scan.gaps)


def run_chain(client: LLMClient, sc: Scenario, schedule: str, ladder: Ladder, *,
              model_role: str = "agent_a", seed: int | None = None,
              hops: int | None = None) -> ChainRun:
    cfg = client.cfg
    seed = cfg.seed if seed is None else seed
    hops = cfg.ladder_hops if hops is None else hops
    cat = category_for(sc.S.proposition_generic, kind=sc.S.kind)
    if cat is None:
        raise ValueError("no ladder category for %s" % sc.id)
    forms = watched_forms(ladder, list(sc.S.paraphrases))
    # the schedule is the only source of randomness, and it is seeded per run so
    # a rerun reproduces the same k-ary draws
    rng = random.Random("%s|%s|%s|%d" % (sc.id, schedule, model_role, seed))

    run = ChainRun(scenario_id=sc.id, use_type=sc.use_type, domain=sc.domain,
                   schedule=schedule, model_role=model_role, seed=seed,
                   category=cat["key"])
    tag = "exp2:%s:%s:%s:%d" % (sc.id, schedule, model_role, seed)

    incoming = ""
    prev_value: str | None = None      # the slot's previous symbol, for composition
    for h in range(1, hops + 1):
        msgs = (P.chain_planner_messages(sc, hops) if h == 1
                else P.chain_messages(sc, h, hops, incoming))
        r = client.chat(model_role, msgs, seed=seed, tag="%s:hop%d" % (tag, h))
        run.calls += 1
        run.paid_calls += 0 if r.cached else 1
        run.cost_usd += r.cost_usd

        if h == hops:
            run.output = r.text
            run.hops.append(ChainHop(hop=h, raw=r.text, sent=r.text,
                                     emission={}, n_slots_found=0,
                                     cost_usd=r.cost_usd, cached=r.cached))
            break

        em: Emission = emit(schedule, ladder, cat, h, rng,
                            prev_value=prev_value, kind=cat["kind"])
        prev_value = em.value
        sent, n = rewrite_slot(r.text, forms, em.value)
        run.hops.append(ChainHop(hop=h, raw=r.text, sent=sent,
                                 emission=em.to_dict(), n_slots_found=n,
                                 cost_usd=r.cost_usd, cached=r.cached))
        incoming = sent

    sr = score(sc, run.output)
    run.utility = sr.utility
    return run
