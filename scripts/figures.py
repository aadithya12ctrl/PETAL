"""Paper figures. Light mode only: the medium is a printed page.

Design follows the project's data-viz procedure -- form first, colour by the job
it does, validated palette, thin marks, recessive axes, text in ink tokens rather
than series colour.

Colour carries identity in exactly one figure. The frontier and the delta plot
put the arms on a *categorical axis* with direct labels, so they need one hue;
that also sidesteps the all-pairs colour-blindness limit, which the eight arms
would breach if each were its own hue. The ladder figure has four series on an
adjacent pairlist, where slots 1-4 of the validated order pass:

    node scripts/validate_palette.js "#2a78d6,#eb6834,#1baf7a,#eda100" --mode light
    -> all checks pass; contrast WARN on aqua (2.74) and yellow (2.11)

That WARN obliges relief, so every line is direct-labelled *and* the same
numbers appear as a table in results/exp2_ladder.md.

  py -3.12 scripts/figures.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from petal import paths

# ----------------------------------------------------------------- tokens
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_MUTED = "#8a8980"
GRID = "#e6e5e0"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
REFERENCE = "#8a8980"      # the theoretical bound: a reference, not a series

ARM_LABEL = {
    "full": "Full", "swap": "Swap", "drop": "Drop", "b1_privacy": "B1 privacy",
    "b4_restriction": "B4 drop-the-fact", "b6_placebo": "B6 placebo",
    "petal_text": "Petal (text)", "decision_only": "Decision-only",
}
SCHED_LABEL = {"none": "no ladder", "deterministic": "deterministic",
               "stochastic": "stochastic ladder", "random_dropout": "random dropout"}


def style(ax, *, xlabel="", ylabel="", title="", grid_axis="both"):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
        ax.spines[side].set_linewidth(1.0)
    ax.tick_params(colors=INK_2, labelsize=9, length=3, width=1.0)
    ax.grid(True, axis=grid_axis, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    if xlabel:
        ax.set_xlabel(xlabel, color=INK_2, fontsize=9.5)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK_2, fontsize=9.5)
    if title:
        ax.set_title(title, color=INK, fontsize=11, loc="left", pad=8)


def save(fig, name: str) -> None:
    paths.FIGURES.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(paths.FIGURES / ("%s.%s" % (name, ext)), dpi=200,
                    facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print("  -> %s.{png,pdf}" % (paths.FIGURES / name))


# ------------------------------------------------------------- fig 1: frontier
def fig_frontier(d: dict) -> None:
    """Leak against utility, one mark per arm, faceted by use type.

    A scatter rather than two bar charts: the question is a trade-off between two
    measures, and the single most common chart mistake would be to put utility
    and leak on two y-scales of one plot.
    """
    uts = [u for u in ("decision", "content") if u in d["use_types"]]
    if not uts:
        return
    fig, axes = plt.subplots(1, len(uts), figsize=(4.6 * len(uts), 4.0),
                             facecolor=SURFACE, squeeze=False)
    for j, ut in enumerate(uts):
        ax = axes[0][j]
        p = d["use_types"][ut]
        style(ax, xlabel="leak rate on the relay (m1)",
              ylabel="task utility" if j == 0 else "",
              title="%s-type" % ut.capitalize())
        # Arms frequently coincide exactly -- every defended arm sits at leak 0
        # with the same utility -- so one label per *point*, listing the arms
        # that share it. Drawn per arm, the labels overprint into mush.
        groups: dict[tuple[float, float], list[str]] = {}
        for arm, u in p["utility"].items():
            lk = p["leak"].get(arm, {}).get("m1")
            if lk is None or lk != lk:
                continue
            groups.setdefault((round(lk, 3), round(u, 3)), []).append(arm)
        for (lk, u), arms in sorted(groups.items()):
            ax.plot([lk], [u], marker="o", markersize=8, color=SERIES[0],
                    markeredgecolor=SURFACE, markeredgewidth=1.8, zorder=3)
            ax.annotate("\n".join(ARM_LABEL.get(a, a) for a in sorted(arms)),
                        (lk, u), textcoords="offset points", xytext=(10, 0),
                        fontsize=8.5, color=INK_2, va="center", linespacing=1.35)
        # headroom for a stacked label centred on a point at utility 1.0, and
        # ticks stop at 1.0 because a rate cannot exceed it -- the extra x range
        # is label gutter, not data range
        ax.set_xlim(-0.08, 1.80)
        ax.set_ylim(-0.05, 1.34)
        ax.set_xticks([0.0, 0.25, 0.5, 0.75, 1.0])
        ax.set_yticks([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
        fl = p.get("phi_floor")
        if fl is not None and fl == fl and fl > 0:
            ax.axvline(fl, color=REFERENCE, linestyle=(0, (4, 3)), linewidth=1.2)
            ax.annotate("inference floor", (fl, 1.28), fontsize=8,
                        color=INK_MUTED, xytext=(4, 0),
                        textcoords="offset points")
    fig.suptitle("Leak-utility position of each arm", color=INK, fontsize=12,
                 x=0.012, ha="left", y=1.02)
    save(fig, "fig1_frontier")


# ---------------------------------------------------------------- fig 2: delta
def fig_delta(d: dict) -> None:
    """Dot-and-whisker, not bars: these are estimates with uncertainty.

    The x-axis is delta / ceiling, not delta. A raw delta of 0.43 on content and
    1.00 on decision can describe the *same* achievement, because the two use
    types have different amounts of room above the Drop arm for a defence that
    never asserts S. Normalising puts both panels on one scale and makes the
    reference line a single vertical at 1.0, which is what Conjecture C1 is a
    claim about. Each panel's caption carries the raw ceiling it was divided by.
    """
    uts = [u for u in ("decision", "content") if u in d["use_types"]]
    order = ["petal_text", "decision_only", "b6_placebo", "b1_privacy",
             "b4_restriction"]
    if not uts:
        return
    key = ("delta_over_ceiling"
           if all(d["use_types"][u].get("delta_over_ceiling") for u in uts)
           else "delta")
    hi = 1.18
    for u in uts:
        for iv in d["use_types"][u].get(key, {}).values():
            if iv["hi"] == iv["hi"]:
                hi = max(hi, iv["hi"] + 0.12)
    fig, axes = plt.subplots(1, len(uts), figsize=(4.9 * len(uts), 3.4),
                             facecolor=SURFACE, squeeze=False, sharex=True)
    for j, ut in enumerate(uts):
        ax = axes[0][j]
        p = d["use_types"][ut]
        arms = [a for a in order if a in p.get(key, {})]
        ys = list(range(len(arms)))[::-1]
        cl = (p.get("ceiling_delta_scale") or {}).get("point")
        title = "%s-type" % ut.capitalize()
        if key == "delta_over_ceiling" and cl:
            title += "   (ceiling: delta = %.2f)" % cl
        style(ax, xlabel=("separability  delta / ceiling"
                          if key == "delta_over_ceiling" else "separability  delta"),
              title=title, grid_axis="x")
        ceil = 1.0 if key == "delta_over_ceiling" else p.get("u_max_no_s_mean")
        if ceil:
            ax.axvline(ceil, color=REFERENCE, linestyle=(0, (4, 3)), linewidth=1.4,
                       zorder=1)
            # flip the annotation inboard when the ceiling sits near the right
            # edge, or it clips off the panel
            right = ceil > 0.7 * hi
            ax.annotate("ceiling", (ceil, len(arms) - 0.35),
                        fontsize=8, color=INK_MUTED,
                        xytext=(-5 if right else 5, 0),
                        ha="right" if right else "left",
                        textcoords="offset points")
        for y, arm in zip(ys, arms):
            iv = p[key][arm]
            if iv["point"] != iv["point"]:
                continue
            ax.plot([iv["lo"], iv["hi"]], [y, y], color=SERIES[0], linewidth=2,
                    solid_capstyle="round", zorder=2, alpha=0.45)
            ax.plot([iv["point"]], [y], marker="o", markersize=8,
                    color=SERIES[0], markeredgecolor=SURFACE,
                    markeredgewidth=1.8, zorder=3)
            ax.annotate("%.2f" % iv["point"], (iv["point"], y), fontsize=8,
                        color=INK_2, xytext=(0, 9), textcoords="offset points",
                        ha="center")
        ax.set_yticks(ys)
        # the arms are identical across panels, so label them once; a second
        # copy lands inside the neighbouring panel's plotting area
        ax.set_yticklabels([ARM_LABEL.get(a, a) for a in arms] if j == 0
                           else [""] * len(arms), fontsize=9, color=INK_2)
        if j:
            # the row labels are on the left panel only, so the tick marks
            # here would be dashes pointing at nothing
            ax.tick_params(axis="y", length=0)
        ax.set_ylim(-0.7, len(arms) - 0.1)
        ax.set_xlim(-0.38, hi)
        ax.axvline(0, color=GRID, linewidth=1.0, zorder=1)
    fig.subplots_adjust(wspace=0.12)
    fig.suptitle("Separability against its own ceiling, 95% bootstrap intervals"
                 if key == "delta_over_ceiling" else
                 "Separability by use type, with 95% bootstrap intervals",
                 color=INK, fontsize=12, x=0.012, ha="left", y=1.04)
    save(fig, "fig2_delta")


# --------------------------------------------------------------- fig 3: ladder
def fig_ladder(rows: list[dict]) -> None:
    """Measured decay against the T3 bound.

    Four series on an adjacent pairlist, so slots 1-4 of the validated order are
    legal. The bound is drawn as a reference in neutral grey rather than taking a
    categorical slot, because it is not a measurement.
    """
    if not rows:
        return
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["schedule"], []).append(r)
    fig, ax = plt.subplots(figsize=(7.4, 4.2), facecolor=SURFACE)
    style(ax, xlabel="hop", ylabel="bits about S")

    sched_order = [s for s in ("none", "deterministic", "stochastic",
                               "random_dropout") if s in by]
    for i, sched in enumerate(sched_order):
        rs = sorted(by[sched], key=lambda r: r["hop"])
        xs = [r["hop"] for r in rs]
        ys = [r["mi_lower_bits"] for r in rs]
        c = SERIES[i % len(SERIES)]
        ax.plot(xs, ys, color=c, linewidth=2, marker="o", markersize=7,
                markeredgecolor=SURFACE, markeredgewidth=1.6,
                label=SCHED_LABEL.get(sched, sched), zorder=3)

    st = sorted(by.get("stochastic", []), key=lambda r: r["hop"])
    if st:
        ax.plot([r["hop"] for r in st], [r["t3_upper_bits"] for r in st],
                color=REFERENCE, linewidth=2, linestyle=(0, (5, 3)),
                marker="s", markersize=6, markeredgecolor=SURFACE,
                markeredgewidth=1.4, label="T3 upper bound", zorder=2)

    ax.set_xticks(sorted({r["hop"] for r in rows}))
    ax.set_xlim(0.8, max(r["hop"] for r in rows) + 0.2)
    ax.set_ylim(bottom=-0.15)
    # Legend only, placed outside the plot. Direct end-labels collided with it
    # and with each other, since three schedules converge on zero by hop 4. The
    # contrast WARN on two of these hues obliges relief, and that is carried by
    # the table of the same numbers in results/exp2_ladder.md.
    leg = ax.legend(frameon=False, fontsize=9, loc="center left",
                    bbox_to_anchor=(1.01, 0.5), labelcolor=INK_2)
    for t in leg.get_texts():
        t.set_color(INK_2)
    ax.set_title("Information about S along the chain, measured against the bound",
                 color=INK, fontsize=11.5, loc="left", pad=10)
    save(fig, "fig3_ladder")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp1", default=str(paths.RESULTS / "exp1.json"))
    ap.add_argument("--exp2", default=str(paths.RESULTS / "exp2_probe_rows.json"))
    args = ap.parse_args()

    p1, p2 = Path(args.exp1), Path(args.exp2)
    print("figures ->")
    if p1.exists():
        d = json.loads(p1.read_text(encoding="utf-8"))
        fig_frontier(d)
        fig_delta(d)
    else:
        print("  (no %s; run scripts/analyse_exp1.py first)" % p1)
    if p2.exists():
        fig_ladder(json.loads(p2.read_text(encoding="utf-8")))
    else:
        print("  (no %s; run scripts/analyse_exp2.py first)" % p2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
