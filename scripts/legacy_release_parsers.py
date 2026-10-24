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
    """Between one and six words, each from `allowed`.

    A whitelist, so a qualifier ("for May", "since January", "per month",
    "on average", "and the number of ...") ends the match instead of being
    read past: such a sentence states some other figure. At least one, so a
    caption with no verb ("Chart 2. Total nonfarm payroll employment
    (+50,000) in July.") is not a statement.
    """
    return rf"(?:\s(?:{allowed})){{1,6}}"


# Every statement opens with its measure's own subject, capitalized as a
# sentence or clause opens it, so a modifier ("Private nonfarm ...", "In
# June, the unemployment rate ...") is never read past. It names its month
# in place ("in July"; a rate statement may instead open with it, _FRONT),
# and it runs to the end of its sentence: after the month (and a payroll
# figure) comes only a tail (_END), then the full stop. So "in July, a year
# earlier", "in July (2025)", "in July (among teenagers)", "in July of last
# year" and "per month" are no statement.
_WHEN = rf" in (?P<month>{_MONTH})(?: (?P<year>[0-9]{{4}}))?"
# A statement may instead leave its month unsaid ("The unemployment rate
# held at 4.3 percent and has remained ...", "... increased by 142,000 over
# the month"). It then only corroborates: it counts toward the two
# statements when it states the figure the dated statements state, and is
# otherwise ignored ("Annual Average Data for 2025 ... The unemployment
# rate was 4.0 percent."). It can neither supply the figure nor veto it.
_WHEN_OR_UNSAID = rf"(?:{_WHEN}| over the month)?"
_COUNT = r"[1-9][0-9]{0,2}(?:,[0-9]{3})*"
_PAYROLL = r"(?:Total n|N)onfarm payroll employment"
_PAYROLL_BOTH = r"Both (?:total )?nonfarm payroll employment"
_PAYROLL_WORDS = (
    "changed|little|was|essentially|unchanged|edged|up|down|rose|increased|"
    "declined|decreased|fell|grew|held|steady|flat|continued|to|trend|showed|"
    "no|or|change"
)
_UP_WORDS = {"rose", "increased", "grew", "up"}
_DOWN_WORDS = {"declined", "decreased", "fell", "down"}
_PAYROLL_VERBS = "rose|increased|grew|edged up|declined|decreased|fell|edged down"
_DOWN = {"declined", "decreased", "fell", "edged down"}
# Printed to the thousand ("143,000", "-23,000"): BLS's payroll change has
# no finer figure, and the contracts count in thousands. Every form
# follows the figure with ")" or the month, so "143,000,500" and
# "143,000.5" are never read as 143,000.
_THOUSANDS = r"[1-9][0-9]{0,2}(?:,[0-9]{3})*,000"
_SIGNED = rf"[+\-\u2212]{_THOUSANDS}"
_RATE_SUBJECT = r"The unemployment rate"
_RATE = r"[0-9]{1,2}\.[0-9]"
_RATE_WORDS = (
    "was|were|changed|little|unchanged|essentially|held|steady|remained|"
    "edged|up|down|ticked|rose|increased|declined|decreased|fell|also|again|"
    "showed|no|or|change|stood"
)
_BY_POINTS = r"(?: (?:by )?[0-9]\.[0-9] percentage points?)?"
_UNEMPLOYED = r"the number of unemployed (?:people|persons)"
_MILLIONS = r"[0-9]{1,2}\.[0-9]"
_OPENINGS_WORDS = (
    "was|were|little|changed|unchanged|essentially|edged|up|down|rose|"
    "increased|declined|decreased|fell|held|steady|mostly|relatively|"
    "continued|to|trend|trended"
)
# JOLTS dates openings to the month's last business day ("on the last
# business day of May" in earlier releases, "in June" in the 2026 ones).
_OPENINGS_WHEN = _WHEN.replace(" in ", " (?:in|on the last business day of) ", 1)
_OPENINGS_WHEN_OR_UNSAID = rf"(?:{_OPENINGS_WHEN}| over the month)?"
# The level may carry its change ("6.5 million (-386,000)"), never read.
_OPENINGS_CHANGE = rf"(?: \([+\-\u2212]{_COUNT}\))?"
# A tail is a clause about some other figure (an average, an earlier
# month, a range, the number unemployed) or about the trend, opened by one
# of these words. It runs to the end of the sentence, and none of it is
# read. Anything else after the month qualifies the statement itself (",
# a year earlier", "(2025)", "(among teenagers)", "of last year"), so the
# sentence is no statement. "Before" opens no tail: "before seasonal
# adjustment" is another measure. Every tail in the corpus of real
# releases (tests/fixtures/release_capture/corpus/) opens with one of these.
_COMPARE = (
    "(?:(?:roughly|about|nearly|slightly|somewhat|well|much|far) )?"
    "(?:following|after|compared with|similar to|in line with|close to|"
    "the same as|up from|down from|(?:higher|lower|less|more) than|above|below)"
)
# A tail never speaks to the statement's own basis, scope or revision: a
# sentence whose tail names one ("... but was 4.1 percent after seasonal
# adjustment", "..., above the national rate", "... among adults", "...,
# after revision") is no statement, for the figure it states may be the
# unadjusted, partial or unrevised one. No tail in the corpus of real
# releases holds one of these words; "after accounting for the annual
# adjustments to the population controls", which BLS prints after the
# January rate, holds none.
_REQUALIFIERS = (
    r"\b(?:"
    + "|".join(
        (
            # Basis: another adjustment, or a figure leaving part out.
            "[Ss]easonal",
            r"(?:un)?adjusted\b",
            "exclud",
            r"without\b",
            r"basis\b",
            "benchmark",
            # Scope: the whole, a subgroup, a sector or a place.
            r"national\b",
            r"nationwide\b",
            r"overall\b",
            r"among\b",
            r"adults?\b",
            "teen",
            r"(?:wo)?men\b",
            "youth",
            "veteran",
            r"(?:White|Black|Asian|Hispanic|Latino)s?\b",
            r"private\b",
            r"government\b",
            r"sectors?\b",
            "industr",
            r"regions?\b",
            r"states?\b",
            r"metropolitan\b",
            # Revision.
            "revis",
        )
    )
    + ")"
)
_TAIL = (
    rf"(?:,? {_COMPARE}\b"
    r"| (?:and|but) (?:has|have|had|continued|remained)\b"
    # JOLTS: "... but was down by 885,000 over the year".
    r"| (?:and|but) (?:was|were) (?:up|down) by\b"
    rf"|, (?:and|while) {_UNEMPLOYED}\b)"
    # To the full stop. A period inside a number ("4.2") has no space after
    # it, so it ends nothing. One ending an abbreviation ("the U.S. average")
    # ends the tail early, which changes nothing: the statement is whole.
    rf"(?:(?!{_REQUALIFIERS})(?:[^.]|\.(?=\S)))*?"
)
_REPORTED = r", the U\.S\. Bureau of Labor Statistics reported today"
_END = rf"(?:{_REPORTED}|{_TAIL})?\.(?=\s|$)"


