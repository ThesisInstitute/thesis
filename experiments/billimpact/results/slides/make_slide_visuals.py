"""Slide visuals for the bill-impact demo — 2026-07-31.

Every plotted number is verified against experiments/billimpact/RESULTS.md
(line numbers in NUMBERS.md) or recomputed from frozen artifacts
(results/summary.json, results/final_multimetric.json, runs_amend3.jsonl,
runs_deconfound.jsonl, ground_truth_extra.json) — see NUMBERS.md.

Renders at 2400x1350 (16:9, 2x for slides). White background; hero also dark.
"""
from __future__ import annotations

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

OUT = Path("/Users/davidgringras26-27/Desktop/HACKATHON-2026-07-31/SLIDE-VISUALS")
FIGSIZE = (13.333, 7.5)
DPI = 180

INK = "#141414"
SUB = "#52514e"
MUTED = "#8a8781"
FAINT = "#b3b1aa"
GRID = "#ececea"
BASE = "#c9c7c1"
BLUE = "#2a78d6"       # accent — the finding / fable-5
GRAY_OPUS = "#6b6862"  # opus-5
GRAY_SONNET = "#9b9891"  # sonnet-5
RED = "#d03b3b"        # recall / realized reference

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial"],
    "axes.unicode_minus": False,
    "svg.fonttype": "none",
    "text.color": INK,
    "axes.edgecolor": BASE,
    "axes.labelcolor": SUB,
    "xtick.color": SUB,
    "ytick.color": SUB,
})


def new_fig(facecolor="white"):
    return plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=facecolor)


def title_block(fig, title, subtitle, color=INK, subcolor=SUB, y=0.955, suby=0.885,
                size=30, subsize=15, x=0.045):
    fig.text(x, y, title, fontsize=size, fontweight="bold", color=color,
             ha="left", va="top")
    fig.text(x, suby, subtitle, fontsize=subsize, color=subcolor, ha="left", va="top",
             linespacing=1.5)


