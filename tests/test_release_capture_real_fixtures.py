"""The parsers against real Archive captures of non-target months.

Each fixture is the exact body the Archive stores for one capture (its ``id_``
form), with the index row's digest beside it. Each pinned figure is checked
against a second source that shares no code with its parser: for the four
first fixtures' CPI, the release's own prose; for every other capture, the
first-print ALFRED vintage dated the capture day, recorded in the sidecar.
corpus/ holds one capture per release month across 2024-2026, so the
readers meet the wordings BLS has actually printed. No fixture is a capture
of a month any reviewed contract forecasts, and every one predates every
reviewed release window for its page.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import pathlib
import re
import sys
import urllib.error
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_pending  # noqa: E402
from legacy_release_contracts import LEGACY_RELEASE_CAPTURE_CONTRACTS  # noqa: E402
from legacy_release_parsers import LABELS as LEGACY_RELEASE_LABELS  # noqa: E402
from legacy_release_parsers import parse_release  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "release_capture"
CORPUS = sorted((FIXTURES / "corpus").glob("*.json"))
CAPTURES = sorted(FIXTURES.glob("*.json")) + CORPUS
_MONTHS = (
    "january february march april may june july august september october "
    "november december"
).split()


def _load(sidecar: pathlib.Path) -> tuple[dict, bytes, str]:
    meta = json.loads(sidecar.read_text())
    raw = sidecar.with_suffix(".raw").read_bytes()
    body = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    return meta, raw, body.decode("utf-8", errors="replace")


def _period(meta: dict) -> str:
    """The release month a sidecar's title names ("M13" is December)."""
    match = re.search(r"(\d{4}) M(\d{2})", meta["title"])
    assert match is not None
    return f"{match.group(1)}-{min(int(match.group(2)), 12):02d}"


def _prose(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text)


_SIGN = {
    "increased": 1,
    "rose": 1,
    "decreased": -1,
    "declined": -1,
    "fell": -1,
}


def _cpi_prose_change(text: str, subject: str, month: str) -> float:
    """The one-month change a CPI release's lead paragraphs state in words."""
    unchanged = re.search(rf"{subject} was unchanged in {month}", text)
    moved = re.search(
        rf"{subject} (increased|rose|decreased|declined|fell) (\d+\.\d) percent"
        rf"(?: on a seasonally adjusted basis)? in {month}",
        text,
    )
    assert bool(unchanged) != bool(moved), f"prose for {subject!r} is not unique"
    if unchanged:
        return 0.0
    assert moved is not None
    return _SIGN[moved.group(1)] * float(moved.group(2))


def test_there_is_a_real_capture_fixture() -> None:
    assert CAPTURES, "no real Archive capture fixture"


@pytest.mark.parametrize("sidecar", CAPTURES, ids=lambda p: p.stem)
def test_each_fixture_is_exactly_the_bytes_its_index_row_names(
    sidecar: pathlib.Path,
) -> None:
    meta, raw, html = _load(sidecar)
    assert resolve_pending.a19_digest(raw) == meta["indexDigest"]
    assert (raw[:2] == b"\x1f\x8b") is meta["gzipEncoded"]
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    assert title is not None
    assert re.sub(r"\s+", " ", title.group(1)).strip() == meta["title"]


@pytest.mark.parametrize("sidecar", CAPTURES, ids=lambda p: p.stem)
def test_no_fixture_is_a_month_a_reviewed_contract_forecasts(
    sidecar: pathlib.Path,
) -> None:
    meta, _raw, _html = _load(sidecar)
    forecast = {
        (entry["contract"]["sourceBinding"]["sourceUrl"], entry["contract"]["period"])
        for entry in LEGACY_RELEASE_CAPTURE_CONTRACTS.values()
    }
    assert (meta["sourceUrl"], _period(meta)) not in forecast


@pytest.mark.parametrize("sidecar", CAPTURES, ids=lambda p: p.stem)
def test_every_fixture_predates_every_reviewed_window_for_its_page(
    sidecar: pathlib.Path,
) -> None:
    """Assignment stays blind: no fixture was captured once a target could print."""
    meta = json.loads(sidecar.read_text())
    stamp = meta["stamp"]
    assert (
        meta["captureUrl"] == f"https://web.archive.org/web/{stamp}/{meta['sourceUrl']}"
    )
    captured = dt.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
    starts = [
        dt.date.fromisoformat(
            entry["contract"]["sourceBinding"]["expectedReleaseWindow"]["start"]
        )
        for entry in LEGACY_RELEASE_CAPTURE_CONTRACTS.values()
        if entry["contract"]["sourceBinding"]["sourceUrl"] == meta["sourceUrl"]
    ]
    assert starts
    assert captured < min(starts)


