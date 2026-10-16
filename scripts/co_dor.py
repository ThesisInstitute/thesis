#!/usr/bin/env python3
"""Read the Colorado DOR General Fund Net Collections workbook.

Pure standard library (plus the hardened OOXML reader in ``va_mmwr``). Used
by ``scripts/resolve_pending.py`` for the
``co.dor.individual_income_tax.net_collections`` family and by its tests.

What was observed (2026-10-09; see "Colorado DOR net individual income tax
collections" in docs/anchor-verifications.md):

* The Wayback Machine's 2026-05-05 capture of the General Fund Collections
  Reports page
  (https://cdor.colorado.gov/data-and-reports/general-fund-collections-reports)
  links the label "General Fund Collections Report, July 2019 to Date" to a
  Google Drive file id, ``WORKBOOK_FILE_ID`` below. A curl request for the
  live page with a browser User-Agent got a Cloudflare challenge (HTTP 403),
  so the adapter reads the Drive file by that reviewed id and not the page.
* For a signed-in reader, Drive reported the file as created 2023-12-14 and
  last modified 2026-09-28, ``canReadRevisions`` as false, and only the head
  revision. The download served on 2026-10-09 has one sheet, ``Report``: a
  title cell ("General Fund (GF) and Other Miscellaneous Net Collections by
  Month / Dollar Amounts in Thousands / July 2019 to Date"), a header row of
  months with the newest month in the first data column (August 2026), one
  row per revenue category, and the line "Publish date: September 2026".
* Nothing observed establishes how or when DOR changes the file, or when a
  given month first appeared in it. The resolver's custody rule
  (``served_unchanged_since_resolution_date`` in ``resolve_pending``) works
  from the download's Last-Modified header alone.
"""

from __future__ import annotations

import re
import zipfile
import zlib
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import va_mmwr

LANDING_URL = (
    "https://cdor.colorado.gov/data-and-reports/general-fund-collections-reports"
)
WORKBOOK_FILE_ID = "1Bg4VFz2V2sWbR9Nj9v0ygYOgViFor_CN"
WORKBOOK_URL = f"https://drive.google.com/uc?export=download&id={WORKBOOK_FILE_ID}"
# Drive answers the download URL with a redirect to its content host.
ALLOWED_HOSTS = ("drive.google.com", "drive.usercontent.google.com")
SHEET_NAME = "Report"
TITLE_PREFIX = "General Fund (GF) and Other Miscellaneous Net Collections by Month"
UNITS_LINE = "Dollar Amounts in Thousands"
SOURCE_LINE = "Source: Colorado State Accounting System"
HEADER_LABEL = "Revenue Category"
NET_LABEL = "Total Net Individual Income"
GROSS_LABEL = "Gross Individual Income"
REFUNDS_LABEL = "Less: Individual Refunds"
COMPONENT_LABELS = ("Withholding", "Individual Estimated Payments", "Individual Cash")
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
_MONTH_LABEL = re.compile(rf"^({'|'.join(MONTH_NAMES)}) (\d{{4}})$")
_PUBLISH_DATE = re.compile(rf"^Publish date: ({'|'.join(MONTH_NAMES)}) (\d{{4}})$")
# What a damaged workbook can raise from the stdlib ZIP and XML readers that
# ``va_mmwr.sheet_cells`` does not already turn into its own error.
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
# Footnote markers DOR appends to row labels ("Less: Individual Refunds ²").
_FOOTNOTE_MARKS = "¹²³⁴⁵⁶⁷⁸⁹⁰"


class CoDorError(ValueError):
    """The source exists but cannot be read without guessing."""


