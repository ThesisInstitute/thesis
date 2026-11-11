#!/usr/bin/env python3
"""Parse SSA's official statistical HTML tables and OHO XML datasets.

Pure standard library. Used by ``scripts/resolve_pending.py`` for the SSA
family (SSI Monthly Statistics Tables 1/2/4, the Monthly Statistical
Snapshot, and the Office of Hearings Operations workload XML) and by its
tests. Every selector is label-anchored — never a hard-coded cell position —
and every reader fails closed on ambiguity: zero or several matches, a
non-integer where a whole count is expected, a page whose ``<title>`` names
a different edition, or an arithmetic identity (row or column parts that
must sum to a published total) that does not hold.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Callable
from xml.etree import ElementTree as ET

MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}


class SsaPageError(ValueError):
    """The page exists but cannot be read without guessing."""


# ---------------------------------------------------------------------------
# Generic HTML table model


def normalized_text(value: str) -> str:
    """Collapse whitespace, decode entities, unify dashes, strip."""
    text = unescape(value).replace("\xa0", " ")
    text = text.replace("–", "-").replace("—", "-").replace("‑", "-")
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class TableCell:
    tag: str
    text: str = ""
    id: str = ""
    headers: tuple[str, ...] = ()
    colspan: int = 1
    rowspan: int = 1
    _parts: list[str] = field(default_factory=list, repr=False)

    def finish(self) -> None:
        self.text = normalized_text("".join(self._parts))


@dataclass
class HtmlTable:
    caption: str = ""
    rows: list[list[TableCell]] = field(default_factory=list)
    _caption_parts: list[str] = field(default_factory=list, repr=False)

    def header_cells(self) -> dict[str, TableCell]:
        out: dict[str, TableCell] = {}
        for row in self.rows:
            for cell in row:
                if cell.tag == "th" and cell.id:
                    if cell.id in out:
                        raise SsaPageError(f"duplicate header id {cell.id!r}")
                    out[cell.id] = cell
        return out


class _TablesParser(HTMLParser):
    """Collect every <table> in document order with caption and cells.

    Footnote markers inside ``<sup>`` are dropped from cell text (the raw
    label ``Blind and disabled <sup>a</sup>`` reads as ``Blind and
    disabled``); everything else nested in a cell concatenates.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[HtmlTable] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._title_seen = False
        self._table_stack: list[HtmlTable] = []
        self._row: list[TableCell] | None = None
        self._cell: TableCell | None = None
        self._sup_depth = 0
        self._in_caption = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: (value or "") for name, value in attrs}
        if tag == "title" and not self._title_seen:
            # Only the document title counts; inline SVG icons carry their
            # own <title> elements ("Search") further down the page.
            self._in_title = True
            self._title_seen = True
        elif tag == "table":
            table = HtmlTable()
            self._table_stack.append(table)
            self.tables.append(table)
        elif tag == "caption" and self._table_stack:
            self._in_caption = True
        elif tag == "tr" and self._table_stack:
            self._row = []
            self._table_stack[-1].rows.append(self._row)
        elif tag in {"td", "th"} and self._row is not None:
            headers = tuple(
                token for token in attributes.get("headers", "").split() if token
            )
            self._cell = TableCell(
                tag=tag,
                id=attributes.get("id", ""),
                headers=headers,
                colspan=_span(attributes.get("colspan")),
                rowspan=_span(attributes.get("rowspan")),
            )
            self._row.append(self._cell)
        elif tag == "sup" and self._cell is not None:
            self._sup_depth += 1
        elif tag == "br" and self._cell is not None:
            self._cell._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in {"td", "th"} and self._cell is not None:
            self._cell.finish()
            self._cell = None
            self._sup_depth = 0
        elif tag == "tr":
            if self._cell is not None:
                self._cell.finish()
                self._cell = None
            self._row = None
        elif tag == "caption" and self._table_stack:
            self._in_caption = False
            table = self._table_stack[-1]
            table.caption = normalized_text("".join(table._caption_parts))
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()
            self._row = None
            self._cell = None
        elif tag == "sup" and self._sup_depth:
            self._sup_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_caption and self._table_stack:
            self._table_stack[-1]._caption_parts.append(data)
        if self._cell is not None and not self._sup_depth:
            self._cell._parts.append(data)