def test_cpi_table_a_cells_agree_with_the_release_prose() -> None:
    sidecar = FIXTURES / "cpi.nr0-20260720045436.json"
    _meta, _raw, html = _load(sidecar)
    text = _prose(html)
    month = "June"
    headline = _cpi_prose_change(
        text, r"The Consumer Price Index for All Urban Consumers \(CPI-U\)", month
    )
    core = _cpi_prose_change(
        text, r"The index for all items less food and energy", month
    )
    assert parse_release(html, "cpi_headline_mom") == ("2026-06", headline)
    assert parse_release(html, "cpi_core_mom") == ("2026-06", core)
    # The two rows are different cells of one table, and here they differ.
    assert headline != core


_PAGE_PARSERS = {
    "https://www.bls.gov/news.release/cpi.nr0.htm": {
        "cpi_headline_mom",
        "cpi_core_mom",
    },
    "https://www.bls.gov/news.release/empsit.nr0.htm": {
        "empsit_unemployment_rate",
        "empsit_payroll_change",
    },
    "https://www.bls.gov/news.release/jolts.nr0.htm": {"jolts_job_openings"},
    "https://www.bls.gov/news.release/jolts.t04.htm": {"jolts_quits_rate"},
}


def test_every_reviewed_page_and_parser_has_a_real_fixture() -> None:
    contracts = {
        (entry["contract"]["sourceBinding"]["sourceUrl"], entry["parser"])
        for entry in LEGACY_RELEASE_CAPTURE_CONTRACTS.values()
    }
    assert contracts == {
        (url, parser_id) for url, ids in _PAGE_PARSERS.items() for parser_id in ids
    }
    fixtures = {json.loads(sidecar.read_text())["sourceUrl"] for sidecar in CAPTURES}
    assert fixtures == set(_PAGE_PARSERS)


@pytest.mark.parametrize("sidecar", CAPTURES, ids=lambda p: p.stem)
def test_each_real_page_is_read_only_by_its_own_parsers(sidecar: pathlib.Path) -> None:
    meta, _raw, html = _load(sidecar)
    own = _PAGE_PARSERS[meta["sourceUrl"]] - set(meta.get("expectedRefusal", {}))
    for parser_id in LEGACY_RELEASE_LABELS:
        reading = parse_release(html, parser_id)
        assert (reading is not None) is (parser_id in own), parser_id


def _discover_capture(meta: dict, raw: bytes, parser_id: str):
    """What the leg's own discovery makes of one real capture, as stored.

    A one-row index holds the capture's own stamp and digest, inside a
    closed window around the capture day.
    """
    stamp, source_url = meta["stamp"], meta["sourceUrl"]
    day = dt.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
    index = json.dumps(
        [resolve_pending._WAYBACK_CDX_HEADER]
        + [[stamp, source_url, "200", meta["indexDigest"]]]
    ).encode()

    def read(url: str) -> tuple[bytes, str]:
        if url.startswith("https://web.archive.org/cdx/"):
            return index, url
        if url == f"https://web.archive.org/web/{stamp}id_/{source_url}":
            return raw, url
        raise urllib.error.HTTPError(url, 404, "no capture", None, None)

    return resolve_pending.a19_registered_capture(
        _period(meta),
        {
            "start": f"{day - dt.timedelta(days=3)}",
            "end": f"{day + dt.timedelta(days=1)}",
        },
        day + dt.timedelta(days=2),
        read,
        request_capture=False,
        source_url=source_url,
        parser=lambda page: parse_release(page, parser_id),
        parser_name=f"the BLS release ({parser_id})",
        require_digest=True,
    )


_OWN = [
    (sidecar, parser_id)
    for sidecar in CAPTURES
    for parser_id in sorted(_PAGE_PARSERS[json.loads(sidecar.read_text())["sourceUrl"]])
]


@pytest.mark.parametrize(
    ("sidecar", "parser_id"),
    _OWN,
    ids=[f"{sidecar.stem}-{parser_id}" for sidecar, parser_id in _OWN],
)
def test_each_real_capture_resolves_through_discovery_or_defers_for_its_reason(
    sidecar: pathlib.Path, parser_id: str
) -> None:
    meta, raw, _html = _load(sidecar)
    found = _discover_capture(meta, raw, parser_id)
    if parser_id in meta.get("expectedRefusal", {}):
        assert found.url is None
        assert "CAPTURE UNIDENTIFIED (deferring)" in found.verdict
    else:
        assert found.verdict == ""
        assert found.url == meta["captureUrl"]


def test_every_expected_refusal_says_why_and_is_a_cpi_shutdown_month() -> None:
    refusals = {
        sidecar.stem: json.loads(sidecar.read_text()).get("expectedRefusal", {})
        for sidecar in CAPTURES
    }
    refused = {stem: ids for stem, ids in refusals.items() if ids}
    # November 2025 CPI: Table A prints "-" where the one-month changes go.
    assert set(refused) == {"cpi.nr0-20251220005743"}
    for ids in refused.values():
        assert set(ids) == {"cpi_headline_mom", "cpi_core_mom"}
        assert all("October 2025" in reason for reason in ids.values())


