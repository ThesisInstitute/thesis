"""BEA Data Archive leg: a missed release day read from BEA's own archive copy.

Invariants these tests hold the leg to:

- The archive leg runs only after a registered release day, only for the two
  NIPA Table 5.3.5 stems, and never for the ITA stem.
- Every value it returns is the registered row's newest column in millions
  times 0.001, rounded to four places, and it is the same number the live
  iTable leg read from the same release (the differential test below).
- It resolves only when BEA's index lists exactly one Advance folder, named
  for the registered day, with no estimate dated earlier; when the workbook
  states that day as its publication day; and when BEA's server dates the
  workbook's last modification to that UTC day. Anything else refuses, except
  a transport failure or a quarter the index does not list yet, which defer.
- No input bytes raise: every malformed index or workbook is a refusal.
"""

from __future__ import annotations

import base64
import datetime as dt
import email.utils
import hashlib
import http.client
import io
import json
import pathlib
import re
import sys
import urllib.error
import warnings
import zipfile
from typing import Any
from xml.sax.saxutils import escape

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import register_targets  # noqa: E402
import resolution_status  # noqa: E402
import resolve_pending  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "bea_archive"
ITABLE_FIXTURES = ROOT / "tests" / "fixtures" / "ingestion_wave1" / "bea"
RELEASE_DAY = dt.date(2026, 7, 30)
PERIOD = "2026-04"
NONRES = "bea.private_nonresidential_fixed_investment"
RD = "bea.research_and_development_fixed_investment"
ITA = "bea.ita.personal_transfer_payments"
WORKBOOK = (FIXTURES / "section5-2026-q2-advance.xlsx").read_bytes()
INDEX = (FIXTURES / "index-2026-q2.json").read_bytes()
WORKBOOK_URL = (
    "https://apps.bea.gov/histdata/Files/Releases/GDP_and_PI/2026/Q2/"
    "Advance_July-30-2026/Section5all_xls.xlsx"
)
INDEX_URL = (
    "https://apps.bea.gov/histdata/core/data/Fea_DisplayChildrenC/"
    "?HistMainId=7&thePath=%2FInetpub%2Fwwwroot%2Fwebsite%2Fwebsite%2FHistData"
    "%2FFiles%2FReleases%2FGDP_and_PI%5C2026%5CQ2&getFiles=false&getDirs=true"
)
WORKBOOK_HEADERS = {
    "content-type": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    "content-length": "1807316",
    "last-modified": "Thu, 30 Jul 2026 13:48:02 GMT",
    "etag": '"73a973a2a20dd1:0"',
}
INDEX_HEADERS = {"content-type": "application/json", "content-length": "2469"}
QUARTER_ROOT = resolve_pending.BEA_ARCHIVE_SERVER_ROOT + "\\2026\\Q2\\"
MISSED = "FIRST-PRINT WINDOW MISSED (refusing)"


def _spec(series: str) -> dict[str, Any]:
    return resolve_pending.BEA_RELEASE_ADAPTERS[series]


def _archive_spec(series: str) -> dict[str, str]:
    return resolve_pending.BEA_ARCHIVE_ADAPTERS[series]


# --- the fixtures -----------------------------------------------------------


def test_archive_fixtures_are_hash_pinned() -> None:
    assert len(WORKBOOK) == 1_807_316
    assert hashlib.sha256(WORKBOOK).hexdigest() == (
        "5d0bc3fd1d1fe216418dc5dfe3c5737fbe240086dd5f3a2cd77d7ed6ceaf8439"
    )
    assert len(INDEX) == 2_469
    assert hashlib.sha256(INDEX).hexdigest() == (
        "dacf6b33932a14c73236f144451576f952207702a2e27c775686ae72eec93191"
    )


def test_archive_urls_are_the_ones_the_fixtures_came_from() -> None:
    assert resolve_pending.bea_archive_index_url(PERIOD) == INDEX_URL
    for series in (NONRES, RD):
        assert (
            resolve_pending.bea_archive_workbook_url(_spec(series), PERIOD, RELEASE_DAY)
            == WORKBOOK_URL
        )
    assert (
        resolve_pending.bea_archive_estimate_folder(dt.date(2026, 4, 9), "Third")
        == "Third_April-09-2026"
    )
    assert (
        resolve_pending.bea_archive_estimate_folder(dt.date(2026, 10, 29))
        == "Advance_October-29-2026"
    )
    with pytest.raises(ValueError, match="quarter start"):
        resolve_pending.bea_archive_index_url("2026-Q2")


