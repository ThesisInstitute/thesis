"""Report: REPORT.md, REPORT.html, reliability figures, CSV tables."""

from __future__ import annotations

import html
import json
import pathlib
from collections import Counter

from kalshi_compare.report import Doc, write_csv

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


def with_ci(
    entry: dict | None, key: str = "mean", digits: int = 2, signed: bool = False
) -> str:
    if not entry or entry.get(key) is None:
        return "—"
    value = num(entry[key], digits, signed)
    return f"{value} {ci(entry.get('ci95'), digits, signed)}".strip()


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
                'fill="none" stroke="#dddcd7" class="grid"/>'
            )
            parts.append(
                '<line class="zero" stroke="#8a8983" stroke-width="1.5" '
                f'x1="{sx(0)}" y1="{sy(0)}" x2="{sx(1)}"'
                f' y2="{sy(1)}"/>'
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
                        f'<line class="mean" stroke="#0b0b0b" x1="{x:.1f}" '
                        f'x2="{x:.1f}" '
                        f'y1="{sy(lo):.1f}" y2="{sy(hi):.1f}"/>'
                    )
                radius = max(2.0, min(6.0, b["n"] ** 0.5 / 4))
                label = (
                    f"{GROUP_LABELS.get(group, group)}, {HORIZON_LABELS[horizon]},"
                    f" prices {b['lo']:.1f}-{b['hi']:.1f}: {int(b['n'])} markets, mean"
                    f" price {b['meanP']:.3f}, YES rate {b['freq']:.3f}"
                    + (f" [{lo:.3f}, {hi:.3f}]" if lo is not None and lo == lo else "")
                )
                parts.append(
                    f'<circle class="dot" fill="#2a78d6" cx="{x:.1f}" '
                    f'cy="{y:.1f}" r="{radius:.1f}">'
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
                    (GROUP_LABELS.get(group) or SERIES_LABELS.get(group, group))
                    + (
                        " (too few events to conclude)"
                        if group in history.SERIES
                        and fit.get("events", MIN_SERIES_EVENTS) < MIN_SERIES_EVENTS
                        else ""
                    ),
                    str(fit["n"]),
                    str(fit["clusters"]),
                    f"{num(fit['beta'])} {ci(fit['betaCi95'])}",
                    (
                        f"{num(fit['alpha'], signed=True)}"
                        f" {ci(fit['alphaCi95'], signed=True)}"
                    ),
                    fit["verdict"]
                    + (
                        f" ({fit['nonConvergedDraws']:,} of {fit['draws']:,} draws did"
                        " not converge)"
                        if fit.get("nonConvergedDraws")
                        else ""
                    ),
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
                    f"{num(s['reliability'], 4)} {ci(c.get('reliability'), 4)}",
                    f"{num(s['resolution'], 3)} {ci(c.get('resolution'), 3)}",
                    num(s["uncertainty"], 3),
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


def oos_rows(oos: dict, groups, metrics=("binaryLog", "bracketLog")) -> list[list[str]]:
    rows = []
    for horizon in pipeline.HORIZON_NAMES:
        for group in groups:
            o = oos[horizon].get(group, {})
            if not o.get("folds"):
                continue
            cells = [
                HORIZON_LABELS[horizon],
                GROUP_LABELS.get(group, group),
                str(o["folds"]),
                str(o["skippedFolds"]),
                str(o["testMarkets"]),
            ]
            for model in ("logistic", "beta"):
                m = o["models"][model]
                cells.append(with_ci(m.get(metrics[0]), digits=4, signed=True))
                cells.append(with_ci(m.get(metrics[1]), digits=3, signed=True))
            rows.append(cells)
    return rows


def sensitivity_rows(sens: dict) -> list[list[str]]:
    from .sensitivity import QUOTED_IN_381_SUMMARY

    rows = []
    logistic = {
        tuple(r[k] for k in ("spec", "horizon", "subset", "metric")): r
        for r in sens["models"]["logistic"]["comparison"]
    }
    beta = {
        tuple(r[k] for k in ("spec", "horizon", "subset", "metric")): r
        for r in sens["models"]["beta"]["comparison"]
    }
    for key, row in logistic.items():
        other = beta.get(key, {})
        rows.append(
            [
                key[0],
                key[1],
                key[2],
                key[3],
                f"{row['nBefore']}",
                (
                    f"{num(row['meanBefore'], signed=True)}"
                    f" {ci(row['ciBefore'], signed=True)}"
                ),
                (
                    f"{num(row.get('meanAfter'), signed=True)}"
                    f" {ci(row.get('ciAfter'), signed=True)}"
                ),
                (
                    f"{num(other.get('meanAfter'), signed=True)}"
                    f" {ci(other.get('ciAfter'), signed=True)}"
                ),
                ", ".join(
                    name
                    for name, r in (("logistic", row), ("beta", other))
                    if r.get("changes")
                )
                or "no change",
                QUOTED_IN_381_SUMMARY.get(key, ""),
            ]
        )
    return rows


# Writing -----------------------------------------------------------------------


FLAT_FIELDS_DROP = ("raw", "repaired", "brackets", "strikes")


def reliability_bin_rows(analyses: dict) -> list[dict]:
    """Every bin of every reliability table: counts, mean price, YES share, interval."""
    rows = []
    for key, value in analyses.items():
        if not key.startswith("reliability"):
            continue
        for horizon, groups in value.items():
            for group, summary in groups.items():
                for b in summary.get("bins", []):
                    rows.append(
                        {
                            "analysis": key,
                            "horizon": horizon,
                            "group": group,
                            "binLo": b["lo"],
                            "binHi": b["hi"],
                            "markets": b["n"],
                            "events": b.get("events"),
                            "releaseDates": b.get("clusters"),
                            "meanPrice": b["meanP"],
                            "yesShare": b["freq"],
                            "yesShareCi95": b.get("ci95"),
                        }
                    )
    return rows


def compression_csv_rows(analyses: dict) -> list[dict]:
    rows = []
    for key, value in analyses.items():
        if not key.startswith("compression"):
            continue
        for horizon, groups in value.items():
            for group, fit in groups.items():
                rows.append(
                    {"analysis": key, "horizon": horizon, "group": group, **fit}
                )
    return rows


def oos_csv_rows(analyses: dict) -> list[dict]:
    rows = []
    for key, value in analyses.items():
        if not key.startswith("outOfSample"):
            continue
        for horizon, groups in value.items():
            for group, entry in groups.items():
                for model, metrics in entry.get("models", {}).items():
                    for metric, result in metrics.items():
                        rows.append(
                            {
                                "analysis": key,
                                "horizon": horizon,
                                "group": group,
                                "model": model,
                                "metric": metric,
                                "folds": result.get("folds"),
                                "meanImprovement": result.get("mean"),
                                "ci95": result.get("ci95"),
                            }
                        )
    return rows


def write(
    results: dict, out: pathlib.Path, summary_lines: list[str] | None = None
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "inventory.csv", results["inventory"])
    write_csv(out / "settlement.csv", results["settlement"])
    write_csv(out / "exclusions.csv", results["exclusions"])
    write_csv(out / "binary_rows.csv", results["binaryRows"])
    write_csv(out / "paper_rows.csv", results["paperRows"])
    write_csv(out / "event_rows.csv", results["eventRows"])
    (out / "analyses.json").write_text(
        json.dumps(results["analyses"], indent=1, default=str) + "\n"
    )
    write_csv(out / "reliability_bins.csv", reliability_bin_rows(results["analyses"]))
    write_csv(out / "compression.csv", compression_csv_rows(results["analyses"]))
    write_csv(out / "out_of_sample.csv", oos_csv_rows(results["analyses"]))
    doc, figures = build(results, summary_lines or [])
    for name, svg in figures.items():
        (out / name).write_text(svg + "\n")
    (out / "REPORT.md").write_text(doc.markdown())
    (out / "REPORT.html").write_text(
        doc.html("Kalshi's calibration on economic releases")
    )


def build(results: dict, summary_lines: list[str]) -> tuple[Doc, dict[str, str]]:
    a = results["analyses"]
    meta = results["meta"]
    doc = Doc()
    figures: dict[str, str] = {}
    doc.h(1, "Kalshi's calibration on economic releases")
    doc.p(
        "Read-only study. It places no orders, uses no Kalshi account and simulates no"
        " trading; every Kalshi number is public market data. Data as of"
        f" {meta['asOf']}. The analysis plan is `docs/kalshi-econ-calibration.md` in"
        " [ThesisInstitute/thesis#391](https://github.com/ThesisInstitute/thesis/pull/391);"
        " it was committed before any Kalshi price was compared with an outcome, and"
        " its last section lists every later change."
    )
    doc.h(2, "Summary")
    doc.ul(summary_lines or ["(summary to be written from the numbers below)"])

    doc.h(2, "What was scored")
    doc.table(
        [
            "Series",
            "Statistic",
            "Events listed",
            "Settled",
            "Periods",
            "Legacy tickers",
            "Official print",
            "No official print",
            "Period unreadable",
            "Markets agreeing with Kalshi's result",
        ],
        coverage_rows(results),
        "Events listed are every event Kalshi returns for the series ticker (KXUE:"
        " Australian events only). Legacy tickers are events Kalshi lists inside the"
        " series under an older ticker (for example `CPI-21JUN`). The last column"
        " applies each event's official first print to each market's rule.",
    )
    settlement = results["settlement"]
    disagreements = [s for s in settlement if s.get("agrees") is False]
    no_print = [
        r
        for r in results["inventory"]
        if r["settled"] and r["period"] and r["officialValue"] is None
    ]
    unread = [r for r in results["inventory"] if r["settled"] and not r["period"]]
    doc.h(3, "Where the official print and Kalshi's settlement differ")
    if disagreements:
        doc.table(
            [
                "Market",
                "Strike",
                "Official print",
                "Official result",
                "Kalshi result",
                "Kalshi's recorded value",
            ],
            [
                [
                    f"`{s['ticker']}`",
                    s["strike"],
                    s["officialValue"],
                    s["officialResult"],
                    s["kalshiResult"],
                    s["kalshiExpirationValue"] or "—",
                ]
                for s in disagreements
            ],
            "The official print governs every primary result; the Kalshi-results "
            "sensitivity uses Kalshi's settlement instead.",
        )
    else:
        doc.p("None: every market agrees.")
    doc.h(3, "Events with no official print or no readable period")
    doc.table(
        ["Event", "Period", "Why"],
        [
            [
                f"`{r['eventTicker']}`",
                r["period"] or "—",
                r["officialNote"] or r["periodCheck"],
            ]
            for r in no_print + unread
        ],
    )
    expiration = Counter(
        r["expirationAgrees"]
        for r in results["inventory"]
        if r["officialValue"] is not None
    )
    doc.p(
        "Kalshi's recorded underlying value (`expiration_value`) equals the official"
        f" print for {expiration.get(True, 0)} events and differs for"
        f" {expiration.get(False, 0)}; {expiration.get(None, 0)} events record no"
        " single number."
    )
    late = results.get("lateCloses", [])
    doc.p(
        f"Markets that closed after their event's release: {len(late)}"
        + (": " + ", ".join(f"`{m['ticker']}`" for m in late) if late else "")
        + ". A market's life for the life fractions ends at the release in any case."
    )
    if results["duplicatePeriods"]:
        doc.p(
            "Kalshi lists more than one event for "
            + "; ".join(
                f"{d['series']} {d['period']} ({', '.join(d['events'])})"
                for d in results["duplicatePeriods"]
            )
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
        [
            "Horizon",
            "Group",
            "Markets",
            "Release dates",
            "β [95%]",
            "α [95%]",
            "Reading",
        ],
        compression_rows(a["compression"], groups=pipeline.GROUPS),
        "The six all-series rows are the primary tests; family rows are secondary."
        " Where some bootstrap refits did not converge (few release dates, outcomes"
        " separated by price), the interval uses the converged draws only and is"
        " not reliable.",
    )

    doc.h(2, "Reliability")
    figures["figure_reliability.svg"] = reliability_grid(
        a["reliability"],
        list(pipeline.GROUPS),
        "Reliability diagrams by family and horizon",
    )
    doc.figure(
        figures["figure_reliability.svg"],
        "Reliability by family (rows) and horizon (columns). Each dot is a tenth of the"
        " price range; whiskers are 95% release-date cluster bootstrap intervals for"
        " the share that settled YES.",
        "figure_reliability.svg",
    )
    doc.table(
        [
            "Horizon",
            "Group",
            "Markets",
            "Events",
            "Release dates",
            "Brier [95%]",
            "Reliability",
            "Resolution",
            "Uncertainty",
            "ECE [95%]",
            "Mean of y − p, p < 0.5",
            "Mean of y − p, p > 0.5",
        ],
        reliability_rows(a["reliability"], pipeline.GROUPS),
        "The paper's Kalshi pattern would show as a negative mean of y − p below 0.5 "
        "and a positive one above 0.5. ECE is an average of absolute gaps, so it runs "
        "higher in resamples than in the data, and its interval can lie above the "
        "point estimate.",
    )

    doc.h(2, "Scores on Kalshi's own brackets")
    doc.p(
        "Each event's repaired ladder gives its bracket probabilities, scored on the "
        "realized bracket under the official print (#381's rules: 0.001 floor for the "
        "log score, multi-category Brier from 0 to 2, and the ladder Brier over the "
        "event's binary markets). Intervals resample release dates."
    )
    doc.table(
        [
            "Horizon",
            "Group",
            "Events",
            "Log score",
            "Brier",
            "Ladder Brier",
            "Floor hits",
        ],
        event_score_rows(
            a["eventScores"], list(pipeline.GROUPS) + list(history.SERIES)
        ),
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
        [
            "Horizon",
            "Group",
            "Folds",
            "Skipped",
            "Test markets",
            "Logistic: binary log loss",
            "Logistic: bracket log score",
            "Beta: binary log loss",
            "Beta: bracket log score",
        ],
        oos_rows(a["outOfSample"], pipeline.GROUPS),
    )
    doc.table(
        [
            "Horizon",
            "Group",
            "Folds",
            "Skipped",
            "Test markets",
            "Logistic: binary Brier",
            "Logistic: bracket Brier",
            "Beta: binary Brier",
            "Beta: bracket Brier",
        ],
        oos_rows(a["outOfSample"], pipeline.GROUPS, ("binaryBrier", "bracketBrier")),
        "The same folds scored with Brier scores; positive means recalibration"
        " lowered (improved) the Brier score.",
    )

    if "sensitivity381" in a:
        sens = a["sensitivity381"]
        doc.h(2, "Sensitivity: a recalibrated Kalshi baseline in #381")
        doc.p(
            "#381's pre-registered results are unchanged. Here Kalshi's ladder in each"
            " #381 pair is replaced by the recalibrated ladder, with maps trained only"
            " on markets released before that pair's horizon instant, and #381's own"
            " code recomputes its summaries. #381's code on its frozen scores"
            " reproduces its published summary:"
            f" {'yes' if sens['reproducesFrozenSummary'] else 'NO'}."
        )
        doc.table(
            [
                "#381 rule",
                "Horizon",
                "Subset",
                "Score",
                "Events",
                "#381 [95%, release dates]",
                "Logistic-recalibrated Kalshi",
                "Beta-recalibrated Kalshi",
                "Changes a conclusion?",
                "Quoted in #381's Summary as",
            ],
            sensitivity_rows(sens),
            "Positive differences favor Thesis. A change is a flip in the mean's sign"
            " or in whether the release-clustered interval includes zero.",
        )

    doc.h(2, "Sensitivity analyses")
    for key, label in (
        ("compressionByEvent", "Intervals resampling events instead of release dates"),
        ("compressionRaw", "Unrepaired midpoints"),
        ("compressionLiquid", "Quotes with spreads of 20 cents or less"),
        ("compressionPaper", "Paper-matched: last traded price, life from first trade"),
        (
            "compressionPaperVolume",
            "Paper-matched, lifetime volume above 20,000 contracts",
        ),
        ("compressionKalshiResults", "Kalshi's recorded results as outcomes"),
        (
            "compressionInterior",
            "Prices from 0.05 to 0.95 only (added after the CPI test run)",
        ),
    ):
        doc.h(3, label)
        doc.table(
            [
                "Horizon",
                "Group",
                "Markets",
                "Release dates",
                "β [95%]",
                "α [95%]",
                "Reading",
            ],
            compression_rows(a[key]),
        )
    doc.h(3, "Compression by series")
    doc.table(
        [
            "Horizon",
            "Series",
            "Markets",
            "Release dates",
            "β [95%]",
            "α [95%]",
            "Reading",
        ],
        compression_rows(a["compressionBySeries"], groups=history.SERIES),
    )
    doc.h(3, "Out-of-sample recalibration with Kalshi's recorded results")
    doc.table(
        [
            "Horizon",
            "Group",
            "Folds",
            "Skipped",
            "Test markets",
            "Logistic: binary log loss",
            "Logistic: bracket log score",
            "Beta: binary log loss",
            "Beta: bracket log score",
        ],
        oos_rows(a["outOfSampleKalshiResults"], ["all"]),
    )
    doc.h(3, "Scores on Kalshi's brackets, intervals resampling events")
    doc.table(
        [
            "Horizon",
            "Group",
            "Events",
            "Log score",
            "Brier",
            "Ladder Brier",
            "Floor hits",
        ],
        event_score_rows(a["eventScoresByEvent"], ["all"]),
    )
    for split in ("series", "generation", "era", "volume"):
        rel = a[f"reliabilityBy_{split}"]
        groups = sorted({g for h in rel.values() for g in h})
        doc.h(3, f"By {split}")
        doc.table(
            [
                "Horizon",
                "Class",
                "Markets",
                "Events",
                "Release dates",
                "Brier [95%]",
                "ECE [95%]",
                "Mean of y − p, p < 0.5",
                "Mean of y − p, p > 0.5",
            ],
            reliability_rows(rel, groups),
        )

    doc.h(2, "What this does and does not measure")
    doc.p(
        "It measures the calibration and accuracy of Kalshi's prices on twelve economic"
        " release series at stated horizons, against the official first print. It says"
        " nothing about Kalshi in other categories or about any trading strategy, and"
        " it does not test the paper's pooled result. The paper's Kalshi pattern comes"
        " from its sample of markets with more than $20,000 of volume, and the"
        " preprint's figure for that sample (Fig. S5) is captioned as excluding the"
        " Economy and Sports domains, so these series may not be in the sample the"
        " paper's Kalshi statement describes. Prices here sit on a one-cent grid"
        " (midpoints from half a cent to 99.5 cents), which bounds how extreme a quoted"
        " price can be."
    )
    doc.h(2, "Reproduce")
    doc.p(
        "`python3 scripts/kalshi_calibration_study.py --out <dir> --cache"
        f" ~/reviews/kalshi-econ-calibration-2026-10/fetch --as-of {meta['asOf']}"
        " --repro381 ~/reviews/thesis-vs-kalshi-2026-10/results/results.json"
        " --offline`"
    )
    return doc, figures


# Summary ---------------------------------------------------------------------


def summary_lines(results: dict) -> list[str]:
    """Summary bullets built from the computed numbers only."""
    from . import calibration

    a = results["analyses"]
    inventory = results["inventory"]
    printed = [r for r in inventory if r["officialValue"] is not None]
    settled = [r for r in inventory if r["settled"]]
    no_print = [r for r in settled if r["period"] and r["officialValue"] is None]
    unread = [r for r in settled if not r["period"]]
    markets = [s for s in results["settlement"] if "agrees" in s]
    disagree = [s for s in markets if not s["agrees"]]
    periods = sorted(r["period"] for r in printed)
    lines = [
        f"**Scope.** {len(settled)} settled Kalshi events in the twelve series, "
        f"{len(printed)} of them with an official first print ({periods[0]} to "
        f"{periods[-1]}), covering {len(markets)} binary markets. Applying each print "
        "to each market's rule reproduces Kalshi's recorded result for "
        f"{len(markets) - len(disagree)} of {len(markets)} markets"
        + (
            "; the exceptions are "
            + ", ".join(
                f"`{s['ticker']}` (official first print {s['officialValue']}, Kalshi's "
                f"recorded value {s['kalshiExpirationValue']})"
                for s in disagree
            )
            + "."
            if disagree
            else "."
        )
        + f" {len(no_print)} settled events have no official first print to check "
        f"against and {len(unread)} have a market whose rule names another period; "
        "they are left out of the primary results and enter the Kalshi-results "
        "sensitivity.",
    ]

    def fits(key):
        return [
            a[key][h]["all"]
            for h in pipeline.HORIZON_NAMES
            if "beta" in a[key][h]["all"]
        ]

    def count(key, verdict):
        return sum(1 for f in fits(key) if f["verdict"] == verdict)

    def span(key):
        values = [f["beta"] for f in fits(key)]
        return f"{min(values):.2f} to {max(values):.2f}"

    parts = []
    for horizon in pipeline.HORIZON_NAMES:
        fit = a["compression"][horizon]["all"]
        parts.append(
            f"{HORIZON_LABELS[horizon]} {num(fit['beta'])} {ci(fit['betaCi95'])}"
        )
    one_day = a["compression"]["anchor_1d"]["all"]
    lines.append(
        "**Compression toward 50%, on the pre-registered price rule** (repaired "
        "midpoints). The logistic calibration slope β, all series pooled, is "
        + "; ".join(parts)
        + ". Its interval lies above 1 at"
        f" {count('compression', 'compressed toward 50%')} of the six horizons, so"
        " outcomes were more extreme than these prices. The intercept is negative"
        f" too (one day before: {num(one_day['alpha'], signed=True)}"
        f" {ci(one_day['alphaCi95'], signed=True)}): at that horizon the fitted curve"
        f" puts a 50-cent price at about {calibration.expit(one_day['alpha']):.0%}"
        " YES."
    )
    shares = {}
    for horizon in pipeline.HORIZON_NAMES:
        chosen = [
            r
            for r in results["binaryRows"]
            if r["horizon"] == horizon and r["hasOfficial"]
        ]
        empty = sum(1 for r in chosen if r["spread"] >= 0.999)
        wide = sum(1 for r in chosen if r["spread"] > pipeline.LIQUID_SPREAD + 1e-9)
        shares[horizon] = (empty / len(chosen), wide / len(chosen))
    empty_lo = min(shares.items(), key=lambda kv: kv[1][0])
    empty_hi = max(shares.items(), key=lambda kv: kv[1][0])
    wide_lo = min(v[1] for v in shares.values())
    wide_hi = max(v[1] for v in shares.values())
    gen = a["reliabilityBy_generation"]["anchor_30d"]
    gen1 = a["reliabilityBy_generation"]["anchor_1d"]
    lines.append(
        "**The slope does not survive changes to the price rule.** Under #381's "
        "rule an empty book (no bid, no ask) is priced at 50 cents. Empty books are "
        f"{empty_lo[1][0]:.0%} of these prices {HORIZON_LABELS[empty_lo[0]]} and "
        f"{empty_hi[1][0]:.0%} at {HORIZON_LABELS[empty_hi[0]]}, and books wider "
        f"than 20 cents {wide_lo:.0%} to {wide_hi:.0%}. With quotes of 20 "
        f"cents or less only, β runs {span('compressionLiquid')} and its interval lies "
        f"above 1 at {count('compressionLiquid', 'compressed toward 50%')} of six "
        "horizons. With last traded prices and market life measured from the first "
        f"trade (the paper's own measure), β runs {span('compressionPaper')} "
        f"({count('compressionPaper', 'compressed toward 50%')} of six above 1). On "
        "markets with more than 20,000 contracts traded (the paper's volume "
        f"threshold), β runs {span('compressionPaperVolume')} and lies below 1 at "
        f"{count('compressionPaperVolume', 'too extreme')} horizons, the opposite of "
        "compression. Thirty days out, the mean of outcome minus price for prices "
        "below 0.5 is "
        f"{num(gen['legacy']['belowHalf'], 3, True)} "
        f"{ci(gen['legacy']['ci95']['belowHalf'], 3, True)} in legacy-ticker markets "
        f"and {num(gen['KX']['belowHalf'], 3, True)} "
        f"{ci(gen['KX']['ci95']['belowHalf'], 3, True)} under KX tickers; one day out "
        f"the two are {num(gen1['legacy']['belowHalf'], 3, True)} and "
        f"{num(gen1['KX']['belowHalf'], 3, True)}."
    )
    rel = a["reliability"]["life_25"]["all"]
    paper = a["reliabilityPaper"]["life_25"]["all"]
    lines.append(
        "**The paper's pattern at 25% of market life** (its headline time point). The"
        " paper reports Kalshi prices too high below 0.5 and too low above it, which"
        " would make the mean of outcome minus price negative below 0.5 and positive"
        f" above. Here it is {num(rel['belowHalf'], 3, True)}"
        f" {ci(rel['ci95']['belowHalf'], 3, True)} below and"
        f" {num(rel['aboveHalf'], 3, True)} {ci(rel['ci95']['aboveHalf'], 3, True)}"
        f" above on midpoints, and {num(paper['belowHalf'], 3, True)}"
        f" {ci(paper['ci95']['belowHalf'], 3, True)} and"
        f" {num(paper['aboveHalf'], 3, True)} {ci(paper['ci95']['aboveHalf'], 3, True)}"
        " on last trades: prices below 0.5 ran high, and prices above 0.5 show no"
        " matching shortfall."
    )
    improved = worse = 0
    bracket_worse = []
    for horizon in pipeline.HORIZON_NAMES:
        o = a["outOfSample"][horizon]["all"]
        if not o.get("folds"):
            continue
        for model in ("logistic", "beta"):
            m = o["models"][model]
            if m["binaryLog"]["ci95"][0] > 0:
                improved += 1
            if m["binaryLog"]["ci95"][1] < 0:
                worse += 1
            for metric in ("bracketLog", "bracketBrier"):
                if m[metric]["ci95"][1] < 0:
                    bracket_worse.append(
                        f"{model} {metric.replace('bracket', 'bracket ').lower()} "
                        f"{HORIZON_LABELS[horizon]} {num(m[metric]['mean'], 3, True)} "
                        f"{ci(m[metric]['ci95'], 3, True)}"
                    )
    labor = sum(
        1
        for h in pipeline.HORIZON_NAMES
        for model in ("logistic", "beta")
        if a["outOfSample"][h].get("monthly labor", {}).get("folds")
        and a["outOfSample"][h]["monthly labor"]["models"][model]["bracketLog"]["ci95"][
            1
        ]
        < 0
    )
    lines.append(
        "**Out of sample, recalibration did not help.** Trained only on outcomes "
        "public before each test date, the logistic and beta maps improved Kalshi's "
        f"binary log loss with an interval above zero in {improved} of 12 "
        f"horizon-and-map cases, and worsened it in {worse}. On Kalshi's brackets "
        "the recalibrated prices scored worse on average, with intervals below zero "
        f"in {len(bracket_worse)} cases"
        + (" (" + "; ".join(bracket_worse) + ")" if bracket_worse else "")
        + ". Maps fitted on the monthly labor family alone made its bracket log "
        f"scores worse in {labor} of 12 cases."
    )
    if "sensitivity381" in a:
        lines.append(sensitivity_line(a["sensitivity381"]))
    return lines


def sensitivity_line(sens: dict) -> str:
    """The #381 bullet: quoted numbers first, then the full count."""
    from .sensitivity import QUOTED_IN_381_SUMMARY, describe

    def key(r):
        return (r["spec"], r["horizon"], r["subset"], r["metric"])

    rows = {m: sens["models"][m]["comparison"] for m in ("logistic", "beta")}
    changed = {m: [r for r in rows[m] if r.get("changes")] for m in rows}
    same_maps = {key(r) for r in changed["logistic"]} == {
        key(r) for r in changed["beta"]
    }
    largest = max(
        abs(r["meanAfter"] - r["meanBefore"])
        for m in rows
        for r in rows[m]
        if "meanAfter" in r
    )
    quoted = [r for r in changed["logistic"] if key(r) in QUOTED_IN_381_SUMMARY]
    primary_pooled = [
        r
        for r in changed["logistic"]
        if r["spec"] == "primary" and r["subset"] == "pooled"
    ]
    flips = [r for r in changed["logistic"] if r.get("signFlips")]
    crossings = [r for r in changed["logistic"] if r.get("zeroInclusionChanges")]
    flip_size = max(
        (max(abs(r["meanBefore"]), abs(r["meanAfter"])) for r in flips), default=0
    )
    cross_size = max(
        (min(abs(r["ciAfter"][0]), abs(r["ciAfter"][1])) for r in crossings), default=0
    )
    text = (
        "**#381 with a recalibrated Kalshi baseline** (sensitivity only; #381's "
        "pre-registered results stand). Recalibration moves each #381 mean "
        f"difference by at most {largest:.2f}. "
    )
    text += (
        "Under #381's primary rule, no pooled result changes sign or crosses zero. "
        if not primary_pooled
        else f"Under #381's primary rule, {len(primary_pooled)} pooled results change. "
    )
    if quoted:
        text += (
            f"Of the {len(QUOTED_IN_381_SUMMARY)} numbers #381's Summary quotes, "
            f"{len(quoted)} change under the pre-specified criterion (logistic map): "
            + "; ".join(
                describe(r).replace(" (quoted in #381's Summary)", "")
                + f" (#381 quoted {QUOTED_IN_381_SUMMARY[key(r)]})"
                for r in quoted
            )
            + ". "
        )
    text += (
        f"Across all {len(rows['logistic'])} pooled and subset numbers under #381's "
        f"five price rules, {len(changed['logistic'])} change"
        + (", the same ones under both maps" if same_maps else "")
        + f": {len(flips)} sign flips of means within {flip_size:.3f} of zero and "
        f"{len(crossings)} intervals whose end crosses zero by at most "
        f"{cross_size:.3f}. All are listed in the sensitivity table."
    )
    return text