def _span(value: str | None) -> int:
    try:
        span = int(str(value or "1"))
    except ValueError:
        return 1
    return span if span >= 1 else 1


@dataclass
class ParsedPage:
    title: str
    tables: list[HtmlTable]


def parse_page(raw: bytes | str) -> ParsedPage:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    parser = _TablesParser()
    parser.feed(text)
    parser.close()
    return ParsedPage(
        title=normalized_text("".join(parser.title_parts)), tables=parser.tables
    )


def parse_whole_count(text: str) -> int:
    """``7,323,731`` -> 7323731; anything else is a refusal."""
    cleaned = normalized_text(text)
    if not re.fullmatch(r"\d{1,3}(,\d{3})*|\d+", cleaned):
        raise SsaPageError(f"expected a whole count, found {cleaned!r}")
    return int(cleaned.replace(",", ""))


def period_label(period: str) -> str:
    """``2026-06`` -> ``June 2026``."""
    match = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise SsaPageError(f"period must be YYYY-MM, got {period!r}")
    return f"{MONTH_NAMES[int(match.group(2))]} {match.group(1)}"


def select_table(page: ParsedPage, *, caption_prefix: str) -> HtmlTable:
    matches = [
        table
        for table in page.tables
        if table.caption.startswith(normalized_text(caption_prefix))
    ]
    if len(matches) != 1:
        raise SsaPageError(
            f"expected exactly one table captioned {caption_prefix!r}, found "
            f"{len(matches)} (captions: {[t.caption for t in page.tables]!r})"
        )
    return matches[0]


def cell_by_header_labels(
    table: HtmlTable, *, labels: list[str]
) -> tuple[TableCell, dict[str, tuple[str, ...]]]:
    """The one TD whose ``headers`` reach a TH for every label.

    ``labels`` are normalized TH texts (footnote markers already dropped).
    Each label may be carried by several ids (``Total`` repeats per panel);
    a data cell qualifies when, for every label, at least one of that
    label's ids is among the cell's ``headers``. Exactly one cell may
    qualify.
    """
    by_id = table.header_cells()
    ids_by_label: dict[str, tuple[str, ...]] = {}
    for label in labels:
        wanted = normalized_text(label)
        ids = tuple(cell_id for cell_id, cell in by_id.items() if cell.text == wanted)
        if not ids:
            raise SsaPageError(
                f"no header cell reads {label!r} (headers: "
                f"{sorted(c.text for c in by_id.values())!r})"
            )
        ids_by_label[label] = ids
    matches: list[TableCell] = []
    for row in table.rows:
        for cell in row:
            if cell.tag != "td":
                continue
            headers = set(cell.headers)
            if all(headers.intersection(ids) for ids in ids_by_label.values()):
                matches.append(cell)
    if len(matches) != 1:
        raise SsaPageError(
            f"expected exactly one data cell under {labels!r}, found {len(matches)}"
        )
    return matches[0], ids_by_label


def count_by_header_labels(table: HtmlTable, *, labels: list[str]) -> int:
    cell, _ = cell_by_header_labels(table, labels=labels)
    return parse_whole_count(cell.text)