def _payroll_clauses(prefix: str) -> tuple[str, ...]:
    """The forms that state the month's change in total nonfarm payrolls.

    The printed figure and its verb are captured under `prefix`, so a clause
    another measure's statement leans on is checked like any other.
    """
    signed = rf"(?P<{prefix}signed>{_SIGNED})"
    words = rf"(?P<{prefix}words>{_words(_PAYROLL_WORDS)})"
    verb = rf"(?P<{prefix}verb>{_PAYROLL_VERBS})"
    count = rf"(?P<{prefix}count>{_THOUSANDS})"
    when = _WHEN_OR_UNSAID
    return (
        # "Total nonfarm payroll employment changed little in July (-23,000)"
        rf"{_PAYROLL}{words}{when} \({signed}\)",
        # "Total nonfarm payroll employment (+50,000) changed little in July"
        rf"{_PAYROLL} \({signed}\){words}{when}",
        # "Total nonfarm payroll employment changed little (+50,000) in July"
        rf"{_PAYROLL}{words} \({signed}\){when}",
        # "Total nonfarm payroll employment rose by 143,000 in January"
        rf"{_PAYROLL} {verb}(?: by)? {count}{when}",
    )


def _payroll_after(prefix: str) -> tuple[str, ...]:
    """The payroll clauses a rate statement may carry on into.

    ", and nonfarm payroll employment edged up by 114,000": the clause has
    no month of its own and takes the rate statement's. Captured under
    `prefix`, like _payroll_clauses.
    """
    signed = rf"(?P<{prefix}signed>{_SIGNED})"
    words = rf"(?P<{prefix}words>{_words(_PAYROLL_WORDS)})"
    verb = rf"(?P<{prefix}verb>{_PAYROLL_VERBS})"
    count = rf"(?P<{prefix}count>{_THOUSANDS})"
    subject = r", (?:and|while) (?:total )?nonfarm payroll employment"
    return (
        rf"{subject}{words} \({signed}\)",
        rf"{subject} \({signed}\){words}",
        rf"{subject} {verb}(?: by)? {count}",
    )


