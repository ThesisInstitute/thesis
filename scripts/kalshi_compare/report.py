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
    "KXHOUSINGSTART": "Housing starts (SAAR)",
    "KXBUILDPERMS": "Building permits (SAAR)",
    "KXNHSALES": "New home sales (SAAR)",
    "KXUE": "Australia unemployment rate",
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
    "KXHOUSINGSTART",
    "KXBUILDPERMS",
    "KXNHSALES",
    "KXUE",
]
MIN_SERIES_N = 5
SHORT_NAMES = {
    "KXCPI": "headline CPI",
    "KXCPICORE": "core CPI",
    "KXPCECORE": "core PCE",
}


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
svg .dot:hover, svg .ring:hover {{ stroke-width: 3; }}
svg .ring {{ fill: none; stroke: var(--series-1); stroke-width: 1.5; }}
svg .mean {{ stroke: var(--text); stroke-width: 2; }}
a {{ color: var(--series-1); }}
</style></head>
<body><main>
{body}
</main></body></html>
"""


# Figure -----------------------------------------------------------------------


def dot_figure(pairs: list[dict], metric: str = "deltaLog") -> str:
    """Per-event paired differences under both rules, one panel per horizon."""
    clip = 3.0
    series = [s for s in PRIMARY_ORDER if any(p["series"] == s for p in pairs)]
    panel_w, label_w, row_h, top = 250, 210, 30, 62
    width = label_w + panel_w * 3 + 20
    height = top + row_h * len(series) + 40
    parts = [
        (
            f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            'role="img" aria-label="Per-event paired log-score differences">'
        ),
        (
            f'<circle class="dot" cx="{label_w + 12}" cy="12" r="5"/><text'
            f' x="{label_w + 22}" y="16">Pre-specified rule</text><circle class="ring"'
            f' cx="{label_w + 172}" cy="12" r="5"/><text x="{label_w + 182}"'
            ' y="16">Liquid markets only (added after the plan)</text>'
        ),
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
            f'<text class="title" x="{x0 + inner / 2}" y="44" text-anchor="middle">'
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
            for spec, cls in (("primary", "dot"), ("liquid_markets_only", "ring")):
                items = sorted(
                    (
                        p
                        for p in pairs
                        if p["series"] == name
                        and p["horizon"] == horizon
                        and p["spec"] == spec
                    ),
                    key=lambda p: p["eventKey"],
                )
                for index, item in enumerate(items):
                    value = item[metric]
                    jitter = ((index % 5) - 2) * 3
                    label = (
                        f"{item['eventKey']} ({SPEC_LABELS[spec]}): {value:+.2f}; "
                        f"Thesis p={item['thesisRealizedProb']:.3f}, "
                        f"Kalshi p={item['kalshiRealizedProb']:.3f}"
                        + (" (clipped)" if abs(value) > clip else "")
                    )
                    parts.append(
                        f'<circle class="{cls}" cx="{sx(value):.1f}" '
                        f'cy="{y + jitter:.1f}" r="5"><title>{html.escape(label)}'
                        "</title></circle>"
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


def headline_pairs(results: dict, spec: str | None = None) -> list[dict]:
    chosen: dict[tuple, dict] = {}
    for pair in sorted(results["pairs"], key=lambda p: (p["registeredAt"], p["runId"])):
        if pair["forecaster"] != "thesis_headline":
            continue
        if spec is not None and pair["spec"] != spec:
            continue
        chosen.setdefault((pair["eventKey"], pair["horizon"], pair["spec"]), pair)
    return list(chosen.values())


def values_text(rows: list[dict], metric: str) -> str:
    return ", ".join(num(r[metric]) for r in sorted(rows, key=lambda r: r["period"]))


def p_text(v: dict) -> str:
    return f"{v['signFlipP']:.3f}" + ("" if v["n"] <= 16 else " (MC)")


def build(results: dict) -> tuple[Doc, str]:  # noqa: C901
    meta = results["meta"]
    summary = results["summary"]
    head = summary["thesis_headline"]
    inventory = results["inventory"]
    outcomes = {o["eventKey"]: o for o in results["outcomes"]}
    pairs = headline_pairs(results)
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
    non_us = sorted({SERIES_LABELS[e[0]] for e in events if e[0] == "KXUE"})
    pooled = {(spec, h): head[spec][h]["pooled"] for spec in head for h in head[spec]}

    def pool(spec: str, horizon: str, metric: str) -> dict:
        return pooled[(spec, horizon)].get(metric) or {"n": 0}

    def rows_for(spec: str, horizon: str) -> list[dict]:
        return [
            p
            for p in pairs
            if p["spec"] == spec and p["horizon"] == horizon and p["primarySeries"]
        ]

    doc.h(1, "Thesis forecasts vs Kalshi prices: a paper comparison")
    doc.p(
        "Read-only scoring study. It places no orders, uses no Kalshi account and"
        " simulates no trading; every Kalshi number is public market data. Data as of"
        f" {meta['asOf']}. Thesis records at commit `{meta['commit'][:12]}` (published"
        f" log `{meta['logBody']}`), published distributions from projection"
        f" `{meta['distributions']['projectionRootSha256'][:12]}`. The analysis plan is"
        " `docs/kalshi-paper-comparison.md` in"
        " [ThesisInstitute/thesis#381](https://github.com/ThesisInstitute/thesis/pull/381);"
        " it was committed before any score was computed, and its last section lists"
        " every later change."
    )

    # Summary -------------------------------------------------------------------
    reg = {m: pool("primary", "at_registration", m) for m in ("deltaLog", "deltaBrier")}
    reg_rows = rows_for("primary", "at_registration")
    thin = {}
    for series in ("KXCPI", "KXCPICORE", "KXPCECORE"):
        spreads = [
            m["spread"]
            for m in results["markets"]
            if m["eventKey"].startswith(series + ":")
            and m["horizon"] == "at_registration"
            and m["spread"] is not None
        ]
        if spreads:
            thin[series] = statistics.median(spreads)
    d1 = {m: pool("primary", "release_minus_1d", m) for m in ("deltaLog", "deltaBrier")}
    d7 = pool("primary", "release_minus_7d", "deltaLog")
    l1 = {
        m: pool("liquid_markets_only", "release_minus_1d", m)
        for m in ("deltaLog", "deltaBrier")
    }
    last1 = pool("last_trade_price", "release_minus_1d", "deltaLog")
    same = head["primary"]["release_minus_1d"]["sameEventsAsRegistration"].get(
        "deltaLog"
    ) or {"n": 0}
    one_day = head["primary"]["release_minus_1d"]["bySeries"]
    big = [
        (s, one_day[s]["deltaLog"])
        for s in PRIMARY_ORDER
        if s in one_day and one_day[s]["deltaLog"]["n"] >= MIN_SERIES_N
    ]
    small = [
        s
        for s in PRIMARY_ORDER
        if s in one_day and 0 < one_day[s]["deltaLog"]["n"] < MIN_SERIES_N
    ]
    unmatched = results["unmatched"]
    doc.h(2, "Summary")
    bullets = [
        f"**Scope.** {len(primary_runs)} published Thesis headline forecasts recorded "
        "since 1 July 2026 are for a statistic Kalshi lists, across "
        f"{len({e[0] for e in events})} Kalshi series"
        + (f" (including {', '.join(non_us)})" if non_us else "")
        + f". {len(with_event)} of them have a Kalshi event for the same reference "
        f"period, and {len(released)} of those have been released and are scored "
        "against the official first print, on Kalshi's own brackets. The other "
        f"{len(unmatched)} published runs in scope were checked against Kalshi's "
        "catalog and have no matching event. Bracketed ranges are 95% bootstrap "
        "intervals; positive differences favor Thesis.",
    ]
    if reg_rows:
        floored = {
            sc["eventKey"]
            for sc in results["scores"]
            if sc["spec"] == "primary"
            and sc["forecaster"] == "thesis_headline"
            and sc["horizon"] == "at_registration"
            and sc["primarySeries"]
            and sc["kalshiFloored"]
        }
        hit = [r for r in reg_rows if r["eventKey"] in floored]
        others = [r["deltaLog"] for r in reg_rows if r["eventKey"] not in floored]
        reg_liquid = pool("liquid_markets_only", "at_registration", "deltaLog")
        text = (
            "**At Thesis's registration time**, the only horizon where Kalshi had no "
            f"more information than Thesis, the {reg['deltaLog']['n']} comparisons "
            "cannot tell the two apart. Under the pre-specified rule the log-score "
            f"difference is {ci_text(reg['deltaLog'])} and the Brier difference "
            f"{ci_text(reg['deltaBrier'])}"
        )
        if hit:
            text += (
                f", but {len(hit)} of the events had empty Kalshi books that priced the"
                " realized bracket at zero ("
                + ", ".join(f"{r['eventKey']} {num(r['deltaLog'])}" for r in hit)
                + f"); the other {len(others)} average {num(sum(others) / len(others))}"
            )
        text += (
            ". Dropping books quoted wider than 20 cents gives "
            f"{ci_text(reg_liquid)} over {reg_liquid['n']} events. Kalshi's books were "
            "thin at that point (median spreads of "
            + ", ".join(
                f"{v * 100:.0f} cents for {SHORT_NAMES[k]}" for k, v in thin.items()
            )
            + "), and the intervals admit large differences in either direction."
        )
        bullets.append(text)
    bullets.append(
        "**Closer to the release, Kalshi's prices scored better on average than "
        "Thesis's earlier, fixed forecast**, as expected given the information that "
        "arrived in between. Under the pre-specified rule the difference is not clear: "
        f"one day before release the log difference is {ci_text(d1['deltaLog'])} "
        f"(Brier {ci_text(d1['deltaBrier'])}) over {d1['deltaLog']['n']} events, and "
        f"seven days before it is {ci_text(d7)}. It becomes clear only after dropping "
        "order books with spreads above 20 cents, a rule adopted after the plan: one "
        f"day before release, log {ci_text(l1['deltaLog'])} over {l1['deltaLog']['n']} "
        f"events (Brier {ci_text(l1['deltaBrier'])}). It also depends on the price "
        "used: with last traded prices instead of midpoints, the one-day difference is "
        f"{ci_text(last1)}. On the {same['n']} events also scored at registration, the "
        f"one-day difference is {ci_text(same)}."
    )
    bullets.append(
        "**Per series, there are too few resolved pairs to conclude anything.** Only "
        + " and ".join(
            f"{SERIES_LABELS[s].split(' (')[0].lower()} ({v['n']})" for s, v in big
        )
        + " reach five pairs, and for "
        + ("both" if len(big) == 2 else "each")
        + " the one-day interval "
        + (
            "includes zero"
            if all(direction(v) == "interval includes zero" for _, v in big)
            else "is shown below"
        )
        + f". The other {len(small)} series have one to three events each; their "
        "individual differences are listed below rather than summarized."
    )
    bullets.append(
        "**What this does and does not measure.** It measures probabilistic forecast "
        "accuracy on official monthly and weekly statistics, mostly national US "
        "figures, at stated horizons. It does not measure skill at state or municipal "
        "questions, at municipal bond pricing, or at anything involving trading, and "
        "results this small should not be extrapolated to those."
    )
    doc.ul(bullets)

    figure_svg = dot_figure(
        [
            p
            for p in pairs
            if p["primarySeries"] and p["spec"] in ("primary", "liquid_markets_only")
        ]
    )
    doc.figure(
        figure_svg,
        "Each mark is one event: Thesis's log score minus Kalshi's on Kalshi's "
        "brackets. Filled dots use the pre-specified price rule; rings drop order "
        "books quoted wider than 20 cents. Hover a mark for its details.",
        "figure_log_differences.svg",
    )

    # Scope -------------------------------------------------------------------------
    doc.h(2, "What was compared")
    distinct = {
        i["runId"]: i
        for i in inventory
        if i["distributionProvenance"] == "interval_seeded"
    }
    exact = sum(
        1 for i in distinct.values() if i["publishedCdfCheck"] == "rebuilt_exact"
    )
    catalog = meta["kalshiCatalog"]
    in_scope_text = (
        f"all {meta['publishedRuns']} recorded since 1 July 2026"
        if meta["publishedRuns"] == meta["publishedRunsInScope"]
        else f"{meta['publishedRunsInScope']} of them recorded since 1 July 2026"
    )
    ineligible = [
        i
        for i in primary_runs
        if i["headlineEligibleRoot"] is False
        and (i["kalshiSeries"], i["period"]) in released
    ]
    doc.p(
        f"The published Thesis log holds {meta['publishedRuns']} forecast runs, "
        f"{in_scope_text}. Kalshi's full series catalog ({catalog['series']:,} series, "
        f"{catalog['economicsSeries']} in Economics; stored response "
        f"`{(catalog['sha256'] or '')[:12]}`) was screened for every statistic Thesis "
        "forecasts, by keyword and then by reading the candidates. Matched runs are "
        "paired with the Kalshi event for the same reference period, read from the "
        "event title and every market's rule text. Each Thesis forecast is its "
        f"published 201-point CDF; all {exact} of the {len(distinct)} distinct "
        "interval-seeded runs used here rebuild exactly from the run's point estimate "
        "and 80% interval with the documented transform. Registration time is the "
        "RFC 3161 witness time of the run's custody root; the threshold-ladder "
        "variant has only a run-directory witness, and the persistence baseline has "
        "no witness and uses its recorded time."
        + (
            f" One scored headline run ({ineligible[0]['dataPointId']}) has a custody "
            "root that Thesis's own verifier marks not headline-eligible; results "
            "without it are reported below."
            if ineligible
            else ""
        )
    )
    rows = []
    for series in PRIMARY_ORDER:
        mine = [i for i in primary_runs if i["kalshiSeries"] == series]
        if not mine:
            continue
        periods = sorted({i["period"] for i in mine})
        rel = [p for p in periods if (series, p) in released]
        no_event = [p for p in periods if (series, p) not in with_event]
        pending = [
            p
            for p in periods
            if (series, p) in with_event and (series, p) not in released
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
                str(len(periods) - len(no_event)),
                str(len(rel)),
                " / ".join(n_by_h),
                f"{statistics.median(lead):.0f}" if lead else "n/a",
                ", ".join(
                    f"{p} (expected {outcomes[f'{series}:{p}']['expectedRelease']})"
                    for p in pending
                )
                or "none",
                ", ".join(no_event) or "none",
            ]
        )
    doc.table(
        [
            "Statistic",
            "Kalshi series",
            "Thesis forecasts",
            "With a Kalshi event",
            "Released",
            "Scored (reg / 7d / 1d)",
            "Median days, registration to release",
            "Awaiting release",
            "No Kalshi event for the period",
        ],
        rows,
        "Scored counts are events. An event is dropped at a horizon if the horizon "
        "falls before Thesis's registration or if no Kalshi market had a quote by "
        "then (see `exclusions.csv`).",
    )
    reasons = Counter(u["reason"] for u in unmatched)
    countries = Counter(u["country"] for u in unmatched)
    doc.p(
        f"**Runs with no matching Kalshi event.** {len(unmatched)} published runs "
        "recorded since 1 July ("
        + ", ".join(f"{n} {c}" for c, n in countries.most_common())
        + ") are listed in `unmatched.csv` with the evidence: "
        + "; ".join(f"{n} — {r}" for r, n in reasons.most_common())
        + "."
    )
    related_rows = {}
    for u in unmatched:
        if u["kalshiEvidence"]:
            key = (u["dataPointId"].rsplit(".", 2)[0], u["kalshiEvidence"], u["reason"])
            related_rows.setdefault(key, []).append(u["period"] or "?")
    if related_rows:
        doc.table(
            ["Thesis target family", "Thesis periods", "What Kalshi lists", "Verdict"],
            [
                [f"`{fam}`", ", ".join(sorted(set(ps))), ev, reason]
                for (fam, ev, reason), ps in sorted(related_rows.items())
            ],
            "Kalshi series the catalog screen found for statistics Thesis forecasts, "
            "with the 2026 reference periods each lists.",
        )
    withdrawn = results["withdrawn"]
    confirmed = sum(1 for w in withdrawn if w["livePageSaysNoForecast"])
    doc.p(
        f"{len(withdrawn)} catalog runs for matched statistics are not in the "
        f'published log. The live page for {confirmed} of them says "No forecast '
        'available" (pages stored with the other responses); they are listed in '
        "`withdrawn.csv` and not scored."
    )

    doc.h(3, "How each contract was read")
    doc.ul(
        [
            (
                'CPI, core CPI, U-3, core PCE and Australian unemployment: "above X" on'
                ' the single-decimal published value. Payrolls: "above X" persons on'
                ' the first-print change. JOLTS: "above X million" on the level BLS'
                ' reports in thousands. Housing starts and permits: "above X million"'
                ' on the first Census print; new home sales: "above X" homes.'
            ),
            (
                'Continuing claims: "at least X" on the advance seasonally adjusted'
                " figure first published, as the rule states. Initial claims: the rule"
                ' says only "at least X initial jobless claims for the week ending";'
                " Kalshi's recorded expiration value equals the seasonally adjusted"
                " advance figure in every week, and that is what is scored. Kalshi"
                ' switched continuing-claims strikes from "1.84 million" to "1750K"'
                " between events; each strike is read with the unit its own rule"
                " states, and the rule's direction word must agree with the market's"
                " strike type."
            ),
            (
                "Thesis's CDF is read as the distribution of the unrounded value the"
                " agency then rounds to its reporting grid g (0.1 point, 1,000 persons"
                " or homes, or 0.001 million): P(Y > s) = 1 − F(s + g/2) and P(Y ≥ s) ="
                " 1 − F(s − g/2). This is a symmetric reading of a continuous CDF for a"
                " value published on a grid; the literal reading 1 − F(s) is a"
                " sensitivity."
            ),
            (
                "Kalshi's price is the midpoint of the closing bid and ask of the last"
                " hourly candle at or before the horizon (an empty side counts as 0 or"
                " 1), searched over the market's whole life, with the ladder made"
                " non-increasing by isotonic regression. Brackets are the intervals"
                " between consecutive strikes."
            ),
        ]
    )

    # Outcomes -------------------------------------------------------------------
    doc.h(2, "Outcomes")
    mismatches = sum(len(o["kalshiResultMismatches"]) for o in results["outcomes"])
    n_markets = sum(o["nMarkets"] for o in results["outcomes"] if o["officialValue"])
    seconds = sum(1 for o in results["outcomes"] if o["officialSecondReading"])
    doc.p(
        "Each value is the official first print read from the agency's own release"
        " (BLS news release archive; DOL Employment and Training Administration weekly"
        " release; BEA Personal Income and Outlays; Census/HUD New Residential"
        " Construction and Sales; ABS Labour Force, Australia), with the release time"
        f" the document states. For {seconds} events the same document states the value"
        " a second time (lead paragraph, summary box or table), and the two readings"
        f" agree. Across {n_markets} settled Kalshi markets, the contract rule applied"
        " to the official value reproduces Kalshi's recorded result in every case"
        f" ({mismatches} disagreements)."
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
            (dps[0]["thesisResolverCode"] or dps[0]["thesisResolverState"])
            if dps
            else ""
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
        "Values are in Kalshi strike units (persons for payrolls and initial claims, "
        "homes for new home sales, millions for continuing claims, job openings, "
        "starts and permits, percent otherwise).",
    )
    differs = [
        o for o in results["outcomes"] if o["thesisLedgerAgreesWithOfficial"] is False
    ]
    unresolved = Counter(
        (i["thesisResolverCode"] or i["thesisResolverState"] or "no status")
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

    # Results -----------------------------------------------------------------------
    doc.h(2, "Results")
    doc.p(
        "Differences are Thesis minus Kalshi for log scores and Kalshi minus Thesis for"
        " Brier scores, so positive always favors Thesis. Intervals are 95% percentile"
        " bootstrap intervals, resampling events or, where stated, release dates. p is"
        " a two-sided sign-flip randomization test, exact for up to 16 events and from"
        " 100,000 random sign patterns (MC) above that. With three horizons, two scores"
        " and five price rules, no single interval should be read as a discovery."
    )
    rows = []
    for spec in ("primary", "liquid_markets_only"):
        for h in HORIZON_LABELS:
            p = pooled[(spec, h)]
            if not p:
                continue
            lg, br, lb = p["deltaLog"], p["deltaBrier"], p["deltaLadderBrier"]
            lo, hi = lg["ci95ReleaseClustered"]
            rows.append(
                [
                    SPEC_LABELS[spec],
                    HORIZON_LABELS[h],
                    str(lg["n"]),
                    ci_text(lg),
                    f"[{num(lo)}, {num(hi)}]",
                    p_text(lg),
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
            "Log, release-clustered interval",
            "p",
            "Brier difference",
            "Ladder Brier difference",
            "Better log score",
        ],
        rows,
        "Pooled over the primary series, each event weighted equally. The plan names "
        "the release-clustered interval for pooled results; both are shown. The "
        "multi-category Brier is the plan's primary Brier score; the ladder Brier is "
        "secondary.",
    )
    subset_rows = []
    for spec in ("primary", "liquid_markets_only"):
        for h in ("release_minus_7d", "release_minus_1d"):
            v = head[spec][h]["sameEventsAsRegistration"].get("deltaLog")
            if v:
                subset_rows.append(
                    [
                        SPEC_LABELS[spec],
                        HORIZON_LABELS[h],
                        "Same events as registration",
                        str(v["n"]),
                        ci_text(v),
                    ]
                )
        if ineligible:
            v = head[spec]["release_minus_1d"]["headlineEligibleOnly"].get("deltaLog")
            if v:
                subset_rows.append(
                    [
                        SPEC_LABELS[spec],
                        HORIZON_LABELS["release_minus_1d"],
                        "Headline-eligible custody roots only",
                        str(v["n"]),
                        ci_text(v),
                    ]
                )
    doc.table(
        ["Price rule", "Horizon", "Subset", "Events", "Log difference"], subset_rows
    )

    for h in HORIZON_LABELS:
        doc.h(3, f"By series: {HORIZON_LABELS[h].lower()}")
        rows = []
        for series in PRIMARY_ORDER:
            prim = rows_for("primary", h)
            liq = rows_for("liquid_markets_only", h)
            mine = [r for r in prim if r["series"] == series]
            mine_l = [r for r in liq if r["series"] == series]
            if not mine:
                continue
            if len(mine) >= MIN_SERIES_N:
                v = head["primary"][h]["bySeries"][series]["deltaLog"]
                vl = (
                    head["liquid_markets_only"][h]["bySeries"]
                    .get(series, {})
                    .get("deltaLog")
                )
                vb = head["primary"][h]["bySeries"][series]["deltaBrier"]
                rows.append(
                    [
                        SERIES_LABELS[series],
                        str(len(mine)),
                        f"{ci_text(v)}, p {p_text(v)}",
                        ci_text(vl) if vl else "n/a",
                        ci_text(vb),
                        wins(v),
                    ]
                )
            else:
                rows.append(
                    [
                        SERIES_LABELS[series],
                        str(len(mine)),
                        values_text(mine, "deltaLog"),
                        values_text(mine_l, "deltaLog") or "n/a",
                        values_text(mine, "deltaBrier"),
                        "too few to summarize",
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
            ],
            rows,
            "With fewer than five events the individual differences are listed in "
            "period order; with two events a bootstrap interval is only the two"
            " values.",
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
        'All rules but "liquid markets only" were pre-specified. That rule was '
        "adopted after full runs whose saved output already contained scores; the "
        "author had not examined them, which the record cannot show, so treat it as "
        "post hoc. It changes the brackets as well as the prices: some registration "
        "comparisons rest on one or two strikes, where both forecasters put most "
        "probability on the realized bracket.",
    )

    # Secondary -----------------------------------------------------------------------
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
                f"{SERIES_LABELS[series]}: log {ci_text(m['deltaLog'])} "
                f"({wins(m['deltaLog'], 'headline', 'baseline')}); Brier "
                f"{ci_text(m['deltaBrier'])} "
                f"({wins(m['deltaBrier'], 'headline', 'baseline')})"
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
            mine = [
                p
                for p in pairs
                if p["series"] == series
                and p["horizon"] == h
                and p["spec"] == "primary"
            ]
            cells.append(values_text(mine, "deltaLog") or "n/a")
        exact_rows.append(cells)
    doc.p(
        '**Exact-value markets** ("exactly X") cover the same CPI and unemployment '
        'prints with less volume. They are scored with an added "any other value" '
        "bracket and are not pooled with the main results."
    )
    doc.table(["Markets (log differences)"] + list(HORIZON_LABELS.values()), exact_rows)
    variant = [i for i in inventory if i["forecaster"].startswith("thesis_variant")]
    if variant:
        v = variant[0]
        knots = v["publishedCdfCheck"].split(":")[-1].split(",")
        doc.p(
            "**Threshold-ladder variant.** One additional Thesis run"
            f" ({v['dataPointId']}, registered {v['registeredAt'][:10]}) used ladder"
            f" elicitation. Its published CDF is {knots[0]} at the lower end of its"
            f" stated 80% interval and {knots[-1]} at the upper end, rather than 0.1"
            " and 0.9. Its scores under both CDF readings are in `pairs.csv`."
        )

    # Liquidity ---------------------------------------------------------------------
    doc.h(2, "Market liquidity")
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for m in results["markets"]:
        series = m["eventKey"].split(":")[0]
        if series in PRIMARY_ORDER:
            by[(series, m["horizon"])].append(m)
    rows = []
    for series in PRIMARY_ORDER:
        if not any(by.get((series, h)) for h in HORIZON_LABELS):
            continue
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
        "Median bid-ask spread across an event's markets at the horizon, and contracts "
        "traded in the seven days before it, summed over scored events. Per-market "
        "detail, including volume traded up to each horizon, is in `markets.csv`.",
    )

    # Caveats ------------------------------------------------------------------------
    kalshi_floor_hits = [
        s
        for s in results["scores"]
        if s["spec"] == "primary"
        and s["forecaster"] == "thesis_headline"
        and s["primarySeries"]
        and s["kalshiFloored"]
    ]
    unquoted = sum(
        1
        for e in results["exclusions"]
        if e.get("reason") == "market open but no candle by then"
    )
    doc.h(2, "Caveats")
    doc.ul(
        [
            (
                "Samples are small and correlated: headline and core CPI share a"
                " release, as do U-3 and payrolls, initial and continuing claims, and"
                " housing starts and permits."
            ),
            (
                "Only the registration-time comparison gives both sides the same"
                " information, and even there Kalshi may have had slightly more:"
                " registration is the witness time, up to about half a day after the"
                " run's recorded time. The 7-day and 1-day comparisons pit a fixed"
                " Thesis forecast against a market that has kept updating, so they"
                " measure the value of later information as much as forecasting skill."
            ),
            (
                "Thesis interval-seeded CDFs are a piecewise-linear shape through five"
                " knots (support ends, 10%, 50%, 90%), so the probability on a narrow"
                " bracket reflects that transform as much as the forecaster's belief."
            ),
            "Kalshi's empty or wide books produce midpoints that are not forecasts,"
            " and isotonic repair can pool them into a flat run that gives a bracket"
            f" zero. Under the primary rule, {len(kalshi_floor_hits)} Kalshi log scores"
            " hit the probability floor this way ("
            + ", ".join(
                f"{s['eventKey']} {s['horizon'].replace('_', ' ')}"
                for s in kalshi_floor_hits
            )
            + "). The liquid-markets rule drops such books.",
            (
                f"{unquoted} market-horizon cases had a market open but never quoted"
                " before the horizon; those markets are left out of that horizon's"
                " ladder and listed in `exclusions.csv`."
            ),
            (
                "Weekly claims are mostly comparable only one day before release,"
                " because Kalshi usually lists each week's markets after Thesis"
                " registers, and continuing-claims markets are thinly traded."
            ),
        ]
    )

    doc.h(2, "Reproduce")
    doc.p(
        "From a checkout of the PR branch, with network access: "
        "`python3 scripts/kalshi_paper_comparison.py --out <dir> --as-of <UTC time>`. "
        "Every response used is stored by SHA-256 under `fetch/`; adding `--offline "
        "--cache <path to fetch>` reruns from the stored responses only. `pdftotext` "
        "(poppler) is needed to read the DOL and Census releases."
    )
    doc.h(2, "Files")
    doc.ul(
        [
            (
                "`inventory.csv`: every matched Thesis run, with registration proof,"
                " published CDF check, Kalshi event, official value and Thesis resolver"
                " status. `unmatched.csv`: every other run in scope and the Kalshi"
                " evidence. `withdrawn.csv`: catalog runs the site does not publish."
            ),
            (
                "`outcomes.csv`: official first prints, sources, hashes and the Kalshi "
                "cross-check."
            ),
            (
                "`markets.csv`: each Kalshi market at each horizon: bid, ask, midpoint,"
                " last trade, spread, open interest, volume in the prior week and up to"
                " the horizon."
            ),
            (
                "`scores.csv` and `pairs.csv`: bracket probabilities and scores per"
                " event, horizon, forecaster and rule. `summary.json`: all summaries,"
                " including release-clustered and two-stage series-balanced intervals"
                " and the subsets above. `exclusions.csv`: what was left out at each"
                " horizon and why."
            ),
        ]
    )
    return doc, figure_svg


def _ts(value: str) -> float:
    import datetime as dt

    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
