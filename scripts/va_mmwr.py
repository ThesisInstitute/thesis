#!/usr/bin/env python3
"""Read the VA VBA Monday Morning Workload Report (MMWR) workbook.

Pure standard library. Used by ``scripts/resolve_pending.py`` for the
``va.vba.mmwr.claims_inventory`` family and by its tests.

Source facts (verified 2026-08-23 against the live site):

* The VBA Detailed Claims Data page
  (https://www.benefits.va.gov/REPORTS/detailed_claims_data.asp) lists each
  weekly report by its Monday *report date* (``07/13/2026``) and links the
  workbook named by the preceding Saturday's *data-through* date
  (``/REPORTS/mmwr/2026/MMWR-07-11-2026.xlsx``). The page's own
  label -> href mapping is the authority the adapter uses; it never
  infers a file name from cadence.
* The workbook's ``Transformation`` sheet carries the national
  "Compensation and Pension Rating Bundle Metrics" block: a
  ``Reporting through <Month DD, YYYY>`` identity cell, a ``# Pending``
  header, and the ``Compensation and Pension Rating Bundle`` / ``Total``
  row whose ``# Pending`` value is the page's headline "Pending Claims"
  status card (601,630 on the 07/06/2026 report; 632,308 on 08/17/2026).
  The data cells are formulas; their cached values are read, never
  recomputed.
* The server sends ``Last-Modified`` for each workbook, and every 2026
  report observed was last modified on its report Monday (the 07/06
  holiday-week report on the Tuesday after). That header is the adapter's
  first-posting evidence: a workbook modified long after its report date
  has been re-posted and is refused rather than recorded as a first print.
"""

from __future__ import annotations

import datetime as dt
import io
import pathlib
import posixpath
import re
import zipfile
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

LANDING_URL = "https://www.benefits.va.gov/REPORTS/detailed_claims_data.asp"
WORKBOOK_HREF_PATTERN = re.compile(
    r"^/REPORTS/mmwr/(?P<dir_year>\d{4})/MMWR-(?P<month>\d{2})-(?P<day>\d{2})-"
    r"(?P<year>\d{4})\.(?P<ext>xlsx|xlsm)$"
)
SHEET_NAME = "Transformation"
SECTION_TITLE = "Compensation and Pension Rating Bundle Metrics"
REPORTING_THROUGH = re.compile(
    r"^Reporting through (?P<date>[A-Za-z]+ \d{1,2}, \d{4})$"
)
PENDING_HEADER = "# Pending"
PENDING_OVER_125_HEADER = "# Pending > 125"
PCT_OVER_125_HEADER = "% Pending > 125 days"
ROW_LABEL = "Compensation and Pension Rating Bundle"
ROW_MARKER = "Total"
MONTHS = {
    name: number
    for number, name in enumerate(
        [
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
        ],
        start=1,
    )
}
MAX_WORKBOOK_BYTES = 25_000_000
MAX_MEMBER_BYTES = 60_000_000


class VaMmwrError(ValueError):
    """The source exists but cannot be read without guessing."""


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value).replace("\xa0", " ")).strip()


# ---------------------------------------------------------------------------
# Landing page: report-date label -> workbook href


class _LandingLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            self._href = href if isinstance(href, str) else None
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, normalized_text("".join(self._parts))))
            self._href = None
            self._parts = []


def report_date_label(report_date: dt.date) -> str:
    return f"{report_date.month:02d}/{report_date.day:02d}/{report_date.year}"


def landing_workbook_href(landing_html: bytes | str, report_date: dt.date) -> str:
    """The href the Detailed Claims Data page binds to ``report_date``.

    Exactly one anchor may carry the report-date label; its href must be a
    same-origin MMWR workbook path. A fragment suffix (``...xlsx#``) is
    tolerated and stripped.
    """
    text = (
        landing_html.decode("utf-8", "replace")
        if isinstance(landing_html, bytes)
        else landing_html
    )
    parser = _LandingLinks()
    parser.feed(text)
    parser.close()
    label = report_date_label(report_date)
    matches = sorted(
        {href.split("#", 1)[0] for href, anchor in parser.links if anchor == label}
    )
    if len(matches) != 1:
        raise VaMmwrError(
            f"expected exactly one report link labelled {label!r} on the Detailed "
            f"Claims Data page, found {len(matches)}: {matches!r}"
        )
    href = matches[0]
    if not WORKBOOK_HREF_PATTERN.match(href):
        raise VaMmwrError(f"report link {href!r} is not an MMWR workbook path")
    return href