def _period(label: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.fullmatch(label)
    if not match:
        return None
    return f"{int(match.group(2)):04d}-{_MONTH_NUMBER[match.group(1)]:02d}"


def period_label(period: str) -> str:
    year, month = period.split("-")
    return f"{MONTH_NAMES[int(month) - 1]} {year}"


def _previous(period: str) -> str:
    year, month = (int(part) for part in period.split("-"))
    return f"{year - (month == 1):04d}-{12 if month == 1 else month - 1:02d}"


@dataclass(frozen=True)
class NetIndividualIncome:
    """One month's net individual income tax collections, $ thousands."""

    period: str
    net: int
    gross: int
    refunds: int
    # The rows listed between the gross line and the refunds line, summed (in
    # the inspected file, TABOR refund and rate-reduction lines); they are
    # added to gross before refunds.
    adjustments: int
    components: tuple[int, int, int]


@dataclass(frozen=True)
class CollectionsWorkbook:
    # Months in column order: newest first.
    months: tuple[str, ...]
    publish_period: str | None
    _figures: dict[str, NetIndividualIncome]
    # Why a listed month could not be read, for the months that could not.
    _unreadable: dict[str, str]

    @property
    def newest(self) -> str:
        return self.months[0]

    def net_individual_income(self, period: str) -> NetIndividualIncome:
        if period in self._unreadable:
            raise CoDorError(f"{period}: {self._unreadable[period]}")
        if period not in self._figures:
            raise CoDorError(f"the workbook has no {period} column")
        return self._figures[period]


def _label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return va_mmwr.normalized_text(value).rstrip(_FOOTNOTE_MARKS).strip()


def read_collections(raw: bytes) -> CollectionsWorkbook:
    """Parse the ``Report`` sheet.

    The identity cells (title, units, source line, header label) and the
    selected row labels must each appear exactly once, and the selected rows
    must sit where the checks below expect them. Every month column is parsed;
    a month whose selected cells are not whole numbers is kept as unreadable
    and refused only when asked for. This function does not check the
    accounting identities; ``check_identities`` does, for one month. A
    damaged archive raises ``CoDorError``, never a ZIP or XML error.
    """
    try:
        cells = va_mmwr.sheet_cells(raw, SHEET_NAME)
    except WORKBOOK_ARCHIVE_ERRORS as exc:
        raise CoDorError(
            f"collections workbook: {type(exc).__name__}: {str(exc)[:160]}"
        ) from exc
    labels = {key: _label(cell.value) for key, cell in cells.items()}

    def one(text: str, *, prefix: bool = False) -> tuple[int, int]:
        hits = [
            key
            for key, label in labels.items()
            if (label.startswith(text) if prefix else label == text)
        ]
        if len(hits) != 1:
            raise CoDorError(
                f"expected exactly one {text!r} cell on the {SHEET_NAME!r} "
                f"sheet, found {len(hits)}"
            )
        return hits[0]

    title_key = one(TITLE_PREFIX, prefix=True)
    if UNITS_LINE not in labels[title_key]:
        raise CoDorError(f"the title cell does not say {UNITS_LINE!r}")
    one(SOURCE_LINE)
    header_row, label_column = one(HEADER_LABEL)
    months: list[str] = []
    columns: list[int] = []
    for key in sorted(k for k in cells if k[0] == header_row and k[1] > label_column):
        period = _period(labels[key], _MONTH_LABEL)
        if period is None:
            raise CoDorError(
                f"header cell {labels[key] or cells[key].value!r} is not a month"
            )
        months.append(period)
        columns.append(key[1])
    if not months:
        raise CoDorError("the header row names no month")
    if columns != list(range(label_column + 1, label_column + 1 + len(columns))):
        raise CoDorError("the month columns are not contiguous")
    for newer, older in zip(months, months[1:]):
        if _previous(newer) != older:
            raise CoDorError(
                f"header months are not consecutive, newest first: {newer} is "
                f"followed by {older}"
            )

    def row_of(text: str, *, prefix: bool = False) -> int:
        row, column = one(text, prefix=prefix)
        if column != label_column or row <= header_row:
            raise CoDorError(f"{text!r} is not a row label under the header")
        return row

    net_row = row_of(NET_LABEL)
    gross_row = row_of(GROSS_LABEL)
    refunds_row = row_of(REFUNDS_LABEL, prefix=True)
    component_rows = [row_of(label) for label in COMPONENT_LABELS]
    if component_rows != [gross_row - 3, gross_row - 2, gross_row - 1]:
        raise CoDorError(
            "withholding, estimated payments and cash are not the three rows "
            "above the gross line"
        )
    if not gross_row < refunds_row < net_row or net_row != refunds_row + 1:
        raise CoDorError("the gross, refunds and net rows are out of order")

    def amount(row: int, column: int) -> int:
        cell = cells.get((row, column))
        value = cell.value if cell is not None else None
        if (
            isinstance(value, bool)
            or not isinstance(value, float)
            or not value.is_integer()
        ):
            raise CoDorError(
                f"{labels.get((row, label_column), row)!r} holds {value!r}, not "
                "a whole number of thousands"
            )
        return int(value)

    publish = [
        period
        for label in labels.values()
        if (period := _period(label, _PUBLISH_DATE)) is not None
    ]
    if len(publish) > 1:
        raise CoDorError("the sheet carries more than one publish date")
    figures: dict[str, NetIndividualIncome] = {}
    unreadable: dict[str, str] = {}
    for period, column in zip(months, columns):
        try:
            withholding, estimated, cash = (
                amount(row, column) for row in component_rows
            )
            figures[period] = NetIndividualIncome(
                period=period,
                net=amount(net_row, column),
                gross=amount(gross_row, column),
                refunds=amount(refunds_row, column),
                adjustments=sum(
                    amount(row, column) for row in range(gross_row + 1, refunds_row)
                ),
                components=(withholding, estimated, cash),
            )
        except CoDorError as exc:
            # An unreadable month is refused when it is asked for, so one
            # damaged historical column cannot hide the newest month.
            unreadable[period] = str(exc)
    return CollectionsWorkbook(
        months=tuple(months),
        publish_period=publish[0] if publish else None,
        _figures=figures,
        _unreadable=unreadable,
    )


def check_identities(figure: NetIndividualIncome) -> None:
    """Refuse a month whose printed lines do not add up.

    Net must equal gross plus the listed adjustments less refunds exactly,
    and withholding, estimated payments and cash must sum to within one
    thousand of gross. In the workbook downloaded 2026-10-09 (publish-date
    line September 2026) net holds exactly in all 86 months, and the
    component sum differs from gross by one thousand in 28 of them and by
    nothing in the rest. Why those 28 differ is not established.
    """
    if abs(sum(figure.components) - figure.gross) > 1:
        raise CoDorError(
            f"{figure.period}: withholding, estimated payments and cash sum to "
            f"{sum(figure.components)}, not the gross line {figure.gross}"
        )
    expected = figure.gross + figure.adjustments - figure.refunds
    if expected != figure.net:
        raise CoDorError(
            f"{figure.period}: gross plus adjustments less refunds is {expected}, "
            f"not the net line {figure.net}"
        )