def _rate_bodies(value: str) -> tuple[str, ...]:
    """What a rate statement says between its subject and its month."""
    return (
        # " (4.1 percent) changed little"
        rf" \({value} percent\){_words(_RATE_WORDS)}",
        # ", at 4.1 percent, changed little"
        rf", at {value} percent,{_words(_RATE_WORDS)}",
        # " rose by 0.2 percentage point to 4.3 percent"
        rf"{_words(_RATE_WORDS)}{_BY_POINTS} (?:at|to) {value} percent",
        # " was 4.1 percent"
        rf" was {value} percent",
    )


_RATE_BODIES = _rate_bodies(rf"(?P<value>{_RATE})")
# The month may instead open the sentence ("In July, the unemployment rate
# ..."); then nothing but a tail follows the figure.
_FRONT = rf"In (?P<month>{_MONTH})(?: (?P<year>[0-9]{{4}}))?, "


def _rate_after(value: str) -> str:
    """The rate clause a payroll clause may carry on into.

    ", and the unemployment rate changed little at 4.0 percent"
    """
    return (
        rf", (?:and|while) the unemployment rate{_words(_RATE_WORDS)}"
        rf"{_BY_POINTS} (?:at|to) {value} percent"
    )


@dataclass(frozen=True)
class _Prose:
    title: str
    heading: str
    statements: tuple[re.Pattern[str], ...]


def _compile(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern + _END) for pattern in patterns)


