"""The parsers against real Archive captures of non-target months.

Each fixture is the exact body the Archive stores for one capture (its ``id_``
form), with the index row's digest beside it. The expected values are read
from the same release's own prose, by a pattern that shares no code with the
table parser, so each test is a differential check of the table cell the
parser pins. No fixture is a capture of a month any reviewed contract
forecasts.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_pending  # noqa: E402
from legacy_release_contracts import LEGACY_RELEASE_CAPTURE_CONTRACTS  # noqa: E402
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


def test_a_real_cpi_release_is_refused_for_a_parser_of_another_page() -> None:
    _meta, _raw, html = _load(FIXTURES / "cpi.nr0-20260720045436.json")
    for parser_id in (
        "empsit_unemployment_rate",
        "empsit_payroll_change",
        "jolts_job_openings",
        "jolts_quits_rate",
    ):
        assert parse_release(html, parser_id) is None