def leaf_columns(table: HtmlTable, *, header_rows: int = 2) -> list[tuple[str, ...]]:
    """Flatten a two-level header into leaf column paths, stub column first.

    Handles ``rowspan``/``colspan`` the way SSA's tables use them: a top
    header with ``rowspan=2`` is its own leaf; a top header with
    ``colspan=n`` owns the next ``n`` second-row headers.
    """
    if len(table.rows) < header_rows:
        raise SsaPageError("table has fewer header rows than expected")
    top, second = table.rows[0], table.rows[1]
    if any(cell.tag != "th" for cell in top + second):
        raise SsaPageError("header rows contain non-header cells")
    leaves: list[tuple[str, ...]] = []
    second_index = 0
    for cell in top:
        if cell.rowspan >= header_rows:
            leaves.append((cell.text,))
            continue
        for _ in range(cell.colspan):
            if second_index >= len(second):
                raise SsaPageError("second header row shorter than colspans imply")
            leaves.append((cell.text, second[second_index].text))
            second_index += 1
    if second_index != len(second):
        raise SsaPageError("second header row longer than colspans imply")
    return leaves


def row_values_by_stub(
    table: HtmlTable,
    *,
    stub: str,
    group: str | None = None,
    header_rows: int = 2,
) -> tuple[dict[tuple[str, ...], str], list[tuple[str, ...]]]:
    """Map leaf column path -> cell text for the body row labelled ``stub``.

    With ``group`` (SSI Table 2's year rows), the stub is searched only
    after the row whose stub equals ``group`` and before the next group
    row. The stub (and group) must match exactly one row.
    """
    leaves = leaf_columns(table, header_rows=header_rows)
    body = table.rows[header_rows:]
    wanted_stub = normalized_text(stub)
    wanted_group = normalized_text(group) if group is not None else None
    candidates: list[list[TableCell]] = []
    in_group = wanted_group is None
    seen_group = 0
    for row in body:
        if not row or row[0].tag != "th":
            continue
        label = row[0].text
        is_group_row = len(row) >= 2 and row[1].colspan > 1 and row[1].text == ""
        if wanted_group is not None and is_group_row:
            if label == wanted_group:
                seen_group += 1
                in_group = True
            else:
                in_group = False
            continue
        if in_group and label == wanted_stub:
            candidates.append(row)
    if wanted_group is not None and seen_group != 1:
        raise SsaPageError(
            f"expected exactly one group row {group!r}, found {seen_group}"
        )
    if len(candidates) != 1:
        raise SsaPageError(
            f"expected exactly one row labelled {stub!r}, found {len(candidates)}"
        )
    row = candidates[0]
    data_cells = row[1:]
    data_leaves = leaves[1:]
    if len(data_cells) != len(data_leaves):
        raise SsaPageError(
            f"row {stub!r} has {len(data_cells)} data cells for "
            f"{len(data_leaves)} leaf columns"
        )
    return {leaf: cell.text for leaf, cell in zip(data_leaves, data_cells)}, leaves


def require_identity(
    label: str,
    total: int,
    parts: list[int],
    *,
    tolerance: int = 0,
) -> None:
    if abs(total - sum(parts)) > tolerance:
        raise SsaPageError(
            f"identity {label} failed: total {total} vs parts {parts} "
            f"(sum {sum(parts)}, tolerance {tolerance})"
        )


def require_title(page: ParsedPage, expected: str) -> None:
    if page.title != normalized_text(expected):
        raise SsaPageError(
            f"page title {page.title!r} is not the expected {expected!r}"
        )


# ---------------------------------------------------------------------------
# SSI Monthly Statistics, All Federally Administered Payments


@dataclass(frozen=True)
class SsaTableReading:
    value: int
    row: str
    column: str
    table_caption: str
    identities: tuple[str, ...]


