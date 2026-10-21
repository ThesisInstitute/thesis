#!/usr/bin/env python3
"""Read the Colorado HCPF Joint Budget Committee Monthly Premiums Report.

Pure standard library (plus the hardened OOXML reader in ``va_mmwr``). Used
by ``scripts/resolve_pending.py`` for the ``co.hcpf.medicaid.total_caseload``
family and by its tests.

What the inspected files show (read 2026-10-09; see "Colorado HCPF Medicaid
caseload" in docs/anchor-verifications.md). These are observations of the
June to September 2026 reports, not a description of HCPF's process:

* The Premiums, Expenditures and Caseload Reports page
  (https://hcpf.colorado.gov/budget/FY-Premiums-Expenditures-Caseload-Reports)
  listed June to September 2026 report sets, each a PDF and a workbook under
  ``/sites/hcpf/files/<YYYY> <Month>, Joint Budget Committee Monthly Premiums
  Report<suffix>.<ext>``. Observed suffixes: none, `` no links`` (July's
  workbook) and ``_0`` (the February PDF, no longer listed).
* In each inspected report the newest populated month is the month before
  the month in the file name: the ``2026 September`` PDF leads with August
  2026. The page's own note describes a different convention ("a report with
  the link August will reference August activity"), so the reader selects a
  report by file name and then also requires it to print the requested month
  as its newest populated month.
* Page 4 of each PDF, and the ``Medicaid Caseload`` sheet of the September
  workbook, carry the table "MEDICAID CASELOAD WITHOUT RETROACTIVITY": one row
  per month, seventeen eligibility categories and a ``TOTAL`` column. Later
  months are listed without figures.
* The reports reprint earlier months, and values can change between reports:
  January 2026 is 1,236,302 in the February report and 1,236,285 in the June
  report. The table's note says the data "may be restated in future reports".
  The reader therefore returns only the newest populated month's TOTAL. That
  selection does not by itself establish when the figure was first published;
  the resolver's custody rule (``served_unchanged_since_resolution_date`` in
  ``resolve_pending``) decides whether the bytes may be recorded.
"""

from __future__ import annotations

import datetime as dt
import posixpath
import re
import zipfile
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse
from xml.etree import ElementTree as ET

import va_mmwr

LANDING_URL = (
    "https://hcpf.colorado.gov/budget/FY-Premiums-Expenditures-Caseload-Reports"
)
ALLOWED_HOSTS = ("hcpf.colorado.gov",)
FILES_PREFIX = "/sites/hcpf/files/"
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_MONTH_NUMBER = {name: number for number, name in enumerate(MONTH_NAMES, start=1)}
_MONTH_ALTERNATION = "|".join(MONTH_NAMES)
# ``variant`` accepts suffixes, including the observed " no links" and "_0".
# The cover letter has a different name ("... Monthly Premiums Cover Letter")
# and never matches.
REPORT_FILE = re.compile(
    rf"^(?P<year>\d{{4}}) (?P<month>{_MONTH_ALTERNATION}), Joint Budget "
    r"Committee Monthly Premiums Report(?P<variant>(?: [A-Za-z ]+)?(?:_\d+)?)"
    r"\.(?P<ext>pdf|xlsx)$"
)
TABLE_TITLE = re.compile(r"^MEDICAID CASELOAD WITHOUT RETROACTIVITY ?1?$")
# "YTD Average" in the FY 2026-27 reports, "Year-to-Date Average" before.
TABLE_END = re.compile(r"^FY \d{4}-\d{2} (?:YTD|Year-to-Date) Average\b")
FISCAL_YEAR_ROW = re.compile(r"^FY \d{4}-\d{2} Actuals\b")
MONTH_ROW = re.compile(
    rf"^(?P<month>{_MONTH_ALTERNATION}) (?P<year>\d{{4}})(?P<rest>.*)$"
)
COUNT = re.compile(r"^\d{1,3}(?:,\d{3})*$")
SHEET_NAME = "Medicaid Caseload"
# Seventeen eligibility categories and TOTAL, in every report read at wiring.
PDF_COLUMNS = 18
_EXCEL_EPOCH = dt.date(1899, 12, 30)
# What a damaged workbook can raise from the stdlib ZIP and XML readers that
# ``va_mmwr.sheet_cells`` does not already turn into its own error (a bad
# CRC raises ``zipfile.BadZipFile`` on read, a truncated member ``EOFError``
# or ``zlib.error``).
WORKBOOK_ARCHIVE_ERRORS = (
    va_mmwr.VaMmwrError,
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    zlib.error,
    EOFError,
    OSError,
    NotImplementedError,
    RuntimeError,
    KeyError,
    ValueError,
    ET.ParseError,
)


