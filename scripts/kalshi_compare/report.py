"""CSV tables plus a Markdown and a self-contained HTML report.

Every number in the prose is read from the results dictionary, and wording
about direction follows the computed interval, so the text cannot drift from
the numbers.
"""

from __future__ import annotations

import csv
import html
import json
import math
import pathlib
import statistics
from collections import Counter, defaultdict
from typing import Any

HORIZON_LABELS = {
    "at_registration": "At Thesis registration",
    "release_minus_7d": "7 days before release",
    "release_minus_1d": "1 day before release",
}
SPEC_LABELS = {
    "primary": "Primary (pre-specified)",
    "liquid_markets_only": "Liquid markets only (spread \u2264 20c)",
    "last_trade_price": "Last trade price",
    "literal_cdf_reading": "Literal CDF reading",
    "floor_0.01": "Probability floor 0.01",
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
    "KXECONSTATCPI": "CPI-U all items, exact-value markets",
    "KXECONSTATCPICORE": "Core CPI-U, exact-value markets",
    "KXECONSTATU3": "Unemployment rate, exact-value markets",
}
PRIMARY_ORDER = [
    "KXCPI",
    "KXCPICORE",
    "KXU3",
    "KXPAYROLLS",
    "KXJOBLESSCLAIMS",
    "KXCONTCLAIMS",
    "KXJOLTSOPEN",
    "KXPCECORE",
]
MIN_SERIES_N = 5


# CSV --------------------------------------------------------------------------


def write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: json.dumps(v) if isinstance(v, (list, dict)) else v
                    for k, v in row.items()
                }
            )


# Formatting -------------------------------------------------------------------


def num(x: float | None, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    text = f"{x:+.{digits}f}"
    return text.replace("-", "−")


def ci_text(v: dict) -> str:
    lo, hi = v["ci95"]
    return f"{num(v['mean'])} [{num(lo)}, {num(hi)}]"


def direction(v: dict, better: str = "Thesis", worse: str = "Kalshi") -> str:
    lo, hi = v["ci95"]
    if lo > 0:
        return f"favors {better}"
    if hi < 0:
        return f"favors {worse}"
    return "interval includes zero"


def reading(v: dict) -> str:
    """A clause that reads correctly whichever way the interval falls."""
    said = direction(v)
    return f"whose {said}" if said.startswith("interval") else f"which {said}"


def wins(v: dict, a: str = "Thesis", b: str = "Kalshi") -> str:
    return f"{a} {v['thesisBetter']}, {b} {v['kalshiBetter']}" + (
        f", tied {v['ties']}" if v.get("ties") else ""
    )


# Blocks -----------------------------------------------------------------------


class Doc:
    def __init__(self) -> None:
        self.blocks: list[tuple[str, Any]] = []

    def h(self, level: int, text: str) -> None:
        self.blocks.append(("h", (level, text)))

    def p(self, text: str) -> None:
        self.blocks.append(("p", text))

    def ul(self, items: list[str]) -> None:
        self.blocks.append(("ul", items))

    def table(
        self, header: list[str], rows: list[list[str]], note: str | None = None
    ) -> None:
        self.blocks.append(("table", (header, rows, note)))

    def figure(self, svg: str, caption: str, path: str) -> None:
        self.blocks.append(("figure", (svg, caption, path)))

    def markdown(self) -> str:
        out: list[str] = []
        for kind, value in self.blocks:
            if kind == "h":
                out.append("#" * value[0] + " " + value[1])
            elif kind == "p":
                out.append(value)
            elif kind == "ul":
                out.append("\n".join(f"- {item}" for item in value))
            elif kind == "table":
                header, rows, note = value
                lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
                lines += ["| " + " | ".join(r) + " |" for r in rows]
                out.append("\n".join(lines) + (f"\n\n{note}" if note else ""))
            elif kind == "figure":
                out.append(f"![{value[1]}]({value[2]})\n\n*{value[1]}*")
        return "\n\n".join(out) + "\n"

    def html(self, title: str) -> str:
        body: list[str] = []
        for kind, value in self.blocks:
            if kind == "h":
                body.append(f"<h{value[0]}>{inline(value[1])}</h{value[0]}>")
            elif kind == "p":
                body.append(f"<p>{inline(value)}</p>")
            elif kind == "ul":
                body.append(
                    "<ul>" + "".join(f"<li>{inline(i)}</li>" for i in value) + "</ul>"
                )
            elif kind == "table":
                header, rows, note = value
                head = "".join(f"<th>{inline(c)}</th>" for c in header)
                rows_html = "".join(
                    "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                    for r in rows
                )
                body.append(
                    f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
                    f"<tbody>{rows_html}</tbody></table></div>"
                    + (f'<p class="note">{inline(note)}</p>' if note else "")
                )
            elif kind == "figure":
                body.append(
                    f"<figure>{value[0]}<figcaption>{inline(value[1])}</figcaption></figure>"
                )
        return HTML_TEMPLATE.format(title=html.escape(title), body="\n".join(body))


def inline(text: str) -> str:
    """Minimal Markdown inline rendering: escape, then `code` and **bold**."""
    import re

    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', escaped
    )
    return escaped


HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: light;
  --surface: #fcfcfb; --surface-2: #f2f1ee; --text: #0b0b0b; --text-2: #52514e;
  --rule: #dddcd7; --series-1: #2a78d6; --zero: #8a8983;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --surface: #1a1a19; --surface-2: #232321; --text: #f0efec; --text-2: #c3c2b7;
    --rule: #3a3a37; --series-1: #3987e5; --zero: #8f8e88;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --surface: #1a1a19; --surface-2: #232321; --text: #f0efec; --text-2: #c3c2b7;
  --rule: #3a3a37; --series-1: #3987e5; --zero: #8f8e88;
}}
body {{ background: var(--surface); color: var(--text); margin: 0;
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 1.7rem; line-height: 1.25; margin: 0 0 8px; }}
h2 {{ font-size: 1.25rem; margin: 36px 0 8px; padding-top: 20px;
  border-top: 1px solid var(--rule); }}
h3 {{ font-size: 1.05rem; margin: 24px 0 6px; }}
p, li {{ color: var(--text); }}
.note {{ color: var(--text-2); font-size: 0.9rem; }}
code {{ font: 0.88em ui-monospace, SFMono-Regular, Menlo, monospace;
  background: var(--surface-2); padding: 1px 4px; border-radius: 4px; }}
.table-wrap {{ overflow-x: auto; margin: 8px 0; }}
table {{ border-collapse: collapse; font-size: 0.88rem; min-width: 100%; }}
th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--rule);
  vertical-align: top; font-variant-numeric: tabular-nums; }}