def test_the_corpus_covers_every_page_across_many_release_months() -> None:
    months: dict[str, set[str]] = {}
    for sidecar in CORPUS:
        meta = json.loads(sidecar.read_text())
        months.setdefault(meta["sourceUrl"], set()).add(_period(meta))
    assert set(months) == set(_PAGE_PARSERS)
    counts = {url.rsplit("/", 1)[1]: len(periods) for url, periods in months.items()}
    assert counts == {
        "cpi.nr0.htm": 12,
        "empsit.nr0.htm": 21,
        "jolts.nr0.htm": 9,
        "jolts.t04.htm": 8,
    }


_INDEPENDENT = [
    (sidecar, parser_id)
    for sidecar in CAPTURES
    for parser_id in json.loads(sidecar.read_text()).get("independentFirstPrint", {})
]


@pytest.mark.parametrize(
    ("sidecar", "parser_id"),
    _INDEPENDENT,
    ids=[f"{sidecar.stem}-{parser_id}" for sidecar, parser_id in _INDEPENDENT],
)
def test_each_figure_agrees_with_the_independent_first_print(
    sidecar: pathlib.Path, parser_id: str
) -> None:
    meta, _raw, html = _load(sidecar)
    independent = meta["independentFirstPrint"][parser_id]
    reading = parse_release(html, parser_id)
    assert reading is not None
    assert reading[0] == _period(meta)
    expected = Decimal(str(independent["value"]))
    precision = independent.get("printedPrecision")
    if precision is not None:
        expected = expected.quantize(Decimal(str(precision)), ROUND_HALF_UP)
    assert Decimal(str(reading[1])) == expected


def test_every_fixture_but_the_first_cpi_records_an_independent_first_print() -> None:
    for sidecar in CAPTURES:
        meta = json.loads(sidecar.read_text())
        if sidecar.stem == "cpi.nr0-20260720045436":
            continue
        own = _PAGE_PARSERS[meta["sourceUrl"]] - set(meta.get("expectedRefusal", {}))
        assert set(meta["independentFirstPrint"]) == own


def test_the_jolts_summary_prints_openings_only_rounded_so_the_cells_are_held() -> None:
    """The evidence behind resolve_pending.LEGACY_RELEASE_PRECISION_HELD."""
    meta, _raw, html = _load(FIXTURES / "jolts.nr0-20260810093236.json")
    assert "<table" not in html.lower()
    assert re.search(r"\b7,?359\b", html) is None
    assert parse_release(html, "jolts_job_openings") == ("2026-06", 7.4)
    assert set(resolve_pending.LEGACY_RELEASE_PRECISION_HELD) == {"jolts_job_openings"}
    factors = {
        entry["contract"]["sourceBinding"]["transform"]["factor"]
        for entry in LEGACY_RELEASE_CAPTURE_CONTRACTS.values()
        if entry["parser"] == "jolts_job_openings"
    }
    # The contracts read thousands; the page prints 0.1 million.
    assert factors == {0.001}
    assert meta["independentFirstPrint"]["jolts_job_openings"]["value"] == 7.359


def test_one_disagreeing_statement_in_a_real_release_refuses_the_read() -> None:
    _meta, _raw, html = _load(FIXTURES / "empsit.nr0-20260810222604.json")
    assert parse_release(html, "empsit_unemployment_rate") == ("2026-07", 4.1)
    lead = "unemployment rate (4.1 percent)"
    assert html.count(lead) == 1
    changed = html.replace(lead, "unemployment rate (4.3 percent)")
    assert parse_release(changed, "empsit_unemployment_rate") is None
    assert parse_release(html, "empsit_payroll_change") == ("2026-07", -23.0)
    section = "changed little in July (-23,000)"
    assert html.count(section) == 1
    changed = html.replace(section, "changed little in July (-24,000)")
    assert parse_release(changed, "empsit_payroll_change") is None


def _with_sentence(html: str, sentence: str) -> str:
    """The page with one more sentence at the end of its release text."""
    end = html.lower().rindex("</pre>")
    return f"{html[:end]}\n{sentence}\n{html[end:]}"


_EMPSIT_REAL = FIXTURES / "empsit.nr0-20260810222604.json"
_EMPSIT_READINGS = {
    "empsit_unemployment_rate": ("2026-07", 4.1),
    "empsit_payroll_change": ("2026-07", -23.0),
}