PROSE_PARSERS = {
    # empsit_unemployment_rate questions: the release's U-3 rate, which its
    # text states to 0.1 percent, the precision of Summary table A. Never a
    # subgroup's rate ("The unemployment rate for teenagers"), never another
    # month's.
    "empsit_unemployment_rate": _Prose(
        _EMPSIT,
        "THE EMPLOYMENT SITUATION",
        _compile(
            # "The unemployment rate (4.1 percent) changed little in July"
            *(rf"{_RATE_SUBJECT}{body}{_WHEN_OR_UNSAID}" for body in _RATE_BODIES),
            # "The unemployment rate rose to 4.3 percent in July, and nonfarm
            # payroll employment edged up by 114,000": the payroll clause is
            # checked like any payroll statement.
            *(
                rf"{_RATE_SUBJECT}{body}{_WHEN}{after}"
                for body in _RATE_BODIES
                for after in _payroll_after("payroll_")
            ),
            # "In July, the unemployment rate (4.1 percent) changed little"
            *(rf"{_FRONT}the unemployment rate{body}" for body in _RATE_BODIES),
            # "Both the unemployment rate (4.1 percent) and the number of
            # unemployed people (6.9 million) changed little in July"
            rf"(?:Both t|T)he unemployment rate \((?P<value>{_RATE}) percent\) "
            rf"and {_UNEMPLOYED} \({_MILLIONS} million\){_words(_RATE_WORDS)}"
            rf"{_WHEN_OR_UNSAID}",
            # "Both the unemployment rate, at 4.1 percent, and the number of
            # unemployed people, at 6.9 million, changed little in July"
            rf"(?:Both t|T)he unemployment rate, at (?P<value>{_RATE}) percent, "
            rf"and {_UNEMPLOYED}, at {_MILLIONS} million,{_words(_RATE_WORDS)}"
            rf"{_WHEN_OR_UNSAID}",
            # "The unemployment rate and the number of unemployed people were
            # little changed at 4.1 percent and 6.9 million, respectively, in
            # July"
            rf"(?:Both t|T)he unemployment rate and {_UNEMPLOYED}"
            rf"{_words(_RATE_WORDS)} (?:at|to) (?P<value>{_RATE}) percent and "
            rf"{_MILLIONS} million, respectively,{_WHEN}",
            # "Both nonfarm payroll employment (-23,000) and the unemployment
            # rate (4.1 percent) changed little in July"
            rf"{_PAYROLL_BOTH} \((?P<payroll_signed>{_SIGNED})\) and the "
            rf"unemployment rate \((?P<value>{_RATE}) percent\)"
            rf"(?P<payroll_words>{_words(_RATE_WORDS)}){_WHEN_OR_UNSAID}",
            # "Total nonfarm payroll employment increased by 143,000 in
            # January, and the unemployment rate changed little at 4.0
            # percent": the rate takes the payroll clause's month, and the
            # payroll clause is checked like any payroll statement.
            *(
                clause + _rate_after(rf"(?P<value>{_RATE})")
                for clause in _payroll_clauses("payroll_")
            ),
        ),
    ),
    # empsit_payroll_change questions: the over-the-month change in total
    # nonfarm payroll employment, which the text states to the thousand,
    # the precision of Summary table B. Never private payrolls, never the
    # average monthly gain, and never a revised earlier month ("the change
    # ... for May was revised").
    "empsit_payroll_change": _Prose(
        _EMPSIT,
        "THE EMPLOYMENT SITUATION",
        _compile(
            *(rf"{clause}(?:{_rate_after(_RATE)})?" for clause in _payroll_clauses("")),
            # "The unemployment rate rose to 4.3 percent in July, and nonfarm
            # payroll employment edged up by 114,000"
            *(
                rf"{_RATE_SUBJECT}{body}{_WHEN}{after}"
                for body in _rate_bodies(_RATE)
                for after in _payroll_after("")
            ),
            rf"{_PAYROLL_BOTH} \((?P<signed>{_SIGNED})\) and the unemployment "
            rf"rate \({_RATE} percent\)(?P<words>{_words(_RATE_WORDS)})"
            rf"{_WHEN_OR_UNSAID}",
        ),
    ),
    # jolts_job_openings questions: total job openings. The summary states
    # it only in millions to one decimal ("7.4 million"); see
    # resolve_pending.LEGACY_RELEASE_PRECISION_HELD before reading it.
    "jolts_job_openings": _Prose(
        _JOLTS,
        "JOB OPENINGS AND LABOR TURNOVER",
        _compile(
            # "The number of job openings was little changed at 7.4 million
            # in June"
            rf"The number of job openings{_words(_OPENINGS_WORDS)}"
            rf"(?: by {_COUNT})? (?:at|to) (?P<value>{_MILLIONS}) million"
            rf"{_OPENINGS_CHANGE}{_OPENINGS_WHEN_OR_UNSAID}",
            rf"The number of job openings was (?P<value>{_MILLIONS}) million"
            rf"{_OPENINGS_CHANGE}{_OPENINGS_WHEN_OR_UNSAID}",
            # "The number and rate of job openings were little changed at 7.4
            # million and 4.4 percent, respectively, in June"
            rf"The number and rate of job openings{_words(_OPENINGS_WORDS)} "
            rf"(?:at|to) (?P<value>{_MILLIONS}) million{_OPENINGS_CHANGE} and "
            rf"{_RATE} percent, respectively,{_OPENINGS_WHEN}",
        ),
    ),
}