def workbook_file_date(href: str) -> dt.date:
    match = WORKBOOK_HREF_PATTERN.match(href)
    if not match:
        raise VaMmwrError(f"not an MMWR workbook path: {href!r}")
    try:
        file_date = dt.date(
            int(match.group("year")), int(match.group("month")), int(match.group("day"))
        )
    except ValueError as exc:
        raise VaMmwrError(
            f"MMWR workbook path carries an invalid date: {href!r}"
        ) from exc
    return file_date


def require_file_date_near_report(
    file_date: dt.date, report_date: dt.date, *, max_lag_days: int = 6
) -> None:
    lag = (report_date - file_date).days
    if not 0 <= lag <= max_lag_days:
        raise VaMmwrError(
            f"workbook data-through date {file_date} is {lag} days before report "
            f"date {report_date}; expected 0-{max_lag_days}"
        )


def workbook_url(href: str) -> str:
    return "https://www.benefits.va.gov" + href


# ---------------------------------------------------------------------------
# First-posting gate


def posting_gate(
    last_modified: str | None,
    *,
    file_date: dt.date,
    report_date: dt.date,
    window_days: int,
) -> tuple[dt.datetime | None, str | None]:
    """(parsed Last-Modified, refusal) — refuse when the header is missing,
    unreadable, earlier than the data-through date, or later than
    ``report_date + window_days``."""
    if not last_modified:
        return None, (
            "workbook response carries no Last-Modified header; first posting "
            "cannot be established"
        )
    try:
        modified = parsedate_to_datetime(last_modified)
    except (TypeError, ValueError) as exc:
        return None, f"Last-Modified {last_modified!r} unreadable: {exc}"
    if modified.tzinfo is None:
        modified = modified.replace(tzinfo=dt.timezone.utc)
    modified_day = modified.astimezone(dt.timezone.utc).date()
    if modified_day < file_date:
        return modified, (
            f"Last-Modified {modified_day} precedes the workbook's data-through "
            f"date {file_date}"
        )
    latest = report_date + dt.timedelta(days=window_days)
    if modified_day > latest:
        return modified, (
            f"workbook was modified {modified_day}, after the first-posting "
            f"window ending {latest} ({window_days} days past report date "
            f"{report_date}); the served file is a re-post, not the first print"
        )
    return modified, None


# ---------------------------------------------------------------------------
# Workbook reading (OOXML primitives; cached formula values accepted)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _column_index(letters: str) -> int:
    column = 0
    for letter in letters:
        column = column * 26 + ord(letter) - ord("A") + 1
    return column - 1


def _cell_coordinates(reference: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Z]+)([1-9]\d*)", reference)
    if match is None:
        raise VaMmwrError(f"invalid XLSX cell reference {reference!r}")
    return int(match.group(2)) - 1, _column_index(match.group(1))


def _member_xml(archive: zipfile.ZipFile, name: str):
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise VaMmwrError(f"workbook is missing {name}") from exc
    if info.file_size > MAX_MEMBER_BYTES:
        raise VaMmwrError(f"workbook member {name} exceeds the size limit")
    try:
        return ET.fromstring(archive.read(info))
    except ET.ParseError as exc:
        raise VaMmwrError(f"workbook member {name} did not parse: {exc}") from exc


@dataclass(frozen=True)
class SheetCell:
    value: object
    formula: bool


