"""Colorado HCPF Monthly Premiums Report reader: first prints only, fail-closed.

Official fixtures (``tests/fixtures/co_hcpf``, see its README): the landing
page as served 2026-10-09, the caseload page of the June to September 2026
report PDFs with the ``pdftotext -layout`` text of each, and the September
2026 report workbook. Synthetic sources (``tests/co_fixtures.py``) vary one
fact at a time.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import shutil
import sys
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import co_hcpf  # noqa: E402
import resolve_pending  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from co_fixtures import (  # noqa: E402
    HCPF_CATEGORIES,
    hcpf_file_url,
    hcpf_landing,
    hcpf_pdf_text,
    hcpf_rows,
    hcpf_workbook,
    months_through,
    shift,
    xlsx_from_cells,
)

FIXTURES = ROOT / "tests" / "fixtures" / "co_hcpf"
LANDING = (FIXTURES / "landing_2026-10-09.html").read_bytes()
# Report month -> (activity month it first prints, TOTAL, months with figures).
OFFICIAL = {
    "2026-06": ("2026-05", 1238720, 59),
    "2026-07": ("2026-06", 1237772, 60),
    "2026-08": ("2026-07", 1242335, 49),
    "2026-09": ("2026-08", 1247588, 50),
}
FILES = "https://hcpf.colorado.gov/sites/hcpf/files/"


def _official_text(report_period: str) -> str:
    name = f"report_{report_period}_caseload_page.pdftotext.txt"
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- official files ----------------------------------------------------------


def test_official_landing_binds_each_report_month_to_its_own_files() -> None:
    links = co_hcpf.landing_report_links(LANDING, "2026-09")
    assert links.pdf_url == (
        FILES + "2026%20September%2C%20Joint%20Budget%20Committee%20Monthly"
        "%20Premiums%20Report.pdf"
    )
    assert links.xlsx_url == links.pdf_url[: -len("pdf")] + "xlsx"
    # The cover letter shares the month and the directory and is never a report.
    assert "Cover" not in links.pdf_url
    assert links.listed == ("2026-06", "2026-07", "2026-08", "2026-09")
    # July's workbook was posted as "... Report no links.xlsx".
    july = co_hcpf.landing_report_links(LANDING, "2026-07")
    assert july.xlsx_url is not None and july.xlsx_url.endswith(
        "Premiums%20Report%20no%20links.xlsx"
    )
    # Not listed yet: refuse rather than guess a file name from cadence.
    with pytest.raises(co_hcpf.CoHcpfError, match="October 2026 report, found 0"):
        co_hcpf.landing_report_links(LANDING, "2026-10")


@pytest.mark.parametrize("report_period", sorted(OFFICIAL))
def test_official_reports_first_print_the_month_before_they_are_dated(
    report_period: str,
) -> None:
    period, total, populated = OFFICIAL[report_period]
    assert co_hcpf.report_period_for(period) == report_period
    table = co_hcpf.caseload_table_from_pdf_text(_official_text(report_period))
    assert (table.latest, len(table.rows)) == (period, populated)
    assert co_hcpf.first_print_total(table, period) == total
    # Every month the PDF prints is a row whose categories add up.
    assert all(len(row.categories) == HCPF_CATEGORIES for row in table.rows)
    assert all(row.categories_sum == row.total for row in table.rows)
    # A month the report merely restates is never read from it.
    with pytest.raises(co_hcpf.CoHcpfError, match=f"newest caseload month is {period}"):
        co_hcpf.first_print_total(table, shift(period, -1))
    with pytest.raises(co_hcpf.CoHcpfError, match="does not first print"):
        co_hcpf.first_print_total(table, shift(period, 1))


def test_official_reports_restate_earlier_months() -> None:
    """Why a month is read only from the report where it is the newest.

    The forecast's own history records the February 2026 report's first
    print of January 2026, 1,236,302; the June report prints 1,236,285.
    """
    june = co_hcpf.caseload_table_from_pdf_text(_official_text("2026-06"))
    january = june.row("2026-01")
    assert january is not None and january.total == 1236285 != 1236302
    # Not every month moves: the next three reports left their predecessors'
    # newest month as first printed.
    for report_period in ("2026-07", "2026-08", "2026-09"):
        table = co_hcpf.caseload_table_from_pdf_text(_official_text(report_period))
        previous_period, previous_total, _ = OFFICIAL[shift(report_period, -1)]
        row = table.row(previous_period)
        assert row is not None and row.total == previous_total


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="needs poppler")
@pytest.mark.parametrize("report_period", sorted(OFFICIAL))
def test_official_pdf_pages_read_the_same_through_this_machines_pdftotext(
    report_period: str,
) -> None:
    """Differential across poppler builds: the committed text was rendered by
    poppler 26.09; whatever build runs this test must yield the same table."""
    raw = (FIXTURES / f"report_{report_period}_caseload_page.pdf").read_bytes()
    text, refusal = resolve_pending.co_hcpf_pdf_text(raw)
    assert refusal is None and text is not None
    assert co_hcpf.caseload_table_from_pdf_text(
        text
    ) == co_hcpf.caseload_table_from_pdf_text(_official_text(report_period))


def test_official_workbook_agrees_with_the_pdf_on_every_month_both_print() -> None:
    """Differential: the two prints of the September 2026 report."""
    pdf = co_hcpf.caseload_table_from_pdf_text(_official_text("2026-09"))
    book = co_hcpf.caseload_table_from_workbook(
        (FIXTURES / "report_2026-09.xlsx").read_bytes()
    )
    assert (book.latest, book.unpopulated) == (pdf.latest, pdf.unpopulated)
    assert co_hcpf.first_print_total(book, "2026-08") == 1247588
    by_period = {row.period: row for row in book.rows}
    for row in pdf.rows:
        other = by_period[row.period]
        assert other.total == row.total, row.period
        # The PDF prints "-" where the workbook holds an empty cell or zero.
        assert [v or 0 for v in other.categories] == [v or 0 for v in row.categories]
    # The workbook reaches back to July 2009; three months of that older
    # history hold a figure that is not a whole count and are never read.
    assert book.rows[0].period == "2009-07" and pdf.rows[0].period == "2022-07"
    assert [row.period for row in book.rows if row.irregular] == [
        "2014-09",
        "2014-10",
        "2014-11",
    ]


# --- landing page ------------------------------------------------------------


def test_landing_counts_a_repeated_link_once_and_refuses_two_reports() -> None:
    repeated = f'<a href="{hcpf_file_url("2026-09", "pdf")}">Report (again)</a>'
    page = hcpf_landing(["2026-08", "2026-09"], extra=repeated)
    assert co_hcpf.landing_report_links(page, "2026-09").pdf_url == hcpf_file_url(
        "2026-09", "pdf"
    )
    second = f'<a href="{hcpf_file_url("2026-09", "pdf", variant="_0")}">Report</a>'
    with pytest.raises(co_hcpf.CoHcpfError, match="September 2026 report, found 2"):
        co_hcpf.landing_report_links(hcpf_landing(["2026-09"], extra=second), "2026-09")
    two_books = (
        f'<a href="{hcpf_file_url("2026-09", "xlsx", variant=" no links")}">XLS</a>'
    )
    with pytest.raises(co_hcpf.CoHcpfError, match="at most one report workbook"):
        co_hcpf.landing_report_links(
            hcpf_landing(["2026-09"], extra=two_books), "2026-09"
        )


def test_landing_ignores_links_that_are_not_the_agencys_stored_report() -> None:
    name = hcpf_file_url("2026-09", "pdf").rsplit("/", 1)[1]
    decoys = "".join(
        f'<a href="{href}">Report</a>'
        for href in (
            f"https://example.org/sites/hcpf/files/{name}",
            f"http://hcpf.colorado.gov/sites/hcpf/files/{name}",
            f"https://hcpf.colorado.gov/sites/hcpf/files/archive/{name}",
            f"https://hcpf.colorado.gov/sites/hcpf/files/{name}?v=2",
            "https://hcpf.colorado.gov/sites/hcpf/files/2026%20September%2C%20"
            "Joint%20Budget%20Committee%20Monthly%20Premiums%20Cover%20Letter.pdf",
        )
    )
    page = hcpf_landing(["2026-08"], workbooks=False, extra=decoys)
    with pytest.raises(co_hcpf.CoHcpfError, match="found 0"):
        co_hcpf.landing_report_links(page, "2026-09")
    # A same-origin relative link is the stored report.
    relative = f'<a href="/sites/hcpf/files/{name}">Report</a>'
    links = co_hcpf.landing_report_links(
        hcpf_landing(["2026-08"], extra=relative), "2026-09"
    )
    assert links.pdf_url == FILES + name and links.xlsx_url is None


@settings(max_examples=100, deadline=None)
@given(
    listed=st.sets(st.integers(2020 * 12, 2030 * 12), max_size=8),
    target=st.integers(2020 * 12, 2030 * 12),
)
def test_a_report_is_found_exactly_when_the_page_lists_it(listed, target) -> None:
    def period(index: int) -> str:
        return f"{index // 12:04d}-{index % 12 + 1:02d}"

    page = hcpf_landing([period(index) for index in sorted(listed)])
    if target in listed:
        links = co_hcpf.landing_report_links(page, period(target))
        assert links.pdf_url == hcpf_file_url(period(target), "pdf")
        assert links.listed == tuple(period(index) for index in sorted(listed))
    else:
        with pytest.raises(co_hcpf.CoHcpfError, match="found 0"):
            co_hcpf.landing_report_links(page, period(target))


# --- first-posting gate --------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "refusal"),
    [
        ("Mon, 14 Sep 2026 17:35:17 GMT", None),  # the official September file
        # Denver is UTC-6 in September: 05:30 GMT on 1 October is still
        # 30 September there, and 05:30 GMT on 1 September is still August.
        ("Thu, 01 Oct 2026 05:30:00 GMT", None),
        ("Tue, 01 Sep 2026 05:30:00 GMT", "before September 2026"),
        ("Thu, 15 Oct 2026 16:00:00 GMT", "re-post"),
        ("Mon, 17 Aug 2026 18:00:45 GMT", "before September 2026"),
        (None, "no Last-Modified header"),
        ("yesterday", "unreadable"),
    ],
)
def test_posting_gate_accepts_only_the_month_the_report_is_dated(
    header, refusal
) -> None:
    modified, verdict = co_hcpf.posting_gate(header, report_period="2026-09")
    if refusal is None:
        assert verdict is None and modified is not None
    else:
        assert verdict is not None and refusal in verdict


@settings(max_examples=300, deadline=None)
@given(
    moment=st.datetimes(
        min_value=dt.datetime(2020, 1, 1),
        max_value=dt.datetime(2035, 1, 1),
        timezones=st.just(dt.timezone.utc),
    ),
    report=st.integers(2020 * 12, 2035 * 12),
)
def test_posting_gate_is_exactly_the_denver_month_test(moment, report) -> None:
    report_period = f"{report // 12:04d}-{report % 12 + 1:02d}"
    header = moment.strftime("%a, %d %b %Y %H:%M:%S GMT")
    local = moment.astimezone(ZoneInfo("America/Denver"))
    _modified, verdict = co_hcpf.posting_gate(header, report_period=report_period)
    same_month = (local.year, local.month) == (report // 12, report % 12 + 1)
    assert (verdict is None) == same_month
    if verdict is not None:
        later = (local.year, local.month) > (report // 12, report % 12 + 1)
        assert ("re-post" in verdict) == later


# --- the caseload table ------------------------------------------------------

ROWS = hcpf_rows("2026-08", [1_230_001, 1_240_002, 1_247_588])
AHEAD = months_through("2027-06", 10)


def test_synthetic_report_reads_like_the_official_one() -> None:
    for table in (
        co_hcpf.caseload_table_from_pdf_text(hcpf_pdf_text(ROWS, AHEAD)),
        co_hcpf.caseload_table_from_workbook(hcpf_workbook(ROWS, AHEAD)),
    ):
        assert [(r.period, r.total) for r in table.rows] == [
            ("2026-06", 1_230_001),
            ("2026-07", 1_240_002),
            ("2026-08", 1_247_588),
        ]
        assert table.unpopulated == tuple(AHEAD)
        assert co_hcpf.first_print_total(table, "2026-08") == 1_247_588
    # The FY 2025-26 reports close the table with the longer spelling.
    older = hcpf_pdf_text(ROWS, closing="FY 2025-26 Year-to-Date Average")
    assert co_hcpf.caseload_table_from_pdf_text(older).latest == "2026-08"


@pytest.mark.parametrize(
    ("text", "refusal"),
    [
        (hcpf_pdf_text(ROWS, title="MEDICAID CASELOAD"), "found 0"),
        (
            hcpf_pdf_text(ROWS) + hcpf_pdf_text(ROWS),
            "found 2",
        ),
        (hcpf_pdf_text(ROWS, closing="Monthly Growth"), "unexpected line"),
        (
            hcpf_pdf_text(ROWS).replace("FY 2026-27 YTD Average", "", 1),
            "unexpected line",
        ),
        (hcpf_pdf_text(ROWS).replace("TOTAL", "ALL", 1), "Month and TOTAL"),
        (
            hcpf_pdf_text([(p, c[:-1], t) for p, c, t in ROWS]),
            "has 17 figures, expected 18",
        ),
        (
            hcpf_pdf_text(ROWS).replace("1,247,588", "<30", 1),
            "non-count figure '<30'",
        ),
        (
            hcpf_pdf_text(ROWS).replace("1,247,588", "-", 1),
            "prints no TOTAL",
        ),
        (
            hcpf_pdf_text([ROWS[0], ROWS[2]]),
            "2026-06 is followed by 2026-08",
        ),
        (
            hcpf_pdf_text(ROWS[:1], ["2026-07", "2026-08"]).replace(
                "August 2026", "August 2026" + "".join(f"{1:>14}" for _ in range(18))
            ),
            "listed without any",
        ),
    ],
    ids=[
        "no-title",
        "two-titles",
        "other-closing-line",
        "no-closing-line",
        "header-without-total",
        "seventeen-figures",
        "suppressed-figure",
        "no-total",
        "month-gap",
        "figures-after-an-empty-month",
    ],
)
def test_pdf_table_refuses_what_it_cannot_read_without_guessing(
    text: str, refusal: str
) -> None:
    with pytest.raises(co_hcpf.CoHcpfError, match=refusal):
        co_hcpf.caseload_table_from_pdf_text(text)


def test_pdf_table_ends_before_the_by_program_table() -> None:
    """The next page repeats every month under another title, with
    suppressed ("<30") figures; none of it belongs to the statewide table."""
    text = hcpf_pdf_text(ROWS)
    assert "MEDICAID CASELOAD BY PROGRAM" in text and "<30" in text
    assert co_hcpf.caseload_table_from_pdf_text(text).latest == "2026-08"
    # A statewide table cut off before its closing line is not read into
    # the next table.
    cut = text.replace("FY 2026-27 YTD Average", "Monthly Growth", 1)
    with pytest.raises(co_hcpf.CoHcpfError):
        co_hcpf.caseload_table_from_pdf_text(cut)


def test_workbook_refuses_a_restructured_sheet() -> None:
    with pytest.raises(co_hcpf.CoHcpfError, match="exactly one 'Medicaid Caseload'"):
        co_hcpf.caseload_table_from_workbook(hcpf_workbook(ROWS, sheet_name="Sheet1"))
    with pytest.raises(co_hcpf.CoHcpfError, match="table title"):
        co_hcpf.caseload_table_from_workbook(hcpf_workbook(ROWS, title="CASELOAD"))
    with pytest.raises(co_hcpf.CoHcpfError, match="not an OOXML workbook"):
        co_hcpf.caseload_table_from_workbook(b"<html>missing</html>")
    no_total = xlsx_from_cells(
        "Medicaid Caseload",
        {
            (0, 1): "MEDICAID CASELOAD WITHOUT RETROACTIVITY1",
            (1, 1): "Month",
            (2, 1): 46235,
            (2, 2): 5,
        },
    )
    with pytest.raises(co_hcpf.CoHcpfError, match="one TOTAL column"):
        co_hcpf.caseload_table_from_workbook(no_total)


def test_a_newest_row_that_is_not_whole_counts_is_refused_when_read() -> None:
    period, categories, total = ROWS[-1]
    raw = hcpf_workbook([*ROWS[:-1], (period, (0.5, *categories[1:]), total)])
    table = co_hcpf.caseload_table_from_workbook(raw)
    assert table.latest == period and table.rows[-1].irregular
    with pytest.raises(co_hcpf.CoHcpfError, match="non-count figure 0.5"):
        co_hcpf.first_print_total(table, period)


def test_a_total_that_its_categories_do_not_add_up_to_is_refused() -> None:
    period, categories, total = ROWS[-1]
    for source in (hcpf_pdf_text, hcpf_workbook):
        off = source([*ROWS[:-1], (period, categories, total + 1)])
        table = (
            co_hcpf.caseload_table_from_pdf_text(off)
            if isinstance(off, str)
            else co_hcpf.caseload_table_from_workbook(off)
        )
        with pytest.raises(co_hcpf.CoHcpfError, match="categories sum to 1247588"):
            co_hcpf.first_print_total(table, period)


# --- properties --------------------------------------------------------------

_FIGURE = st.one_of(st.none(), st.integers(0, 600_000))


@st.composite
def _tables(draw):
    newest_index = draw(st.integers(2015 * 12, 2034 * 12))
    newest = f"{newest_index // 12:04d}-{newest_index % 12 + 1:02d}"
    count = draw(st.integers(1, 14))
    rows = []
    for period in months_through(newest, count):
        categories = tuple(
            draw(st.lists(_FIGURE, min_size=HCPF_CATEGORIES, max_size=HCPF_CATEGORIES))
        )
        rows.append((period, categories, sum(v for v in categories if v is not None)))
    ahead = draw(st.integers(0, 11))
    unpopulated = [shift(newest, offset) for offset in range(1, ahead + 1)]
    return rows, unpopulated


@settings(max_examples=150, deadline=None)
@given(table=_tables())
def test_both_prints_round_trip_and_agree(table) -> None:
    """Round trip and differential: a table rendered as the PDF's text and as
    the workbook reads back as itself from both."""
    rows, unpopulated = table
    pdf = co_hcpf.caseload_table_from_pdf_text(hcpf_pdf_text(rows, unpopulated))
    book = co_hcpf.caseload_table_from_workbook(hcpf_workbook(rows, unpopulated))
    assert [(r.period, r.categories, r.total) for r in pdf.rows] == rows
    assert [(r.period, r.total) for r in book.rows] == [(p, t) for p, _c, t in rows]
    assert [[v or 0 for v in r.categories] for r in book.rows] == [
        [v or 0 for v in categories] for _p, categories, _t in rows
    ]
    assert pdf.unpopulated == book.unpopulated == tuple(unpopulated)
    assert pdf.latest == book.latest == rows[-1][0]


@settings(max_examples=150, deadline=None)
@given(table=_tables(), offset=st.integers(-30, 30), delta=st.integers(-5, 5))
def test_only_the_newest_month_is_read_and_only_when_it_adds_up(
    table, offset, delta
) -> None:
    """No restatement is ever read, and a figure is returned only when it is
    the row's own total."""
    rows, unpopulated = table
    newest, categories, total = rows[-1]
    if total + delta < 0:
        delta = 0
    printed = [*rows[:-1], (newest, categories, total + delta)]
    parsed = co_hcpf.caseload_table_from_pdf_text(hcpf_pdf_text(printed, unpopulated))
    asked = shift(newest, offset)
    if offset == 0 and delta == 0:
        assert co_hcpf.first_print_total(parsed, asked) == total
    else:
        with pytest.raises(co_hcpf.CoHcpfError):
            co_hcpf.first_print_total(parsed, asked)
