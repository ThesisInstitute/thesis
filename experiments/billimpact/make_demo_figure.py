"""Render the demo chart from the frozen summary.json.

Kept separate from analyze.py so the presentation asset can be re-rendered
without re-running the analysis (and without racing anyone else editing it).
Reads only summary.json — it computes nothing, so the chart cannot disagree
with the reported numbers.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = Path(__file__).parent

STATE_COLORS = {
    "CA": "#1f77b4", "FL": "#d62728", "NY": "#2ca02c",
    "TX": "#ff7f0e", "PA": "#9467bd", "OH": "#8c564b",
}
DIM_FIELD = {"D1": "policy_context", "D2": "elicitation", "D3": "pipeline",
             "D4": "model", "D5": "magnitude"}
PRETTY = {"claude-opus-5": "opus-5", "claude-sonnet-5": "sonnet-5",
          "claude-haiku-4-5-20251001": "haiku-4.5", "claude-fable-5": "fable-5"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, default=HERE / "results" / "summary.json")
    ap.add_argument("--outdir", type=Path, default=HERE / "results")
    args = ap.parse_args()

    S = json.loads(args.summary.read_text())
    cols = S["figure"]["columns"]
    series = S["figure_series_normalised"]
    units = S["units"]
    disp = S["dispersion"]
    q = S["data_quality"]

    plt.rcParams.update({
        "font.size": 15, "axes.labelsize": 17, "xtick.labelsize": 14,
        "ytick.labelsize": 15, "legend.fontsize": 13,
    })
    fig, ax = plt.subplots(figsize=(19.5, 10.2))

    parsed = [(c.split(":", 1)[0], c.split(":", 1)[1]) for c in cols]
    labels = [PRETTY.get(lv, lv) for _, lv in parsed]
    x = list(range(len(cols)))

    for uid, ys in series.items():
        st = units[uid].get("state", "?")
        dashed = uid.endswith("2024-03")
        xs = [i for i, y in enumerate(ys) if y is not None]
        vs = [y for y in ys if y is not None]
        ax.plot(xs, vs, color=STATE_COLORS.get(st, "#666"),
                linestyle="--" if dashed else "-", linewidth=2.4,
                marker="o", markersize=5, alpha=0.9)

    ax.axhline(1.0, color="black", linestyle=":", linewidth=1.6)
    ax.annotate("unconditioned median (policy_context = none)", xy=(0.2, 1.0),
                xytext=(0, 7), textcoords="offset points", fontsize=13)

    # dimension bands + verdict labels
    bounds: list[tuple[str, int, int]] = []
    cur, start = parsed[0][0], 0
    for i, c in enumerate([d for d, _ in parsed] + [None]):
        if c != cur:
            bounds.append((cur, start, i - 1))
            cur, start = c, i
    ylo, yhi = ax.get_ylim()
    for dim, a, b in bounds:
        if dim is None:
            continue
        if a > 0:
            ax.axvline(a - 0.5, color="#999", linewidth=1.1)
        d = disp.get(dim, {})
        rm = d.get("ratio_of_medians") or {}
        ratio = rm.get("point")
        ci = [rm.get("ci_low"), rm.get("ci_high")]
        verdict = "EXCEEDS" if d.get("verdict", "").startswith("EXCEEDS") else "NULL"
        colour = "#b30000" if verdict == "EXCEEDS" else "#31708f"
        txt = f"{dim} {DIM_FIELD.get(dim, '')}\n{verdict}"
        if ratio is not None and ci[0] is not None:
            txt += f"\n{ratio:.2f}x noise\n[{ci[0]:.2f}, {ci[1]:.2f}]"
        elif ratio is not None:
            txt += f"\n{ratio:.2f}x noise"
        ax.text((a + b) / 2, yhi - (yhi - ylo) * 0.012, txt, ha="center", va="top",
                fontsize=12, fontweight="bold", color=colour,
                bbox=dict(boxstyle="round,pad=0.28", facecolor="white",
                          edgecolor=colour, alpha=0.92))

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=38, ha="right")
    ax.set_xlim(-0.6, len(cols) - 0.4)
    ax.set_ylabel("median forecast ÷ that unit's unconditioned median", labelpad=12)
    ax.set_xlabel("configuration  (one dimension varied; all others held at reference)",
                  labelpad=12)
    ax.grid(axis="y", alpha=0.28)

    fig.suptitle("Forecast sensitivity to harness configuration, one dimension at a time",
                 fontsize=23, fontweight="bold", y=0.985)
    ax.set_title(
        f"Retrospective backtest, SNAP participation under Pub. L. 118-5 §§311–314.  "
        f"N = {q['records_read']} runs · {len(series)} units · {len(cols)} configurations · "
        f"5 repeats per cell · pre-registered before first run",
        fontsize=14.5, pad=14)

    handles = [Line2D([], [], color=c, linewidth=3, label=s)
               for s, c in STATE_COLORS.items()
               if any(units[u].get("state") == s for u in series)]
    handles += [Line2D([], [], color="#444", linewidth=3, linestyle="-", label="target 2023-12"),
                Line2D([], [], color="#444", linewidth=3, linestyle="--", label="target 2024-03")]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.004, 0.5),
              frameon=True, title="unit", title_fontsize=14)

    fig.text(0.006, 0.006,
             "Flat = robust to the harness. Fanning = harness-sensitive. "
             "Every configuration is shown with its repeat variance.",
             fontsize=12.5, color="#444")
    fig.tight_layout(rect=(0, 0.028, 1, 0.965))
    for ext in ("png", "svg"):
        out = args.outdir / f"demo_dispersion.{ext}"
        fig.savefig(out, dpi=140, bbox_inches="tight")
        print("wrote", out)


if __name__ == "__main__":
    main()