def sheet_cells(
    raw: bytes, sheet_name: str = SHEET_NAME
) -> dict[tuple[int, int], SheetCell]:
    """Every populated cell of ``sheet_name`` keyed (row, column), 0-based.

    Formula cells contribute their cached ``<v>`` value (a ``data_only``
    read); the flag records that they were formulas. Shared strings,
    inline strings, booleans, errors and numbers are decoded; merged ranges
    are not propagated (the selectors below match labels in place).
    """
    if len(raw) > MAX_WORKBOOK_BYTES:
        raise VaMmwrError("workbook exceeds the 25 MB adapter limit")
    if raw[:4] != b"PK\x03\x04":
        raise VaMmwrError("response is not an OOXML workbook (no ZIP signature)")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (OSError, zipfile.BadZipFile) as exc:
        raise VaMmwrError(f"workbook parse failed: {exc}") from exc
    with archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(set(names)):
            raise VaMmwrError("workbook contains duplicate ZIP members")
        if any(member.flag_bits & 0x1 for member in members):
            raise VaMmwrError("workbook contains encrypted ZIP members")
        for name in names:
            member_path = pathlib.PurePosixPath(name)
            if "\\" in name or member_path.is_absolute() or ".." in member_path.parts:
                raise VaMmwrError(
                    f"workbook contains an unsafe ZIP member path: {name!r}"
                )
        workbook = _member_xml(archive, "xl/workbook.xml")
        relationships = _member_xml(archive, "xl/_rels/workbook.xml.rels")
        sheets = [
            sheet
            for sheet in workbook.iter()
            if _local_name(sheet.tag) == "sheet"
            and normalized_text(sheet.attrib.get("name", "")) == sheet_name
        ]
        if len(sheets) != 1:
            raise VaMmwrError(
                f"expected exactly one {sheet_name!r} sheet, found {len(sheets)}"
            )
        relationship_id = next(
            (
                value
                for key, value in sheets[0].attrib.items()
                if _local_name(key) == "id"
            ),
            None,
        )
        relationship = [
            item
            for item in relationships.iter()
            if _local_name(item.tag) == "Relationship"
            and item.attrib.get("Id") == relationship_id
        ]
        if len(relationship) != 1:
            raise VaMmwrError(
                f"{sheet_name!r} sheet relationship is missing or ambiguous"
            )
        if relationship[0].attrib.get("TargetMode") == "External":
            raise VaMmwrError(f"{sheet_name!r} sheet relationship is external")
        target = relationship[0].attrib.get("Target", "")
        sheet_path = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("xl", target))
        )
        if sheet_path.startswith("../") or not sheet_path.startswith("xl/"):
            raise VaMmwrError(f"{sheet_name!r} sheet relationship leaves xl/")
        worksheet = _member_xml(archive, sheet_path)
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for item in _member_xml(archive, "xl/sharedStrings.xml").iter():
                if _local_name(item.tag) == "si":
                    shared_strings.append(
                        "".join(
                            node.text or ""
                            for node in item.iter()
                            if _local_name(node.tag) == "t"
                        )
                    )
        cells: dict[tuple[int, int], SheetCell] = {}
        for cell in worksheet.iter():
            if _local_name(cell.tag) != "c":
                continue
            reference = cell.attrib.get("r", "")
            key = _cell_coordinates(reference)
            if key[0] >= 100_000 or key[1] >= 1_024:
                raise VaMmwrError(
                    f"{sheet_name!r} sheet dimensions exceed adapter limits"
                )
            if key in cells:
                raise VaMmwrError(f"duplicate XLSX cell reference {reference!r}")
            formula = any(_local_name(node.tag) == "f" for node in cell)
            value_node = next(
                (node for node in cell if _local_name(node.tag) == "v"), None
            )
            cell_type = cell.attrib.get("t")
            text = value_node.text if value_node is not None else None
            try:
                if cell_type == "s":
                    value: object = shared_strings[int(str(text))]
                elif cell_type == "inlineStr":
                    value = "".join(
                        node.text or ""
                        for node in cell.iter()
                        if _local_name(node.tag) == "t"
                    )
                elif cell_type in {"str", "e"}:
                    value = text or ""
                elif cell_type == "b":
                    value = text == "1"
                elif text in {None, ""}:
                    continue
                else:
                    value = float(text)
            except (IndexError, TypeError, ValueError) as exc:
                raise VaMmwrError(
                    f"invalid value in XLSX cell {reference!r}: {exc}"
                ) from exc
            if isinstance(value, str) and not value.strip():
                continue
            cells[key] = SheetCell(value=value, formula=formula)
    if not cells:
        raise VaMmwrError(f"{sheet_name!r} sheet has no cells")
    return cells


@dataclass(frozen=True)
class RatingBundleReading:
    pending: int
    pending_over_125: int
    pct_over_125: float
    reporting_through: dt.date
    cell: str
    sheet: str = SHEET_NAME


def _find_cells(
    cells: dict[tuple[int, int], SheetCell], text: str
) -> list[tuple[int, int]]:
    wanted = normalized_text(text)
    return sorted(
        key
        for key, cell in cells.items()
        if isinstance(cell.value, str) and normalized_text(cell.value) == wanted
    )


