"""Gap detection and the two filler mechanisms (petal and matched placebo).

Definition 2 of PETAL_v2 calls a gap "a generation position where sampled
continuations assert S with probability above a threshold tau_g". Sampling
continuations at every position costs one call per position, which the paper-v1
budget cannot carry, so this module scores *spans of an already-drafted relay
message* instead: the draft is the model's own continuation, and a span that
asserts S is a position where asserting S is what the model in fact does.

That makes gap detection a scoring problem over spans, with the scorer swappable:

    LexicalScorer   surface forms of S, word-boundary matched. Free, and the
                    conservative choice: it fires only on explicit mention.
    NliScorer       wired in phase 4; returns a real probability, so tau_g
                    becomes meaningful rather than a 0/1 threshold.

The petal then regenerates the flagged spans from the permitted context alone
(PETAL_v2 section 4.2.3a: f ~ p_theta(. | C \\ S)), and the placebo fills the same
spans with permitted but irrelevant text of matched length, which is what makes
B6 a control for "does merely occupying the slot change anything".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .textnorm import fold

MARKER = "[[FILL %d]]"
MARKER_RE = re.compile(r"\[\[\s*FILL\s*(\d+)\s*\]\]")

# Split on sentence enders and newlines, keeping offsets. Bullet lists and
# single-line relay messages are common, so newlines are boundaries too.
_SPLIT_RE = re.compile(r"(?<=[.!?;:])\s+|\n+")


@dataclass
class Span:
    start: int
    end: int
    text: str
    score: float = 0.0

    @property
    def is_gap(self) -> bool:
        return self.score > 0.0


def split_spans(text: str, min_chars: int = 12) -> list[Span]:
    """Sentence-ish spans with character offsets into `text`."""
    spans: list[Span] = []
    pos = 0
    for piece in _SPLIT_RE.split(text or ""):
        if piece is None:
            continue
        idx = text.find(piece, pos)
        if idx < 0:
            continue
        pos = idx + len(piece)
        if len(piece.strip()) >= min_chars:
            spans.append(Span(idx, idx + len(piece), piece))
    return spans


class SpanScorer(Protocol):
    name: str

    def __call__(self, span_text: str) -> float:
        ...


class LexicalScorer:
    """1.0 if any surface form of S appears, else 0.0.

    Conservative by design: it cannot fire on a paraphrase we did not anticipate,
    so gaps it finds are real and gaps it misses are the reason phase 4 adds an
    entailment scorer on top.
    """
    name = "lexical"

    def __init__(self, surface_forms: list[str]):
        # Both the forms and the text are ASCII-folded, so a watched form
        # written with a non-breaking space or a typographic hyphen still
        # matches. `fold` is length-preserving, which matters here: `scan`
        # masks gaps by character offset into the *unfolded* draft.
        forms = sorted({fold(f) for f in surface_forms if f.strip()},
                       key=len, reverse=True)
        self.forms = forms
        self._re = (re.compile(r"\b(?:" + "|".join(re.escape(f) for f in forms) + r")\b",
                               re.I) if forms else None)

    def __call__(self, span_text: str) -> float:
        if not self._re:
            return 0.0
        return 1.0 if self._re.search(fold(span_text or "")) else 0.0

    def hits(self, text: str) -> list[str]:
        if not self._re:
            return []
        return sorted({m.group(0) for m in self._re.finditer(fold(text or ""))})


class CachedNliSpanScorer:
    """Entailment-backed gap scoring, from a precomputed score cache.

    Why this exists
    ---------------
    The petal found its gaps with `LexicalScorer` while leaks were *scored* by
    the entailment cascade. Those are not the same detector, and the asymmetry
    runs the wrong way: a paraphrase the lexical gate has no form for passes
    through the petal unmasked, and is then counted as a petal failure. The
    petal would be charged for leaks it was never shown.

    Scoring with the same signal that grades it removes that. It cannot run
    in-process here (the entailment model does not fit in this machine's
    memory), so it reads scores produced out of band by `scripts/nli_score.py`,
    keyed exactly as `detector.pair_key` keys them.

    A span with no cached score is **not** silently treated as clean: it is
    counted in `missing`, and the runner refuses to report a petal arm built on
    a scan with misses. A silent miss is the same failure as the lexical gate,
    only harder to see.
    """
    name = "nli"

    def __init__(self, cached, hypothesis: str):
        self.cached = cached
        self.hypothesis = hypothesis
        self.missing: list[str] = []

    def __call__(self, span_text: str) -> float:
        p = self.cached.score(span_text, self.hypothesis)
        if p is None or p < 0.0:
            self.missing.append(span_text)
            return 0.0
        return float(p)


class MaxSpanScorer:
    """max over several scorers. Lexical OR entailment, whichever fires."""

    def __init__(self, *scorers, name: str = "lexical+nli"):
        self.scorers = [s for s in scorers if s is not None]
        self.name = name

    def __call__(self, span_text: str) -> float:
        return max([float(s(span_text)) for s in self.scorers] or [0.0])

    @property
    def missing(self) -> list[str]:
        out: list[str] = []
        for s in self.scorers:
            out.extend(getattr(s, "missing", []))
        return out

    def hits(self, text: str) -> list[str]:
        for s in self.scorers:
            if hasattr(s, "hits"):
                return s.hits(text)
        return []


@dataclass
class GapScan:
    spans: list[Span]
    gaps: list[Span]
    scorer: str
    tau: float
    n_missing_scores: int = 0

    @property
    def n_gaps(self) -> int:
        return len(self.gaps)

    @property
    def gap_chars(self) -> int:
        return sum(g.end - g.start for g in self.gaps)

    def to_dict(self) -> dict:
        return {"scorer": self.scorer, "tau": self.tau, "n_spans": len(self.spans),
                "n_gaps": self.n_gaps, "gap_chars": self.gap_chars,
                "n_missing_scores": self.n_missing_scores,
                "gaps": [{"start": g.start, "end": g.end, "score": round(g.score, 4),
                          "text": g.text} for g in self.gaps]}


def scan(text: str, scorer: SpanScorer, tau: float) -> GapScan:
    before = len(getattr(scorer, "missing", []))
    spans = split_spans(text)
    for s in spans:
        s.score = float(scorer(s.text))
    gaps = [s for s in spans if s.score >= tau]
    missed = len(getattr(scorer, "missing", [])) - before
    return GapScan(spans=spans, gaps=gaps, scorer=getattr(scorer, "name", "?"),
                   tau=tau, n_missing_scores=max(0, missed))


# --------------------------------------------------------------------- masking
def mask(text: str, gaps: list[Span]) -> str:
    """Replace each gap with a numbered marker, left to right."""
    out: list[str] = []
    pos = 0
    for k, g in enumerate(sorted(gaps, key=lambda s: s.start), start=1):
        out.append(text[pos:g.start])
        out.append(MARKER % k)
        pos = g.end
    out.append(text[pos:])
    return "".join(out)


def strip_unfilled_markers(text: str) -> tuple[str, int]:
    """Drop any markers the filler left behind. Returns (text, n_left)."""
    n = len(MARKER_RE.findall(text or ""))
    if not n:
        return text or "", 0
    cleaned = MARKER_RE.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), n


# -------------------------------------------------------------------- placebo
def placebo_fill(text: str, gaps: list[Span], pool: list[str], seed_key: str) -> str:
    """Fill each gap with permitted-but-irrelevant text of matched length.

    Deterministic in `seed_key`, so the placebo arm is reproducible and is
    matched to the petal arm span by span: same positions, same approximate
    length, content unrelated to the gap. Any difference between B6 and the petal
    arm is therefore attributable to *what* fills the slot, not to the fact that
    something does.
    """
    import hashlib

    if not gaps or not pool:
        return text
    out: list[str] = []
    pos = 0
    for k, g in enumerate(sorted(gaps, key=lambda s: s.start), start=1):
        target = g.end - g.start
        h = int(hashlib.sha256(("%s|%d" % (seed_key, k)).encode()).hexdigest()[:8], 16)
        buf: list[str] = []
        n = 0
        j = 0
        while n < target and j < len(pool) * 2:
            piece = pool[(h + j) % len(pool)]
            buf.append(piece)
            n += len(piece) + 1
            j += 1
        filler = " ".join(buf)
        if len(filler) > target + 20:            # trim on a word boundary
            cut = filler.rfind(" ", 0, target)
            filler = (filler[:cut] if cut > 0 else filler[:target]).rstrip(" ,;") + "."
        out.append(text[pos:g.start])
        out.append(filler)
        pos = g.end
    out.append(text[pos:])
    return "".join(out)
