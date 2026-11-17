"""Experiment 2 in one panel: measured decay against the contraction bound.

Two things have to be visible at once, because the section's whole argument is
the difference between them:

* the **in-slot** curves, which satisfy T3 by construction -- our code applies
  the randomised response, so this is a check on the implementation; and
* the **no-slot** curves, which are the part about the agents, and which sit at
  zero for every schedule.

The `none` schedule carries the exact value every hop, so it is the positive
control: in-slot it is the only curve with information in it, and removing one
line takes it to zero. That contrast is what licenses reading the no-slot zeros
as absence rather than as a blind probe, so both are drawn on the same axis.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK = "#1a1a1a"
MUTED = "#6b6b6b"
GRID = "#d9d9d9"

# One hue per schedule, fixed order, never cycled.
COLOUR = {
    "none": "#2f6f9f",            # blue   -- the control
    "deterministic": "#c25a3c",   # orange
    "stochastic": "#7a5ba6",      # purple -- the one with a decaying bound
    "random_dropout": "#3f7d5a",  # green
}
LABEL = {
    "none": "none (control)",
    "deterministic": "deterministic",
    "stochastic": "stochastic",
    "random_dropout": "random dropout",
}
ORDER = ["none", "deterministic", "stochastic", "random_dropout"]
# Three of the four schedules sit at exactly zero from hop 2 on, so colour alone
# cannot separate them -- the last line drawn would simply hide the rest. Marker
# shape carries the identity where the lines coincide.
MARKER = {"none": "o", "deterministic": "s", "stochastic": "^",
          "random_dropout": "D"}


def main() -> int:
    rows = json.loads(Path("results/exp2_probe_rows.json").read_text(encoding="utf-8"))
    # The file holds the in-slot block then the no-slot block, same shape.
    half = len(rows) // 2
    in_slot, no_slot = rows[:half], rows[half:]

    def series(block, sched):
        xs, ys, ub = [], [], []
        for r in block:
            if r.get("schedule") != sched:
                continue
            xs.append(r["hop"])
            ys.append(r.get("mi_lower_bits_conservative", 0.0))
            ub.append(r.get("t3_upper_bits"))
        z = sorted(zip(xs, ys, ub))
        return [a for a, _, _ in z], [b for _, b, _ in z], [c for _, _, c in z]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.4, 3.9), sharey=True)

    for ax, block, title in (
            (ax1, in_slot, "In the slot: a check on our implementation"),
            (ax2, no_slot, "Around the slot: the part about the agents")):
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, color=GRID, linewidth=0.8)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.set_title(title, fontsize=9.5, color=INK, loc="left", pad=8)
        ax.set_xlabel("hop", fontsize=9, color=INK)
        ax.set_xticks([1, 2, 3, 4])
        ax.tick_params(colors=MUTED, length=0, labelsize=8.5)

        for sched in ORDER:
            xs, ys, ub = series(block, sched)
            if not xs:
                continue
            ax.plot(xs, ys, marker=MARKER[sched], markersize=5.5, linewidth=2,
                    color=COLOUR[sched], zorder=3,
                    markerfacecolor="white", markeredgewidth=1.6,
                    label=LABEL[sched] if ax is ax1 else None)
            if sched == "stochastic" and ax is ax1:
                ax.plot(xs, ub, linestyle="--", linewidth=1.6, color=COLOUR[sched],
                        alpha=0.65, zorder=2, label="T3 bound (stochastic)")

    ax1.set_ylabel("conservative Fano lower bound (bits)", fontsize=9, color=INK)
    ax1.set_ylim(-0.08, 4.8)

    # The control, named on the plot rather than left to the caption.
    ax1.annotate("only the control\ncarries information",
                 xy=(3.9, 1.482), xytext=(2.35, 2.25), fontsize=8.5, color=INK,
                 ha="left",
                 arrowprops=dict(arrowstyle="-", color=MUTED, linewidth=0.9,
                                 shrinkA=2, shrinkB=4))
    ax2.annotate("every schedule at zero,\nincluding the control",
                 xy=(2.5, 0.0), xytext=(1.5, 1.35), fontsize=8.5, color=INK,
                 ha="left",
                 arrowprops=dict(arrowstyle="-", color=MUTED, linewidth=0.9,
                                 shrinkA=2, shrinkB=4))

    # Legend below both panels: inside either one it lands on the annotation or
    # on the control curve, whichever way it is anchored.
    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5, frameon=False,
               fontsize=8.5, bbox_to_anchor=(0.5, -0.07))

    fig.tight_layout()
    out = Path("paper/fig_ladder.pdf")
    fig.savefig(out, bbox_inches="tight")
    fig.savefig(out.with_suffix(".png"), dpi=200, bbox_inches="tight")
    print("-> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
