"""The paper's one figure: utility, assertion and disclosure per arm.

Three quantities on one axis pair, because the paper's whole argument is that
the second and third come apart:

* **utility** -- did the downstream agent do the task.
* **assertion** -- did the relay state S, by the validated cascade. This is what
  a privacy filter measures.
* **disclosure** -- what a reader actually learns, in bits. For the arms where
  the generator gives a closed form we use it; where it does not, the bar is
  absent rather than zero, because "not computed" and "zero" are the two things
  this paper most needs to keep apart.

Deliberately not a scatter of utility against assertion: that is the plot that
makes constraint_only look like a free lunch, which is the reading the bits
column exists to refuse.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# Tokens, so light and dark exports stay one system.
INK = "#1a1a1a"
MUTED = "#6b6b6b"
GRID = "#d9d9d9"
C_UTIL = "#2f6f9f"     # blue   -- utility
C_ASSERT = "#c25a3c"   # orange -- assertion, the thing defences target
C_BITS = "#7a5ba6"     # purple -- disclosure in bits

ARMS = [
    ("full", "Full"),
    ("constraint_only", "Constraint\nonly"),
    ("decision_only", "Decision\nonly"),
    ("petal_text", "Petal"),
    ("b1_privacy", "Privacy\ninstruction"),
    ("b4_restriction", "Restriction\naware"),
    ("swap", "Swap"),
    ("drop", "Drop"),
]

# Closed-form disclosure, generator-aware, in bits of H(S) = 2.585.
# Only the arms whose content the generator pins down; None = not computed.
BITS = {
    "full": 2.585,             # relays the annex: all of H(S)
    "constraint_only": 1.585,  # I(constraint; S), Table 6
    "decision_only": 1.585,    # I(answer; S) -- the answer alone
    "drop": 0.0,
    "swap": 0.0,
    "petal_text": None,
    "b1_privacy": None,
    "b4_restriction": None,
}
H_S = 2.585


def load(path: str, use_type: str):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return d["use_types"][use_type]


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "results/exp1_with_petal.json"
    p = load(src, "decision")

    labels, util, assertion, bits = [], [], [], []
    for key, label in ARMS:
        if key not in p["leak"]:
            continue
        u = p["utility"].get(key)
        u = u["point"] if isinstance(u, dict) else u
        labels.append(label)
        util.append(u)
        assertion.append(p["leak"][key]["m1"])
        b = BITS.get(key)
        bits.append(None if b is None else b / H_S)

    n = len(labels)
    x = range(n)
    w = 0.26

    fig, ax = plt.subplots(figsize=(9.2, 4.0))
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)

    ax.bar([i - w for i in x], util, w * 0.92, color=C_UTIL, zorder=3)
    ax.bar(list(x), assertion, w * 0.92, color=C_ASSERT, zorder=3)

    drawn = [(i, v) for i, v in enumerate(bits) if v is not None]
    ax.bar([i + w for i, _ in drawn], [v for _, v in drawn], w * 0.92,
           color=C_BITS, zorder=3)

    # A measured zero and a quantity we did not compute must not look alike.
    # Zero gets a visible floor tick in its own colour; not-computed gets a
    # label and no mark at all.
    def zero_tick(pos, colour):
        ax.plot([pos - w * 0.46, pos + w * 0.46], [0.004, 0.004],
                color=colour, linewidth=2.2, solid_capstyle="butt", zorder=4)

    for i, v in enumerate(assertion):
        if v == 0:
            zero_tick(i, C_ASSERT)
    for i, v in enumerate(bits):
        if v is None:
            ax.text(i + w, 0.02, "not\ncomputed", ha="center", va="bottom",
                    fontsize=6.8, color=MUTED, linespacing=0.95)
        elif v == 0:
            zero_tick(i + w, C_BITS)

    # The one comparison the figure exists to make.
    ci = next((i for i, (k, _) in enumerate(ARMS) if k == "constraint_only"), None)
    if ci is not None and ci < n:
        ax.annotate("asserts $S$ at 0.03,\ndiscloses 61% of $H(S)$",
                    xy=(ci + w, bits[ci]), xytext=(ci - 0.30, 0.90),
                    fontsize=8.5, color=INK, ha="left",
                    arrowprops=dict(arrowstyle="-", color=MUTED, linewidth=0.9,
                                    shrinkA=2, shrinkB=3))

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=8.5, color=INK)
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_ylabel("rate, or fraction of $H(S)$", fontsize=9, color=INK)
    ax.tick_params(colors=MUTED, length=0, labelsize=8.5)

    ax.legend(handles=[Patch(color=C_UTIL, label="task utility"),
                       Patch(color=C_ASSERT, label="asserts $S$ (detector)"),
                       Patch(color=C_BITS,
                             label="discloses $S$ (bits, closed form)")],
              loc="upper right", frameon=False, fontsize=8.5, ncol=1)

    ax.set_title("Decision tasks: a defence can take assertion to zero and "
                 "leave disclosure untouched",
                 fontsize=10, color=INK, loc="left", pad=10)

    fig.tight_layout()
    out = Path("paper/fig_frontier.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    fig.savefig(out.with_suffix(".png"), dpi=200, bbox_inches="tight")
    print("-> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