def test_archive_adapters_cover_exactly_the_two_nipa_stems() -> None:
    assert set(resolve_pending.BEA_ARCHIVE_ADAPTERS) == {NONRES, RD}
    assert ITA in resolve_pending.BEA_RELEASE_ADAPTERS
    for series in resolve_pending.BEA_ARCHIVE_ADAPTERS:
        assert _spec(series)["table_id"] == "T50305"
        assert _spec(series).get("variant") is None


# --- the differential check against the live leg ------------------------------


@pytest.mark.parametrize(
    ("series", "value", "printed", "row"),
    [(NONRES, 4623.657, 4_623_657.0, 10), (RD, 937.772, 937_772.0, 26)],
)
def test_archive_workbook_reads_the_first_print_the_live_itable_served(
    series: str, value: float, printed: float, row: int
) -> None:
    reading, refusal = resolve_pending.bea_archive_reading(
        WORKBOOK, _spec(series), _archive_spec(series), PERIOD, RELEASE_DAY
    )
    assert refusal is None
    assert reading == {
        "value": value,
        "printedMillions": printed,
        "sheet": "T50305-Q",
        "row": row,
        "column": "2026Q2",
        "seriesCode": _archive_spec(series)["series_code"],
        "publishedLine": "Data published July 30, 2026",
    }
    # The live leg's own parse of the iTable response captured on 2026-08-07,
    # while the advance estimate was still BEA's current print.
    live_raw = (ITABLE_FIXTURES / "nipa-table-5-3-5-2026-q2.json").read_bytes()
    assert resolve_pending.bea_itable_value(
        live_raw, _spec(series), PERIOD, RELEASE_DAY
    ) == (reading["value"], None)


# --- the archive index --------------------------------------------------------


def _index(paths: Any, **overrides: Any) -> bytes:
    body = json.loads(INDEX)
    body["FileArray"] = paths
    body.update(overrides)
    return json.dumps(body).encode()


def _q2_paths() -> list[str]:
    return list(json.loads(INDEX)["FileArray"])


def test_index_check_accepts_the_q2_index() -> None:
    assert resolve_pending.bea_archive_index_check(INDEX, PERIOD, RELEASE_DAY) == (
        None,
        None,
    )


@pytest.mark.parametrize(
    "paths", [[], None, [QUARTER_ROOT + "Advance_July-30-2026\\UND"]]
)
def test_index_check_defers_a_quarter_with_no_estimate_yet(paths: Any) -> None:
    assert resolve_pending.bea_archive_index_check(
        _index(paths), PERIOD, RELEASE_DAY
    ) == ("the archive index lists no estimate for 2026 Q2 yet", None)


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        (b"<!DOCTYPE html><html></html>", "not UTF-8 JSON"),
        (b"\xff\xfe", "not UTF-8 JSON"),
        (b"[]", "not a JSON object"),
        (_index(None, MainName="Regional"), "names 'Regional'"),
        (_index(None, FolderPattern="GDP\\x"), "folder pattern"),
        (_index("Advance_July-30-2026"), "folder list is malformed"),
        (_index([1]), "folder list is malformed"),
        (
            _index([resolve_pending.BEA_ARCHIVE_SERVER_ROOT + "\\2026\\Q3\\x"]),
            "outside 2026 Q2",
        ),
        (_index([QUARTER_ROOT + "Advance"]), "names no estimate and day"),
        (_index([QUARTER_ROOT + "Advance_Julember-30-2026"]), "no calendar day"),
        (_index([QUARTER_ROOT + "Advance_July-32-2026"]), "no calendar day"),
        (
            _index([*_q2_paths(), QUARTER_ROOT + "Advance_July-31-2026"]),
            "not exactly the registered 'Advance_July-30-2026'",
        ),
        (
            _index([QUARTER_ROOT + "Second_August-26-2026"]),
            "Advance folders [], not exactly",
        ),
        (
            _index([*_q2_paths(), QUARTER_ROOT + "Initial_July-15-2026"]),
            "estimates dated before the registered release day",
        ),
    ],
)
def test_index_check_refuses(raw: bytes, fragment: str) -> None:
    deferral, refusal = resolve_pending.bea_archive_index_check(
        raw, PERIOD, RELEASE_DAY
    )
    assert deferral is None
    assert refusal is not None and fragment in refusal


def test_index_check_refuses_deep_nesting_instead_of_recursing() -> None:
    assert resolve_pending.bea_archive_index_check(
        b"[" * 100_000, PERIOD, RELEASE_DAY
    ) == (None, "the archive index is not UTF-8 JSON")


def test_index_check_refuses_another_registered_day() -> None:
    _deferral, refusal = resolve_pending.bea_archive_index_check(
        INDEX, PERIOD, dt.date(2026, 7, 29)
    )
    assert refusal == (
        "the archive index lists Advance folders ['Advance_July-30-2026'], not "
        "exactly the registered 'Advance_July-29-2026'"
    )