def ssi_table1_count(
    raw: bytes, period: str, *, row: str, column: str
) -> SsaTableReading:
    """Table 1 (``table01.html``): ``Number of recipients`` panel, one cell.

    ``row`` is the stub (``Total``, ``Federal payment only``, ...) and
    ``column`` a leaf column (``All recipients``, ``Aged``, ``Blind and
    disabled``, ``Under 18``, ``18-64``, ``65 or older``).
    """
    page = parse_page(raw)
    label = period_label(period)
    require_title(page, f"SSI Monthly Statistics, {label} - Table 1")
    table = select_table(page, caption_prefix="Table 1.")
    if not table.caption.endswith(label):
        raise SsaPageError(f"Table 1 caption {table.caption!r} is not for {label}")
    panel = "Number of recipients"
    value = count_by_header_labels(table, labels=[panel, row, column])
    all_recipients = count_by_header_labels(
        table, labels=[panel, row, "All recipients"]
    )
    by_age = [
        count_by_header_labels(table, labels=[panel, row, age])
        for age in ("Under 18", "18-64", "65 or older")
    ]
    by_category = [
        count_by_header_labels(table, labels=[panel, row, category])
        for category in ("Aged", "Blind and disabled")
    ]
    require_identity(
        f"{row}: age columns sum to All recipients", all_recipients, by_age
    )
    require_identity(
        f"{row}: eligibility columns sum to All recipients", all_recipients, by_category
    )
    return SsaTableReading(
        value=value,
        row=row,
        column=column,
        table_caption=table.caption,
        identities=(
            f"{row}: Under 18 + 18-64 + 65 or older = {all_recipients}",
            f"{row}: Aged + Blind and disabled = {all_recipients}",
        ),
    )


def ssi_table4_count(
    raw: bytes, period: str, *, state: str, column: str
) -> SsaTableReading:
    """Table 4 (``table04.html``): one state row, one leaf column.

    ``column`` is ``Total``, ``Aged``, ``Blind and disabled``, ``Under 18``,
    ``18-64`` or ``65 or older``.
    """
    page = parse_page(raw)
    label = period_label(period)
    require_title(page, f"SSI Monthly Statistics, {label} - Table 4")
    table = select_table(page, caption_prefix="Table 4.")
    if not table.caption.endswith(label):
        raise SsaPageError(f"Table 4 caption {table.caption!r} is not for {label}")
    values, leaves = row_values_by_stub(table, stub=state)
    expected_leaves = [
        ("State or area",),
        ("Total",),
        ("Eligibility category", "Aged"),
        ("Eligibility category", "Blind and disabled"),
        ("Age", "Under 18"),
        ("Age", "18-64"),
        ("Age", "65 or older"),
    ]
    if leaves != expected_leaves:
        raise SsaPageError(f"Table 4 columns restructured: {leaves!r}")

    def count(leaf_label: str) -> int:
        leaf = next(leaf for leaf in expected_leaves[1:] if leaf[-1] == leaf_label)
        return parse_whole_count(values[leaf])

    if column not in {leaf[-1] for leaf in expected_leaves[1:]}:
        raise SsaPageError(f"unknown Table 4 column {column!r}")
    total = count("Total")
    require_identity(
        f"{state}: age columns sum to Total",
        total,
        [count("Under 18"), count("18-64"), count("65 or older")],
    )
    require_identity(
        f"{state}: eligibility columns sum to Total",
        total,
        [count("Aged"), count("Blind and disabled")],
    )
    return SsaTableReading(
        value=count(column),
        row=state,
        column=column,
        table_caption=table.caption,
        identities=(
            f"{state}: Under 18 + 18-64 + 65 or older = {total}",
            f"{state}: Aged + Blind and disabled = {total}",
        ),
    )


