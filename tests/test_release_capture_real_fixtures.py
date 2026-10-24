"""The parsers against real Archive captures of non-target months.

Each fixture is the exact body the Archive stores for one capture (its ``id_``
form), with the index row's digest beside it. Each pinned figure is checked
against a second source that shares no code with its parser: for CPI, the
release's own prose; for the Employment Situation and JOLTS pages, the
first-print ALFRED vintage recorded in the sidecar. No fixture is a capture
of a month any reviewed contract forecasts.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import re
import sys
from decimal import ROUND_HALF_UP, Decimal

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_pending  # noqa: E402
from legacy_release_contracts import LEGACY_RELEASE_CAPTURE_CONTRACTS  # noqa: E402
from legacy_release_parsers import LABELS as LEGACY_RELEASE_LABELS  # noqa: E402
from legacy_release_parsers import parse_release  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "release_capture"
CAPTURES = sorted(FIXTURES.glob("*.json"))
_MONTHS = (
    "january february march april may june july august september october "
    "november december"
).split()


def _load(sidecar: pathlib.Path) -> tuple[dict, bytes, str]:
    meta = json.loads(sidecar.read_text())
    raw = sidecar.with_suffix(".raw").read_bytes()
    body = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    return meta, raw, body.decode("utf-8", errors="replace")


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
    match = re.search(r"(\d{4}) M(\d{2})", meta["title"])
    assert match is not None
    period = f"{match.group(1)}-{match.group(2)}"
    forecast = {
        (entry["contract"]["sourceBinding"]["sourceUrl"], entry["contract"]["period"])
        for entry in LEGACY_RELEASE_CAPTURE_CONTRACTS.values()
    }
    assert (meta["sourceUrl"], period) not in forecast


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
    own = _PAGE_PARSERS[meta["sourceUrl"]]
    for parser_id in LEGACY_RELEASE_LABELS:
        reading = parse_release(html, parser_id)
        assert (reading is not None) is (parser_id in own), parser_id


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
    match = re.search(r"(\d{4}) M(\d{2})", meta["title"])
    assert match is not None
    reading = parse_release(html, parser_id)
    assert reading is not None
    assert reading[0] == f"{match.group(1)}-{match.group(2)}"
    expected = Decimal(str(independent["value"]))
    precision = independent.get("printedPrecision")
    if precision is not None:
        expected = expected.quantize(Decimal(str(precision)), ROUND_HALF_UP)
    assert Decimal(str(reading[1])) == expected


def test_every_non_cpi_fixture_records_an_independent_first_print() -> None:
    for sidecar in CAPTURES:
        meta = json.loads(sidecar.read_text())
        if "cpi" in sidecar.stem:
            continue
        assert set(meta["independentFirstPrint"]) == _PAGE_PARSERS[meta["sourceUrl"]]


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
        "In June, the unemployment rate was 4.8 percent.",
        "The unemployment rate for teenagers (12.1 percent) changed little in "
        "July.",
        "The unemployment rates for adult men (3.9 percent) and adult women "
        "(3.8 percent) changed little in July.",
        "The change in total nonfarm payroll employment for June was revised "
        "down by 37,000, from +57,000 to +20,000.",
        "Employment in health care rose by 55,000 in July.",
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
            "empsit_payroll_change",
            "Total nonfarm payroll employment rose by 63,000 in May.",
        ),
        (
            "empsit_payroll_change",
            "Total nonfarm payroll employment changed little in July 2025 "
            "(-23,000).",
        ),
    ),
)
def test_a_headline_statement_of_another_month_refuses_a_real_release(
    parser_id: str, sentence: str
) -> None:
    _meta, _raw, html = _load(_EMPSIT_REAL)
    assert parse_release(_with_sentence(html, sentence), parser_id) is None


def test_the_respectively_wording_of_the_household_paragraph_reads_the_same() -> None:
    _meta, _raw, html = _load(_EMPSIT_REAL)
    household = re.compile(
        r"Both the unemployment rate,\s+at 4\.1 percent,\s+and the number of"
        r"\s+unemployed people,\s+at 6\.9 million,\s+changed little in July\."
    )
    assert len(household.findall(html)) == 1
    changed = household.sub(
        "The unemployment rate and the number of unemployed people were little\n"
        "changed at 4.1 percent and 6.9 million, respectively, in July.",
        html,
    )
    assert changed != html
    assert parse_release(changed, "empsit_unemployment_rate") == ("2026-07", 4.1)
    # Without the household paragraph the lead alone is one statement.
    alone = household.sub("Household measures changed little.", html)
    assert parse_release(alone, "empsit_unemployment_rate") is None
