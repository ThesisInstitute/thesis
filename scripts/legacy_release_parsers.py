"""Fail-closed parsers for the reviewed legacy BLS release contracts.

Each cell is pinned from its forecast's own question (QUESTIONS below,
quoted from site/src/data/forecast-examples and tied to it by a test), not
inferred from a series id. Layout reference (never a target release): the
real non-target Archive captures in tests/fixtures/release_capture/, namely
the June 2026 CPI summary, the July 2026 Employment Situation summary, and
the June 2026 JOLTS summary and Table 4.

Two page shapes occur. The CPI summary (cpi.nr0.htm) and JOLTS Table 4
(jolts.t04.htm) print HTML tables, read by SPECS below. The Employment
Situation and JOLTS summaries (empsit.nr0.htm, jolts.nr0.htm) print no
table at all: the release is one preformatted block of prose, and the
figure is read from the sentences that state it (PROSE_PARSERS).

These parsers return the number printed by the page. Registered transforms
belong to the caller.
"""

from __future__ import annotations

import html as html_lib
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser

# The forecast question each reviewed reference answers, verbatim, and the
# parser that reads the one cell it names (dataPointId -> (parser, question)).
QUESTIONS: dict[str, tuple[str, str]] = {
    "bls.ces.total_nonfarm.payroll_employment.change.sa.2026-08.first_print": (
        "empsit_payroll_change",
        (
            "What will the U.S. Bureau of Labor Statistics report as the "
            "first-print seasonally adjusted month-over-month change in total "
            "nonfarm payroll employment for August 2026, in thousands?"
        ),
    ),
    "bls.ces.total_nonfarm.payroll_employment.change.sa.2026-09.first_print": (
        "empsit_payroll_change",
        (
            "What will the BLS first-print seasonally adjusted change in total "
            "nonfarm payroll employment be for September 2026?"
        ),
    ),
    "bls.cpi.u.core_mom.august_2026.first_print": (
        "cpi_core_mom",
        (
            "What will the BLS first print report for seasonally adjusted CPI-U "
            "all items less food and energy month-over-month percent change in "
            "August 2026?"
        ),
    ),
    "bls.cpi.u.core_mom.september_2026.first_print": (
        "cpi_core_mom",
        (
            "What will the U.S. Bureau of Labor Statistics report as the "
            "September 2026 seasonally adjusted 1-month percent change in CPI-U "
            "all items less food and energy in the first CPI news release?"
        ),
    ),
    "bls.cpi.u.headline_mom.august_2026.first_print": (
        "cpi_headline_mom",
        (
            "What will the BLS first print for the seasonally adjusted "
            "month-over-month percent change in U.S. CPI-U all items, U.S. city "
            "average, for August 2026?"
        ),
    ),
    "bls.cpi.u.headline_mom.september_2026.first_print": (
        "cpi_headline_mom",
        (
            "What will the U.S. Bureau of Labor Statistics first print report "
            "for CPI-U all items, U.S. city average, seasonally adjusted "
            "month-over-month percent change for September 2026?"
        ),
    ),
    "bls.cps.unemployment_rate.august_2026.first_print": (
        "empsit_unemployment_rate",
        (
            "What will the BLS Current Population Survey U-3 unemployment rate, "
            "seasonally adjusted, be for August 2026 in the first Employment "
            "Situation print?"
        ),
    ),
    "bls.cps.unemployment_rate.september_2026.first_print": (
        "empsit_unemployment_rate",
        (
            "What will the U.S. Bureau of Labor Statistics report as the "
            "seasonally adjusted civilian unemployment rate for September 2026 "
            "in the Current Population Survey, first print?"
        ),
    ),
    "bls.jolts.job_openings.august_2026.first_print": (
        "jolts_job_openings",
        (
            "What will the U.S. Bureau of Labor Statistics first report for "
            "seasonally adjusted total nonfarm job openings in the Job Openings "
            "and Labor Turnover Survey for August 2026, in millions?"
        ),
    ),
    "bls.jolts.job_openings.july_2026.first_print": (
        "jolts_job_openings",
        (
            "What will BLS first report for total nonfarm job openings, "
            "seasonally adjusted, in the July 2026 Job Openings and Labor "
            "Turnover Survey release?"
        ),
    ),
    "bls.jolts.quits_rate.2026-07.first_print": (
        "jolts_quits_rate",
        (
            "BLS Job Openings and Labor Turnover Survey Table 4 total quits "
            "rate, seasonally adjusted, July 2026, first print"
        ),
    ),
    "bls.jolts.quits_rate.2026-08.first_print": (
        "jolts_quits_rate",
        (
            "What will the U.S. Bureau of Labor Statistics JOLTS Table 4 "
            "seasonally adjusted Total nonfarm quits rate be for August 2026 in "
            "the first print?"
        ),
    ),
}