@settings(max_examples=200, deadline=None)
@given(
    st.lists(
        st.dates(min_value=dt.date(2026, 1, 1), max_value=dt.date(2027, 12, 31)),
        max_size=4,
    )
)
def test_index_check_refuses_exactly_when_an_estimate_predates_the_day(
    days: list[dt.date],
) -> None:
    paths = [QUARTER_ROOT + "Advance_July-30-2026"] + [
        QUARTER_ROOT + resolve_pending.bea_archive_estimate_folder(day, "Second")
        for day in days
    ]
    deferral, refusal = resolve_pending.bea_archive_index_check(
        _index(paths), PERIOD, RELEASE_DAY
    )
    assert deferral is None
    assert (refusal is not None) == any(day < RELEASE_DAY for day in days)


# --- the posting gate -----------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "refused"),
    [
        ("Thu, 30 Jul 2026 13:48:02 GMT", False),
        ("Thu, 30 Jul 2026 00:00:00 GMT", False),
        ("Thu, 30 Jul 2026 23:59:59 GMT", False),
        ("Fri, 31 Jul 2026 00:00:00 GMT", True),
        ("Wed, 29 Jul 2026 23:59:59 GMT", True),
        # 02:00 UTC on 31 July: the window is read as a UTC day.
        ("Thu, 30 Jul 2026 22:00:00 -0400", True),
        ("Wed, 26 Aug 2026 13:30:00 GMT", True),
        (None, True),
        ("", True),
        ("not a date", True),
    ],
)
def test_posting_gate(header: str | None, refused: bool) -> None:
    refusal = resolve_pending.bea_archive_posting_refusal(header, RELEASE_DAY)
    assert (refusal is not None) == refused


@settings(max_examples=300, deadline=None)
@given(
    st.datetimes(
        min_value=dt.datetime(2026, 7, 28),
        max_value=dt.datetime(2026, 8, 2),
        timezones=st.just(dt.timezone.utc),
    )
)
def test_posting_gate_passes_exactly_the_release_days_utc_instants(
    moment: dt.datetime,
) -> None:
    header = email.utils.format_datetime(moment.replace(microsecond=0), usegmt=True)
    refusal = resolve_pending.bea_archive_posting_refusal(header, RELEASE_DAY)
    assert (refusal is None) == (moment.date() == RELEASE_DAY)


# --- the workbook reader ------------------------------------------------------


def _cell(reference: str, value: Any, *, formula: bool = False) -> str:
    if isinstance(value, tuple):
        cell_type, text = value
        return f'<c r="{reference}" t="{cell_type}"><v>{escape(text)}</v></c>'
    if isinstance(value, str):
        return (
            f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">'
            f"{escape(value)}</t></is></c>"
        )
    body = "<f>1+1</f>" if formula else ""
    return f'<c r="{reference}">{body}<v>{value!r}</v></c>'


def _sheet_xml(cells: dict[str, Any], formulas: frozenset[str]) -> str:
    rows: dict[int, list[str]] = {}
    for reference, value in cells.items():
        row = int(re.sub(r"[A-Z]+", "", reference))
        rows.setdefault(row, []).append(
            _cell(reference, value, formula=reference in formulas)
        )
    body = "".join(
        f'<row r="{row}">{"".join(items)}</row>' for row, items in sorted(rows.items())
    )
    return (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{body}</sheetData></worksheet>"
    )


def _table(**changes: Any) -> dict[str, Any]:
    """The layout of BEA's Table 5.3.5 sheet, cut to two quarters."""

    cells: dict[str, Any] = {
        "A1": "Table 5.3.5. Private Fixed Investment by Type",
        "A2": "[Millions of dollars] Seasonally adjusted at annual rates",
        "A3": "Quarterly data from 2026Q1 to 2026Q2",
        "A4": "Bureau of Economic Analysis",
        "A5": "Data published July 30, 2026",
        "A6": "File created Jul 29 2026 11:34AM",
        "A8": "Line",
        "D8": "2026Q1",
        "E8": "2026Q2",
        "A9": "1",
        "B9": "    Private fixed investment",
        "C9": "A007RC",
        "D9": 5662069.0,
        "E9": 5809422.0,
        "A10": "2",
        "B10": "Nonresidential",
        "C10": "A008RC",
        "D10": 4490516.0,
        "E10": 4623657.0,
        "A26": "18",
        "B26": "    Research and development\\6\\",
        "C26": "Y006RC",
        "D26": 920000.0,
        "E26": 937772.0,
        "A42": "1. Includes petroleum and mineral exploration.",
    }
    for reference, value in changes.items():
        if value is None:
            cells.pop(reference, None)
        else:
            cells[reference] = value
    return cells