@pytest.mark.parametrize(
    "sentence",
    (
        "Private nonfarm payroll employment rose by 123,000 in July.",
        "Private nonfarm payroll employment increased by 123,000 in July.",
        "Total nonfarm payroll employment rose by 123,000 per month, on "
        "average, over the prior 12 months.",
        "Total nonfarm payroll employment has increased by an average of "
        "123,000 per month since January.",
        "In June, the unemployment rate for teenagers was 12.1 percent.",
        "The unemployment rate for teenagers (12.1 percent) changed little in July.",
        "The unemployment rates for adult men (3.9 percent) and adult women "
        "(3.8 percent) changed little in July.",
        "The change in total nonfarm payroll employment for June was revised "
        "down by 37,000, from +57,000 to +20,000.",
        "Employment in health care rose by 55,000 in July.",
        "Total nonfarm payroll employment rose by 123,000 in July of last year.",
        "The unemployment rate was 3.9 percent in July a year earlier.",
        "Nonfarm payroll employment in July (+999,000) by industry is shown in "
        "table B-1.",
        # Round-3 review, finding 1: a qualifier after the month names
        # another period or measure, so the statement is not read.
        "The unemployment rate was 4.8 percent in July, a year earlier.",
        "The unemployment rate (4.8 percent) was unchanged in July (2025).",
        "The unemployment rate (4.8 percent) changed little in July (among teenagers).",
        "The unemployment rate (4.8 percent) changed little in July (not seasonally "
        "adjusted).",
        "The unemployment rate was 4.8 percent in July, before seasonal adjustment.",
        "Total nonfarm payroll employment rose by 123,000 in July, a year earlier.",
        "Total nonfarm payroll employment changed little in July (+123,000) (not "
        "seasonally adjusted).",
        "Total nonfarm payroll employment rose by 123,000 in July, and the "
        "unemployment rate was little changed at 4.8 percent in June.",
        "Chart 1. The unemployment rate (4.8 percent) in July.",
        "Chart 2. Total nonfarm payroll employment (+123,000) in July.",
    ),
)
def test_a_decoy_added_to_a_real_release_never_changes_its_reading(
    sentence: str,
) -> None:
    _meta, _raw, html = _load(_EMPSIT_REAL)
    changed = _with_sentence(html, sentence)
    for parser_id, reading in _EMPSIT_READINGS.items():
        assert parse_release(html, parser_id) == reading
        assert parse_release(changed, parser_id) == reading


@pytest.mark.parametrize(
    ("parser_id", "sentence"),
    (
        (
            "empsit_unemployment_rate",
            "The unemployment rate (4.8 percent) changed little in June.",
        ),
        (
            "empsit_unemployment_rate",
            "The unemployment rate, at 4.8 percent, was unchanged in June.",
        ),
        (
            "empsit_unemployment_rate",
            "The unemployment rate was 4.1 percent in July 2025.",
        ),
        (
            "empsit_unemployment_rate",
            "In June, the unemployment rate was 4.8 percent.",
        ),
        (
            "empsit_unemployment_rate",
            "In July 2025, the unemployment rate was 4.1 percent.",
        ),
        (
            "empsit_payroll_change",
            "Total nonfarm payroll employment rose by 63,000 in May.",
        ),
        (
            "empsit_payroll_change",
            "Total nonfarm payroll employment changed little in July 2025 (-23,000).",
        ),
    ),
)
def test_a_headline_statement_of_another_month_refuses_a_real_release(
    parser_id: str, sentence: str
) -> None:
    _meta, _raw, html = _load(_EMPSIT_REAL)
    assert parse_release(_with_sentence(html, sentence), parser_id) is None


@pytest.mark.parametrize(
    "paragraph",
    (
        "The unemployment rate and the number of unemployed people were little\n"
        "changed at 4.1 percent and 6.9 million, respectively, in July.",
        # Round-3 review, finding 2: the range is not read, the rate is.
        "The unemployment rate was unchanged at 4.1 percent in July and has\n"
        "remained in a narrow range of 4.0 percent to 4.2 percent since January.",
        "In July, the unemployment rate was unchanged at 4.1 percent.",
        "In July, the unemployment rate, at 4.1 percent, changed little, and the\n"
        "number of unemployed people was little changed at 6.9 million.",
        "The unemployment rate rose 0.1 percentage point to 4.1 percent in July\n"
        "and has shown little change since May 2025.",
    ),
)
def test_another_wording_of_the_household_paragraph_reads_the_same(
    paragraph: str,
) -> None:
    _meta, _raw, html = _load(_EMPSIT_REAL)
    household = re.compile(
        r"Both the unemployment rate,\s+at 4\.1 percent,\s+and the number of"
        r"\s+unemployed people,\s+at 6\.9 million,\s+changed little in July\."
    )
    assert len(household.findall(html)) == 1
    changed = household.sub(paragraph, html)
    assert changed != html
    assert parse_release(changed, "empsit_unemployment_rate") == ("2026-07", 4.1)
    # The same paragraph of another month refuses the page.
    june = household.sub(paragraph.replace("July", "June"), html)
    assert parse_release(june, "empsit_unemployment_rate") is None
    # Without the household paragraph the lead alone is one statement.
    alone = household.sub("Household measures changed little.", html)
    assert parse_release(alone, "empsit_unemployment_rate") is None