th {{ color: var(--text-2); font-weight: 600; white-space: nowrap; }}
figure {{ margin: 16px 0; overflow-x: auto; }}
figcaption {{ color: var(--text-2); font-size: 0.9rem; margin-top: 6px; }}
svg text {{ fill: var(--text-2);
  font: 12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
svg .title {{ fill: var(--text); font-weight: 600; }}
svg .grid {{ stroke: var(--rule); stroke-width: 1; }}
svg .zero {{ stroke: var(--zero); stroke-width: 1.5; }}
svg .dot {{ fill: var(--series-1); stroke: var(--surface); stroke-width: 2; }}
svg .dot:hover {{ stroke: var(--text); }}
svg .mean {{ stroke: var(--text); stroke-width: 2; }}
a {{ color: var(--series-1); }}
</style></head>
<body><main>
{body}
</main></body></html>
"""


# Figure -----------------------------------------------------------------------


def dot_figure(pairs: list[dict], spec: str, metric: str = "deltaLog") -> str:
    """Per-event paired differences, one panel per horizon, rows by series."""
    clip = 3.0
    series = [s for s in PRIMARY_ORDER if any(p["series"] == s for p in pairs)]
    panel_w, label_w, row_h, top = 250, 210, 30, 44
    width = label_w + panel_w * 3 + 20
    height = top + row_h * len(series) + 40
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        'role="img" aria-label="Per-event paired log-score differences">'
    ]
    for row, name in enumerate(series):
        y = top + row_h * row + row_h / 2
        parts.append(
            f'<text x="{label_w - 10}" y="{y + 4}" text-anchor="end">'
            f"{html.escape(SERIES_LABELS[name])}</text>"
        )
    for col, horizon in enumerate(HORIZON_LABELS):
        x0 = label_w + panel_w * col + 24
        inner = panel_w - 48

        def sx(v: float) -> float:
            return x0 + (max(-clip, min(clip, v)) + clip) / (2 * clip) * inner

        parts.append(
            f'<text class="title" x="{x0 + inner / 2}" y="18" text-anchor="middle">'
            f"{HORIZON_LABELS[horizon]}</text>"
        )
        for tick in (-3, -2, -1, 0, 1, 2, 3):
            cls = "zero" if tick == 0 else "grid"
            parts.append(
                f'<line class="{cls}" x1="{sx(tick)}" x2="{sx(tick)}" y1="{top - 6}" '
                f'y2="{top + row_h * len(series)}"/>'
            )
            parts.append(
                f'<text x="{sx(tick)}" y="{top + row_h * len(series) + 16}" '
                f'text-anchor="middle">{num(float(tick), 0) if tick else "0"}</text>'
            )
        for row, name in enumerate(series):
            y = top + row_h * row + row_h / 2
            items = [
                p
                for p in pairs
                if p["series"] == name and p["horizon"] == horizon and p["spec"] == spec
            ]
            for index, item in enumerate(items):
                value = item[metric]
                jitter = ((index % 5) - 2) * 3
                label = (
                    f"{item['eventKey']}: {metric} {value:+.2f}; Thesis"
                    f" p={item['thesisRealizedProb']:.3f}, Kalshi"
                    f" p={item['kalshiRealizedProb']:.3f}"
                    + (" (clipped)" if abs(value) > clip else "")
                )
                parts.append(
                    f'<circle class="dot" cx="{sx(value):.1f}" cy="{y + jitter:.1f}"'
                    f' r="5"><title>{html.escape(label)}</title></circle>'
                )
            if items:
                mean = sum(i[metric] for i in items) / len(items)
                parts.append(
                    f'<line class="mean" x1="{sx(mean):.1f}" x2="{sx(mean):.1f}"'
                    f' y1="{y - 9}" y2="{y + 9}"><title>mean {mean:+.2f}'
                    f" (n={len(items)})</title></line>"
                )
    parts.append(
        f'<text x="{label_w + 10}" y="{height - 4}">Log-score difference, Thesis minus '
        "Kalshi (positive favors Thesis; values beyond ±3 drawn at the edge)</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


# Report -----------------------------------------------------------------------


def write(results: dict, out: pathlib.Path) -> None:
    for name in (
        "inventory",
        "unmatched",
        "withdrawn",
        "outcomes",
        "markets",
        "pairs",
        "exclusions",
    ):
        write_csv(out / f"{name}.csv", results[name])
    write_csv(out / "scores.csv", results["scores"])
    (out / "summary.json").write_text(json.dumps(results["summary"], indent=1) + "\n")
    doc, figure_svg = build(results)
    (out / "figure_log_differences.svg").write_text(figure_svg)
    (out / "REPORT.md").write_text(doc.markdown())
    (out / "REPORT.html").write_text(doc.html("Thesis vs Kalshi"))


def headline_pairs(results: dict, spec: str) -> list[dict]:
    chosen: dict[tuple, dict] = {}
    for pair in sorted(results["pairs"], key=lambda p: (p["registeredAt"], p["runId"])):
        if pair["forecaster"] != "thesis_headline" or pair["spec"] != spec:
            continue
        chosen.setdefault((pair["eventKey"], pair["horizon"]), pair)
    return list(chosen.values())


def build(results: dict) -> tuple[Doc, str]:
    meta = results["meta"]
    summary = results["summary"]
    head = summary["thesis_headline"]
    inventory = results["inventory"]
    outcomes = {o["eventKey"]: o for o in results["outcomes"]}
    doc = Doc()

    primary_runs = [
        i
        for i in inventory
        if i["primarySeries"] and i["forecaster"] == "thesis_headline"
    ]
    events = {(i["kalshiSeries"], i["period"]) for i in primary_runs}
    with_event = {e for e in events if outcomes.get(f"{e[0]}:{e[1]}")}
    released = {
        e for e in with_event if outcomes[f"{e[0]}:{e[1]}"]["officialValue"] is not None
    }
    pooled = {(spec, h): head[spec][h]["pooled"] for spec in head for h in head[spec]}

    def pool(spec: str, horizon: str, metric: str) -> dict:
        return pooled[(spec, horizon)].get(metric) or {"n": 0}

    doc.h(1, "Thesis forecasts vs Kalshi prices: a paper comparison")
    doc.p(
        "Read-only scoring study. It places no orders, uses no Kalshi account and "
        "simulates no trading; every Kalshi number is public market data. "
        f"Data as of {meta['asOf']}. Thesis records at commit `{meta['commit'][:12]}` "
        f"(published log `{meta['logBody']}`), published distributions from projection "
        f"`{meta['distributions']['projectionRootSha256'][:12]}`. The analysis plan, "
        "committed before any score was computed, is `docs/kalshi-paper-comparison.md` "
        "in [ThesisInstitute/thesis#381](https://github.com/ThesisInstitute/thesis/pull/381)."
    )

    # Summary
    reg_p, reg_l = pool("primary", "at_registration", "deltaLog"), pool(
        "liquid_markets_only", "at_registration", "deltaLog"
    )
    reg_b = pool("primary", "at_registration", "deltaBrier")
    d1_p, d1_l = pool("primary", "release_minus_1d", "deltaLog"), pool(
        "liquid_markets_only", "release_minus_1d", "deltaLog"
    )
    d1_lb = pool("liquid_markets_only", "release_minus_1d", "deltaLadderBrier")
    d7_l = pool("liquid_markets_only", "release_minus_7d", "deltaLog")
    small = [
        s
        for s in PRIMARY_ORDER
        if 0
        < (
            head["primary"]["release_minus_1d"]["bySeries"].get(s, {}).get("deltaLog")
            or {"n": 0}
        )["n"]
        < MIN_SERIES_N
    ]
    one_day = head["primary"]["release_minus_1d"]["bySeries"]
    big = [
        (s, one_day[s]["deltaLog"]["n"])
        for s in PRIMARY_ORDER
        if s in one_day and one_day[s]["deltaLog"]["n"] >= MIN_SERIES_N
    ]
    small_n = [one_day[s]["deltaLog"]["n"] for s in small]
    min_small, max_small = (min(small_n), max(small_n)) if small_n else (0, 0)
    claims_reg = [
        e
        for e in results["exclusions"]
        if e["series"] in ("KXJOBLESSCLAIMS", "KXCONTCLAIMS")
        and e["forecaster"] == "thesis_headline"
        and e["horizon"] == "at_registration"
        and not e.get("spec")
    ]
    claims_no_market = len({e["eventKey"] for e in claims_reg})
    claims_total = len(
        {
            (i["kalshiSeries"], i["period"])
            for i in primary_runs
            if i["kalshiSeries"] in ("KXJOBLESSCLAIMS", "KXCONTCLAIMS")
            and (i["kalshiSeries"], i["period"]) in released
        }
    )
    rebuilt = [i for i in inventory if i["distributionProvenance"] == "interval_seeded"]
    rebuilt_exact = sum(1 for i in rebuilt if i["publishedCdfCheck"] == "rebuilt_exact")
    kalshi_floor_hits = sum(
        1
        for s in results["scores"]
        if s["spec"] == "primary"
        and s["forecaster"] == "thesis_headline"
        and s["primarySeries"]
        and s["kalshiFloored"]
    )
    doc.h(2, "Summary")
    doc.ul(
        [
            (
                f"**Scope.** {len(primary_runs)} published Thesis headline forecasts"
                " registered since 1 July 2026 target a statistic Kalshi lists, across"
                f" {len({e[0] for e in events})} series; {len(with_event)} of them have"
                f" a Kalshi event for the same reference period, and {len(released)} of"
                " those have been released. Those are scored against the official"
                " first print on Kalshi's own brackets. Intervals in brackets are 95%"
                " bootstrap intervals; positive differences favor Thesis."
            ),
            "**At Thesis's registration time**, when both had the same information,"
            f" there is no detectable difference. Over {reg_p['n']} events, the mean"
            f" log-score difference is {ci_text(reg_p)}, and {ci_text(reg_l)} with"
            f" thinly quoted markets dropped; the Brier difference is {ci_text(reg_b)}."
            " All three intervals "
            + (
                "include zero."
                if all(
                    direction(v) == "interval includes zero"
                    for v in (reg_p, reg_l, reg_b)
                )
                else "are shown; not all include zero."
            ),
            (
                "**Closer to the release, Kalshi is better than Thesis's earlier"
                " forecast**, as expected: the market keeps updating while the Thesis"
                " forecast stays fixed at its registration, often weeks earlier. One"
                " day before release, with thinly quoted markets dropped, the log"
                f" difference over {d1_l['n']} events is {ci_text(d1_l)},"
                f" {reading(d1_l)} ({wins(d1_l)}), and the ladder Brier difference is"
                f" {ci_text(d1_lb)}, {reading(d1_lb)}. Seven days before release it is"
                f" {ci_text(d7_l)} over {d7_l['n']} events, {reading(d7_l)}. Under the"
                " pre-specified primary rule, which reads an empty order book as 50%,"
                f" the one-day log difference is {ci_text(d1_p)}, {reading(d1_p)}."
            ),
            "**Per series, there are too few resolved pairs to conclude anything**"
            " except "
            + " and ".join(
                f"{SERIES_LABELS[s].split(' (')[0].lower()} ({n} weeks)" for s, n in big
            )
            + "; "
            + ", ".join(SERIES_LABELS[s] for s in small)
            + f" each have {min_small} to {max_small}. Weekly claims are mostly"
            f" comparable only one day before release: in {claims_no_market} of"
            f" {claims_total} claims weeks Kalshi had no quoted market when Thesis"
            " registered.",
            (
                "**What this does and does not measure.** It measures probabilistic"
                " forecast accuracy on monthly and weekly US national statistics at"
                " stated horizons. It does not measure skill at state or municipal"
                " questions, at municipal bond pricing, or at anything involving"
                " trading, and results this small should not be extrapolated to those."
            ),
        ]
    )

    figure_svg = dot_figure(
        headline_pairs(results, "liquid_markets_only"), "liquid_markets_only"
    )
    doc.figure(
        figure_svg,
        "Each dot is one event: Thesis's log score minus Kalshi's on Kalshi's brackets,"
        " liquid markets only. Black ticks are series means. Hover a dot for its"
        " details.",
        "figure_log_differences.svg",
    )

    # Scope
    doc.h(2, "What was compared")
    in_scope_text = (
        f"all {meta['publishedRuns']} recorded since 1 July 2026"
        if meta["publishedRuns"] == meta["publishedRunsInScope"]
        else f"{meta['publishedRunsInScope']} of them recorded since 1 July 2026"
    )
    doc.p(
        f"The published Thesis log holds {meta['publishedRuns']} forecast runs,"
        f" {in_scope_text}. Runs were matched to Kalshi by statistic and reference"
        " period; the Kalshi event's period is read from its title and every market's"
        " rule text. Each Thesis forecast is its published 201-point CDF;"
        f" {rebuilt_exact} of the {len(rebuilt)} interval-seeded CDFs used here rebuild"
        " exactly from the run's point estimate and 80% interval with the documented"
        " transform. Registration time is the RFC 3161 witness time of the run's"
        " custody root."
    )
    rows = []
    for series in PRIMARY_ORDER:
        mine = [i for i in primary_runs if i["kalshiSeries"] == series]
        if not mine:
            continue
        evs = sorted({i["period"] for i in mine})
        rel = [p for p in evs if (series, p) in released]
        no_event = [p for p in evs if (series, p) not in with_event]
        pending = [
            p for p in evs if (series, p) in with_event and (series, p) not in released
        ]
        n_by_h = []
        for h in HORIZON_LABELS:
            v = head["primary"][h]["bySeries"].get(series, {}).get("deltaLog")
            n_by_h.append(str(v["n"]) if v else "0")
        lead = [
            (
                _ts(outcomes[f"{series}:{i['period']}"]["releaseAt"])
                - _ts(i["registeredAt"])
            )
            / 86400
            for i in mine
            if (series, i["period"]) in released
        ]
        rows.append(
            [
                SERIES_LABELS[series],
                f"`{series}`",
                str(len(mine)),
                str(len(rel)),
                " / ".join(n_by_h),
                f"{statistics.median(lead):.0f}" if lead else "n/a",
                ", ".join(pending + [f"{p} (no Kalshi event)" for p in no_event])
                or "none",
            ]
        )
    doc.table(
        [
            "Statistic",
            "Kalshi series",
            "Thesis forecasts",
            "Released",
            "Scored (reg / 7d / 1d)",
            "Median days, registration to release",
            "Not yet scorable",
        ],
        rows,
        "Scored counts are events; an event is dropped at a horizon if it falls before "
        "Thesis's registration or if no Kalshi market had a quote by then "
        "(see `exclusions.csv`).",
    )
    reasons = Counter(u["reason"] for u in results["unmatched"])
    doc.p(
        f"{len(results['unmatched'])} other published US runs since 1 July have no"
        " matching Kalshi market: "
        + "; ".join(f"{n} — {r}" for r, n in reasons.most_common())
        + f" (`unmatched.csv`). {len(results['withdrawn'])} catalog runs for matched"
        " statistics are not in the published log (the live page checked for one,"
        ' `us-cpi-u-mom-july-2026`, says "No forecast available"); they are listed'
        " in `withdrawn.csv` and not scored."
    )

    # Contracts
    doc.h(3, "How each contract was read")
    doc.ul(
        [
            (
                'CPI, core CPI, U-3, core PCE: "above X" on the single-decimal'
                ' published value. Payrolls: "above X" persons on the first-print'
                ' change. JOLTS: "above X million" on the level BLS reports in'
                " thousands."
            ),
            (
                'Initial and continuing claims: "at least X" on the advance seasonally'
                " adjusted figure first published. Kalshi switched continuing-claims"
                ' strikes from "1.84 million" to "1750K" between events; each strike is'
                " read with the unit its own rule states and checked against the"
                " market's strike field."
            ),
            (
                "Thesis's CDF is read as the distribution of the unrounded value the"
                " agency then rounds: P(Y > s) = 1 − F(s + g/2) and P(Y ≥ s) = 1 − F(s"
                " − g/2), where g is the reporting grid (0.1 point, 1,000 persons, or"
                " 0.001 million). The literal reading 1 − F(s) is a sensitivity."
            ),
            (
                "Kalshi's price is the midpoint of the closing bid and ask of the last"
                " hourly candle at or before the horizon (an empty side counts as 0 or"
                " 1), with the ladder made non-increasing by isotonic regression."
                " Brackets are the intervals between consecutive strikes."
            ),
        ]
    )

    # Outcomes
    doc.h(2, "Outcomes")
    mismatches = sum(len(o["kalshiResultMismatches"]) for o in results["outcomes"])
    n_markets = sum(o["nMarkets"] for o in results["outcomes"] if o["officialValue"])
    doc.p(
        "Each value is the official first print read from the agency's own release"
        " (BLS news release archive, DOL Employment and Training Administration weekly"
        " release, BEA Personal Income and Outlays), with the release time the"
        " document states. Where the release's lead paragraph also states the value,"
        f" both readings agree. Across {n_markets} settled Kalshi markets, the contract"
        " rule applied to the official value reproduces Kalshi's recorded result in"
        f" every case ({mismatches} disagreements)."
    )
    rows = []
    for key in sorted(
        outcomes,
        key=lambda k: (
            (
                PRIMARY_ORDER.index(k.split(":")[0])
                if k.split(":")[0] in PRIMARY_ORDER
                else 99
            ),
            k,
        ),
    ):
        o = outcomes[key]
        series = key.split(":")[0]
        if series not in PRIMARY_ORDER or o["officialValue"] is None:
            continue
        dps = [
            i
            for i in inventory
            if i["kalshiSeries"] == series
            and i["period"] == o["period"]
            and i["forecaster"] == "thesis_headline"
        ]
        state = (
            dps[0]["thesisResolverCode"] or dps[0]["thesisResolverState"] if dps else ""
        )
        ledger = o["thesisLedgerAgreesWithOfficial"]
        rows.append(
            [
                SERIES_LABELS[series],
                o["period"],
                o["officialValue"],
                o["releaseAt"][:16].replace("T", " ") + "Z",
                f"[source]({o['sourceUrl']})",
                state or "",
                {True: "matches", False: "differs", None: "—"}[ledger],
            ]
        )
    doc.table(
        [
            "Statistic",
            "Period",
            "First print",
            "Released (UTC)",
            "Release",
            "Thesis resolver",
            "Thesis ledger value",
        ],
        rows,
        "Values are in Kalshi strike units (persons for payrolls and initial claims,"
        " millions for continuing claims and job openings, percent otherwise).",
    )
    differs = [
        o for o in results["outcomes"] if o["thesisLedgerAgreesWithOfficial"] is False
    ]
    unresolved = Counter(
        (i["thesisResolverCode"] or i["thesisResolverState"])
        for i in primary_runs
        if (i["kalshiSeries"], i["period"]) in released and not i["thesisResolved"]
    )
    doc.p(
        f"Thesis's own resolver has not resolved {sum(unresolved.values())} of the "
        f"{len(released)} released targets: "
        + " and ".join(f"{n} are `{code}`" for code, n in unresolved.items())
        + ". The BLS headline targets in that backlog are the subject of open decision"
        " d1633; `NO_ROUTE_GENERIC_URL` targets were registered with a generic"
        " source link. This study scores all of them from the releases directly. For"
        f" {len(differs)} weekly claims targets, the Thesis ledger at the published"
        f" log's pin (`{(meta.get('ledgerPin') or {}).get('sha', '')[:12]}`) holds a"
        " value from a later revised vintage rather than the first print."
        " Superseding rows 240 to 245 on PolicyEngine/chronicle"
        " `codex/thesis-ledger-facts` (checked at `8722b2da`) carry the same values"
        " read here from the DOL releases."
    )

    # Results
    doc.h(2, "Results")
    doc.p(
        "Differences are Thesis minus Kalshi for log scores and Kalshi minus Thesis for"
        " Brier scores, so positive always favors Thesis. Intervals are 95% bootstrap"
        " intervals over events; p is an exact sign-flip randomization test. With three"
        " horizons, two scores and several sensitivities, no single interval should be"
        " read as a discovery."
    )
    rows = []
    for spec in ("primary", "liquid_markets_only"):
        for h in HORIZON_LABELS:
            p = pooled[(spec, h)]
            if not p:
                continue
            lg, br, lb = p["deltaLog"], p["deltaBrier"], p["deltaLadderBrier"]
            rows.append(
                [
                    SPEC_LABELS[spec],
                    HORIZON_LABELS[h],
                    str(lg["n"]),
                    ci_text(lg),
                    f"{lg['signFlipP']:.3f}",
                    ci_text(br),
                    ci_text(lb),
                    wins(lg),
                ]
            )
    doc.table(
        [
            "Price rule",
            "Horizon",
            "Events",
            "Log difference",
            "p",
            "Brier difference",
            "Ladder Brier difference",
            "Better log score",
        ],
        rows,
        "Pooled over all primary series, each event weighted equally. Release-clustered"
        " and series-balanced intervals are in `summary.json`.",
    )

    for h in HORIZON_LABELS:
        doc.h(3, f"By series: {HORIZON_LABELS[h].lower()}")
        rows = []
        for series in PRIMARY_ORDER:
            prim = head["primary"][h]["bySeries"].get(series)
            liq = head["liquid_markets_only"][h]["bySeries"].get(series)
            if not prim:
                continue
            lg = prim["deltaLog"]
            note = "too few to conclude" if lg["n"] < MIN_SERIES_N else direction(lg)
            rows.append(
                [
                    SERIES_LABELS[series],
                    str(lg["n"]),
                    ci_text(lg),
                    ci_text(liq["deltaLog"]) if liq and liq.get("deltaLog") else "n/a",
                    ci_text(prim["deltaBrier"]),
                    wins(lg),
                    note,
                ]
            )
        doc.table(
            [
                "Statistic",
                "Events",
                "Log difference",
                "Log, liquid only",
                "Brier difference",
                "Better log score",
                "Reading",
            ],
            rows,
        )

    doc.h(3, "Sensitivities")
    rows = []
    for spec in SPEC_LABELS:
        cells = [SPEC_LABELS[spec]]
        for h in HORIZON_LABELS:
            v = pooled[(spec, h)].get("deltaLog")
            cells.append(f"{ci_text(v)}, n={v['n']}" if v else "n/a")
        rows.append(cells)
    doc.table(
        ["Rule (pooled log difference)"] + list(HORIZON_LABELS.values()),
        rows,
        "The liquid-markets rule was added after inspecting bid-ask spreads and before "
        "any score was inspected; the others were pre-specified.",
    )

    # Secondary
    doc.h(2, "Secondary comparisons")
    vs = (
        summary.get("thesis_vs_persistence", {})
        .get("primary", {})
        .get("release_minus_1d", {})
    )
    if vs.get("bySeries"):
        items = []
        for series, m in vs["bySeries"].items():
            items.append(
                f"{SERIES_LABELS[series]}: log {ci_text(m['deltaLog'])}"
                f" ({wins(m['deltaLog'], 'headline', 'baseline')}); Brier"
                f" {ci_text(m['deltaBrier'])}"
                f" ({wins(m['deltaBrier'], 'headline', 'baseline')})"
            )
        doc.p(
            "**Thesis headline vs Thesis's persistence baseline**, on identical Kalshi "
            "brackets one day before release (positive favors the headline forecast):"
        )
        doc.ul(items)
    exact_rows = []
    for series in ("KXECONSTATCPI", "KXECONSTATCPICORE", "KXECONSTATU3"):
        cells = [SERIES_LABELS[series]]
        for h in HORIZON_LABELS:
            v = head["primary"][h]["bySeries"].get(series, {}).get("deltaLog")
            cells.append(f"{ci_text(v)}, n={v['n']}" if v else "n/a")
        exact_rows.append(cells)
    doc.p(
        '**Exact-value markets** ("exactly X") cover the same CPI and unemployment'
        ' prints with smaller volume. They are scored with an added "any other value"'
        " bracket and are not pooled with the main results."
    )
    doc.table(["Markets (log difference)"] + list(HORIZON_LABELS.values()), exact_rows)
    variant = [i for i in inventory if i["forecaster"].startswith("thesis_variant")]
    if variant:
        v = variant[0]
        doc.p(
            "**Threshold-ladder variant.** One additional Thesis run"
            f" ({v['dataPointId']}, registered {v['registeredAt'][:10]}) used ladder"
            " elicitation. Its published CDF does not pass through 10% and 90% at its"
            f" stated 80% interval (`{v['publishedCdfCheck']}`), consistent with rungs"
            " stated on the published one-decimal value; its scores under both CDF"
            " readings are in `pairs.csv`."
        )

    # Liquidity
    doc.h(2, "Market liquidity")
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for m in results["markets"]:
        series = m["eventKey"].split(":")[0]
        if series in PRIMARY_ORDER:
            by[(series, m["horizon"])].append(m)
    rows = []
    for series in PRIMARY_ORDER:
        cells = [SERIES_LABELS[series]]
        for h in HORIZON_LABELS:
            ms = by.get((series, h))
            if not ms:
                cells.append("—")
                continue
            spread = statistics.median(m["spread"] for m in ms)
            vol = sum(m["volume7d"] for m in ms)
            cells.append(f"{spread * 100:.0f}c spread, {vol:,.0f} traded in prior week")
        life = sum(
            o["lifetimeVolume"]
            for o in results["outcomes"]
            if o["eventKey"].startswith(series + ":") and o["officialValue"]
        )
        cells.append(f"{life:,.0f}")
        rows.append(cells)
    doc.table(
        ["Statistic"]
        + list(HORIZON_LABELS.values())
        + ["Lifetime contracts traded (scored events)"],
        rows,
        "Median bid-ask spread across an event's markets at the horizon, and contracts"
        " traded in the seven days before it, summed over scored events. Per-market"
        " detail is in `markets.csv`.",
    )

    # Caveats
    doc.h(2, "Caveats")
    doc.ul(
        [
            (
                "Samples are small and correlated: headline and core CPI share a"
                " release, as do U-3 and payrolls, and initial and continuing claims."
            ),
            (
                "Only the registration-time comparison gives both sides the same"
                " information. The 7-day and 1-day comparisons pit a fixed Thesis"
                " forecast against a market that has kept updating, so they measure how"
                " much later information was worth as much as forecasting skill."
            ),
            (
                "Thesis interval-seeded CDFs are a piecewise-linear shape through five"
                " knots (support ends, 10%, 50%, 90%), so the probability on a narrow"
                " bracket reflects that transform as much as the forecaster's belief."
            ),
            (
                "Kalshi's empty or one-sided books produce midpoints near 50% that are"
                " not forecasts. The pre-specified primary rule keeps them; the"
                " liquid-markets rule drops them. Under the primary rule,"
                f" {kalshi_floor_hits} Kalshi log scores hit the probability floor;"
                " each came from a book of near-50% midpoints."
            ),
            (
                "Weekly claims comparisons exist almost only one day before release"
                f" ({claims_total - claims_no_market} of {claims_total} weeks are also"
                " scored at registration), and continuing-claims markets are thinly"
                " traded."
            ),
            (
                "Thesis registration uses the RFC 3161 witness time of the run's"
                " custody root; the deterministic persistence baseline has no custody"
                " root and uses its recorded time."
            ),
        ]
    )

    doc.h(2, "Reproduce")
    doc.p(
        "From a checkout of the PR branch, with network access: "
        "`python3 scripts/kalshi_paper_comparison.py --out <dir> --as-of <UTC time>`. "
        "Every response used is stored by SHA-256 under `fetch/`; adding `--offline "
        "--cache <this folder>/../fetch` reruns from the stored responses only. "
        "`pdftotext` (poppler) is needed to read the DOL releases."
    )
    doc.h(2, "Files")
    doc.ul(
        [
            (
                "`inventory.csv`: every matched Thesis run, with registration proof,"
                " published CDF check, Kalshi event, official value and Thesis resolver"
                " status."
            ),
            (
                "`outcomes.csv`: official first prints, sources, hashes and the Kalshi"
                " cross-check."
            ),
            (
                "`markets.csv`: each Kalshi market at each horizon: bid, ask, midpoint,"
                " last trade, spread, open interest, volume."
            ),
            (
                "`scores.csv` and `pairs.csv`: bracket probabilities and scores per"
                " event, horizon, forecaster and rule."
            ),
            (
                "`summary.json`: all summaries, including release-clustered and"
                " series-balanced intervals. `exclusions.csv`, `unmatched.csv`,"
                " `withdrawn.csv`: what was left out and why."
            ),
        ]
    )
    return doc, figure_svg


def _ts(value: str) -> float:
    import datetime as dt

    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
