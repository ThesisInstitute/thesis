"""Report: REPORT.md, REPORT.html, reliability figures, CSV tables."""

from __future__ import annotations

import html
import json
import pathlib
from collections import Counter
from typing import Any

from kalshi_compare.report import HTML_TEMPLATE, Doc, write_csv

from . import history, pipeline

HORIZON_LABELS = {
    "anchor_30d": "30 days before",
    "anchor_7d": "7 days before",
    "anchor_1d": "1 day before",
    "life_25": "25% of life",
    "life_50": "50% of life",
    "life_75": "75% of life",
}
GROUP_LABELS = {
    "all": "All series",
    "inflation": "Inflation",
    "monthly labor": "Monthly labor",
    "weekly claims": "Weekly claims",
    "housing": "Housing",
    "Australian unemployment": "Australian unemployment",
}
SERIES_LABELS = {
    "KXCPI": "CPI-U, all items (MoM)",
    "KXCPICORE": "CPI-U, less food and energy (MoM)",
    "KXU3": "Unemployment rate (U-3)",
    "KXPAYROLLS": "Nonfarm payroll change",
    "KXJOBLESSCLAIMS": "Initial claims (weekly)",
    "KXCONTCLAIMS": "Continuing claims (weekly)",
    "KXJOLTSOPEN": "JOLTS job openings",
    "KXPCECORE": "Core PCE price index (MoM)",
    "KXHOUSINGSTART": "Housing starts (SAAR)",
    "KXBUILDPERMS": "Building permits (SAAR)",
    "KXNHSALES": "New home sales (SAAR)",
    "KXUE": "Australia unemployment rate",
}
MIN_SERIES_EVENTS = 10


def num(x: float | None, digits: int = 2, signed: bool = False) -> str:
    if x is None or x != x:
        return "—"
    return f"{x:+.{digits}f}" if signed else f"{x:.{digits}f}"


def ci(interval, digits: int = 2, signed: bool = False) -> str:
    if not interval or interval[0] != interval[0]:
        return ""
    return f"[{num(interval[0], digits, signed)}, {num(interval[1], digits, signed)}]"


def with_ci(entry: dict | None, key: str = "mean", digits: int = 2, signed: bool = False) -> str:
    if not entry or entry.get(key) is None:
        return "—"
    return f"{num(entry[key], digits, signed)} {ci(entry.get('ci95'), digits, signed)}".strip()


# Figures ---------------------------------------------------------------------


