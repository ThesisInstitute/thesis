#!/usr/bin/env python3
"""Read the Colorado DOR General Fund Net Collections workbook.

Pure standard library (plus the hardened OOXML reader in ``va_mmwr``). Used
by ``scripts/resolve_pending.py`` for the
``co.dor.individual_income_tax.net_collections`` family and by its tests.

Source facts (verified 2026-10-09; see "Colorado DOR net individual income
tax collections" in docs/anchor-verifications.md):

* The General Fund Collections Reports page
  (https://cdor.colorado.gov/data-and-reports/general-fund-collections-reports)
  links its current data as one workbook, "General Fund Collections Report,
  July 2019 to Date", stored in Google Drive. Drive reports that file id as
  created on 2023-12-14 and last modified on 2026-09-28. The page itself
  answers non-browser clients with a Cloudflare challenge (HTTP 403), so the
  adapter reads the Drive file by its reviewed id and never the page.
* The workbook has one sheet, ``Report``: a title cell ("General Fund (GF)
  and Other Miscellaneous Net Collections by Month / Dollar Amounts in
  Thousands / July 2019 to Date"), a header row of months with the NEWEST
  month in the first data column, one row per revenue category, and a
  "Publish date: <Month YYYY>" line.
* DOR publishes by replacing that file in place. Drive serves readers only
  the current revision (``canReadRevisions`` is false), and no copy of an
  earlier one was found in a web archive. A month's first print can
  therefore be identified only while that month is still the newest column:
  once a newer month is there, the figure first published can no longer be
  told apart from a restated one, and the read is refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
    # Rows DOR lists between the gross line and the refunds line (TABOR
    # refund mechanisms), summed; they are added to gross before refunds.
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
    """Parse the ``Report`` sheet and check the rows it will be read by.

    Every label is matched in place and must be unique. For every month the
    two accounting identities the sheet prints are recomputed: gross is the
    sum of withholding, estimated payments and cash, and net is gross plus
    the listed adjustments less refunds. ``check_identities`` refuses a month
    where either fails.
    """
    try:
        cells = va_mmwr.sheet_cells(raw, SHEET_NAME)
    except va_mmwr.VaMmwrError as exc:
        raise CoDorError(f"collections workbook: {exc}") from exc
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

    Checked on all 86 months of the workbook published in September 2026:
    net equals gross plus adjustments less refunds exactly in every month,
    and the three separately rounded components are within one thousand of
    the gross line in every month (28 months differ by exactly one).
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


def first_print_status(workbook: CollectionsWorkbook, period: str) -> str:
    """``"first_print"``, ``"not_yet_published"`` or ``"overwritten"``.

    ``period`` is a first print only while it is the workbook's newest
    month. Before that it is unpublished; after it, the file has been
    replaced at least once since the month first appeared.
    """
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise CoDorError(f"period {period!r} is not YYYY-MM")
    if period == workbook.newest:
        return "first_print"
    return "not_yet_published" if period > workbook.newest else "overwritten"
