"""Test fixtures, written from a run's stored responses.

- ``settlements.json.gz``: every settled event in scope with its official
  print (or why it has none) and, for each market, the fields the contract
  reader uses and Kalshi's recorded result. The differential test re-reads
  every strike and checks the print under each rule against the result.
- ``official_excerpts.json``: normalized text excerpts of the releases whose
  layouts the parsers were extended for, with each document's URL and SHA-256.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import re

from kalshi_compare import official
from kalshi_compare.fetch import BROWSER_COMPATIBLE_UA, FetchCache

MARKET_FIELDS = (
    "ticker",
    "rules_primary",
    "strike_type",
    "floor_strike",
    "yes_sub_title",
    "result",
    "expiration_value",
    "open_time",
    "close_time",
)

EXCERPT_DOCS = {
    # key: (url, anchors as (regex, before, after))
    "bls_cpi_2021-06": "https://www.bls.gov/news.release/archives/cpi_07132021.htm",
    "bls_cpi_2022-07": "https://www.bls.gov/news.release/archives/cpi_08102022.htm",
    "bls_cpi_2025-11": "https://www.bls.gov/news.release/archives/cpi_12182025.htm",
    "bls_cpi_2025-12": "https://www.bls.gov/news.release/archives/cpi_01132026.htm",
    "bls_empsit_2025-11": (
        "https://www.bls.gov/news.release/archives/empsit_12162025.htm"
    ),
    "bls_empsit_2025-12": (
        "https://www.bls.gov/news.release/archives/empsit_01092026.htm"
    ),
    "bea_pio_2022-11": (
        "https://www.bea.gov/news/2022/personal-income-and-outlays-november-2022"
    ),
    "bea_pio_2024-11": (
        "https://www.bea.gov/news/2024/personal-income-and-outlays-november-2024"
    ),
    "bea_pio_2024-12": (
        "https://www.bea.gov/news/2025/personal-income-and-outlays-december-2024"
    ),
    "bea_pio_2025-03": (
        "https://www.bea.gov/news/2025/personal-income-and-outlays-march-2025"
    ),
    "bea_pio_2025-10-11": (
        "https://www.bea.gov/news/2026/personal-income-and-outlays-october-and-november-2025"
    ),
    "bea_pio_2026-03": (
        "https://www.bea.gov/news/2026/personal-income-and-outlays-march-2026"
    ),
    "abs_lf_2026-02": (
        "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/"
        "labour-force-australia/feb-2026"
    ),
    "abs_lf_2026-04": (
        "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/"
        "labour-force-australia/apr-2026"
    ),
}
ANCHORS = {
    "bls_cpi": (
        (r"(?i)embargoed until", 0, 400),
        (r"CONSUMER PRICE INDEX\s*\W+\s*[A-Z]+ \d{4}", 0, 1200),
        (
            r"index for all items less food and"
            r" energy\s+(?:rose|increased|fell|declined|"
            r"decreased|was unchanged|edged)",
            0,
            300,
        ),
        (r"Table A\. Percent changes in CPI", 0, 2600),
    ),
    "bls_empsit": (
        (r"(?i)embargoed until", 0, 400),
        (r"THE EMPLOYMENT SITUATION\s*\W+", 0, 900),
        (r"Summary table A\. Household data", 0, 1700),
        (r"Summary table B\. Establishment data", 0, 700),
    ),
    "bea_pio": (
        (r"EMBARGOED UNTIL RELEASE AT", 0, 900),
        (r"Excluding food and energy, the PCE", 300, 300),
        (r"Related Measures \[", 0, 900),
        (r"Percent change from preceding month Personal income", 120, 900),
    ),
    "abs_lf": (
        (r"Reference period", 0, 160),
        (r"Release date and time", 0, 120),
        (r"In seasonally adjusted terms, in", 0, 520),
        (r"Key statistics - ", 0, 800),
    ),
}


def excerpt(text: str, anchors) -> str:
    """Windows around each anchor, merged and joined in document order."""
    spans = []
    for pattern, before, after in anchors:
        for found in re.finditer(pattern, text):
            spans.append(
                (max(0, found.start() - before), min(len(text), found.start() + after))
            )
    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return " ".join(text[s:e] for s, e in merged)


def write(
    cache: FetchCache, results: dict, events_built: list, directory: pathlib.Path
) -> None:
    directory = directory.expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    markets_by_event: dict[str, list[dict]] = {}
    for row in results["settlement"]:
        markets_by_event.setdefault(row["eventTicker"], []).append(row)
    events = []
    raw_markets = {event.ticker: event.event_markets_raw for event in events_built}
    for item in results["inventory"]:
        if not item["settled"]:
            continue
        events.append(
            {
                "series": item["series"],
                "eventTicker": item["eventTicker"],
                "period": item["period"],
                "periodCheck": item["periodCheck"],
                "officialValue": item["officialValue"],
                "releaseAt": item["releaseAt"],
                "sourceUrl": item["sourceUrl"],
                "sourceSha256": item["sourceSha256"],
                "officialNote": item["officialNote"],
                "droppedMarkets": item["droppedMarkets"],
                "markets": [
                    {k: m.get(k) for k in MARKET_FIELDS}
                    for m in raw_markets.get(item["eventTicker"], [])
                ],
            }
        )
    payload = json.dumps(
        {"asOf": results["meta"]["asOf"], "events": events}, indent=0, sort_keys=True
    ).encode()
    (directory / "settlements.json.gz").write_bytes(gzip.compress(payload, mtime=0))
    excerpts = {}
    for key, url in EXCERPT_DOCS.items():
        body = cache.get(url, user_agent=BROWSER_COMPATIBLE_UA, accept="*/*")
        text = official.html_text(body)
        kind = key.rsplit("_", 1)[0]
        excerpts[key] = {
            "url": url,
            "sourceSha256": cache.sha256_of(url),
            "kind": "html",
            "excerpt": excerpt(text, ANCHORS[kind]),
        }
    (directory / "official_excerpts.json").write_text(
        json.dumps(excerpts, indent=1) + "\n"
    )