# ---------------------------------------------------------------- FIG 1
def fig1():
    # RESULTS.md L41-45 (spread %, ratios, verdicts); IQR whiskers recomputed
    # from results/summary.json dispersion[dim] spread_pp_median / spread_pp_iqr.
    rows = [
        ("model tier", 9.31, 4.89, 12.69, True,
         ["12.4× its permutation null — survives Bonferroni",
          "and state clustering; the most defensible number",
          "in the study  ·  naive ratio 4.65 [2.11, 6.46]"]),
        ("elicitation format", 8.10, 5.91, 10.77, False,
         ["4.8× its null but fragile to state clustering —",
          "reported as suggestive  ·  1.73 [1.17, 2.92]"]),
        ("policy context shown", 3.54, 2.86, 4.69, False,
         ["4.1× its null (p<0.0003) — carried entirely by",
          "the purpose-clause arm: named-statute recall,",
          "not bill-reading (§2)  ·  1.81 [1.11, 2.65]"]),
        ("statutory magnitude", 2.13, 1.06, 2.86, False,
         ["null — 0.97 after a red-team denominator fix;",
          "rewriting the bill's numbers moves ~nothing"]),
        ("debate pipeline", 1.04, 0.52, 1.73, False,
         ["null on magnitude — but shifts forecasts up in",
          "8/9 moving units (p=0.039); variance ×5.4"]),
    ]

    fig = new_fig()
    title_block(
        fig,
        "The biggest knob in the harness is the model itself",
        "Spread of the median forecast across the settings of each harness dimension, varied one at a time with all else at reference.\n"
        "12 SNAP units (6 states × 2 months), Pub. L. 118-5 §§311–314  ·  2,520 pre-registered runs  ·  first prints frozen before any model call.",
    )

    ax = fig.add_axes([0.235, 0.16, 0.295, 0.565])
    n = len(rows)
    ys = list(range(n))[::-1]
    for y, (label, med, lo, hi, accent, ann) in zip(ys, rows):
        barcolor = BLUE if accent else "#d6d4ce"
        wcolor = SUB if accent else MUTED
        ax.barh(y, med, height=0.56, color=barcolor, zorder=3)
        ax.plot([lo, hi], [y, y], color=wcolor, lw=1.6, zorder=4, solid_capstyle="butt")
        ax.plot([lo, lo], [y - 0.10, y + 0.10], color=wcolor, lw=1.6, zorder=4)
        ax.plot([hi, hi], [y - 0.10, y + 0.10], color=wcolor, lw=1.6, zorder=4)
        ax.text(hi + 0.4, y, f"{med:.1f}%", fontsize=17, fontweight="bold",
                color=BLUE if accent else SUB, va="center", ha="left")
        ax.text(-0.55, y, label, fontsize=17, color=INK, va="center", ha="right",
                fontweight="bold" if accent else "normal")

    ax.set_xlim(0, 15.5)
    ax.set_ylim(-0.65, n - 0.35)
    ax.set_yticks([])
    ax.set_xticks([0, 5, 10, 15])
    ax.set_xticklabels(["0", "5", "10", "15%"], fontsize=13.5)
    ax.tick_params(axis="x", length=0, pad=6)
    ax.grid(axis="x", color=GRID, lw=1.0, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BASE)
    ax.set_xlabel("forecast spread across settings (% of unit's unconditioned forecast) · bar = median unit, whisker = IQR",
                  fontsize=12.5, color=MUTED, labelpad=10)

    # annotation column, row-aligned with the bars
    col_x = 0.575
    fig.text(col_x, 0.745, "CORRECTED INFERENCE  ·  permutation test, red-team audited",
             fontsize=12.5, color=MUTED, ha="left", va="center")
    ax_y0, ax_h, ylo, yhi = 0.16, 0.565, -0.65, n - 0.35
    for y, (label, med, lo, hi, accent, ann) in zip(ys, rows):
        fy = ax_y0 + ax_h * ((y - ylo) / (yhi - ylo))
        fig.text(col_x, fy, "\n".join(ann), fontsize=13.5,
                 color=INK if accent else SUB, ha="left", va="center",
                 linespacing=1.42, fontweight="bold" if accent else "normal")

    fig.text(0.045, 0.014,
             "Naive spread-over-noise ratios in brackets; the honest test restates each against its permutation null (expected 0.12–0.52 under a true null, not 1)\n"
             "— the restatement strengthens the headline. RESULTS §1, corrections applied from the study's own red-team audit.",
             fontsize=12, color=MUTED, ha="left", va="bottom", linespacing=1.45)

    fig.savefig(OUT / "fig1_harness_dimensions.png", dpi=DPI, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- FIG 2
def fig2():
    # results/final_multimetric.json mean_ncrps: fable bill 0.3390, fable bill
    # effort=max 0.2079, fable no-bill 0.2923, opus bill 0.2606, opus bill
    # effort=max 0.2470, opus no-bill 0.2533.
    # CIs: RESULTS.md L228-232 (effort-only), L190 + L202-204 (vs naive).
    fable_bill = [0.339, 0.208]
    opus_bill = [0.261, 0.247]
    fable_naive = 0.292
    opus_naive = 0.253

    fig = new_fig()
    title_block(
        fig,
        "Bill text hurts at default effort — and pays at max",
        "fable-5, identical prompt and bill text; only the reasoning-effort setting changes. Mean normalized CRPS on 28 retrospective\n"
        "units across 5 enacted laws (lower = better). opus-5, same recipe: no interaction.",
    )

    ax = fig.add_axes([0.09, 0.16, 0.50, 0.60])
    x = [0, 1]

    # shaded cost / pay regions between fable's bill line and its naive baseline
    xs = np.linspace(0, 1, 200)
    line = fable_bill[0] + (fable_bill[1] - fable_bill[0]) * xs
    ax.fill_between(xs, line, fable_naive, where=line > fable_naive,
                    color=RED, alpha=0.10, lw=0, zorder=1)
    ax.fill_between(xs, line, fable_naive, where=line <= fable_naive,
                    color=BLUE, alpha=0.10, lw=0, zorder=1)

    # naive baselines (span the columns only, not the label margin)
    ax.plot([0, 1], [fable_naive] * 2, color=BLUE, lw=1.4, ls=(0, (5, 4)),
            alpha=0.75, zorder=2)
    ax.plot([0, 1], [opus_naive] * 2, color=GRAY_OPUS, lw=1.4, ls=(0, (5, 4)),
            alpha=0.65, zorder=2)

    ax.plot(x, opus_bill, color=GRAY_OPUS, lw=3.0, zorder=4, marker="o",
            markersize=9, markeredgecolor="white", markeredgewidth=1.5)
    ax.plot(x, fable_bill, color=BLUE, lw=4.2, zorder=5, marker="o",
            markersize=11, markeredgecolor="white", markeredgewidth=1.5)

    ax.set_xlim(-0.42, 1.95)
    ax.set_ylim(0, 0.375)
    ax.set_xticks(x)
    ax.set_xticklabels(["default reasoning effort", "max reasoning effort"],
                       fontsize=16, color=INK)
    ax.set_yticks([0, 0.1, 0.2, 0.3])
    ax.set_yticklabels(["0", "0.1", "0.2", "0.3"], fontsize=13.5)
    ax.tick_params(length=0, pad=9)
    ax.grid(axis="y", color=GRID, lw=1.0, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BASE)
    ax.set_ylabel("mean nCRPS   (lower = more accurate)", fontsize=14.5, color=SUB)

    # left-side values
    ax.text(-0.07, fable_bill[0], "0.339", fontsize=17, fontweight="bold",
            color=BLUE, ha="right", va="center")
    ax.text(-0.07, opus_bill[0], "0.261", fontsize=15, color=GRAY_OPUS,
            ha="right", va="center")

    # right-side stacked labels (explicit y to avoid collisions)
    ax.text(1.07, fable_naive + 0.012, "0.292 · fable-5 without the bill",
            fontsize=13.5, color=BLUE, alpha=0.85, ha="left", va="center")
    ax.text(1.07, opus_naive + 0.012, "0.253 · opus-5 without the bill",
            fontsize=13.5, color=GRAY_OPUS, alpha=0.9, ha="left", va="center")
    ax.text(1.07, opus_bill[1] - 0.022,
            "0.247 · opus-5 + bill — flat: −0.014 [−0.038, +0.015], n.s.",
            fontsize=13.5, color=GRAY_OPUS, ha="left", va="center")
    ax.text(1.07, fable_bill[1] - 0.002,
            "0.208 · fable-5 + bill — best arm in the study",
            fontsize=16, fontweight="bold", color=BLUE, ha="left", va="center")

    # interaction callouts
    ax.text(0.03, 0.3585, "+0.047 — showing the bill made fable worse\nthan not showing it at all",
            fontsize=14.5, color=RED, ha="left", va="bottom", linespacing=1.35)
    ax.text(0.35, 0.175,
            "same bill, effort raised to max: −0.131 [−0.205, −0.062]\n"
            "39% lower error · 19/28 units · and −0.084 [−0.164, −0.008] vs naive",
            fontsize=14.5, color=BLUE, ha="left", va="top", linespacing=1.45)

    # mechanism, set inside the empty lower band of the zero-based axis
    ax.text(-0.35, 0.098,
            "Mechanism (§5): directional overshoot. At default effort the bill pushes forecasts further along the statute's\n"
            "implied direction, past the truth — worst case, a one-time payment booked into a seasonally-adjusted\n"
            "annual-rate series at 12×. Max effort sizes the same adjustment correctly — effort disciplines the\n"
            "magnitude of the bill-triggered adjustment, not its direction.",
            fontsize=13, color=SUB, ha="left", va="top", linespacing=1.5)

    fig.savefig(OUT / "fig2_effort_context_interaction.png", dpi=DPI, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- FIG 3
def fig3():
    # results/final_multimetric.json mean_ncrps: opus no-bill 0.2533, fable
    # no-bill 0.2923, opus bill max 0.2470, fable bill max 0.2079,
    # persistence 0.3258. CIs and counts: RESULTS.md L202-210.
    left = {"opus-5": 0.253, "fable-5": 0.292}
    right = {"opus-5": 0.247, "fable-5": 0.208}
    persistence = 0.326

    fig = new_fig()
    title_block(
        fig,
        "Same models, same bills — elicitation inverts the ranking",
        "Mean normalized CRPS on 28 retrospective units across 5 enacted laws; lower = more accurate, plotted higher.\n"
        "The only change between columns is the harness: bill text in context, reasoning effort raised from default to max.",
    )

    ax = fig.add_axes([0.16, 0.14, 0.56, 0.56])
    x0, x1 = 0, 1

    def ypos(v):
        return -v

    ax.plot([x0, x1], [ypos(persistence)] * 2, color=FAINT, lw=1.4,
            ls=(0, (4, 4)), zorder=1)
    ax.plot([x0, x1], [ypos(left["opus-5"]), ypos(right["opus-5"])],
            color=GRAY_OPUS, lw=3.0, marker="o", markersize=10, zorder=3,
            markeredgecolor="white", markeredgewidth=1.5)
    ax.plot([x0, x1], [ypos(left["fable-5"]), ypos(right["fable-5"])],
            color=BLUE, lw=4.2, marker="o", markersize=12, zorder=4,
            markeredgecolor="white", markeredgewidth=1.5)

    ax.set_xlim(-0.85, 2.10)
    ax.set_ylim(ypos(0.345), ypos(0.185))
    ax.axis("off")

    # node labels
    ax.text(x0 - 0.07, ypos(left["opus-5"]), "opus-5 · 0.253", fontsize=16.5,
            color=GRAY_OPUS, ha="right", va="center", fontweight="bold")
    ax.text(x0 - 0.07, ypos(left["fable-5"]), "fable-5 · 0.292", fontsize=16.5,
            color=BLUE, ha="right", va="center", fontweight="bold")
    ax.text(x1 + 0.07, ypos(right["opus-5"]), "opus-5 · 0.247", fontsize=16.5,
            color=GRAY_OPUS, ha="left", va="center", fontweight="bold")
    ax.text(x1 + 0.07, ypos(right["fable-5"]), "fable-5 · 0.208", fontsize=16.5,
            color=BLUE, ha="left", va="center", fontweight="bold")
    ax.text(x1 + 0.07, ypos(persistence), "persistence · 0.326", fontsize=13,
            color=MUTED, ha="left", va="center")
    ax.text(x0 - 0.07, ypos(persistence), "0.326 · persistence", fontsize=13,
            color=MUTED, ha="right", va="center")

    # column headers (figure coords, computed over column x positions)
    def xfig(xd):
        return 0.16 + 0.56 * ((xd + 0.85) / 2.95)

    fig.text(xfig(x0), 0.775, "naive harness", fontsize=17, fontweight="bold",
             color=INK, ha="center", va="center")
    fig.text(xfig(x0), 0.732, "no bill text\ndefault effort", fontsize=13.5,
             color=MUTED, ha="center", va="top", linespacing=1.35)
    fig.text(xfig(x1), 0.775, "tuned harness", fontsize=17, fontweight="bold",
             color=INK, ha="center", va="center")
    fig.text(xfig(x1), 0.732, "bill text +\nmax reasoning effort", fontsize=13.5,
             color=MUTED, ha="center", va="top", linespacing=1.35)

    # verdicts
    fig.text(0.045, 0.40, "opus wins the naive\ncomparison by 0.039",
             fontsize=15, color=SUB, ha="left", va="center", linespacing=1.4)
    fig.text(0.735, 0.545,
             "fable wins the tuned one by 0.039 —\n"
             "and significantly beats its own naive\n"
             "arm (−0.084 [−0.164, −0.008]) and\n"
             "persistence (−0.118 [−0.211, −0.035],\n"
             "22/28 units), leading the Winkler\n"
             "interval score at 0.75 coverage.",
             fontsize=14.5, color=INK, ha="left", va="center", linespacing=1.45)
    fig.text(0.735, 0.36,
             "The naive-arm CI is nominal — marginal\nunder multiplicity; the persistence\nmargin is the robust one (§5).",
             fontsize=12.5, color=MUTED, ha="left", va="center", linespacing=1.4)

    fig.text(0.045, 0.038,
             "A leaderboard entry is a property of the (model, harness) pair — report the harness with the number.\n"
             "Vertical position to scale in nCRPS (CRPS normalized by each unit's history dispersion); every value printed.",
             fontsize=12.5, color=MUTED, ha="left", va="bottom", linespacing=1.45)

    fig.savefig(OUT / "fig3_ranking_inversion.png", dpi=DPI, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- HERO
def hero(dark=False):
    # Medians recomputed from runs_amend3.jsonl / runs_deconfound.jsonl by
    # recompute_hero_medians.py (point_ci_json, median of 5 reps per point).
    named = {
        "sonnet-5": [380.0, 400.0, 380.0],
        "opus-5": [510.0, 545.0, 540.0],
        "fable-5": [540.0, 540.0, 950.0],
    }
    redacted = {
        "opus-5": [460.0, 505.0, 900.0],
        "fable-5": [420.0, 550.0, 1000.0],
    }
    realized = 570.6  # ground_truth_extra.json fpuc300.us.2021-01 first_print_value

    if dark:
        bg, ink, sub, muted, grid, base = "#1a1a19", "#f4f3ef", "#c3c2b7", "#8a8781", "#2c2c2a", "#44433f"
        blue, gray_o, gray_s, red = "#4a90e8", "#a8a59d", "#7f7c75", "#e66767"
        suffix = "_dark"
    else:
        bg, ink, sub, muted, grid, base = "white", INK, SUB, MUTED, GRID, BASE
        blue, gray_o, gray_s, red = BLUE, GRAY_OPUS, GRAY_SONNET, RED
        suffix = ""

    model_color = {"fable-5": blue, "opus-5": gray_o, "sonnet-5": gray_s}

    fig = new_fig(facecolor=bg)
    title_block(
        fig,
        "Redact the law's name and the model starts reading the bill",
        r"The FPUC unemployment supplement (Pub. L. 116-260 §203) rewritten at \$100 / \$300 / \$900 a week; forecast Jan-2021 UI" "\n"
        "outlays — a target deep inside training data. Only change between panels: the statute's name is deleted from the header.",
        color=ink, subcolor=sub,
    )

    xpos = [0, 1, 2]
    xlabels = [r"\$100/wk", r"\$300/wk" + "\n(enacted)", r"\$900/wk"]

    panels = [
        ("statute named in the header", named,
         "strictly monotone in dose:  0 / 3 models", red,
         "dose spread ÷ repeat noise: 0.2–2.0×"),
        ("name redacted — nothing else changed", redacted,
         "monotone in dose:  4 / 4 cells", blue,
         "dose spread ÷ repeat noise: 3.0–8.1×"),
    ]

    # per-panel label offsets to prevent collisions
    start_off = {
        ("statute named in the header", "fable-5"): 18,
        ("statute named in the header", "opus-5"): -26,
        ("statute named in the header", "sonnet-5"): 0,
        ("name redacted — nothing else changed", "opus-5"): 20,
        ("name redacted — nothing else changed", "fable-5"): -24,
    }
    end_off = {
        ("statute named in the header", "fable-5"): 0,
        ("statute named in the header", "opus-5"): 0,
        ("statute named in the header", "sonnet-5"): 0,
        ("name redacted — nothing else changed", "fable-5"): 26,
        ("name redacted — nothing else changed", "opus-5"): -34,
    }

    for i, (ptitle, data, tag, tagcolor, noise) in enumerate(panels):
        ax = fig.add_axes([0.085 + i * 0.465, 0.19, 0.335, 0.50])
        ax.set_facecolor(bg)

        ax.axhline(realized, color=red, lw=1.5, ls=(0, (5, 4)), alpha=0.85, zorder=2)

        for m, vals in data.items():
            c = model_color[m]
            ax.plot(xpos, vals, color=c, lw=3.6 if m == "fable-5" else 2.8,
                    marker="o", markersize=9, zorder=4,
                    markeredgecolor=bg if dark else "white", markeredgewidth=1.5)
            ax.text(2.13, vals[-1] + end_off[(ptitle, m)], f"{m} · {vals[-1]:.0f}",
                    fontsize=14.5, color=c, ha="left", va="center",
                    fontweight="bold" if m == "fable-5" else "normal")
            ax.text(-0.14, vals[0] + start_off[(ptitle, m)], f"{vals[0]:.0f}",
                    fontsize=13, color=c, ha="right", va="center")

        ax.set_xlim(-0.60, 3.15)
        ax.set_ylim(0, 1120)
        ax.set_xticks(xpos)
        ax.set_xticklabels(xlabels, fontsize=14, color=ink, linespacing=1.3)
        ax.set_yticks([0, 250, 500, 750, 1000])
        ax.set_yticklabels(["0", "250", "500", "750", "1000"], fontsize=12.5, color=sub)
        ax.tick_params(length=0, pad=7)
        ax.grid(axis="y", color=grid, lw=1.0, zorder=0)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(base)

        ax.set_title(ptitle, fontsize=18.5, fontweight="bold", color=ink, pad=52)
        ax.text(1.27, 1218, tag, fontsize=15.5, color=tagcolor, ha="center",
                fontweight="bold", clip_on=False)
        ax.text(1.27, 1148, noise, fontsize=12.5, color=muted, ha="center", clip_on=False)

        if i == 0:
            ax.set_ylabel("median forecast — UI transfer receipts,\nJan 2021  ($B, seasonally adj. annual rate)",
                          fontsize=12.5, color=sub, linespacing=1.35)
            ax.text(-0.45, 592, "570.6 · realized\nJan-2021 first print",
                    fontsize=12.5, color=red, ha="left", va="bottom", linespacing=1.32)
            ax.text(1.5, 458, r"fable: flat from \$100 to \$300," "\n" r"partial response at \$900",
                    fontsize=11.5, color=blue, ha="center", va="center", linespacing=1.3)
        else:
            ax.text(3.02, realized + 16, "570.6", fontsize=11.5, color=red,
                    ha="left", va="bottom")

    fig.text(0.045, 0.022,
             "Median of 5 runs per point, point+CI elicitation · series W825RC1, history through Oct 2020 (last value 306) · doses ×3 apart (log-spaced axis).\n"
             "sonnet-5 ran in the named arm only; the 4/4 count includes the derivation elicitation · redaction arm registered before its runs (§3a).\n"
             "The key is identity, not period: derivation elicitation restores dose-response even named (3/3), raising effort does not (§3b); the 2026 window: 6/6 monotone.",
             fontsize=11.5, color=muted, ha="left", va="bottom", linespacing=1.55)

    fig.savefig(OUT / f"hero_named_statute_recall{suffix}.png", dpi=DPI, facecolor=bg)
    plt.close(fig)


if __name__ == "__main__":
    fig1()
    fig2()
    fig3()
    hero(dark=False)
    hero(dark=True)
    print("done:", sorted(p.name for p in OUT.glob("*.png")))