# A distinct, human-readable label per parser for the facts it produces.
LABELS = {
    "cpi_headline_mom": (
        "US CPI-U all items, seasonally adjusted, 1-month percent change"
    ),
    "cpi_core_mom": (
        "US CPI-U all items less food and energy, "
        "seasonally adjusted, 1-month percent change"
    ),
    "empsit_unemployment_rate": "US unemployment rate (CPS), seasonally adjusted",
    "empsit_payroll_change": (
        "US total nonfarm payroll employment (CES), "
        "seasonally adjusted, over-the-month change"
    ),
    "jolts_job_openings": "US total nonfarm job openings (JOLTS), seasonally adjusted",
    "jolts_quits_rate": "US total nonfarm quits rate (JOLTS), seasonally adjusted",
}

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _text(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


@dataclass
class _Cell:
    tag: str
    attrs: dict[str, str]
    parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return _text(self.parts)


@dataclass
class _Table:
    attrs: dict[str, str]
    caption: list[str] = field(default_factory=list)
    rows: list[list[_Cell]] = field(default_factory=list)
    closed: bool = False
    malformed: bool = False
    in_caption: bool = False
    cell: _Cell | None = None


class _Document(HTMLParser):
    """Keep table boundaries, header spans and unsplit numeric text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self.stack: list[_Table] = []
        self.titles: list[list[str]] = []
        self.in_title = False
        self.malformed = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = [name for name, _ in attrs]
        values = {name: value or "" for name, value in attrs}
        if tag == "title":
            if self.in_title:
                self.malformed = True
            self.in_title = True
            self.titles.append([])
        if tag == "table":
            if self.stack:
                self.stack[-1].malformed = True
            table = _Table(values)
            self.tables.append(table)
            self.stack.append(table)
        if not self.stack:
            return
        table = self.stack[-1]
        if any(
            names.count(name) > 1 for name in ("id", "headers", "rowspan", "colspan")
        ):
            table.malformed = True
        if tag == "caption":
            table.in_caption = True
        elif tag == "tr":
            table.cell = None
            table.rows.append([])
        elif tag in ("td", "th"):
            if not table.rows:
                table.malformed = True
                return
            table.cell = _Cell(tag, values)
            table.rows[-1].append(table.cell)
        elif tag == "br":
            if table.cell is not None:
                table.cell.parts.append(" ")
            elif table.in_caption:
                table.caption.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if not self.stack:
            return
        table = self.stack[-1]
        if tag == "table":
            table.closed = True
            table.cell = None
            self.stack.pop()
        elif tag in ("tr", "td", "th"):
            table.cell = None
        elif tag == "caption":
            table.in_caption = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.titles[-1].append(data)
        if not self.stack:
            return
        table = self.stack[-1]
        if table.cell is not None:
            table.cell.parts.append(data)
        elif table.in_caption:
            table.caption.append(data)
        elif data.strip():
            table.malformed = True


def _period(text: str, preliminary: bool) -> str | None:
    # (p)/(P) occurs on employment/JOLTS month headings, never these data cells.
    if preliminary:
        text = re.sub(r"\s*\(\s*[pP]\s*\)$", "", text)
    match = re.fullmatch(r"([A-Za-z]+)\.?\s+([0-9]{4})", text)
    month = _MONTHS.get(match[1].lower()) if match else None
    return f"{match[2]}-{month:02d}" if month else None


def _grid(table: _Table) -> list[list[_Cell | None]] | None:
    grid: list[list[_Cell | None]] = []
    occupied: dict[tuple[int, int], _Cell] = {}
    for row_index, row in enumerate(table.rows):
        column = 0
        for cell in row:
            while (row_index, column) in occupied:
                column += 1
            row_span = cell.attrs.get("rowspan", "1")
            col_span = cell.attrs.get("colspan", "1")
            if not re.fullmatch(r"[1-9][0-9]?", row_span + ""):
                return None
            if not re.fullmatch(r"[1-9][0-9]?", col_span + ""):
                return None
            height, width = int(row_span), int(col_span)
            for y in range(row_index, row_index + height):
                for x in range(column, column + width):
                    if (y, x) in occupied:
                        return None
                    occupied[y, x] = cell
            column += width
    width = max((x for _, x in occupied), default=-1) + 1
    if width > 100 or any(y >= len(table.rows) for y, _ in occupied):
        return None
    for y in range(len(table.rows)):
        grid.append([occupied.get((y, x)) for x in range(width)])
    return grid


@dataclass(frozen=True)
class _Spec:
    title: str
    caption: str
    row: str
    group: str | None = None
    section: str | None = None
    preliminary: bool = False
    table_id: str | None = None


_CPI = r"Consumer Price Index (?:Summary|News Release)"
_EMPSIT = r"Employment Situation (?:Summary|News Release)"
_JOLTS = r"Job Openings and Labor Turnover (?:Summary|Survey News Release)"
_QUITS = r"Table 4\. Quits levels and rates by industry and region, seasonally adjusted"
SPECS = {
    # CPI questions: Table A, the named row,
    # SA changes from preceding month, latest displayed month (not 12-month NSA).
    "cpi_headline_mom": _Spec(
        _CPI,
        r"Table A\. Percent changes in CPI for All Urban Consumers "
        r"\(CPI-U\): U\.S\. city average",
        "All items",
        group="Seasonally adjusted changes from preceding month",
        table_id="cpi_pressa",
    ),
    "cpi_core_mom": _Spec(
        _CPI,
        r"Table A\. Percent changes in CPI for All Urban Consumers "
        r"\(CPI-U\): U\.S\. city average",
        "All items less food and energy",
        group="Seasonally adjusted changes from preceding month",
        table_id="cpi_pressa",
    ),
    # jolts_quits_rate questions: Table 4 Total, Rates (not levels), latest
    # month, not the change-from column. (2) is this header's known note.
    "jolts_quits_rate": _Spec(
        rf"(?:{_JOLTS}|{_QUITS})",
        _QUITS + r"(?:\s*\(\s*1\s*\))?",
        "Total",
        group="Rates",
        preliminary=True,
    ),
}


_MONTH_NAMES = (
    "January February March April May June July August September October "
    "November December"
).split()
_MONTH = "|".join(_MONTH_NAMES)


def _words(allowed: str) -> str:
    """Up to six words between a subject and its figure, each from `allowed`.

    A whitelist, so a qualifier ("for May", "since January", "average",
    "over the year", "and the number of ...") ends the match instead of
    being read past: such a sentence states some other figure.
    """
    return rf"(?:\s(?:{allowed})){{0,6}}"


_PAYROLL_SUBJECT = r"(?<![A-Za-z])(?:[Tt]otal )?nonfarm payroll employment"
_PAYROLL_WORDS = _words(
    "changed|little|was|were|essentially|unchanged|edged|up|down|rose|"
    "increased|declined|decreased|fell|grew|held|steady|flat|continued|to|"
    "trend|over|the|month|showed|no|change"
)
# Printed to the thousand ("143,000", "-23,000"): BLS's payroll change has
# no finer figure, and the contracts count in thousands.
_THOUSANDS = r"[1-9][0-9]{0,2}(?:,[0-9]{3})*,000"
_RATE_SUBJECT = r"(?<![A-Za-z-])[Tt]he unemployment rate"
_RATE_WORDS = _words(
    "was|were|changed|little|unchanged|essentially|held|steady|remained|"
    "edged|up|down|ticked|rose|increased|declined|decreased|fell|also|again"
)
_RATE = r"[0-9]{1,2}\.[0-9]"
_OPENINGS_WORDS = _words(
    "was|were|little|changed|unchanged|essentially|edged|up|down|rose|"
    "increased|declined|decreased|fell|held|steady|mostly|relatively"
)
_IN_MONTH = rf"(?:\sin\s(?P<month>{_MONTH}))?"
_DOWN = {"declined", "decreased", "fell", "edged down"}


@dataclass(frozen=True)
class _Prose:
    title: str
    heading: str
    statements: tuple[re.Pattern[str], ...]


PROSE_PARSERS = {
    # empsit_unemployment_rate questions: the release's U-3 rate, which its
    # text states to 0.1 percent, the precision of Summary table A.
    "empsit_unemployment_rate": _Prose(
        _EMPSIT,
        "THE EMPLOYMENT SITUATION",
        tuple(
            re.compile(pattern)
            for pattern in (
                rf"{_RATE_SUBJECT} \((?P<value>{_RATE}) percent\)",
                rf"{_RATE_SUBJECT}, at (?P<value>{_RATE}) percent,",
                rf"{_RATE_SUBJECT}{_RATE_WORDS}"
                rf"(?: by [0-9]\.[0-9] percentage points?)?"
                rf" (?:at|to) (?P<value>{_RATE}) percent{_IN_MONTH}",
                rf"{_RATE_SUBJECT} was (?P<value>{_RATE}) percent{_IN_MONTH}",
            )
        ),
    ),
    # empsit_payroll_change questions: the over-the-month change in total
    # nonfarm payroll employment, which the text states to the thousand,
    # the precision of Summary table B. Never the average monthly gain, and
    # never a revised earlier month ("the change ... for May was revised").
    "empsit_payroll_change": _Prose(
        _EMPSIT,
        "THE EMPLOYMENT SITUATION",
        tuple(
            re.compile(pattern)
            for pattern in (
                rf"{_PAYROLL_SUBJECT}{_PAYROLL_WORDS}{_IN_MONTH}"
                rf" \((?P<signed>[+-]{_THOUSANDS})\)",
                rf"{_PAYROLL_SUBJECT} (?P<verb>rose|increased|grew|edged up|"
                rf"declined|decreased|fell|edged down) by "
                rf"(?P<count>{_THOUSANDS})(?![,.]?[0-9]){_IN_MONTH}",
            )
        ),
    ),
    # jolts_job_openings questions: total job openings. The summary states
    # it only in millions to one decimal ("7.4 million"); see
    # resolve_pending.LEGACY_RELEASE_PRECISION_HELD before reading it.
    "jolts_job_openings": _Prose(
        _JOLTS,
        "JOB OPENINGS AND LABOR TURNOVER",
        tuple(
            re.compile(pattern)
            for pattern in (
                rf"(?<![A-Za-z])[Tt]he number of job openings{_OPENINGS_WORDS}"
                rf"(?: by [0-9,]+)? (?:at|to) (?P<value>[0-9]{{1,2}}\.[0-9])"
                rf" million{_IN_MONTH}",
                rf"(?<![A-Za-z])[Tt]he number and rate of job openings"
                rf"{_OPENINGS_WORDS} (?:at|to) (?P<value>[0-9]{{1,2}}\.[0-9])"
                rf" million and [0-9]{{1,2}}\.[0-9] percent",
            )
        ),
    ),
}


def _prose_release(html: str, parser_id: str) -> tuple[str, float] | None:
    """The figure every matching sentence of the release month states, or None.

    The page must have exactly one title naming the release and its month,
    exactly one preformatted block, and exactly one release heading naming
    the same month. At least two sentences must state the figure (BLS states
    each headline figure in the lead paragraph and again in its section),
    every such sentence must state the same figure, and a sentence that
    names a month must name the release month.
    """
    spec = PROSE_PARSERS[parser_id]
    doc = _Document()
    try:
        doc.feed(html)
        doc.close()
    except (AssertionError, ValueError):
        return None
    if doc.malformed or doc.in_title or len(doc.titles) != 1:
        return None
    title = re.fullmatch(
        rf"{spec.title} - ([0-9]{{4}}) M(0[1-9]|1[0-2]) Results", _text(doc.titles[0])
    )
    if title is None:
        return None
    period = f"{title[1]}-{title[2]}"
    month_name = _MONTH_NAMES[int(title[2]) - 1]
    blocks = re.findall(r"<pre\b[^>]*>(.*?)</pre\s*>", html, re.S | re.I)
    if len(blocks) != 1:
        return None
    text = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", blocks[0])).split())
    headings = re.findall(
        rf"{spec.heading}\W+({'|'.join(m.upper() for m in _MONTH_NAMES)})"
        rf" ([0-9]{{4}})\b",
        text,
    )
    if headings != [(month_name.upper(), title[1])]:
        return None
    values: set[Decimal] = set()
    statements = 0
    for pattern in spec.statements:
        for match in pattern.finditer(text):
            statements += 1
            groups = match.groupdict()
            if groups.get("month") and groups["month"] != month_name:
                return None
            if groups.get("value"):
                values.add(Decimal(groups["value"]))
            elif groups.get("signed"):
                printed = groups["signed"]
                count = Decimal(printed[1:].replace(",", "")) / 1000
                values.add(-count if printed[0] == "-" else count)
            else:
                count = Decimal(groups["count"].replace(",", "")) / 1000
                values.add(-count if groups["verb"] in _DOWN else count)
    if statements < 2 or len(values) != 1:
        return None
    value = float(values.pop())
    return (period, value) if math.isfinite(value) else None


def parse_release(html: str, parser_id: str) -> tuple[str, float] | None:
    """Read exactly the registered question's pinned release figure, or refuse.

    For a table page, the release title must authenticate its month and the
    chosen table must display that same month as its latest ordinary month
    column. Table ids, captions, section labels, row text and all column
    groups are binding; missing, repeated, malformed or nonnumeric
    candidates never guess. A prose page is read by _prose_release.
    """
    if parser_id in PROSE_PARSERS:
        return _prose_release(html, parser_id)
    spec = SPECS.get(parser_id)
    if spec is None:
        return None
    doc = _Document()
    try:
        doc.feed(html)
        doc.close()
    except (AssertionError, ValueError):
        return None
    if doc.malformed or doc.in_title or len(doc.titles) != 1:
        return None
    title = re.fullmatch(
        rf"{spec.title} - ([0-9]{{4}}) M(0[1-9]|1[0-2]) Results", _text(doc.titles[0])
    )
    if title is None:
        return None
    period = f"{title[1]}-{title[2]}"
    tables = [
        table
        for table in doc.tables
        if (spec.table_id is None or table.attrs.get("id") == spec.table_id)
        and re.fullmatch(spec.caption, _text(table.caption))
    ]
    if len(tables) != 1:
        return None
    table = tables[0]
    if not table.closed or table.malformed:
        return None
    grid = _grid(table)
    if grid is None:
        return None
    candidates: list[int] = []
    section = None
    for i, row in enumerate(table.rows):
        if not row:
            continue
        # Data rows have td cells; a heading-only row changes section.
        if not any(cell.tag == "td" and cell.text for cell in row):
            section = _text([cell.text for cell in row])
        if row[0].text == spec.row and (
            spec.section is None or section == spec.section
        ):
            candidates.append(i)
    if len(candidates) != 1:
        return None
    target_row = candidates[0]
    target_cells = table.rows[target_row]
    # One unspanned row label followed by ordinary numeric columns. A widened
    # label (or a cell spanning two columns/rows) otherwise shifts a preceding
    # value under the current-month header without changing that header.
    if (
        target_cells[0].tag != "th"
        or any(cell.tag != "td" for cell in target_cells[1:])
        or any(
            cell.attrs.get(span, "1") != "1"
            for cell in target_cells
            for span in ("rowspan", "colspan")
        )
    ):
        return None
    # Header coverage is as binding as the target row's shape. Checking only
    # the data row lets an added td widen the grid, slide another value under
    # the target header, and leave an ignored column beyond the header block.
    if any(cell is None for row in grid[: target_row + 1] for cell in row):
        return None
    dated_headers = [
        stamp
        for row in grid[:target_row]
        for cell in row
        if cell is not None
        and cell.tag == "th"
        and (stamp := _period(cell.text, spec.preliminary))
    ]
    if not dated_headers or max(dated_headers) != period:
        return None
    matches: list[_Cell] = []
    for column, cell in enumerate(grid[target_row]):
        if cell is None or cell.tag != "td":
            continue
        if cell.attrs.get("colspan", "1") != "1":
            return None
        # A rowspan repeats one physical header in the grid, not its meaning.
        # Keep distinct header objects so truly duplicated headings still
        # refuse, including a second copy of the required column group.
        headers: list[_Cell] = []
        seen: set[int] = set()
        for row in grid[:target_row]:
            header = row[column]
            if header is not None and header.tag == "th" and id(header) not in seen:
                headers.append(header)
                seen.add(id(header))
        path = [header.text for header in headers]
        dates = [stamp for text in path if (stamp := _period(text, spec.preliminary))]
        labels = [
            re.sub(r"\s*\(\s*2\s*\)$", "", text)
            if parser_id == "jolts_quits_rate"
            and re.fullmatch(r"Rates\s*\(\s*2\s*\)", text)
            else text
            for text in path
            if _period(text, spec.preliminary) is None
        ]
        # Authenticate the whole semantic header path, not mere membership in
        # one desired group. An extra NSA/level/rate/subpopulation heading is
        # contradictory evidence, even when the desired label also appears.
        expected_labels = [spec.group] if spec.group else []
        # A section may span the numeric columns, or live only in the stub
        # column beside empty td cells. Its identity is required separately
        # by target-row selection above; neither form adds another measure.
        expected_paths = [expected_labels]
        if spec.section:
            expected_paths.append([*expected_labels, spec.section])
        if dates == [period] and labels in expected_paths:
            matches.append(cell)
    if len(matches) != 1:
        return None
    printed = matches[0].text
    if not re.fullmatch(
        r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", printed
    ):
        return None
    value = float(Decimal(printed.replace(",", "")))
    return (period, value) if math.isfinite(value) else None