def _workbook(
    cells: dict[str, Any] | None = None,
    *,
    sheet_name: str = "T50305-Q",
    formulas: frozenset[str] = frozenset(),
    target: str = "worksheets/sheet1.xml",
    target_mode: str | None = None,
    extra: dict[str, str] | None = None,
    encrypted: bool = False,
) -> bytes:
    buffer = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate member names, on purpose
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr(
                "xl/workbook.xml",
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml'
                '/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships"><sheets><sheet name="'
                f'{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>',
            )
            mode = f' TargetMode="{target_mode}"' if target_mode else ""
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                '2006/relationships"><Relationship Id="rId1" Type="worksheet" '
                f'Target="{target}"{mode}/></Relationships>',
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                _sheet_xml(_table() if cells is None else cells, formulas),
            )
            for name, data in (extra or {}).items():
                archive.writestr(name, data)
    raw = buffer.getvalue()
    return _flag_encrypted(raw, "xl/worksheets/sheet1.xml") if encrypted else raw


def _flag_encrypted(raw: bytes, name: str) -> bytes:
    """Set the encryption bit on one member's central-directory entry.

    zipfile clears flag bits when it writes, so the bit is set afterwards, in
    the directory a reader lists members from.
    """

    data = bytearray(raw)
    start = 0
    while (at := data.find(b"PK\x01\x02", start)) >= 0:
        name_length = int.from_bytes(data[at + 28 : at + 30], "little")
        if bytes(data[at + 46 : at + 46 + name_length]) == name.encode():
            flags = int.from_bytes(data[at + 8 : at + 10], "little") | 0x1
            data[at + 8 : at + 10] = flags.to_bytes(2, "little")
            return bytes(data)
        start = at + 4
    raise AssertionError(f"no central-directory entry for {name}")


def _read(raw: bytes, series: str = NONRES) -> tuple[dict[str, Any] | None, str | None]:
    return resolve_pending.bea_archive_reading(
        raw, _spec(series), _archive_spec(series), PERIOD, RELEASE_DAY
    )


def test_synthetic_layout_reads_like_the_official_workbook() -> None:
    for series in (NONRES, RD):
        synthetic, synthetic_refusal = _read(_workbook(), series)
        official, official_refusal = _read(WORKBOOK, series)
        assert synthetic_refusal is None and official_refusal is None
        assert synthetic is not None and official is not None
        assert synthetic["value"] == official["value"]
        assert synthetic["publishedLine"] == official["publishedLine"]


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        (b"", "did not open"),
        (b"<!DOCTYPE html><html><title>BEA</title></html>", "did not open"),
        (_workbook(_table(A1="Table 5.3.6. Real Private Fixed Investment")), "title"),
        (_workbook(_table(A2="[Billions of dollars] Seasonally adjusted")), "unit"),
        (_workbook(_table(A2="[Millions of dollars] Not seasonally adjusted")), "unit"),
        (_workbook(_table(A3="Quarterly data from 2026Q1 to 2026Q1")), "span"),
        (_workbook(_table(A3=None)), "span"),
        (_workbook(_table(A5="Data published July 29, 2026")), "July 29"),
        (_workbook(_table(A5="Data published August 26, 2026")), "release day"),
        (_workbook(_table(A5="Data published Julember 30, 2026")), "release day"),
        (_workbook(_table(A5=None)), "release day"),
        (_workbook(_table(A20="Line")), "header row, found 2"),
        (_workbook(_table(A8="Lines")), "header row, found 0"),
        (_workbook(_table(E8="2026Q3")), "2026Q2 archive column, found 0"),
        (_workbook(_table(D8="2026Q2")), "2026Q2 archive column, found 2"),
        (_workbook(_table(F8="2026Q3")), "not the table's newest"),
        (_workbook(_table(A11="2")), "line 2 row, found 2"),
        (_workbook(_table(A10=None)), "line 2 row, found 0"),
        (_workbook(_table(B10="Residential")), "is 'Residential'"),
        (_workbook(_table(C10="A009RC")), "series code 'A009RC'"),
        (_workbook(_table(E10=".....")), "not numeric"),
        (_workbook(_table(E10=None)), "not numeric"),
        (_workbook(_table(E10=("b", "1"))), "not numeric"),
        (_workbook(_table(E10=-1.0)), "nonnegative finite"),
        (_workbook(_table(E10=("n", "NaN"))), "nonnegative finite"),
        (_workbook(_table(E10=("n", "inf"))), "nonnegative finite"),
        (_workbook(_table(E10=("d", "2026-07-30"))), "unknown type 'd'"),
        (_workbook(formulas=frozenset({"E10"})), "formula cell 'E10'"),
        (_workbook(sheet_name="T50305-A"), "one 'T50305-Q' sheet"),
        (_workbook(target_mode="External"), "points outside the workbook"),
        (_workbook(target="../../evil.xml"), "points outside xl/"),
        (_workbook(target="worksheets/missing.xml"), "missing"),
        (_workbook(extra={"../evil.xml": "x"}), "unsafe member path"),
        (_workbook(extra={"xl\\evil.xml": "x"}), "unsafe member path"),
        (_workbook(extra={"xl/workbook.xml": "<x/>"}), "duplicate ZIP members"),
        (_workbook(encrypted=True), "encrypted ZIP members"),
        (_workbook(_table(A10001="x")), "exceeds the adapter's size"),
        # Column BXY is the 2,001st: one past the reader's limit.
        (_workbook(_table(BXY10=1.0)), "exceeds the adapter's size"),
    ],
)
def test_workbook_reader_refuses(raw: bytes, fragment: str) -> None:
    reading, refusal = _read(raw)
    assert reading is None
    assert refusal is not None and fragment in refusal