def ssi_table2_total_recipients(raw: bytes, period: str) -> SsaTableReading:
    """Table 2 (``table02.html``): the target month's ``Total`` recipients.

    The edition's own month is the last row of the time series; the page
    must be that edition (title and caption end with the period).
    """
    page = parse_page(raw)
    label = period_label(period)
    year, month_name = label.split(" ")[1], label.split(" ")[0]
    require_title(page, f"SSI Monthly Statistics, {label} - Table 2")
    table = select_table(page, caption_prefix="Table 2.")
    if not table.caption.endswith(label):
        raise SsaPageError(f"Table 2 caption {table.caption!r} is not for {label}")
    values, leaves = row_values_by_stub(table, stub=month_name, group=year)
    expected_leaves = [
        ("Month",),
        ("Number of recipients", "Total"),
        ("Number of recipients", "Federal payment only"),
        ("Number of recipients", "Federal payment and state supplementation"),
        ("Number of recipients", "State supplementation only"),
        ("Total payments (thousands of dollars)",),
        ("Average monthly payment (dollars)",),
    ]
    if leaves != expected_leaves:
        raise SsaPageError(f"Table 2 columns restructured: {leaves!r}")
    total = parse_whole_count(values[expected_leaves[1]])
    parts = [parse_whole_count(values[leaf]) for leaf in expected_leaves[2:5]]
    require_identity(f"{label}: payment types sum to Total", total, parts)
    return SsaTableReading(
        value=total,
        row=label,
        column="Total",
        table_caption=table.caption,
        identities=(
            f"{label}: Federal only + Federal and state + State only = {total}",
        ),
    )


# ---------------------------------------------------------------------------
# Monthly Statistical Snapshot


def stub_row(table: HtmlTable, stub: str) -> list[TableCell]:
    """The one body row whose first cell is a TH reading ``stub``."""
    wanted = normalized_text(stub)
    rows = [
        row
        for row in table.rows
        if row and row[0].tag == "th" and row[0].text == wanted
    ]
    if len(rows) != 1:
        raise SsaPageError(
            f"expected exactly one row stubbed {stub!r}, found {len(rows)}"
        )
    return rows[0]


def cell_in_row_under(
    table: HtmlTable, row: list[TableCell], column_label: str
) -> TableCell:
    """The one TD in ``row`` whose ``headers`` reach a TH reading ``column_label``."""
    by_id = table.header_cells()
    wanted = normalized_text(column_label)
    ids = {cell_id for cell_id, cell in by_id.items() if cell.text == wanted}
    if not ids:
        raise SsaPageError(f"no header cell reads {column_label!r}")
    matches = [
        cell for cell in row if cell.tag == "td" and ids.intersection(cell.headers)
    ]
    if len(matches) != 1:
        raise SsaPageError(
            f"expected exactly one cell under {column_label!r} in row "
            f"{row[0].text!r}, found {len(matches)}"
        )
    return matches[0]


def snapshot_table2_thousands(
    raw: bytes, period: str, *, group: str, row: str
) -> SsaTableReading:
    """Monthly Statistical Snapshot Table 2, ``Number (thousands)`` column.

    ``group`` is the benefit program row (``Disability Insurance``), ``row``
    the beneficiary type under it (``Disabled workers``). The row must sit
    under the group (its stub header references the group's id), the program
    total must equal its component rows within rounding of published
    thousands, and OASI + DI must reproduce the table total.
    """
    page = parse_page(raw)
    label = period_label(period)
    require_title(page, f"Monthly Statistical Snapshot, {label}")
    table = select_table(page, caption_prefix="Table 2.")
    if not table.caption.endswith(label):
        raise SsaPageError(f"Table 2 caption {table.caption!r} is not for {label}")
    column = "Number (thousands)"
    group_row = stub_row(table, group)
    group_id = group_row[0].id
    if not group_id:
        raise SsaPageError(f"{group!r} row header carries no id")
    target_row = stub_row(table, row)
    if group_id not in target_row[0].headers:
        raise SsaPageError(f"{row!r} is not a component of {group!r}")
    value = parse_whole_count(cell_in_row_under(table, target_row, column).text)
    group_total = parse_whole_count(cell_in_row_under(table, group_row, column).text)
    component_rows = [
        body_row
        for body_row in table.rows
        if body_row and body_row[0].tag == "th" and group_id in body_row[0].headers
    ]
    component_names = [body_row[0].text for body_row in component_rows]
    if row not in component_names or len(component_rows) < 2:
        raise SsaPageError(
            f"{row!r} is not among {group!r} component rows {component_names!r}"
        )
    components = [
        parse_whole_count(cell_in_row_under(table, body_row, column).text)
        for body_row in component_rows
    ]
    # Published thousands are individually rounded; allow one unit per part.
    require_identity(
        f"{group}: component rows sum to program total",
        group_total,
        components,
        tolerance=len(components),
    )
    overall = parse_whole_count(
        cell_in_row_under(table, stub_row(table, "Total"), column).text
    )
    programs = [
        parse_whole_count(cell_in_row_under(table, stub_row(table, name), column).text)
        for name in ("Old-Age and Survivors Insurance", "Disability Insurance")
    ]
    require_identity("OASI + DI = Total beneficiaries", overall, programs, tolerance=2)
    return SsaTableReading(
        value=value,
        row=f"{group} / {row}",
        column=column,
        table_caption=table.caption,
        identities=(
            f"{group}: {' + '.join(component_names)} = {group_total} "
            f"(±{len(components)})",
            f"OASI + DI = {overall} (±2)",
        ),
    )