class CoHcpfError(ValueError):
    """The source exists but cannot be read without guessing."""


class ReportNotListedError(CoHcpfError):
    """No link on the page matches the report name asked for."""


def parse_period(period: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise CoHcpfError(f"period {period!r} is not YYYY-MM")
    return int(match.group(1)), int(match.group(2))


def format_period(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def next_period(period: str) -> str:
    year, month = parse_period(period)
    return format_period(year + month // 12, month % 12 + 1)


def report_period_for(period: str) -> str:
    """Candidate report month for activity month ``period``: the month after.

    That is the relation seen in the inspected reports; the reader still
    requires the report to print ``period`` as its newest populated month.
    """
    return next_period(period)


def period_label(period: str) -> str:
    year, month = parse_period(period)
    return f"{MONTH_NAMES[month - 1]} {year}"


# ---------------------------------------------------------------------------
# Landing page: report month -> the page's own file links


class _Hrefs(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if isinstance(href, str) and href.strip():
                self.hrefs.append(href.strip())


@dataclass(frozen=True)
class ReportLinks:
    report_period: str
    pdf_url: str
    xlsx_url: str | None
    # Every month the page lists a report PDF for, oldest first.
    listed: tuple[str, ...]


def _report_files(landing_html: bytes | str) -> list[tuple[str, str, str]]:
    """(report period, extension, absolute URL) for each distinct report link."""
    text = (
        landing_html.decode("utf-8", "replace")
        if isinstance(landing_html, bytes)
        else landing_html
    )
    parser = _Hrefs()
    parser.feed(text)
    parser.close()
    found: set[tuple[str, str, str]] = set()
    for href in parser.hrefs:
        url = urljoin(LANDING_URL, href)
        parts = urlparse(url)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
            continue
        if parts.query or parts.fragment or parts.params:
            continue
        path = unquote(parts.path)
        if posixpath.dirname(path) + "/" != FILES_PREFIX:
            continue
        match = REPORT_FILE.fullmatch(posixpath.basename(path))
        if not match:
            continue
        period = format_period(int(match.group("year")), _MONTH_NUMBER[match["month"]])
        found.add((period, match.group("ext"), url))
    return sorted(found)


def landing_report_links(landing_html: bytes | str, report_period: str) -> ReportLinks:
    """The files the page binds to the report dated ``report_period``.

    Exactly one PDF may carry that month's report name; at most one workbook
    may. Links are judged by the stored file name, not by their label or
    position, and no file name is built from a cadence. Links on another host
    or path, or with a query or fragment, are ignored, so "found 0" means no
    link matched these filters, not that no report exists.
    """
    parse_period(report_period)
    files = _report_files(landing_html)
    mine = [(ext, url) for period, ext, url in files if period == report_period]
    pdfs = [url for ext, url in mine if ext == "pdf"]
    books = [url for ext, url in mine if ext == "xlsx"]
    label = period_label(report_period)
    if len(pdfs) != 1:
        error = ReportNotListedError if not pdfs else CoHcpfError
        raise error(
            f"expected exactly one report PDF link for the {label} report, "
            f"found {len(pdfs)}"
        )
    if len(books) > 1:
        raise CoHcpfError(
            f"expected at most one report workbook link for the {label} report, "
            f"found {len(books)}"
        )
    return ReportLinks(
        report_period=report_period,
        pdf_url=pdfs[0],
        xlsx_url=books[0] if books else None,
        listed=tuple(sorted({period for period, ext, _ in files if ext == "pdf"})),
    )


# ---------------------------------------------------------------------------
# The caseload table


@dataclass(frozen=True)
class CaseloadRow:
    period: str
    # Category figures in column order; ``None`` where the report prints "-".
    categories: tuple[int | None, ...]
    total: int
    # Why the row cannot be returned, when it carries a figure that is not a
    # whole count. In the inspected workbook such rows occur only in older
    # history (September 2014 holds about 0.0084 in one category); the row is
    # parsed and kept, and ``newest_month_total`` refuses it if asked.
    irregular: str | None = None

    @property
    def categories_sum(self) -> int:
        return sum(value for value in self.categories if value is not None)


@dataclass(frozen=True)
class CaseloadTable:
    rows: tuple[CaseloadRow, ...]
    # Months listed after the newest figure, with no figures.
    unpopulated: tuple[str, ...]

    @property
    def latest(self) -> str:
        return self.rows[-1].period

    def row(self, period: str) -> CaseloadRow | None:
        return next((row for row in self.rows if row.period == period), None)


def _finish_table(
    rows: list[CaseloadRow], unpopulated: list[str], source: str
) -> CaseloadTable:
    if not rows:
        raise CoHcpfError(f"{source} caseload table has no month with figures")
    months = [row.period for row in rows] + unpopulated
    for earlier, later in zip(months, months[1:]):
        if next_period(earlier) != later:
            raise CoHcpfError(
                f"{source} caseload table months are not consecutive: "
                f"{earlier} is followed by {later}"
            )
    return CaseloadTable(rows=tuple(rows), unpopulated=tuple(unpopulated))


def caseload_table_from_pdf_text(text: str) -> CaseloadTable:
    """Parse ``pdftotext -layout`` output of the report.

    The table is the block from the one line that reads "MEDICAID CASELOAD
    WITHOUT RETROACTIVITY" to its "FY ... YTD Average" (or "Year-to-Date
    Average") line. A month row is the month name and year followed by exactly
    eighteen figures; a listed month with no figures is recorded as
    unpopulated. Anything else on a month row is refused.
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    titles = [index for index, line in enumerate(lines) if TABLE_TITLE.fullmatch(line)]
    if len(titles) != 1:
        raise CoHcpfError(
            "expected exactly one 'MEDICAID CASELOAD WITHOUT RETROACTIVITY' "
            f"table title, found {len(titles)}"
        )
    rows: list[CaseloadRow] = []
    unpopulated: list[str] = []
    header: list[str] = []
    ended = False
    for line in lines[titles[0] + 1 :]:
        if TABLE_END.match(line):
            ended = True
            break
        if line.startswith("MEDICAID CASELOAD"):
            break
        match = MONTH_ROW.fullmatch(line)
        if not match:
            if not rows and not unpopulated:
                header.append(line)
            elif line and not FISCAL_YEAR_ROW.match(line):
                raise CoHcpfError(
                    f"unexpected line inside the caseload table: {line[:80]!r}"
                )
            continue
        period = format_period(int(match.group("year")), _MONTH_NUMBER[match["month"]])
        tokens = match.group("rest").split()
        if not tokens:
            unpopulated.append(period)
            continue
        if unpopulated:
            raise CoHcpfError(
                f"{period} carries figures after {unpopulated[-1]}, a month "
                "listed without any"
            )
        if len(tokens) != PDF_COLUMNS:
            raise CoHcpfError(
                f"{period} row has {len(tokens)} figures, expected {PDF_COLUMNS}"
            )
        values: list[int | None] = []
        for token in tokens:
            if token == "-":
                values.append(None)
            elif COUNT.fullmatch(token):
                values.append(int(token.replace(",", "")))
            else:
                raise CoHcpfError(f"{period} row has a non-count figure {token!r}")
        if values[-1] is None:
            raise CoHcpfError(f"{period} row prints no TOTAL")
        rows.append(
            CaseloadRow(period=period, categories=tuple(values[:-1]), total=values[-1])
        )
    if not ended:
        raise CoHcpfError("caseload table has no 'YTD Average' line closing it")
    header_words = set(" ".join(header).split())
    if not {"Month", "TOTAL"} <= header_words:
        raise CoHcpfError("caseload table header does not name Month and TOTAL")
    return _finish_table(rows, unpopulated, "PDF")


def _serial_period(value: object) -> str | None:
    """``YYYY-MM`` for an Excel date serial on the first of a month."""
    if isinstance(value, bool) or not isinstance(value, float):
        return None
    if not value.is_integer() or not 30_000 <= value <= 80_000:
        return None
    day = _EXCEL_EPOCH + dt.timedelta(days=int(value))
    return format_period(day.year, day.month) if day.day == 1 else None


def caseload_table_from_workbook(raw: bytes) -> CaseloadTable:
    """Parse the ``Medicaid Caseload`` sheet (cached values, stdlib OOXML).

    A damaged archive raises ``CoHcpfError``, never a ZIP or XML error.
    """
    try:
        cells = va_mmwr.sheet_cells(raw, SHEET_NAME)
    except WORKBOOK_ARCHIVE_ERRORS as exc:
        raise CoHcpfError(
            f"report workbook: {type(exc).__name__}: {str(exc)[:160]}"
        ) from exc

    def text_at(key: tuple[int, int]) -> str:
        value = cells[key].value
        return va_mmwr.normalized_text(value) if isinstance(value, str) else ""

    titles = [key for key in cells if TABLE_TITLE.fullmatch(text_at(key))]
    if len(titles) != 1:
        raise CoHcpfError(
            f"expected exactly one table title on the {SHEET_NAME!r} sheet, "
            f"found {len(titles)}"
        )
    month_headers = [key for key in cells if text_at(key) == "Month"]
    if len(month_headers) != 1:
        raise CoHcpfError(
            f"expected exactly one 'Month' header on the {SHEET_NAME!r} sheet, "
            f"found {len(month_headers)}"
        )
    header_row, month_column = month_headers[0]
    totals = [key for key in cells if key[0] == header_row and text_at(key) == "TOTAL"]
    if len(totals) != 1 or totals[0][1] <= month_column + 1:
        raise CoHcpfError("the header row does not carry one TOTAL column")
    total_column = totals[0][1]
    category_columns = range(month_column + 1, total_column)
    rows: list[CaseloadRow] = []
    unpopulated: list[str] = []
    for key in sorted(k for k in cells if k[1] == month_column and k[0] > header_row):
        period = _serial_period(cells[key].value)
        if period is None:
            continue
        figures: list[int | None] = []
        irregular: str | None = None
        for column in (*category_columns, total_column):
            cell = cells.get((key[0], column))
            if cell is None:
                figures.append(None)
                continue
            value = cell.value
            if (
                isinstance(value, bool)
                or not isinstance(value, float)
                or not value.is_integer()
                or value < 0
            ):
                irregular = f"{period} row has a non-count figure {value!r}"
                break
            figures.append(int(value))
        if irregular is None and all(value is None for value in figures):
            unpopulated.append(period)
            continue
        if unpopulated:
            raise CoHcpfError(
                f"{period} carries figures after {unpopulated[-1]}, a month "
                "listed without any"
            )
        if irregular is not None:
            rows.append(
                CaseloadRow(period=period, categories=(), total=0, irregular=irregular)
            )
            continue
        if figures[-1] is None:
            raise CoHcpfError(f"{period} row prints no TOTAL")
        rows.append(
            CaseloadRow(
                period=period, categories=tuple(figures[:-1]), total=figures[-1]
            )
        )
    return _finish_table(rows, unpopulated, "workbook")


def newest_month_total(table: CaseloadTable, period: str) -> int:
    """The TOTAL of the table's newest populated month, which must be ``period``.

    Refuses when ``period`` is not the newest populated month, when that row
    holds a figure that is not a whole count, or when its categories do not
    sum to its TOTAL (so the figure is the row's total, not a neighbouring
    column). None of this establishes when the figure was first published.
    """
    parse_period(period)
    if table.latest != period:
        raise CoHcpfError(
            f"the report's newest populated month is {table.latest}, not "
            f"{period}; this adapter reads only the newest populated month"
        )
    row = table.rows[-1]
    if row.irregular:
        raise CoHcpfError(row.irregular)
    if row.categories_sum != row.total:
        raise CoHcpfError(
            f"{period} categories sum to {row.categories_sum}, not the printed "
            f"TOTAL {row.total}"
        )
    return row.total