def test_workbook_reader_refuses_duplicate_cell_references() -> None:
    sheet = _sheet_xml(_table(), frozenset()).replace(
        "</sheetData>", '<row r="99"><c r="E10"><v>1</v></c></row></sheetData>'
    )
    raw = _workbook(extra={})
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        members = {name: source.read(name) for name in source.namelist()}
    members["xl/worksheets/sheet1.xml"] = sheet.encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as target:
        for name, data in members.items():
            target.writestr(name, data)
    reading, refusal = _read(buffer.getvalue())
    assert reading is None and refusal == "duplicate cell reference 'E10'"


def test_workbook_reader_refuses_oversized_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = b"PK\x03\x04" + b"\0" * resolve_pending.BEA_ARCHIVE_MAX_WORKBOOK_BYTES
    assert _read(oversized) == (
        None,
        "the archive workbook exceeds the 25 MB adapter limit",
    )
    monkeypatch.setattr(resolve_pending, "BEA_ARCHIVE_MAX_EXPANDED_BYTES", 1_000)
    assert _read(_workbook()) == (
        None,
        "the archive workbook expands beyond the 100 MB limit",
    )


def test_workbook_reader_refuses_an_unreviewed_transform() -> None:
    spec = {**_spec(NONRES), "value_transform": {"operation": "multiply", "factor": 1}}
    reading, refusal = resolve_pending.bea_archive_reading(
        WORKBOOK, spec, _archive_spec(NONRES), PERIOD, RELEASE_DAY
    )
    assert reading is None and refusal is not None and "transform" in refusal


@settings(max_examples=200, deadline=None)
@given(st.binary(max_size=4096))
def test_no_bytes_raise_from_the_workbook_reader(raw: bytes) -> None:
    reading, refusal = _read(raw)
    assert reading is None and isinstance(refusal, str)


@settings(max_examples=100, deadline=None)
@given(st.integers(min_value=0, max_value=10**13))
def test_every_printed_value_converts_by_the_registered_transform(
    printed: int,
) -> None:
    reading, refusal = _read(_workbook(_table(E10=float(printed))))
    assert refusal is None and reading is not None
    assert reading["printedMillions"] == float(printed)
    assert reading["value"] == round(printed * 0.001, 4) + 0.0


@settings(max_examples=100, deadline=None)
@given(
    st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31)).filter(
        lambda day: day != RELEASE_DAY
    )
)
def test_any_other_publication_day_refuses(day: dt.date) -> None:
    line = f"Data published {day:%B} {day.day}, {day.year}"
    reading, refusal = _read(_workbook(_table(A5=line)))
    assert reading is None and refusal is not None and line in refusal


# --- one cell end to end, with BEA's server faked ---------------------------