def test_a_lead_whose_payroll_verb_contradicts_its_sign_refuses_both_readers() -> None:
    """Round-3 review, finding 4: the rate's lead clause is checked too."""
    _meta, _raw, html = _load(_EMPSIT_REAL)
    lead = re.compile(
        r"Both\s+nonfarm\s+payroll\s+employment\s+\(-23,000\)\s+and\s+the\s+"
        r"unemployment\s+rate\s+\(4\.1\s+percent\)\s+changed\s+little\s+in\s+July"
    )
    assert len(lead.findall(html)) == 1
    for verb in ("rose", "edged up", "increased"):
        changed = lead.sub(
            "Both nonfarm payroll employment (-23,000) and the unemployment rate "
            f"(4.1 percent) {verb} in July",
            html,
        )
        for parser_id in _EMPSIT_READINGS:
            assert parse_release(changed, parser_id) is None
    # The same lead with its verb agreeing reads as before.
    agreeing = lead.sub(
        "Both nonfarm payroll employment (-23,000) and the unemployment rate "
        "(4.1 percent) edged down in July",
        html,
    )
    for parser_id, reading in _EMPSIT_READINGS.items():
        assert parse_release(agreeing, parser_id) == reading


def _phrase(text: str) -> re.Pattern[str]:
    """`text` as the page prints it, wherever its lines break."""
    return re.compile(r"\s+".join(map(re.escape, text.split())))


def _discover(html: str, parser_id: str):
    """What the leg's own discovery makes of one capture holding `html`.

    The capture is the real July fixture's stamp, inside a closed window,
    served as the Archive stores it (gzip) under its index digest.
    """
    meta = json.loads(_EMPSIT_REAL.read_text())
    stamp, source_url = meta["stamp"], meta["sourceUrl"]
    raw = gzip.compress(html.encode())
    index = json.dumps(
        [resolve_pending._WAYBACK_CDX_HEADER]
        + [[stamp, source_url, "200", resolve_pending.a19_digest(raw)]]
    ).encode()

    def read(url: str) -> tuple[bytes, str]:
        if url.startswith("https://web.archive.org/cdx/"):
            return index, url
        if url == f"https://web.archive.org/web/{stamp}id_/{source_url}":
            return raw, url
        raise urllib.error.HTTPError(url, 404, "no capture", None, None)

    return resolve_pending.a19_registered_capture(
        "2026-07",
        {"start": "2026-08-07", "end": "2026-08-14"},
        dt.date(2026, 8, 15),
        read,
        request_capture=False,
        source_url=source_url,
        parser=lambda page: parse_release(page, parser_id),
        parser_name=f"the BLS release ({parser_id})",
        require_digest=True,
    )


@pytest.mark.parametrize(
    "continuation",
    (
        # Round-4 review, finding 1: each deferred the capture forever.
        ", following little change in June (+36,000)",
        ", following gains of 34,000 in May and 41,000 in June",
        ", similar to the average monthly gain of 166,000 in 2019",
        ", compared with an average monthly gain of 158,000 thus far this year",
        ", below the average monthly gain of 168,000 over the past 12 months",
        " and has shown little change since April",
        ", up from -13,000 in June",
        # Round-7 review, finding 2: the real tail with "for" or "during".
        ", following an average monthly gain of 34,000 for the prior 12 months",
        ", following an average monthly gain of 34,000 during the prior 12 months",
        ", following no change in June",
        # Round-8 red team (r8b), finding 1: each deferred the capture.
        ", after changing little over the prior 12 months",
        ", following a large increase in January (+77,000)",
        ", similar to the average increase of 11,000 jobs per month in 2024",
        ", following an average monthly gain of 150,000 over the past six months",
        " and has continued to trend up since April",
        " and has shown little change for the past year",
        " and has shown little or no change since April",
        " and has shown little change in recent months",
        ", above the prior 12-month average gain (+5,000)",
    ),
)
def test_a_payroll_continuation_is_a_tail_through_discovery(continuation: str) -> None:
    _meta, _raw, html = _load(_EMPSIT_REAL)
    section = _phrase(
        "Total nonfarm payroll employment changed little in July (-23,000), "
        "following an average monthly gain of 34,000 over the prior 12 months."
    )
    assert len(section.findall(html)) == 1
    changed = section.sub(
        f"Total nonfarm payroll employment changed little in July (-23,000)"
        f"{continuation}.",
        html,
    )
    assert changed != html
    assert parse_release(changed, "empsit_payroll_change") == ("2026-07", -23.0)
    found = _discover(changed, "empsit_payroll_change")
    assert found.verdict == ""
    assert found.url == _meta["captureUrl"]
    # The same capture with the statement qualified instead defers: the
    # page then holds one statement, and discovery cannot skip it.
    qualified = section.sub(
        "Total nonfarm payroll employment changed little in July (-23,000), a year "
        "earlier.",
        html,
    )
    deferred = _discover(qualified, "empsit_payroll_change")
    assert deferred.url is None
    assert "CAPTURE UNIDENTIFIED (deferring)" in deferred.verdict


