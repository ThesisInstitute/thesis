"""Synthetic Colorado HCPF and DOR sources shared by the resolver tests.

The builders mirror the layouts of the official files committed under
``tests/fixtures/co_hcpf`` and ``tests/fixtures/co_dor`` (the September 2026
HCPF report and the DOR workbook published that month), so a test can vary
one fact at a time: which month is newest, what a row sums to, when a file
was posted.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from html import escape
from urllib.parse import quote

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
HCPF_CATEGORIES = 17
_EXCEL_EPOCH = dt.date(1899, 12, 30)


def period_label(period: str) -> str:
    year, month = period.split("-")
    return f"{MONTH_NAMES[int(month) - 1]} {year}"


def shift(period: str, months: int) -> str:
    year, month = (int(part) for part in period.split("-"))
    index = year * 12 + (month - 1) + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def months_through(newest: str, count: int) -> list[str]:
    """``count`` consecutive months ending at ``newest``, oldest first."""
    return [shift(newest, offset) for offset in range(-(count - 1), 1)]


def split_total(total: int, parts: int = HCPF_CATEGORIES) -> tuple[int, ...]:
    """Whole category counts that sum to ``total``."""
    base, extra = divmod(total, parts)
    return tuple(base + (1 if index < extra else 0) for index in range(parts))


# ---------------------------------------------------------------------------
# Minimal OOXML


def _column_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def xlsx_from_cells(
    sheet_name: str, cells: dict[tuple[int, int], str | int | float]
) -> bytes:
    """One-sheet workbook; keys are 0-based (row, column)."""
    rows: dict[int, list[str]] = {}
    for (row, column), value in sorted(cells.items()):
        reference = f"{_column_letters(column)}{row + 1}"
        if isinstance(value, str):
            cell = (
                f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">'
                f"{escape(value)}</t></is></c>"
            )
        else:
            cell = f'<c r="{reference}"><v>{value}</v></c>'
        rows.setdefault(row, []).append(cell)
    sheet_data = "".join(
        f'<row r="{row + 1}">{"".join(row_cells)}</row>'
        for row, row_cells in sorted(rows.items())
    )
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package = "http://schemas.openxmlformats.org/package/2006/relationships"
    members = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" ContentType="application/xml"/>'
            "</Types>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
            f'<sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/>'
            "</sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{package}"><Relationship Id="rId1" '
            f'Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<worksheet xmlns="{main}"><sheetData>{sheet_data}</sheetData>'
            "</worksheet>"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# HCPF Joint Budget Committee Monthly Premiums Report

HcpfRow = tuple[str, tuple[int | None, ...], int]


def hcpf_rows(newest: str, totals: list[int]) -> list[HcpfRow]:
    """Rows for consecutive months ending at ``newest``; categories add up."""
    return [
        (period, split_total(total), total)
        for period, total in zip(months_through(newest, len(totals)), totals)
    ]


def hcpf_pdf_text(
    rows: list[HcpfRow],
    unpopulated: list[str] | None = None,
    *,
    title: str = "MEDICAID CASELOAD WITHOUT RETROACTIVITY 1",
    closing: str = "FY 2026-27 YTD Average",
    fiscal_year_rows: bool = True,
) -> str:
    """Text shaped like ``pdftotext -layout`` output of the caseload page."""

    def figure(value: int | None) -> str:
        return "-" if value is None else f"{value:,}"

    lines = [
        "  Page 4",
        " " * 60 + "Department of Health Care Policy and Financing",
        " " * 55 + "FY 2026-27 Medical Premiums Expenditure and Caseload Report",
        "",
        " " * 70 + title,
        "",
        " " * 20 + "Adults 65     Disabled      MAGI Parents/      Partial",
        " " * 8 + "Month" + " " * 10 + "and Older     Adults 60" + " " * 30 + "TOTAL",
        " " * 20 + "(OAP-A)       (OAP-B)       68% FPL",
        "",
    ]
    for period, categories, total in rows:
        if fiscal_year_rows and period.endswith("-07") and lines[-1].strip():
            lines.append(
                f"FY {int(period[:4]) - 1}-{period[2:4]} Actuals"
                + "".join(f"{1000 + i:>12,}" for i in range(len(categories) + 1))
            )
        lines.append(
            f"{period_label(period):>40}"
            + "".join(f"{figure(value):>14}" for value in (*categories, total))
        )
    for period in unpopulated or []:
        lines.append(f"{period_label(period):>40}")
    lines.append(closing + "".join(f"{1000 + i:>14,}" for i in range(18)))
    lines.append("Notes:")
    lines.append("1) Source for all caseload data provided is the R-474701 report.")
    lines.append("\f  Page 5")
    lines.append(" " * 60 + "MEDICAID CASELOAD BY PROGRAM WITHOUT RETROACTIVITY1")
    lines.append(f"{period_label(rows[-1][0]):>40}" + f"{'<30':>14}" * 18)
    return "\n".join(lines) + "\n"


def _serial(period: str) -> int:
    year, month = (int(part) for part in period.split("-"))
    return (dt.date(year, month, 1) - _EXCEL_EPOCH).days


def hcpf_workbook(
    rows: list[HcpfRow],
    unpopulated: list[str] | None = None,
    *,
    sheet_name: str = "Medicaid Caseload",
    title: str = "MEDICAID CASELOAD WITHOUT RETROACTIVITY1",
) -> bytes:
    """The ``Medicaid Caseload`` sheet: title, header row, one row per month."""
    width = len(rows[0][1]) if rows else HCPF_CATEGORIES
    cells: dict[tuple[int, int], str | int | float] = {
        (0, 0): "The following table shows historical Medicaid caseload data.",
        (0, 1): title,
        (1, 1): "Month",
        (1, 1 + width + 1): "TOTAL",
    }
    for index in range(width):
        cells[(1, 2 + index)] = f"Category {index + 1}"
    line = 2
    for period, categories, total in rows:
        if period.endswith("-07") and line > 2:
            cells[(line, 1)] = f"FY {int(period[:4]) - 1}-{period[2:4]} Actuals"
            cells[(line, 2)] = 1000.5
            line += 1
        cells[(line, 1)] = _serial(period)
        for index, value in enumerate(categories):
            if value is not None:
                cells[(line, 2 + index)] = value
        cells[(line, 2 + width)] = total
        line += 1
    for period in unpopulated or []:
        cells[(line, 1)] = _serial(period)
        line += 1
    cells[(line, 1)] = "FY 2026-27 YTD Average"
    cells[(line, 2)] = 1000.5
    return xlsx_from_cells(sheet_name, cells)


def hcpf_file_url(report_period: str, ext: str, *, variant: str = "") -> str:
    name = (
        f"{report_period[:4]} {MONTH_NAMES[int(report_period[5:]) - 1]}, Joint "
        f"Budget Committee Monthly Premiums Report{variant}.{ext}"
    )
    return "https://hcpf.colorado.gov/sites/hcpf/files/" + quote(name)


def hcpf_landing(
    report_periods: list[str], *, workbooks: bool = True, extra: str = ""
) -> bytes:
    """Landing page listing one report (letter, PDF, workbook) per month."""
    items = []
    for report_period in report_periods:
        pdf = hcpf_file_url(report_period, "pdf")
        book = hcpf_file_url(report_period, "xlsx")
        letter = pdf.replace("Premiums%20Report", "Premiums%20Cover%20Letter")
        links = [(letter, "Letter"), (pdf, "Report")]
        if workbooks:
            links.append((book, "Report-XLS"))
        items.append(
            f"<p><strong>{period_label(report_period)}</strong></p><ul>"
            + "".join(f'<li><a href="{href}">{text}</a></li>' for href, text in links)
            + "</ul>"
        )
    return (
        "<html><body><h1>Premiums, Expenditures and Caseload Reports</h1>"
        + "".join(items)
        + extra
        + "</body></html>"
    ).encode()


# ---------------------------------------------------------------------------
# DOR General Fund Net Collections workbook

DOR_ADJUSTMENT_LABELS = (
    "2019 Individual TABOR Rate Reduction",
    "2024 Individual TABOR Sales Tax Refund",
)


def dor_figures(seed: int) -> dict[str, int]:
    """One month's individual income lines, internally consistent."""
    withholding = 800_000 + seed * 1_003
    estimated = 20_000 + seed * 17
    cash = 40_000 + seed * 29
    adjustments = (seed % 5, 1_000 + seed)
    refunds = 60_000 + seed * 41
    gross = withholding + estimated + cash
    return {
        "withholding": withholding,
        "estimated": estimated,
        "cash": cash,
        "gross": gross,
        "adjustment_0": adjustments[0],
        "adjustment_1": adjustments[1],
        "refunds": refunds,
        "net": gross + sum(adjustments) - refunds,
    }