class FakeArchive:
    """BEA's archive host, serving the Q2 fixtures by exact URL."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[str] = []
        self.responses = responses or {
            INDEX_URL: (INDEX, INDEX_HEADERS),
            WORKBOOK_URL: (WORKBOOK, WORKBOOK_HEADERS),
        }

    def __call__(self, url: str) -> tuple[bytes, dict[str, str], str, str]:
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, BaseException):
            raise response
        body, headers, *final = response
        return body, dict(headers), "2026-08-07T15:00:01Z", final[0] if final else url


def _first_print(
    monkeypatch: pytest.MonkeyPatch,
    archive: FakeArchive,
    series: str = NONRES,
    cache: dict[str, Any] | None = None,
) -> tuple[Any, str, str]:
    monkeypatch.setattr(resolve_pending, "bea_archive_http_get", archive)
    return resolve_pending.bea_archive_first_print(
        _spec(series),
        _archive_spec(series),
        PERIOD,
        RELEASE_DAY,
        {} if cache is None else cache,
    )


def test_first_print_reads_one_index_and_one_workbook_for_both_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = FakeArchive()
    cache: dict[str, Any] = {}
    nonres, _head, _detail = _first_print(monkeypatch, archive, NONRES, cache)
    research, _head, _detail = _first_print(monkeypatch, archive, RD, cache)
    assert archive.calls == [INDEX_URL, WORKBOOK_URL]
    assert (nonres.value, research.value) == (4623.657, 937.772)
    assert nonres.workbook_url == WORKBOOK_URL
    assert nonres.retrieved_at == "2026-08-07T15:00:01Z"
    assert nonres.source_file == (
        "Section5all_xls.xlsx from BEA Data Archive folder Advance_July-30-2026 "
        "(sheet T50305-Q, row 10, column 2026Q2) + the archive index JSON"
    )

    envelope = json.loads(nonres.raw)
    assert nonres.raw.endswith(b"\n")
    assert envelope["schemaVersion"] == "bea_archive_snapshot_v1"
    assert base64.b64decode(envelope["workbook"]["bodyBase64"]) == WORKBOOK
    assert envelope["workbook"]["sha256"] == hashlib.sha256(WORKBOOK).hexdigest()
    assert envelope["workbook"]["headers"]["last-modified"] == (
        "Thu, 30 Jul 2026 13:48:02 GMT"
    )
    assert base64.b64decode(envelope["index"]["bodyBase64"]) == INDEX
    assert envelope["index"]["url"] == INDEX_URL
    assert envelope["derived"] == {
        "period": PERIOD,
        "releaseDay": "2026-07-30",
        "estimateFolder": "Advance_July-30-2026",
        "sourceSeriesId": "T50305:L2",
        "value": 4623.657,
        "printedMillions": 4_623_657.0,
        "sheet": "T50305-Q",
        "row": 10,
        "column": "2026Q2",
        "seriesCode": "A008RC",
        "publishedLine": "Data published July 30, 2026",
    }

    notes = nonres.evidence_notes.format(period=PERIOD, source_url=WORKBOOK_URL)
    assert notes.startswith(f"First print for {PERIOD} read from {WORKBOOK_URL}, ")
    assert '"Data published July 30, 2026"' in notes
    assert "Thu, 30 Jul 2026 13:48:02 GMT, on the release day" in notes
    assert "{" not in notes


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("down"),
        urllib.error.HTTPError(INDEX_URL, 503, "busy", {}, None),  # type: ignore[arg-type]
        TimeoutError("read timed out"),
        http.client.IncompleteRead(b"partial"),
    ],
)
def test_a_transport_failure_defers(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    capture, head, detail = _first_print(monkeypatch, FakeArchive({INDEX_URL: error}))
    assert capture is None
    assert head == "BEA ARCHIVE INDEX fetch failed (deferring)"
    assert detail.startswith(type(error).__name__)
    ref = f"{NONRES}.2026_q2.first_print"
    statuses, _summary = resolution_status.parse_resolver_log(
        f"  {head}: {ref} — {detail}\n", {ref}
    )
    assert (statuses[ref]["state"], statuses[ref]["code"]) == (
        "fetch_failed",
        "SOURCE_UNREACHABLE",
    )


def test_a_workbook_transport_failure_defers(monkeypatch: pytest.MonkeyPatch) -> None:
    archive = FakeArchive(
        {INDEX_URL: (INDEX, INDEX_HEADERS), WORKBOOK_URL: ConnectionResetError("rst")}
    )
    capture, head, detail = _first_print(monkeypatch, archive)
    assert capture is None
    assert head == "BEA ARCHIVE WORKBOOK fetch failed (deferring)"
    assert detail == "ConnectionResetError: rst"


def test_an_unposted_quarter_defers(monkeypatch: pytest.MonkeyPatch) -> None:
    archive = FakeArchive({INDEX_URL: (_index([]), INDEX_HEADERS)})
    capture, head, detail = _first_print(monkeypatch, archive)
    assert capture is None
    assert head == "BEA ARCHIVE NOT YET POSTED (deferring)"
    assert archive.calls == [INDEX_URL]
    ref = f"{NONRES}.2026_q2.first_print"
    statuses, _summary = resolution_status.parse_resolver_log(
        f"  {head}: {ref} — {detail}\n", {ref}
    )
    assert statuses[ref]["state"] == "deferred"


@pytest.mark.parametrize(
    ("responses", "fragment"),
    [
        (
            {INDEX_URL: (INDEX, INDEX_HEADERS, INDEX_URL + "&x=1")},
            "the index request landed on",
        ),
        (
            {
                INDEX_URL: (INDEX, INDEX_HEADERS),
                WORKBOOK_URL: (WORKBOOK, WORKBOOK_HEADERS, WORKBOOK_URL + ".bak"),
            },
            "the workbook request landed on",
        ),
        (
            {
                INDEX_URL: (INDEX, INDEX_HEADERS),
                WORKBOOK_URL: (b"<!DOCTYPE html>", {"content-type": "text/html"}),
            },
            "answered with 'text/html', not a workbook",
        ),
        (
            {
                INDEX_URL: (INDEX, INDEX_HEADERS),
                WORKBOOK_URL: (
                    WORKBOOK,
                    {
                        **WORKBOOK_HEADERS,
                        "last-modified": "Wed, 26 Aug 2026 13:30:00 GMT",
                    },
                ),
            },
            "last modified 2026-08-26, not on the registered release day 2026-07-30",
        ),
        (
            {
                INDEX_URL: (INDEX, INDEX_HEADERS),
                WORKBOOK_URL: (
                    WORKBOOK,
                    {k: v for k, v in WORKBOOK_HEADERS.items() if k != "last-modified"},
                ),
            },
            "carries no Last-Modified header",
        ),
        (
            {
                INDEX_URL: (INDEX, INDEX_HEADERS),
                WORKBOOK_URL: (
                    _workbook(_table(A5="Data published July 31, 2026")),
                    WORKBOOK_HEADERS,
                ),
            },
            "Data published July 31, 2026",
        ),
    ],
)
def test_after_the_release_day_anything_else_refuses(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, Any], fragment: str
) -> None:
    capture, head, detail = _first_print(monkeypatch, FakeArchive(responses))
    assert capture is None
    assert head == MISSED
    assert detail.startswith(
        "registered release day was 2026-07-30; BEA's archive gives no "
        "first-print custody: "
    )
    assert fragment in detail
    ref = f"{NONRES}.2026_q2.first_print"
    statuses, _summary = resolution_status.parse_resolver_log(
        f"  {head}: {ref} — {detail}\n", {ref}
    )
    assert statuses[ref]["code"] == "FIRST_PRINT_WINDOW_MISSED"


def test_the_host_pin_holds_before_any_request() -> None:
    body, headers, _retrieved_at, final_url, error = resolve_pending.fetch_bea_archive(
        "https://archive.example/histdata/Files/x.xlsx"
    )
    assert body is None and headers == {}
    assert final_url == "https://archive.example/histdata/Files/x.xlsx"
    assert error is not None and "not in adapter allowlist" in error


# --- the main loop -------------------------------------------------------------


def _docket_entry(series: str) -> dict[str, Any]:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    return next(row for row in docket["series"] if row["series"] == series)


def _registration(
    series: str,
    *,
    period: str = "2026-Q2",
    release_day: dt.date = RELEASE_DAY,
    registration_day: dt.date = dt.date(2026, 7, 1),
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    entry = _docket_entry(series)
    target = {
        **entry["extras"],
        "series": series,
        "period": period,
        "catalogSlug": f"unit4-{series.replace('.', '-')}",
        "releaseCalendarUrl": entry["releaseCalendarUrl"],
        "expectedReleaseDate": release_day.isoformat(),
    }
    contract = register_targets.build_contract(target, registration_day)
    envelope = {"targetContentHash": "a" * 64, "contract": contract, "ledgerPin": None}
    forecast = {
        "resolutionDate": release_day.isoformat(),
        "unit": resolve_pending.BEA_RELEASE_ADAPTERS[series]["unit"],
    }
    return contract["dataPointId"], envelope, forecast


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    registrations: list[tuple[str, dict[str, Any], dict[str, Any]]],
    *,
    today: dt.date,
    now: str,
    archive: Any,
) -> None:
    log = {
        "entries": [
            {"kind": "prediction_recorded", "forecastSlug": f"slug-{index}", **forecast}
            for index, (_ref, _envelope, forecast) in enumerate(registrations)
        ],
        "resolutionLinks": [
            {"status": "pending", "forecastSlug": f"slug-{index}", "targetFactRef": ref}
            for index, (ref, _envelope, _forecast) in enumerate(registrations)
        ],
    }

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(today.year, today.month, today.day)

    monkeypatch.setattr(resolve_pending.dt, "date", FixedDate)
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: now)
    monkeypatch.setattr(resolve_pending, "load_thesis_log", lambda _url: log)
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_args: ("", "blob", "b" * 40)
    )
    monkeypatch.setattr(
        resolve_pending,
        "registration_contracts",
        lambda: {ref: envelope for ref, envelope, _forecast in registrations},
    )
    monkeypatch.setattr(resolve_pending, "bea_archive_http_get", archive)
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])


def test_main_resolves_both_q2_cells_from_the_archive_after_the_release_day(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    nonres = _registration(NONRES)
    research = _registration(RD)
    archive = FakeArchive()
    rows: list[dict[str, Any]] = []
    real_fact = resolve_pending.generic_fact

    def record_fact(*args: Any, **kwargs: Any) -> dict[str, Any]:
        row = real_fact(*args, **kwargs)
        rows.append(row)
        return row

    _run_main(
        monkeypatch,
        [nonres, research],
        today=dt.date(2026, 8, 7),
        now="2026-08-07T15:00:00Z",
        archive=archive,
    )
    monkeypatch.setattr(resolve_pending, "generic_fact", record_fact)
    for name in ("fetch_bea_release_page", "fetch_bea_itable_table", "http_request"):
        monkeypatch.setattr(
            resolve_pending,
            name,
            lambda *_args, _name=name, **_kwargs: pytest.fail(
                f"after the release day the live leg must not run ({_name})"
            ),
        )

    assert resolve_pending.main() == 0

    output = capsys.readouterr().out
    assert f"  resolve {nonres[0]} -> 4623.657 usd_billions" in output
    assert f"  resolve {research[0]} -> 937.772 usd_billions" in output
    assert "dry-run: would append 2 row(s)" in output
    assert archive.calls == [INDEX_URL, WORKBOOK_URL]
    assert [row["observed_at"] for row in rows] == ["2026-07-30", "2026-07-30"]
    for row in rows:
        assert row["source"]["url"] == WORKBOOK_URL
        assert row["measure"]["concept_evidence_url"] == WORKBOOK_URL
        assert "BEA's Data Archive folder" in row["measure"]["concept_evidence_notes"]
        assert (
            "Thu, 30 Jul 2026 13:48:02 GMT"
            in (row["measure"]["concept_evidence_notes"])
        )
    # The archive's notes ride on a copy of the spec, never on the adapter.
    assert "evidence_notes" not in resolve_pending.BEA_RELEASE_ADAPTERS[NONRES]


def test_main_on_the_release_day_uses_the_live_leg_not_the_archive(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    nonres = _registration(NONRES)
    _run_main(
        monkeypatch,
        [nonres],
        today=RELEASE_DAY,
        now="2026-07-30T12:31:00Z",
        archive=lambda *_args: pytest.fail("the release day reads the live leg"),
    )
    monkeypatch.setattr(
        resolve_pending,
        "fetch_bea_release_page",
        lambda *_args: (None, "https://www.bea.gov/news", "2026-07-30T12:31:00Z"),
    )

    assert resolve_pending.main() == 0

    output = capsys.readouterr().out
    assert f"  BEA RELEASE fetch failed (deferring): {nonres[0]}" in output
    assert "BEA ARCHIVE" not in output


def test_main_never_reads_the_archive_for_the_ita_stem(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ita = _registration(
        ITA,
        period="2026-Q1",
        release_day=dt.date(2026, 6, 24),
        registration_day=dt.date(2026, 6, 1),
    )
    _run_main(
        monkeypatch,
        [ita],
        today=dt.date(2026, 6, 25),
        now="2026-06-25T09:00:00Z",
        archive=lambda *_args: pytest.fail("the ITA stem has no archive leg"),
    )

    assert resolve_pending.main() == 0

    output = capsys.readouterr().out
    assert (
        f"  FIRST-PRINT WINDOW MISSED (refusing): {ita[0]} — registered release "
        "day was 2026-06-24\n"
    ) in output


def test_main_refuses_a_registration_whose_window_is_not_the_release_day(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ref, envelope, forecast = _registration(NONRES)
    binding = envelope["contract"]["sourceBinding"]
    binding["expectedReleaseWindow"] = {"start": "2026-07-30", "end": "2026-07-31"}
    _run_main(
        monkeypatch,
        [(ref, envelope, forecast)],
        today=dt.date(2026, 8, 7),
        now="2026-08-07T15:00:00Z",
        archive=lambda *_args: pytest.fail("a drifted window must refuse first"),
    )

    assert resolve_pending.main() == 0

    output = capsys.readouterr().out
    assert f"  FORECAST/REGISTERED RELEASE DATE MISMATCH (refusing): {ref}" in output