def _one(cells: dict[tuple[int, int], SheetCell], text: str) -> tuple[int, int]:
    found = _find_cells(cells, text)
    if len(found) != 1:
        raise VaMmwrError(f"expected exactly one {text!r} cell, found {len(found)}")
    return found[0]


def _reference(row: int, column: int) -> str:
    letters = ""
    column += 1
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"{letters}{row + 1}"


def parse_reporting_through(text: str) -> dt.date:
    match = REPORTING_THROUGH.match(normalized_text(text))
    if not match:
        raise VaMmwrError(f"not a 'Reporting through' cell: {text!r}")
    month_name, day, year = re.fullmatch(
        r"([A-Za-z]+) (\d{1,2}), (\d{4})", match.group("date")
    ).groups()
    month = MONTHS.get(month_name)
    if month is None:
        raise VaMmwrError(f"unknown month in {text!r}")
    try:
        return dt.date(int(year), month, int(day))
    except ValueError as exc:
        raise VaMmwrError(f"invalid date in {text!r}") from exc


def rating_bundle_pending(
    cells: dict[tuple[int, int], SheetCell], *, expected_through: dt.date
) -> RatingBundleReading:
    """The national Compensation and Pension Rating Bundle ``# Pending`` count.

    Layout authenticated by labels, not positions: the section title, the
    ``Reporting through`` identity cell (must equal the workbook's
    data-through date), the ``# Pending`` / ``# Pending > 125`` /
    ``% Pending > 125 days`` header cells on one row, and the
    ``Compensation and Pension Rating Bundle`` row whose ``Total`` marker sits
    on the same row. The cached percent must reproduce the cached counts.
    """
    title_key = _one(cells, SECTION_TITLE)
    through_cells = [
        (key, cell)
        for key, cell in cells.items()
        if isinstance(cell.value, str)
        and REPORTING_THROUGH.match(normalized_text(cell.value))
    ]
    if len(through_cells) != 1:
        raise VaMmwrError(
            f"expected exactly one 'Reporting through' cell, found {len(through_cells)}"
        )
    through = parse_reporting_through(str(through_cells[0][1].value))
    if through != expected_through:
        raise VaMmwrError(
            f"workbook reports through {through}, not the expected {expected_through}"
        )
    pending_key = _one(cells, PENDING_HEADER)
    over_key = _one(cells, PENDING_OVER_125_HEADER)
    pct_key = _one(cells, PCT_OVER_125_HEADER)
    header_row = pending_key[0]
    if over_key[0] != header_row or pct_key[0] != header_row:
        raise VaMmwrError("rating-bundle header cells are not on one row")
    if header_row <= title_key[0]:
        raise VaMmwrError("rating-bundle headers precede the section title")
    label_keys = [
        key
        for key in _find_cells(cells, ROW_LABEL)
        if key[0] > header_row
        and any(
            marker_key[0] == key[0] and marker_key[1] > key[1]
            for marker_key in _find_cells(cells, ROW_MARKER)
        )
    ]
    if len(label_keys) != 1:
        raise VaMmwrError(
            f"expected exactly one {ROW_LABEL!r} row with a {ROW_MARKER!r} marker "
            f"below the headers, found {len(label_keys)}"
        )
    row = label_keys[0][0]

    def number(column: int, what: str) -> float:
        cell = cells.get((row, column))
        if cell is None or not isinstance(cell.value, float):
            raise VaMmwrError(f"{what} cell {_reference(row, column)} is not numeric")
        return cell.value

    pending = number(pending_key[1], PENDING_HEADER)
    over = number(over_key[1], PENDING_OVER_125_HEADER)
    pct = number(pct_key[1], PCT_OVER_125_HEADER)
    if pending != int(pending) or over != int(over) or pending <= 0:
        raise VaMmwrError(
            f"rating-bundle counts are not positive integers: {pending}, {over}"
        )
    if abs(over / pending - pct) > 1e-9:
        raise VaMmwrError(
            f"cached percent {pct} does not reproduce {over}/{pending}; "
            "wrong row or columns"
        )
    return RatingBundleReading(
        pending=int(pending),
        pending_over_125=int(over),
        pct_over_125=pct,
        reporting_through=through,
        cell=_reference(row, pending_key[1]),
    )


def read_rating_bundle_pending(
    raw: bytes, *, expected_through: dt.date
) -> RatingBundleReading:
    return rating_bundle_pending(sheet_cells(raw), expected_through=expected_through)