def dor_workbook(
    newest: str,
    count: int = 6,
    *,
    publish: str | None = "",
    overrides: dict[str, dict[str, int | str]] | None = None,
    sheet_name: str = "Report",
    net_label: str = "  Total Net Individual Income",
    months: list[str] | None = None,
    cash_row: int = 7,
) -> bytes:
    """The ``Report`` sheet with ``count`` months, newest first.

    ``publish`` defaults to the month after ``newest``; ``None`` omits the
    line. ``overrides`` replaces single figures of a month (``{"2026-07":
    {"net": 1}}``). ``months`` replaces the header months outright, and
    ``cash_row`` moves the "Individual Cash" line off its place above gross.
    """
    months = months or [shift(newest, -offset) for offset in range(count)]
    cells: dict[tuple[int, int], str | int | float] = {
        (0, 0): (
            "General Fund (GF) and Other Miscellaneous Net Collections by Month\n"
            "Dollar Amounts in Thousands\nJuly 2019 to Date"
        ),
        (1, 0): "Intentionally left blank",
        (2, 0): "Revenue Category",
        (4, 0): "Sales Tax (GF portion)",
        (5, 0): "Withholding",
        (6, 0): "Individual Estimated Payments",
        (cash_row, 0): "Individual Cash",
        (8, 0): "  Gross Individual Income",
        (9, 0): DOR_ADJUSTMENT_LABELS[0],
        (10, 0): DOR_ADJUSTMENT_LABELS[1],
        (11, 0): "Less: Individual Refunds ²",
        (12, 0): net_label,
        (13, 0): "Fiduciary Estimated Payments",
        (15, 0): "Source: Colorado State Accounting System",
    }
    if publish is not None:
        cells[(16, 0)] = "Publish date: " + period_label(publish or shift(newest, 1))
    rows = {
        "withholding": 5,
        "estimated": 6,
        "cash": cash_row,
        "gross": 8,
        "adjustment_0": 9,
        "adjustment_1": 10,
        "refunds": 11,
        "net": 12,
    }
    for index, period in enumerate(months):
        column = 1 + index
        cells[(2, column)] = period_label(period)
        cells[(4, column)] = 400_000 + index
        cells[(13, column)] = 500 + index
        figures: dict[str, int | str] = dict(dor_figures(index))
        figures.update((overrides or {}).get(period, {}))
        for key, row in rows.items():
            cells[(row, column)] = figures[key]
    return xlsx_from_cells(sheet_name, cells)