@pytest.mark.parametrize(
    "paragraph",
    (
        "The unemployment rate was 4.1 percent in July and has remained at either "
        "4.1 percent or 4.2 percent since June.",
        "The unemployment rate was 4.1 percent in July and has shown little "
        "movement since January.",
        "The unemployment rate stood at 4.1 percent in July, compared with 3.9 "
        "percent a year earlier.",
        "The unemployment rate rose 0.1 percentage point to 4.1 percent in July, "
        "following a decline in June.",
    ),
)
def test_a_rate_continuation_is_a_tail_through_discovery(paragraph: str) -> None:
    _meta, _raw, html = _load(_EMPSIT_REAL)
    household = re.compile(
        r"Both the unemployment rate,\s+at 4\.1 percent,\s+and the number of"
        r"\s+unemployed people,\s+at 6\.9 million,\s+changed little in July\."
    )
    changed = household.sub(paragraph, html)
    assert changed != html
    assert parse_release(changed, "empsit_unemployment_rate") == ("2026-07", 4.1)
    found = _discover(changed, "empsit_unemployment_rate")
    assert found.verdict == ""
    assert found.url == _meta["captureUrl"]


@pytest.mark.parametrize(
    "sentence",
    (
        # Round-5 review, finding 1: a sentence whose tail speaks to the
        # figure's basis is no statement, so it neither reads nor refuses.
        "The unemployment rate was 4.8 percent in July and was not seasonally "
        "adjusted.",
        "The unemployment rate was 4.8 percent in July but was 4.1 percent after "
        "seasonal adjustment.",
        "Total nonfarm payroll employment rose by 123,000 in July, compared with "
        "-23,000 after seasonal adjustment.",
        # Round-5 review, finding 2: an undated statement of another figure
        # is ignored.
        "Annual Average Data for 2025\nThe unemployment rate was 4.0 percent.",
        "Total nonfarm payroll employment increased by 2,000,000 over the month.",
        # Round-6 review: the abbreviation ends no tail, and no other measure
        # or period follows one.
        "The unemployment rate was 4.8 percent in July, compared with the U.S. "
        "rate of 4.1 percent on a seasonally adjusted basis.",
        "The unemployment rate was 4.8 percent in July, after including "
        "discouraged workers in the labor force.",
        "The unemployment rate was 4.8 percent in July, after averaging the "
        "latest three months.",
        # Round-7 review: a comparison with a bare period makes the figure a
        # change over that period.
        "Total nonfarm payroll employment rose by 2,000,000 in July, compared with "
        "a year earlier.",
        "Total nonfarm payroll employment increased by 2,000,000 in July compared "
        "with the previous year.",
        # Round-8 review, finding 1: a later clause restating the figure for
        # the month, and a comparison with the release month itself.
        "Total nonfarm payroll employment rose by 2,000,000 in July, compared with "
        "a year earlier, and by 120,000 for the month.",
        "Total nonfarm payroll employment rose by 2,000,000 in July, compared with "
        "a gain of 120,000 in July.",
    ),
)
def test_a_sentence_of_another_basis_or_period_never_defers_a_real_release(
    sentence: str,
) -> None:
    meta, _raw, html = _load(_EMPSIT_REAL)
    changed = _with_sentence(html, sentence)
    for parser_id, reading in _EMPSIT_READINGS.items():
        assert parse_release(changed, parser_id) == reading
        found = _discover(changed, parser_id)
        assert found.verdict == ""
        assert found.url == meta["captureUrl"]


# Sentences in the readers' own forms, of any figure, month and year, with
# or without a tail, for the property below.
_ADDED_TAILS = (
    "",
    ", following little change in June (+36,000)",
    ", compared with an average monthly gain of 158,000 over the prior 12 months",
    " and has remained in a narrow range of 4.0 percent to 4.2 percent since January",
    ", the U.S. Bureau of Labor Statistics reported today",
    ", compared with a year earlier",
    ", a year earlier",
    ", after seasonal adjustment",
    ", compared with the U.S. rate of 4.1 percent",
    ", compared with a year earlier, and by 120,000 for the month",
    ", compared with a gain of 120,000 in July",
)