def reliability_grid(reliability: dict, groups: list[str], title: str) -> str:
    """Small multiples: rows are groups, columns are horizons."""
    panel, pad, left, top = 128, 26, 150, 46
    width = left + (panel + pad) * len(pipeline.HORIZON_NAMES) + 10
    height = top + (panel + pad) * len(groups) + 30
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{html.escape(title)}">'
    ]
    for col, horizon in enumerate(pipeline.HORIZON_NAMES):
        x0 = left + col * (panel + pad)
        parts.append(
            f'<text class="title" x="{x0 + panel / 2}" y="{top - 14}" '
            f'text-anchor="middle">{HORIZON_LABELS[horizon]}</text>'
        )
    for row, group in enumerate(groups):
        y0 = top + row * (panel + pad)
        parts.append(
            f'<text x="{left - 12}" y="{y0 + panel / 2 + 4}" text-anchor="end">'
            f"{html.escape(GROUP_LABELS.get(group, group))}</text>"
        )
        for col, horizon in enumerate(pipeline.HORIZON_NAMES):
            x0 = left + col * (panel + pad)
            summary = reliability.get(horizon, {}).get(group, {})

            def sx(v: float) -> float:
                return x0 + v * panel

            def sy(v: float) -> float:
                return y0 + (1 - v) * panel

            parts.append(
                f'<rect x="{x0}" y="{y0}" width="{panel}" height="{panel}" '
                'fill="none" class="grid"/>'
            )
            parts.append(
                f'<line class="zero" x1="{sx(0)}" y1="{sy(0)}" x2="{sx(1)}" y2="{sy(1)}"/>'
            )
            if row == len(groups) - 1:
                for tick in (0, 0.5, 1):
                    parts.append(
                        f'<text x="{sx(tick)}" y="{y0 + panel + 14}" '
                        f'text-anchor="middle">{tick:g}</text>'
                    )
            if not summary.get("n"):
                parts.append(
                    f'<text x="{x0 + panel / 2}" y="{y0 + panel / 2}" '
                    'text-anchor="middle">no markets</text>'
                )
                continue
            for b in summary["bins"]:
                if not b["n"]:
                    continue
                x, y = sx(b["meanP"]), sy(b["freq"])
                lo, hi = b.get("ci95", [None, None])
                if lo is not None and lo == lo:
                    parts.append(
                        f'<line class="mean" x1="{x:.1f}" x2="{x:.1f}" '
                        f'y1="{sy(lo):.1f}" y2="{sy(hi):.1f}"/>'
                    )
                radius = max(2.0, min(6.0, b["n"] ** 0.5 / 4))
                label = (
                    f"{GROUP_LABELS.get(group, group)}, {HORIZON_LABELS[horizon]}, "
                    f"prices {b['lo']:.1f}-{b['hi']:.1f}: {int(b['n'])} markets, mean price "
                    f"{b['meanP']:.3f}, YES rate {b['freq']:.3f}"
                    + (f" [{lo:.3f}, {hi:.3f}]" if lo is not None and lo == lo else "")
                )
                parts.append(
                    f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}">'
                    f"<title>{html.escape(label)}</title></circle>"
                )
            parts.append(
                f'<text x="{x0 + 4}" y="{y0 + 13}">n={int(summary["n"])}</text>'
            )
    parts.append(
        f'<text x="{left}" y="{height - 6}">x: Kalshi price (bin mean); y: share of '
        "markets that settled YES; whiskers: 95% release-date cluster bootstrap; "
        "diagonal: perfect calibration</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


# Tables ----------------------------------------------------------------------


def coverage_rows(results: dict) -> list[list[str]]:
    inventory = results["inventory"]
    settlement = results["settlement"]
    rows = []
    for series in history.SERIES:
        items = [r for r in inventory if r["series"] == series]
        settled = [r for r in items if r["settled"]]
        readable = [r for r in settled if r["period"]]
        printed = [r for r in readable if r["officialValue"] is not None]
        markets = [s for s in settlement if s["series"] == series and "agrees" in s]
        disagree = [s for s in markets if not s["agrees"]]
        first = min((r["period"] for r in readable), default="—")
        last = max((r["period"] for r in readable), default="—")
        legacy = sum(1 for r in readable if r["generation"] == "legacy")
        rows.append(
            [
                f"`{series}`",
                SERIES_LABELS[series],
                str(len(items)),
                str(len(settled)),
                f"{first} to {last}",
                str(legacy),
                str(len(printed)),
                str(len(readable) - len(printed)),
                str(len(settled) - len(readable)),
                f"{len(markets) - len(disagree)} / {len(markets)}",
            ]
        )
    return rows


def compression_rows(compression: dict, groups=("all",)) -> list[list[str]]:
    rows = []
    for horizon in pipeline.HORIZON_NAMES:
        for group in groups:
            fit = compression[horizon].get(group, {})
            if "beta" not in fit:
                continue
            rows.append(
                [
                    HORIZON_LABELS[horizon],
                    GROUP_LABELS.get(group, group),
                    str(fit["n"]),
                    str(fit["clusters"]),
                    f"{num(fit['beta'])} {ci(fit['betaCi95'])}",
                    f"{num(fit['alpha'], signed=True)} {ci(fit['alphaCi95'], signed=True)}",
                    fit["verdict"],
                ]
            )
    return rows


def reliability_rows(reliability: dict, groups) -> list[list[str]]:
    rows = []
    for horizon in pipeline.HORIZON_NAMES:
        for group in groups:
            s = reliability[horizon].get(group, {})
            if not s.get("n"):
                continue
            c = s.get("ci95", {})
            rows.append(
                [
                    HORIZON_LABELS[horizon],
                    GROUP_LABELS.get(group, group),
                    str(int(s["n"])),
                    str(s.get("events", "")),
                    str(s.get("clusters", "")),
                    f"{num(s['brier'], 3)} {ci(c.get('brier'), 3)}",
                    f"{num(s['ece'], 3)} {ci(c.get('ece'), 3)}",
                    f"{num(s['belowHalf'], 3, True)} {ci(c.get('belowHalf'), 3, True)}",
                    f"{num(s['aboveHalf'], 3, True)} {ci(c.get('aboveHalf'), 3, True)}",
                ]
            )
    return rows


def event_score_rows(scores: dict, groups) -> list[list[str]]:
    rows = []
    for horizon in pipeline.HORIZON_NAMES:
        for group in groups:
            e = scores[horizon].get(group, {})
            if not e.get("events"):
                continue
            label = GROUP_LABELS.get(group) or SERIES_LABELS.get(group, group)
            few = group in history.SERIES and e["events"] < MIN_SERIES_EVENTS
            rows.append(
                [
                    HORIZON_LABELS[horizon],
                    label + (" (too few events to conclude)" if few else ""),
                    str(e["events"]),
                    with_ci(e["log"], signed=True),
                    with_ci(e["brier"], digits=3),
                    with_ci(e["ladderBrier"], digits=3),
                    str(e["floorHits"]),
                ]
            )
    return rows


def oos_rows(oos: dict, groups) -> list[list[str]]:
    rows = []
    for horizon in pipeline.HORIZON_NAMES:
        for group in groups:
            o = oos[horizon].get(group, {})
            if not o.get("folds"):
                continue
            cells = [HORIZON_LABELS[horizon], GROUP_LABELS.get(group, group), str(o["folds"]),
                     str(o["skippedFolds"]), str(o["testMarkets"])]
            for model in ("logistic", "beta"):
                m = o["models"][model]
                cells.append(with_ci(m.get("binaryLog"), digits=4, signed=True))
                cells.append(with_ci(m.get("bracketLog"), digits=3, signed=True))
            rows.append(cells)
    return rows


def sensitivity_rows(sens: dict) -> list[list[str]]:
    rows = []
    logistic = {tuple(r[k] for k in ("spec", "horizon", "subset", "metric")): r
                for r in sens["models"]["logistic"]["comparison"]}
    beta = {tuple(r[k] for k in ("spec", "horizon", "subset", "metric")): r
            for r in sens["models"]["beta"]["comparison"]}
    for key, row in logistic.items():
        other = beta.get(key, {})
        rows.append(
            [
                key[0], key[1], key[2], key[3],
                f"{row['nBefore']}",
                f"{num(row['meanBefore'], signed=True)} {ci(row['ciBefore'], signed=True)}",
                f"{num(row.get('meanAfter'), signed=True)} {ci(row.get('ciAfter'), signed=True)}",
                f"{num(other.get('meanAfter'), signed=True)} {ci(other.get('ciAfter'), signed=True)}",
                ", ".join(
                    name for name, r in (("logistic", row), ("beta", other)) if r.get("changes")
                ) or "no change",
            ]
        )
    return rows


# Writing -----------------------------------------------------------------------


FLAT_FIELDS_DROP = ("raw", "repaired", "brackets", "strikes")


def write(results: dict, out: pathlib.Path, summary_lines: list[str] | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "inventory.csv", results["inventory"])
    write_csv(out / "settlement.csv", results["settlement"])
    write_csv(out / "exclusions.csv", results["exclusions"])
    write_csv(out / "binary_rows.csv", results["binaryRows"])
    write_csv(out / "paper_rows.csv", results["paperRows"])
    write_csv(out / "event_rows.csv", results["eventRows"])
    (out / "analyses.json").write_text(json.dumps(results["analyses"], indent=1, default=str) + "\n")
    doc, figures = build(results, summary_lines or [])
    for name, svg in figures.items():
        (out / name).write_text(svg + "\n")
    (out / "REPORT.md").write_text(doc.markdown())
    (out / "REPORT.html").write_text(doc.html("Kalshi's calibration on economic releases"))


def build(results: dict, summary_lines: list[str]) -> tuple[Doc, dict[str, str]]:
    a = results["analyses"]
    meta = results["meta"]
    doc = Doc()
    figures: dict[str, str] = {}
    doc.h(1, "Kalshi's calibration on economic releases")
    doc.p(
        "Read-only study. It places no orders, uses no Kalshi account and simulates no "
        f"trading; every Kalshi number is public market data. Data as of {meta['asOf']}. "
        "The analysis plan is `docs/kalshi-econ-calibration.md` in "
        "[ThesisInstitute/thesis#391](https://github.com/ThesisInstitute/thesis/pull/391); "
        "it was committed before any Kalshi price was compared with an outcome, and its "
        "last section lists every later change."
    )
    doc.h(2, "Summary")
    doc.ul(summary_lines or ["(summary to be written from the numbers below)"])

    doc.h(2, "What was scored")
    doc.table(
        ["Series", "Statistic", "Events listed", "Settled", "Periods", "Legacy tickers",
         "Official print", "No official print", "Period unreadable",
         "Markets agreeing with Kalshi's result"],
        coverage_rows(results),
        "Events listed are every event Kalshi returns for the series ticker (KXUE: "
        "Australian events only). Legacy tickers are events Kalshi lists inside the "
        "series under an older ticker (for example `CPI-21JUN`). The last column applies "
        "each event's official first print to each market's rule.",
    )
    settlement = results["settlement"]
    disagreements = [s for s in settlement if s.get("agrees") is False]
    no_print = [r for r in results["inventory"] if r["settled"] and r["period"] and r["officialValue"] is None]
    unread = [r for r in results["inventory"] if r["settled"] and not r["period"]]
    doc.h(3, "Where the official print and Kalshi's settlement differ")
    if disagreements:
        doc.table(
            ["Market", "Strike", "Official print", "Official result", "Kalshi result", "Kalshi's recorded value"],
            [[f"`{s['ticker']}`", s["strike"], s["officialValue"], s["officialResult"],
              s["kalshiResult"], s["kalshiExpirationValue"] or "—"] for s in disagreements],
            "The official print governs every primary result; the Kalshi-results "
            "sensitivity uses Kalshi's settlement instead.",
        )
    else:
        doc.p("None: every market agrees.")
    doc.h(3, "Events with no official print or no readable period")
    doc.table(
        ["Event", "Period", "Why"],
        [[f"`{r['eventTicker']}`", r["period"] or "—", r["officialNote"] or r["periodCheck"]]
         for r in no_print + unread],
    )
    expiration = Counter(r["expirationAgrees"] for r in results["inventory"] if r["officialValue"] is not None)
    doc.p(
        f"Kalshi's recorded underlying value (`expiration_value`) equals the official print "
        f"for {expiration.get(True, 0)} events and differs for {expiration.get(False, 0)}; "
        f"{expiration.get(None, 0)} events record no single number."
    )
    if results["duplicatePeriods"]:
        doc.p(
            "Kalshi lists more than one event for "
            + "; ".join(f"{d['series']} {d['period']} ({', '.join(d['events'])})" for d in results["duplicatePeriods"])
            + ". Both are scored and share a release-date cluster."
        )

    doc.h(2, "Compression toward 50%")
    doc.p(
        "Logistic calibration fits logit P(YES) = α + β logit(price) on every binary "
        "market at a horizon. β above 1 means outcomes are more extreme than prices "
        "(prices compressed toward 50%, the pattern the paper reports for Kalshi); β "
        "below 1 means prices are too extreme. Intervals are 95% percentile intervals "
        f"from {meta['refitDraws']:,} release-date cluster bootstrap draws, refitting "
        "each draw."
    )
    doc.table(
        ["Horizon", "Group", "Markets", "Release dates", "β [95%]", "α [95%]", "Reading"],
        compression_rows(a["compression"], groups=pipeline.GROUPS),
        "The six all-series rows are the primary tests; family rows are secondary.",
    )

    doc.h(2, "Reliability")
    figures["figure_reliability.svg"] = reliability_grid(
        a["reliability"], list(pipeline.GROUPS), "Reliability diagrams by family and horizon"
    )
    doc.figure(
        figures["figure_reliability.svg"],
        "Reliability by family (rows) and horizon (columns). Each dot is a tenth of the "
        "price range; whiskers are 95% release-date cluster bootstrap intervals for the "
        "share that settled YES.",
        "figure_reliability.svg",
    )
    doc.table(
        ["Horizon", "Group", "Markets", "Events", "Release dates", "Brier [95%]",
         "ECE [95%]", "Mean of y − p, p < 0.5", "Mean of y − p, p > 0.5"],
        reliability_rows(a["reliability"], pipeline.GROUPS),
        "The paper's Kalshi pattern would show as a negative mean of y − p below 0.5 "
        "and a positive one above 0.5.",
    )

    doc.h(2, "Scores on Kalshi's own brackets")
    doc.p(
        "Each event's repaired ladder gives its bracket probabilities, scored on the "
        "realized bracket under the official print (#381's rules: 0.001 floor for the "
        "log score, multi-category Brier from 0 to 2, and the ladder Brier over the "
        "event's binary markets). Intervals resample release dates."
    )
    doc.table(
        ["Horizon", "Group", "Events", "Log score", "Brier", "Ladder Brier", "Floor hits"],
        event_score_rows(a["eventScores"], list(pipeline.GROUPS) + list(history.SERIES)),
    )

    doc.h(2, "Out-of-sample recalibration")
    doc.p(
        "Each release date is a test fold, trained only on markets whose release came "
        "before the fold's earliest horizon instant; folds with fewer than "
        f"{meta['minTrainClusters']} earlier release dates are skipped. Values are the "
        "mean improvement over raw prices (positive: recalibration helped), averaged "
        "over folds, with release-date bootstrap intervals."
    )
    doc.table(
        ["Horizon", "Group", "Folds", "Skipped", "Test markets",
         "Logistic: binary log loss", "Logistic: bracket log score",
         "Beta: binary log loss", "Beta: bracket log score"],
        oos_rows(a["outOfSample"], pipeline.GROUPS),
    )

    if "sensitivity381" in a:
        sens = a["sensitivity381"]
        doc.h(2, "Sensitivity: a recalibrated Kalshi baseline in #381")
        doc.p(
            "#381's pre-registered results are unchanged. Here Kalshi's ladder in each "
            "#381 pair is replaced by the recalibrated ladder, with maps trained only on "
            "markets released before that pair's horizon instant, and #381's own code "
            f"recomputes its summaries. #381's code on its frozen scores reproduces its "
            f"published summary: {'yes' if sens['reproducesFrozenSummary'] else 'NO'}."
        )
        doc.table(
            ["#381 rule", "Horizon", "Subset", "Score", "Events", "#381 [95%, release dates]",
             "Logistic-recalibrated Kalshi", "Beta-recalibrated Kalshi", "Changes a conclusion?"],
            sensitivity_rows(sens),
            "Positive differences favor Thesis. A change is a flip in the mean's sign or "
            "in whether the release-clustered interval includes zero.",
        )

    doc.h(2, "Sensitivity analyses")
    for key, label in (
        ("compressionRaw", "Unrepaired midpoints"),
        ("compressionLiquid", "Quotes with spreads of 20 cents or less"),
        ("compressionPaper", "Paper-matched: last traded price, life from first trade"),
        ("compressionPaperVolume", "Paper-matched, lifetime volume above 20,000 contracts"),
        ("compressionKalshiResults", "Kalshi's recorded results as outcomes"),
    ):
        doc.h(3, label)
        doc.table(
            ["Horizon", "Group", "Markets", "Release dates", "β [95%]", "α [95%]", "Reading"],
            compression_rows(a[key]),
        )
    for split in ("generation", "era", "volume"):
        rel = a[f"reliabilityBy_{split}"]
        groups = sorted({g for h in rel.values() for g in h})
        doc.h(3, f"By {split}")
        doc.table(
            ["Horizon", "Class", "Markets", "Events", "Release dates", "Brier [95%]",
             "ECE [95%]", "Mean of y − p, p < 0.5", "Mean of y − p, p > 0.5"],
            reliability_rows(rel, groups),
        )

    doc.h(2, "What this does and does not measure")
    doc.p(
        "It measures the calibration and accuracy of Kalshi's prices on twelve economic "
        "release series at stated horizons, against the official first print. It says "
        "nothing about Kalshi in other categories or about any trading strategy, and it "
        "does not test the paper's pooled result."
    )
    doc.h(2, "Reproduce")
    doc.p(
        "`python3 scripts/kalshi_calibration_study.py --out <dir> --cache "
        "~/reviews/kalshi-econ-calibration-2026-10/fetch --as-of "
        f"{meta['asOf']} --repro381 ~/reviews/thesis-vs-kalshi-2026-10/results/results.json "
        "--offline`"
    )
    return doc, figures


# Summary ---------------------------------------------------------------------


def summary_lines(results: dict) -> list[str]:
    """Summary bullets built from the computed numbers only."""
    a = results["analyses"]
    inventory = results["inventory"]
    printed = [r for r in inventory if r["officialValue"] is not None]
    settled = [r for r in inventory if r["settled"]]
    markets = [s for s in results["settlement"] if "agrees" in s]
    disagree = [s for s in markets if not s["agrees"]]
    periods = sorted(r["period"] for r in printed)
    lines = [
        f"**Scope.** {len(settled)} settled Kalshi events in the twelve series, "
        f"{len(printed)} of them with an official first print ({periods[0]} to "
        f"{periods[-1]}), covering {len(markets)} binary markets. Applying each print "
        f"to each market's rule reproduces Kalshi's recorded result for "
        f"{len(markets) - len(disagree)} of {len(markets)} markets"
        + (
            "; the exceptions are "
            + ", ".join(f"`{s['ticker']}`" for s in disagree)
            + ", listed below."
            if disagree
            else "."
        ),
    ]
    parts = []
    for horizon in pipeline.HORIZON_NAMES:
        fit = a["compression"][horizon]["all"]
        parts.append(
            f"{HORIZON_LABELS[horizon]} β = {num(fit['beta'])} {ci(fit['betaCi95'])}"
            f" ({fit['verdict']})"
        )
    lines.append(
        "**Compression toward 50%.** Logistic calibration slopes, all series pooled "
        "(β above 1 would mean prices sit too close to 50%): " + "; ".join(parts) + "."
    )
    rel = a["reliability"]["life_25"]["all"]
    lines.append(
        "**The paper's pattern at 25% of market life** (its headline time point): the "
        f"mean of outcome minus price is {num(rel['belowHalf'], 3, True)} "
        f"{ci(rel['ci95']['belowHalf'], 3, True)} for prices below 0.5 and "
        f"{num(rel['aboveHalf'], 3, True)} {ci(rel['ci95']['aboveHalf'], 3, True)} above "
        "0.5; the paper's Kalshi pattern would make the first negative and the second "
        "positive."
    )
    oos = []
    for horizon in pipeline.HORIZON_NAMES:
        o = a["outOfSample"][horizon]["all"]
        if not o.get("folds"):
            continue
        cells = []
        for model in ("logistic", "beta"):
            m = o["models"][model]["binaryLog"]
            cells.append(f"{model} {num(m['mean'], 4, True)} {ci(m['ci95'], 4, True)}")
        oos.append(f"{HORIZON_LABELS[horizon]}: " + ", ".join(cells))
    lines.append(
        "**Out-of-sample recalibration** (mean improvement in binary log loss per "
        "release date, positive means recalibration helped): " + "; ".join(oos) + "."
    )
    if "sensitivity381" in a:
        sens = a["sensitivity381"]
        changed = {
            model: sens["models"][model]["changes"] for model in ("logistic", "beta")
        }
        if not any(changed.values()):
            lines.append(
                "**#381.** Replacing Kalshi with its recalibrated prices changes none of "
                "#381's pooled conclusions (no sign flips, and no interval moves across "
                "zero), under either map. #381's own results are unchanged."
            )
        else:
            lines.append(
                "**#381.** Replacing Kalshi with its recalibrated prices changes "
                + "; ".join(
                    f"{model}: "
                    + ", ".join(
                        f"{r['spec']} {r['horizon']} {r['subset']} {r['metric']}"
                        for r in rows
                    )
                    for model, rows in changed.items()
                    if rows
                )
                + " (sensitivity only; #381's pre-registered results stand)."
            )
    return lines