# ---------------------------------------------------------------------------
# Office of Hearings Operations public data XML


@dataclass(frozen=True)
class OhoWorkloadFile:
    created: str
    reporting_period_end: dt.date
    rows: tuple[dict[str, str], ...]


def oho_workload_file(raw: bytes) -> OhoWorkloadFile:
    """Read ``02_HO_Workload_Data.xml`` into rows keyed by element name."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SsaPageError(f"OHO XML did not parse: {exc}") from exc
    if root.tag != "data":
        raise SsaPageError(f"OHO XML root is {root.tag!r}, not 'data'")
    title = normalized_text(root.findtext("title") or "")
    if title != "Hearing Office Workload Data":
        raise SsaPageError(f"OHO XML title {title!r} is not the workload dataset")
    period_text = normalized_text(root.findtext("RPTG_PRD_ENDT") or "")
    try:
        period_end = dt.datetime.strptime(period_text, "%m/%d/%Y").date()
    except ValueError as exc:
        raise SsaPageError(f"OHO XML RPTG_PRD_ENDT {period_text!r} unreadable") from exc
    rows: list[dict[str, str]] = []
    for element in root.findall("row"):
        row = {child.tag: normalized_text(child.text or "") for child in element}
        if row.get("RPTG_PRD_ENDT") != period_text:
            raise SsaPageError(
                f"row period {row.get('RPTG_PRD_ENDT')!r} differs from file period"
            )
        rows.append(row)
    declared = root.attrib.get("records")
    if declared is not None and declared != str(len(rows)):
        raise SsaPageError(
            f"OHO XML declares {declared} records but carries {len(rows)} rows"
        )
    if not rows:
        raise SsaPageError("OHO XML carries no rows")
    return OhoWorkloadFile(
        created=normalized_text(root.attrib.get("created", "")),
        reporting_period_end=period_end,
        rows=tuple(rows),
    )


NATIONAL_ROW_PATTERN = re.compile(
    r"^(NATIONAL|NATION|ALL OFFICES|US TOTAL|TOTAL)\b", re.I
)


def oho_national_average_processing_time(
    workload: OhoWorkloadFile,
) -> tuple[int | None, str]:
    """The published national average processing time, if the file has one.

    The dataset is per hearing office; the national aggregate is not a
    published field (verified 2026-08-23 against the live file and its
    2026-06-24/2026-08-02 Wayback captures — 165-166 office rows, no
    national row, and the data dictionary defines ``DSPN_AVGPT`` only per
    office). A disposition-weighted mean of office rows would be a derived
    statistic the cell's resolver never defined, so it is never computed.
    """
    national = [
        row
        for row in workload.rows
        if NATIONAL_ROW_PATTERN.match(row.get("OFFICE", ""))
        and "NATL ADJUDICATION" not in row.get("OFFICE", "").upper()
    ]
    if len(national) > 1:
        raise SsaPageError(
            f"several national-looking rows: {[r.get('OFFICE') for r in national]!r}"
        )
    if not national:
        return None, (
            "the workload XML (RPTG_PRD_ENDT "
            f"{workload.reporting_period_end:%m/%d/%Y}, "
            f"{len(workload.rows)} hearing-office rows) publishes no national "
            "aggregate row; SSA's data dictionary defines DSPN_AVGPT per hearing "
            "office only"
        )
    try:
        return int(national[0]["AVERAGE_PROCESSING_TIME"]), "national row present"
    except (KeyError, ValueError) as exc:
        raise SsaPageError(f"national row lacks an integer APT: {exc}") from exc


# ---------------------------------------------------------------------------
# Wayback Machine corroboration

CDX_URL = (
    "https://web.archive.org/cdx/search/cdx?url={url}&output=json"
    "&fl=timestamp,statuscode,digest,length&filter=statuscode:200"
)
WAYBACK_RAW_URL = "https://web.archive.org/web/{timestamp}id_/{url}"

Fetcher = Callable[[str], bytes]


def wayback_cdx_url(url: str) -> str:
    stripped = re.sub(r"^https?://", "", url)
    return CDX_URL.format(url=urllib.parse.quote(stripped, safe="/:?=&%"))


def wayback_captures(url: str, fetch: Fetcher) -> list[dict[str, str]]:
    """Successful (HTTP 200) captures of ``url``, oldest first."""
    raw = fetch(wayback_cdx_url(url))
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SsaPageError(f"CDX response unreadable: {exc}") from exc
    if not isinstance(payload, list):
        raise SsaPageError("CDX response is not a list")
    if not payload:
        return []
    header, *rows = payload
    captures = []
    for row in rows:
        record = dict(zip(header, row))
        if record.get("statuscode") == "200" and re.fullmatch(
            r"\d{14}", str(record.get("timestamp", ""))
        ):
            captures.append({key: str(value) for key, value in record.items()})
    return sorted(captures, key=lambda record: record["timestamp"])


def wayback_raw_url(timestamp: str, url: str) -> str:
    if not re.fullmatch(r"\d{14}", timestamp):
        raise SsaPageError(f"invalid Wayback timestamp {timestamp!r}")
    return WAYBACK_RAW_URL.format(timestamp=timestamp, url=url)


def wayback_capture_body(timestamp: str, url: str, fetch: Fetcher) -> bytes:
    """Original bytes of one capture; gzip transfer bodies are decompressed."""
    raw = fetch(wayback_raw_url(timestamp, url))
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def wayback_timestamp_to_iso(timestamp: str) -> str:
    return dt.datetime.strptime(timestamp, "%Y%m%d%H%M%S").strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


__all__: list[str] = [
    name
    for name, value in globals().items()
    if not name.startswith("_") and callable(value) or name.isupper()
]


def _selftest(argv: list[str]) -> int:  # pragma: no cover - manual helper
    """``python ssa_official_pages.py table01.html 2026-06`` prints a reading."""
    path, period = argv[0], argv[1]
    raw = open(path, "rb").read()
    if "table01" in path:
        print(ssi_table1_count(raw, period, row="Total", column="65 or older"))
    elif "table04" in path:
        print(ssi_table4_count(raw, period, state="Colorado", column="Total"))
        print(ssi_table4_count(raw, period, state="Colorado", column="65 or older"))
    elif "table02" in path:
        print(ssi_table2_total_recipients(raw, period))
    elif "stat_snapshot" in path:
        print(
            snapshot_table2_thousands(
                raw, period, group="Disability Insurance", row="Disabled workers"
            )
        )
    else:
        workload = oho_workload_file(raw)
        print(workload.created, workload.reporting_period_end, len(workload.rows))
        print(oho_national_average_processing_time(workload))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(_selftest(sys.argv[1:]))