@st.composite
def _added_empsit_sentence(draw: st.DrawFn) -> str:
    month = draw(st.sampled_from(("June", "July", "August")))
    when = draw(
        st.sampled_from(
            (
                "",
                " over the month",
                f" in {month}",
                f" in {month} 2025",
                f" in {month} 2026",
            )
        )
    )
    tail = draw(st.sampled_from(_ADDED_TAILS))
    rate = draw(st.sampled_from(("3.9", "4.1", "4.8")))
    change = draw(st.sampled_from((-23_000, 23_000, -123_000, 123_000)))
    signed, count = f"{change:+,}", f"{abs(change):,}"
    # The verb need not agree with the sign, so some sentences contradict
    # themselves.
    verb = draw(st.sampled_from(("rose by", "increased by", "declined by", "fell by")))
    words = draw(st.sampled_from(("changed little", "edged up", "edged down")))
    return draw(
        st.sampled_from(
            (
                f"The unemployment rate was {rate} percent{when}{tail}.",
                f"The unemployment rate ({rate} percent) changed little{when}{tail}.",
                f"The unemployment rate changed little at {rate} percent{when}{tail}.",
                f"In {month}, the unemployment rate was {rate} percent{tail}.",
                f"Total nonfarm payroll employment {verb} {count}{when}{tail}.",
                f"Total nonfarm payroll employment {words}{when} ({signed}){tail}.",
                f"Both nonfarm payroll employment ({signed}) and the unemployment rate "
                f"({rate} percent) {words}{when}{tail}.",
                f"Total nonfarm payroll employment {verb} {count}{when}, and the "
                f"unemployment rate changed little at {rate} percent{tail}.",
            )
        )
    )


@st.composite
def _added_jolts_sentence(draw: st.DrawFn) -> str:
    month = draw(st.sampled_from(("May", "June", "July")))
    when = draw(
        st.sampled_from(
            (
                "",
                " over the month",
                f" in {month}",
                f" in {month} 2025",
                f" on the last business day of {month}",
            )
        )
    )
    tail = draw(st.sampled_from(_ADDED_TAILS))
    level = draw(st.sampled_from(("6.5", "7.2", "7.4")))
    change = draw(st.sampled_from(("", " (-386,000)", " (+120,000)")))
    return draw(
        st.sampled_from(
            (
                f"The number of job openings was {level} million{change}{when}{tail}.",
                f"The number of job openings was little changed at {level} million"
                f"{change}{when}{tail}.",
                f"The number of job openings declined by 386,000 to {level} million"
                f"{when}{tail}.",
            )
        )
    )


def _sentence_ends(html: str) -> list[int]:
    """Where a sentence of the release text ends (never after "U.S.")."""
    start, end = html.lower().index("<pre"), html.lower().rindex("</pre>")
    return [
        start + match.end()
        for match in re.finditer(r"(?<!U\.S)\.(?=\s+[A-Z])", html[start:end])
    ]


def _check_added_sentences(
    sidecar: pathlib.Path, readings: dict, sentence: st.SearchStrategy[str], draw
) -> None:
    _meta, _raw, html = _load(sidecar)
    ends = _sentence_ends(html)
    added = draw(
        st.lists(st.tuples(st.sampled_from(ends), sentence), min_size=1, max_size=3)
    )
    changed = html
    for at, text in sorted(added, reverse=True):
        changed = f"{changed[:at]} {text}{changed[at:]}"
    for parser_id, reading in readings.items():
        assert parse_release(html, parser_id) == reading
        got = parse_release(changed, parser_id)
        event(f"{parser_id}: {'kept' if got == reading else 'refused'}")
        assert got in (reading, None), (added, got)


@settings(max_examples=300, deadline=None)
@given(data=st.data())
def test_no_added_sentence_changes_a_real_employment_reading(
    data: st.DataObject,
) -> None:
    """Text added to a real page may refuse it, never change what it reads.

    A real release states each headline figure in a dated statement, so a
    statement of another figure for that month disagrees with it and refuses
    the page, and one of another month or year refuses it too. However a
    sentence is worded, then, the reader returns the release's own figure or
    nothing.
    """
    _check_added_sentences(
        _EMPSIT_REAL, _EMPSIT_READINGS, _added_empsit_sentence(), data.draw
    )


@settings(max_examples=150, deadline=None)
@given(data=st.data())
def test_no_added_sentence_changes_a_real_openings_reading(data: st.DataObject) -> None:
    _check_added_sentences(
        FIXTURES / "jolts.nr0-20260810093236.json",
        {"jolts_job_openings": ("2026-06", 7.4)},
        _added_jolts_sentence(),
        data.draw,
    )


