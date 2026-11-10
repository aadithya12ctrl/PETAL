"""Fold typographic characters to ASCII before any surface-form matching.

Why, and why it is length-preserving
------------------------------------
Models do not write the ASCII the case files were authored in. Measured on the
first paid calls, gpt-oss-20b renders the file reference "TC-SCH-1050" with
U+2011 NON-BREAKING HYPHEN and apostrophes as U+2019. Two separate pieces of
this codebase match authored ASCII patterns against model text, and both were
silently wrong:

* the **rubric and option scorers**, where a typographic hyphen cost a correct
  answer its 0.10 reference item -- a scorer grading the tokeniser rather than
  the model;
* the **lexical gate**, shared by the leak detector and the petal's gap
  scanner, where a non-breaking space *inside* a multi-word surface form makes
  the form unfindable. "renal\\u00a0unit" does not match "renal unit".

The second is the worse of the two, and in the worse direction. Most watched
forms here are multi-word -- "renal unit", "psychiatric day programme",
"National Referral Mechanism" -- so a single U+00A0 turns a real leak into a
clean verdict, and turns a span the petal should have masked into one it leaves
alone. A false negative in a leak detector does not announce itself.

`FOLD` is therefore strictly **one character to one character**. The gap
scanner masks spans by character offset into the original draft, so a fold that
changed length would silently shift every offset after it and mask the wrong
text. Anything needing a length-changing rewrite (ellipsis to three dots,
whitespace runs to one space) belongs in the caller, where offsets do not
matter -- see `scenarios.schema._norm`.
"""
from __future__ import annotations

#: one character to one character, always. Do not add an entry whose value is
#: not exactly one character long: `fold` is relied on to preserve offsets.
FOLD = {
    # dashes and minus
    0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-",
    0x2015: "-", 0x2212: "-",
    # quotes
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'", 0x2032: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x201F: '"', 0x2033: '"',
    # spaces that are not a space
    0x00A0: " ", 0x1680: " ", 0x2000: " ", 0x2001: " ", 0x2002: " ",
    0x2003: " ", 0x2004: " ", 0x2005: " ", 0x2006: " ", 0x2007: " ",
    0x2008: " ", 0x2009: " ", 0x200A: " ", 0x200B: " ", 0x202F: " ",
    0x205F: " ", 0x3000: " ", 0xFEFF: " ",
}

assert all(len(v) == 1 for v in FOLD.values()), "FOLD must preserve length"


def fold(text: str) -> str:
    """ASCII-fold punctuation and spacing. len(fold(t)) == len(t), always."""
    return (text or "").translate(FOLD)