def _contradicts(groups: dict[str, str | None], prefix: str) -> bool:
    """A payroll verb that contradicts its printed sign ("edged up (-41,000)")."""
    printed = groups.get(prefix + "signed")
    if not printed:
        return False
    words = set((groups.get(prefix + "words") or "").split())
    return bool(words & (_UP_WORDS if printed[0] != "+" else _DOWN_WORDS))


def _statement_value(groups: dict[str, str | None]) -> Decimal | None:
    """The figure one statement states, or None when it contradicts itself.

    A rate statement that leans on a payroll clause contradicts itself when
    that clause does: the sentence says two things, and neither is guessed.
    """
    if _contradicts(groups, "") or _contradicts(groups, "payroll_"):
        return None
    if groups.get("value"):
        return Decimal(groups["value"])
    if groups.get("signed"):
        printed = groups["signed"]
        count = Decimal(printed[1:].replace(",", "")) / 1000
        return -count if printed[0] != "+" else count
    count = Decimal(str(groups["count"]).replace(",", "")) / 1000
    return -count if groups["verb"] in _DOWN else count


def _prose_release(html: str, parser_id: str) -> tuple[str, float] | None:
    """The figure every statement of the release month states, or None.

    The page must have exactly one title naming the release and its month
    (the Employment Situation titles its December release "M13"), exactly
    one preformatted block, and exactly one release heading naming the same
    month. A statement is one of the reader's forms, whole: the measure's
    own subject opening a sentence or clause, the figure, the month named in
    place or left unsaid, and nothing after it but a tail and the full stop
    (_END). The statements that name the month must all agree, and at least
    two statements in separate stretches of text must state their figure
    (BLS states each headline figure in the lead paragraph and again in its
    section): dated ones, or undated ones that state the same figure. A
    dated statement that names another month or year, or whose verb
    contradicts its printed sign, refuses the page. An undated statement
    never does: one stating another figure, or contradicting itself, is
    ignored. Text in no form is not read.
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
        rf"{spec.title} - ([0-9]{{4}}) M(0[1-9]|1[0-3]) Results", _text(doc.titles[0])
    )
    if title is None:
        return None
    month = min(int(title[2]), 12)
    period = f"{title[1]}-{month:02d}"
    month_name = _MONTH_NAMES[month - 1]
    blocks = re.findall(r"<pre\b[^>]*>(.*?)</pre\s*>", html, re.S | re.I)
    if len(blocks) != 1:
        return None
    text = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", blocks[0])).split())
    # "JULY 2026", and once "March 2026".
    headings = re.findall(
        rf"{spec.heading}\W+((?i:{_MONTH})) ([0-9]{{4}})\b",
        text,
    )
    if [(name.upper(), year) for name, year in headings] != [
        (month_name.upper(), title[1])
    ]:
        return None
    found: list[tuple[int, int]] = []
    values: set[Decimal] = set()
    undated: list[tuple[tuple[int, int], Decimal | None]] = []
    for pattern in spec.statements:
        for match in pattern.finditer(text):
            groups = match.groupdict()
            if groups["month"] is None:
                undated.append((match.span(), _statement_value(groups)))
                continue
            if groups["month"] != month_name or groups["year"] not in (
                None,
                title[1],
            ):
                return None
            value = _statement_value(groups)
            if value is None:
                return None
            values.add(value)
            found.append(match.span())
    if len(values) != 1:
        return None
    (figure,) = values
    found += [span for span, value in undated if value == figure]
    # Two forms matching one stretch of text are one statement, not two.
    statements, reach = 0, -1
    for begin, finish in sorted(found):
        if begin >= reach:
            statements += 1
        reach = max(reach, finish)
    if statements < 2:
        return None
    value = float(figure)
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