def test_round_7_annual_comparisons_never_resolve_through_discovery() -> None:
    """Round-7 review, finding 1, verbatim: discovery accepted 2000."""
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "Total nonfarm payroll employment rose by 120,000 in July, following no "
        "change in June.\n"
        "Total nonfarm payroll employment rose by 2,000,000 in July, compared with a "
        "year earlier.\n"
        "Total nonfarm payroll employment increased by 2,000,000 in July compared "
        "with the previous year."
    )
    page = (
        "<html><head><title>Employment Situation Summary - 2026 M07 Results</title>"
        f"</head><body><pre>\n{pre}\n</pre></body></html>"
    )
    found = _discover(page, "empsit_payroll_change")
    assert found.url is None
    assert "CAPTURE UNIDENTIFIED (deferring)" in found.verdict


def test_round_8_a_later_clause_never_resolves_through_discovery() -> None:
    """Round-8 review, finding 1, verbatim: discovery accepted 2000."""
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "Total nonfarm payroll employment rose by 2,000,000 in July, compared with "
        "a year earlier, and by 120,000 for the month.\n"
        "Total nonfarm payroll employment increased by 2,000,000 in July, compared "
        "with a year earlier, and by 120,000 for the month."
    )
    page = (
        "<html><head><title>Employment Situation Summary - 2026 M07 Results</title>"
        f"</head><body><pre>\n{pre}\n</pre></body></html>"
    )
    assert parse_release(page, "empsit_payroll_change") is None
    found = _discover(page, "empsit_payroll_change")
    assert found.url is None
    assert "CAPTURE UNIDENTIFIED (deferring)" in found.verdict


_JULY_2025 = FIXTURES / "corpus" / "empsit.nr0-20250812021231.json"


@pytest.mark.parametrize(
    "trend",
    (
        "and has shown little change since April",
        # Round-8 red team (r8b), finding 1: each deferred this capture.
        "and has shown little or no change since April",
        "and has shown little change in recent months",
        "and has continued to show little change since April",
    ),
)
def test_another_wording_of_the_2025_trend_reads_the_same(trend: str) -> None:
    """The July 2025 release states payrolls before the rate, both with the
    trend since April; either wording of the trend reads the same."""
    _meta, _raw, html = _load(_JULY_2025)
    original = _phrase("and has shown little change since April")
    assert len(original.findall(html)) == 2
    changed = original.sub(trend, html)
    readings = {
        parser_id: parse_release(changed, parser_id)
        for parser_id in ("empsit_payroll_change", "empsit_unemployment_rate")
    }
    expected = {
        "empsit_payroll_change": ("2025-07", 73.0),
        "empsit_unemployment_rate": ("2025-07", 4.2),
    }
    if trend == "and has continued to show little change since April":
        # Not one of the forms: the payroll statements are no statements,
        # and the payroll reader defers. The rate, which opens after the
        # payroll sentence, then has nothing sound before it but text.
        expected = dict.fromkeys(expected)
    assert readings == expected


def test_round_8_red_team_text_before_the_lead_defers_a_real_release() -> None:
    """Round-8 red team (r8a), finding 2, on the real July capture: a label
    between the heading and the lead refuses both readers, and discovery
    defers."""
    _meta, _raw, html = _load(_EMPSIT_REAL)
    heading = _phrase("THE EMPLOYMENT SITUATION - JULY 2026")
    assert len(heading.findall(html)) == 1
    for label in ("Not seasonally adjusted:", "Puerto Rico", "(p)"):
        labelled = heading.sub(
            f"THE EMPLOYMENT SITUATION - JULY 2026\n\n{label}\n", html
        )
        for parser_id in _EMPSIT_READINGS:
            assert parse_release(labelled, parser_id) is None
            found = _discover(labelled, parser_id)
            assert found.url is None
            assert "CAPTURE UNIDENTIFIED (deferring)" in found.verdict


def test_round_8_red_team_a_commented_out_block_never_reads_a_real_release() -> None:
    """Round-8 red team (r8a), finding 3, on the real July capture: a forged
    block inside a comment changes nothing."""
    _meta, _raw, html = _load(_EMPSIT_REAL)
    forged = (
        "<!--<pre>THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "The unemployment rate was 4.8 percent in July.\n"
        "The unemployment rate was 4.8 percent.\n"
        "Total nonfarm payroll employment rose by 999,000 in July.\n"
        "Total nonfarm payroll employment rose by 999,000 in July.</pre>-->"
    )
    before = html.lower().index("<pre")
    after = html.lower().index("</pre>") + len("</pre>")
    for page in (
        html[:before] + forged + html[before:],
        html[:after] + forged + html[after:],
    ):
        for parser_id, reading in _EMPSIT_READINGS.items():
            assert parse_release(page, parser_id) == reading
