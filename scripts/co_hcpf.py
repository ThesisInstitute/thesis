#!/usr/bin/env python3
"""Read the Colorado HCPF Joint Budget Committee Monthly Premiums Report.

Pure standard library (plus the hardened OOXML reader in ``va_mmwr``). Used
by ``scripts/resolve_pending.py`` for the ``co.hcpf.medicaid.total_caseload``
family and by its tests.

Source facts (verified 2026-10-09 against the live site; see "Colorado HCPF
Medicaid caseload" in docs/anchor-verifications.md):

* The Premiums, Expenditures and Caseload Reports page
  (https://hcpf.colorado.gov/budget/FY-Premiums-Expenditures-Caseload-Reports)
  links one report per month as a PDF and a workbook, both stored as
  ``/sites/hcpf/files/<YYYY> <Month>, Joint Budget Committee Monthly Premiums
  Report.<ext>``. The month in the file name is the month the report is
  dated, and the report's newest caseload month is the month before it: the
  ``2026 September`` report was posted 2026-09-14 and its newest month is
  August 2026. The page's own note describes the opposite convention ("a
  report with the link August will reference August activity"), so this
  reader never trusts the name alone: the report it is handed must itself
  print the requested month as its newest month.
* Page 4 of the PDF, and the ``Medicaid Caseload`` sheet of the workbook,
  carry the table "MEDICAID CASELOAD WITHOUT RETROACTIVITY": one row per
  month, seventeen eligibility categories and a ``TOTAL`` column. Months the
  fiscal year has not reached yet are listed with no figures.
* Every report restates earlier months (January 2026 printed 1,236,302 in
  the February 2026 report and 1,236,285 in the June 2026 report), and the
  table's own note says so: "The data presented in this report is
  preliminary ... and may be restated in future reports". A month's first
  print is therefore the figure in the one report where it is the newest
  month.
* The server sends ``Last-Modified`` for each file, and the four reports
  observed each carry one in the middle of the month they are dated (06-15,
  07-15, 08-17, 09-14). That header is the first-posting evidence: a file
  modified outside its own month is refused.
"""

from __future__ import annotations

import datetime as dt
import posixpath
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

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
# ``variant`` admits the two spellings HCPF has used for a second file of the
# same report (" no links", Drupal's "_0" collision suffix). The cover letter
# is a different name ("... Monthly Premiums Cover Letter") and never matches.
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
POSTING_ZONE = ZoneInfo("America/Denver")
_EXCEL_EPOCH = dt.date(1899, 12, 30)


class CoHcpfError(ValueError):
    """The source exists but cannot be read without guessing."""


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
    """The month the report that first prints ``period`` is dated."""
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
    may. Links are judged by the stored file name, never by their label or
    position, and never inferred from cadence.
    """
    parse_period(report_period)
    files = _report_files(landing_html)
    mine = [(ext, url) for period, ext, url in files if period == report_period]
    pdfs = [url for ext, url in mine if ext == "pdf"]
    books = [url for ext, url in mine if ext == "xlsx"]
    label = period_label(report_period)
    if len(pdfs) != 1:
        raise CoHcpfError(
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


def posting_gate(
    last_modified: str | None, *, report_period: str
) -> tuple[dt.datetime | None, str | None]:
    """(parsed Last-Modified, refusal).

    The file must have been last modified during the month its report is
    dated (Denver time). A later date is a re-post; an earlier one cannot be
    the report that month names. Either way the served bytes are not shown to
    be the first posting, and the read is refused.
    """
    if not last_modified:
        return None, (
            "report response carries no Last-Modified header; first posting "
            "cannot be established"
        )
    try:
        modified = parsedate_to_datetime(last_modified)
    except (TypeError, ValueError) as exc:
        return None, f"Last-Modified {last_modified!r} unreadable: {exc}"
    if modified.tzinfo is None:
        modified = modified.replace(tzinfo=dt.timezone.utc)
    local = modified.astimezone(POSTING_ZONE).date()
    posted = format_period(local.year, local.month)
    if posted > report_period:
        return modified, (
            f"report file was modified {local}, after "
            f"{period_label(report_period)}, the month the report is dated; the "
            "served file is a re-post, not the first print"
        )
    if posted < report_period:
        return modified, (
            f"report file was modified {local}, before "
            f"{period_label(report_period)}, the month the report is dated; it is "
            "not the report that month names"
        )
    return modified, None


# ---------------------------------------------------------------------------
# The caseload table


@dataclass(frozen=True)
class CaseloadRow:
    period: str
    # Category figures in column order; ``None`` where the report prints "-".
    categories: tuple[int | None, ...]
    total: int
    # Why the row cannot be read, when it carries a figure that is not a
    # whole count. Only the workbook's old history has such rows (September
    # 2014 holds 0.0084 in one category); a row like that is never read.
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
    WITHOUT RETROACTIVITY" to its "FY ... YTD Average" line. A month row is
    the month name and year followed by exactly eighteen figures; a listed
    month with no figures has not been reported yet. Anything else on a
    month row is refused.
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
    """Parse the ``Medicaid Caseload`` sheet (cached values, stdlib OOXML)."""
    try:
        cells = va_mmwr.sheet_cells(raw, SHEET_NAME)
    except va_mmwr.VaMmwrError as exc:
        raise CoHcpfError(f"report workbook: {exc}") from exc

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


def first_print_total(table: CaseloadTable, period: str) -> int:
    """The TOTAL the report first prints for ``period``.

    Refuses unless ``period`` is the report's newest month (so the figure is
    not a restatement) and the row's categories add up to its TOTAL (so the
    figure is the row's total and not a neighbouring column).
    """
    parse_period(period)
    if table.latest != period:
        raise CoHcpfError(
            f"the report's newest caseload month is {table.latest}, not {period}; "
            "it does not first print that month"
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
