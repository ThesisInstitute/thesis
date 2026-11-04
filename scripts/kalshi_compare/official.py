"""Official first prints, read from the agencies' own releases.

- BLS news release archive (``/news.release/archives/<release>_<MMDDYYYY>.htm``):
  CPI Table A, Employment Situation summary tables A and B, JOLTS Table A.
- DOL Employment and Training Administration weekly claims press release
  (``oui.doleta.gov/press/<YYYY>/<MMDDYY>.pdf``), via ``pdftotext``.
- BEA Personal Income and Outlays release page.

Each parser returns the value, its reference period, and the release instant
stated in the document itself, plus a second reading from the release's lead
text where the wording allows. Disagreement between the two raises.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import html
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal
from zoneinfo import ZoneInfo

from .contracts import MONTH_WORD, MONTHS, normalize_text
from .fetch import BROWSER_COMPATIBLE_UA, FetchCache

ET = ZoneInfo("America/New_York")
NUMBER = r"-?\d[\d,]*(?:\.\d+)?"


class OfficialParseError(ValueError):
    pass


class NoValuePublishedError(OfficialParseError):
    """The release's table shows no value for the period (a dash)."""


@dataclasses.dataclass(frozen=True)
class OfficialPrint:
    statistic: str
    period: str  # YYYY-MM or week-ending YYYY-MM-DD
    value: Decimal  # in the contract's strike units
    release_at: str  # ISO UTC instant stated by the document
    source_url: str
    source_sha256: str | None
    table_reading: str
    second_reading: str | None  # the same value read elsewhere in the document


def html_text(body: bytes) -> str:
    text = body.decode("utf-8", "replace")
    text = re.sub(
        r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I
    )
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return normalize_text(text)


def pdf_text(body: bytes) -> str:
    if not shutil.which("pdftotext"):
        raise OfficialParseError("pdftotext (poppler) is required for DOL releases")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(body)
        handle.flush()
        out = subprocess.run(
            ["pdftotext", "-layout", handle.name, "-"],
            check=True,
            capture_output=True,
        ).stdout
    return normalize_text(out.decode("utf-8", "replace"))


def to_decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def month_period(month_word: str, year: str) -> str:
    return f"{int(year):04d}-{MONTHS[month_word.lower().rstrip('.')]:02d}"


def release_instant(hour: str, minute: str, meridiem: str, date_text: str) -> str:
    date = dt.datetime.strptime(normalize_text(date_text), "%B %d, %Y").date()
    hour_24 = int(hour) % 12 + (12 if meridiem.lower().startswith("p") else 0)
    local = dt.datetime(
        date.year, date.month, date.day, hour_24, int(minute), tzinfo=ET
    )
    return local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


BLS_RELEASE_TIME = re.compile(
    r"(?:embargoed until|For"
    r" release)\s+(?:USDL-[\d-]+\s+)?(\d{1,2}):(\d{2})\s*([ap])\.m\.\s*"
    r"\((?:ET|EDT|EST)\)\s*(?:[A-Za-z]+,\s*)?([A-Za-z]+ \d{1,2}, \d{4})",
    re.I,
)
VERB_SIGN = {
    "increased": 1,
    "rose": 1,
    "edged up": 1,
    "advanced": 1,
    "decreased": -1,
    "declined": -1,
    "fell": -1,
    "edged down": -1,
    "dropped": -1,
}


def signed_change(verb: str | None, amount: str | None) -> Decimal | None:
    if verb is None:
        return None
    verb = verb.lower()
    if "unchanged" in verb:
        return Decimal("0.0")
    if amount is None:
        return None
    return VERB_SIGN[verb] * Decimal(amount)


def bls_release_at(text: str) -> str:
    found = BLS_RELEASE_TIME.search(text)
    if not found:
        raise OfficialParseError("no release time statement in the BLS release")
    return release_instant(*found.groups())


def parse_bls_cpi(text: str, row: str) -> tuple[str, Decimal, Decimal | None, str]:
    """(period, Table A value, lead-text value, release instant) for a CPI row."""
    title = re.search(
        rf"CONSUMER PRICE INDEX\s*\W+\s*({MONTH_WORD})\s+(\d{{4}})", text, re.I
    )
    if not title:
        raise OfficialParseError("CPI release title not found")
    period = month_period(title.group(1), title.group(2))
    start = text.find("Table A. Percent changes in CPI for All Urban Consumers")
    if start < 0:
        raise OfficialParseError("CPI Table A not found")
    table = text[start : start + 6000]
    # Drop the "12-mos. ended Aug. 2026" label so only column months remain.
    table = re.sub(
        rf"12-mos\.?\s+ended\s+{MONTH_WORD}\.?\s+20\d\d", " ", table, flags=re.I
    )
    header = [
        month_period(*h)
        for h in re.findall(rf"({MONTH_WORD})\.?\s+(20\d\d)", table[:600], re.I)
    ]
    if len(header) < 7:
        # Releases through early 2022 print the seven months, then "ended",
        # then their seven years: "Dec. Jan. ... June ended 2020 2021 ... 2021".
        split = re.search(
            rf"((?:{MONTH_WORD}\.?\s+){{7}})ended\s+((?:20\d\d\s+){{7}})",
            table[:600],
            re.I,
        )
        if not split:
            raise OfficialParseError("CPI Table A header has fewer than seven months")
        months = re.findall(MONTH_WORD, split.group(1), re.I)
        header = [month_period(m, y) for m, y in zip(months, split.group(2).split())]
    if header[6] != period:
        raise OfficialParseError(
            f"CPI Table A's seventh column is {header[6]}, not {period}"
        )
    label = "All items" if row == "headline" else "All items less food and energy"
    # Older releases write ".2" and pad labels with dots; a dash marks a month
    # with no published value (the 2025 lapse in appropriations).
    cell = r"(?:-?\d*\.\d|-(?=\s))"
    values = re.search(rf"\b{re.escape(label)}\.*\s+((?:{cell}\s+){{7}}{cell})", table)
    if not values:
        raise OfficialParseError(f"CPI Table A row {label!r} not found")
    cells = values.group(1).split()
    if cells[6] == "-":
        raise NoValuePublishedError(
            f"CPI Table A shows no {label!r} value for {period}"
        )
    table_value = Decimal(cells[6])
    if row == "headline":
        lead = re.search(
            r"\(CPI-U\)\s+(increased|rose|decreased|declined|fell|was unchanged)"
            r"(?:\s+(\d+\.\d) percent)?\s+on a seasonally adjusted basis",
            text,
        )
    else:
        lead = re.search(
            r"index for all items less food and energy\s+"
            r"(increased|rose|decreased|declined|fell|edged up|edged down|was"
            r" unchanged)"
            r"(?:\s+(\d+\.\d) percent)?",
            text,
        )
    lead_value = signed_change(*lead.groups()) if lead else None
    return period, table_value, lead_value, bls_release_at(text)


def parse_bls_empsit(
    text: str, statistic: str
) -> tuple[str, Decimal, Decimal | None, str]:
    title = re.search(
        rf"THE EMPLOYMENT SITUATION\s*\W+\s*({MONTH_WORD})\s+(\d{{4}})", text, re.I
    )
    if not title:
        raise OfficialParseError("Employment Situation title not found")
    period = month_period(title.group(1), title.group(2))
    if statistic == "payrolls":
        table = re.search(
            r"Summary table B\. Establishment data, seasonally adjusted Category (.*?) "
            r"EMPLOYMENT BY SELECTED INDUSTRY \(Over-the-month change, in thousands\) "
            r"Total nonfarm\s+(-?[\d,]+)\s+(-?[\d,]+)\s+(-?[\d,]+)\s+(-?[\d,]+)",
            text,
        )
        if not table:
            raise OfficialParseError("Summary table B total nonfarm row not found")
        header = re.findall(rf"({MONTH_WORD})\.?\s+(20\d\d)", table.group(1), re.I)
        if month_period(*header[-1]) != period:
            raise OfficialParseError(
                "Summary table B's last column is not the reference month"
            )
        value = to_decimal(table.group(5)) * 1000
        lead = re.search(
            r"Total nonfarm payroll"
            r" employment\s+(increased|rose|decreased|declined|fell|"
            r"edged up|edged down)\s+(?:by\s+)?([\d,]+)",
            text,
        )
        lead_value = (
            VERB_SIGN[lead.group(1).lower()] * to_decimal(lead.group(2))
            if lead
            else None
        )
        return period, value, lead_value, bls_release_at(text)
    # The row is the table's first "Unemployment rate" row; a dash marks a
    # month with no published value (October 2025, during the 2025 lapse in
    # appropriations), so a cell is a one-decimal number or a dash.
    cell = r"(\d+\.\d|-(?=\s))"
    table = re.search(
        r"Summary table A\. Household data, seasonally adjusted \[Numbers in"
        r" thousands\] "
        r"Category (.*?) Employment status .{0,800}? Unemployment"
        rf" rate\s+{cell}\s+{cell}\s+{cell}\s+{cell}",
        text,
    )
    if not table:
        raise OfficialParseError("Summary table A unemployment rate row not found")
    header = re.findall(rf"({MONTH_WORD})\.?\s+(20\d\d)", table.group(1), re.I)
    if month_period(*header[3]) != period:
        raise OfficialParseError(
            "Summary table A's fourth column is not the reference month"
        )
    if table.group(5) == "-":
        raise NoValuePublishedError(
            f"Summary table A shows no unemployment rate for {period}"
        )
    value = Decimal(table.group(5))
    lead = re.search(
        r"unemployment rate\s+(?:was unchanged at|changed little at|was little"
        r" changed at|"
        r"rose to|increased to|edged up to|edged down to|declined to|fell"
        r" to|decreased to|"
        r"remained at|held at|was)\s+(\d+\.\d) percent",
        text,
    )
    return period, value, Decimal(lead.group(1)) if lead else None, bls_release_at(text)


def parse_bls_jolts(text: str) -> tuple[str, Decimal, Decimal | None, str]:
    title = re.search(
        rf"JOB OPENINGS AND LABOR TURNOVER\s*\W+\s*({MONTH_WORD})\s+(\d{{4}})",
        text,
        re.I,
    )
    if not title:
        raise OfficialParseError("JOLTS release title not found")
    period = month_period(title.group(1), title.group(2))
    table = re.search(
        r"Table A\. Job openings, hires, and total separations by industry, seasonally "
        r"adjusted Category Job openings Hires Total separations (.*?) LEVELS BY"
        r" INDUSTRY "
        r"\(in thousands\) Total\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)",
        text,
    )
    if not table:
        raise OfficialParseError("JOLTS Table A total row not found")
    header = re.findall(rf"({MONTH_WORD})\.?\s+(20\d\d)", table.group(1), re.I)
    if month_period(*header[2]) != period:
        raise OfficialParseError(
            "JOLTS Table A's third job-openings column is not the reference month"
        )
    value = to_decimal(table.group(4)) / 1000
    lead = re.search(
        r"number of job openings\s+(?:was )?[a-z ]*?(?:at|to)\s+(\d+\.\d) million", text
    )
    # The lead rounds to 0.1 million, so it can only bound the table value.
    lead_value = Decimal(lead.group(1)) if lead else None
    return period, value, lead_value, bls_release_at(text)


DOL_RELEASE_TIME = re.compile(
    r"EMBARGOED UNTIL\s+(\d{1,2}):(\d{2})\s+([AP])\.M\.\s+\(Eastern\)\s+[A-Za-z]+,\s+"
    r"([A-Za-z]+ \d{1,2}, \d{4})",
    re.I,
)


def _week_date(month_day: str, release_date: dt.date) -> str:
    found = re.match(rf"({MONTH_WORD})\.?\s+(\d{{1,2}})", month_day, re.I)
    month, day = MONTHS[found.group(1).lower()], int(found.group(2))
    year = release_date.year - (1 if month > release_date.month else 0)
    return dt.date(year, month, day).isoformat()


def parse_dol_claims(text: str, statistic: str) -> tuple[str, Decimal, None, str]:
    released = DOL_RELEASE_TIME.search(text)
    if not released:
        raise OfficialParseError("no embargo statement in the DOL release")
    release_at = release_instant(*released.groups())
    release_date = dt.datetime.strptime(released.group(4), "%B %d, %Y").date()
    if statistic == "initial":
        found = re.search(
            rf"In the week ending ({MONTH_WORD}\.? \d{{1,2}}), the advance figure for "
            rf"seasonally adjusted initial claims was ([\d,]+)",
            text,
            re.I,
        )
    else:
        found = re.search(
            rf"The advance number for seasonally adjusted insured unemployment during"
            rf" the "
            rf"week ending ({MONTH_WORD}\.? \d{{1,2}}) was ([\d,]+)",
            text,
            re.I,
        )
    if not found:
        raise OfficialParseError(f"DOL {statistic} claims advance figure not found")
    period = _week_date(found.group(1), release_date)
    persons = to_decimal(found.group(2))
    value = persons if statistic == "initial" else persons / Decimal(1_000_000)
    return period, value, None, release_at


BEA_RELEASE_TIME = re.compile(
    r"EMBARGOED UNTIL RELEASE AT\s+(\d{1,2}):(\d{2})\s+([ap])\.m\.\s+(?:EDT|EST|ET),\s+"
    r"[A-Za-z]+,\s+([A-Za-z]+ \d{1,2}, \d{4})",
    re.I,
)


def parse_bea_core_pce(text: str) -> tuple[str, Decimal, Decimal | None, str]:
    released = BEA_RELEASE_TIME.search(text)
    if not released:
        raise OfficialParseError("no embargo statement in the BEA release")
    title = re.search(
        rf"Personal Income and Outlays,\s+({MONTH_WORD})\s+(\d{{4}})", text, re.I
    )
    if not title:
        raise OfficialParseError("BEA release title not found")
    period = month_period(title.group(1), title.group(2))
    table = re.search(
        rf"Personal Income and Related Measures \[Percent change from preceding"
        rf" month\]\s+"
        rf"({MONTH_WORD})\s+({MONTH_WORD})\s+.*?PCE price index excluding food and"
        r" energy\s+"
        rf"(-?\d+\.\d)\s+(-?\d+\.\d)",
        text,
        re.I,
    )
    if not table:
        raise OfficialParseError("BEA percent-change table row not found")
    if MONTHS[table.group(2).lower()] != int(period[5:]):
        raise OfficialParseError("BEA table's second column is not the reference month")
    value = Decimal(table.group(4))
    lead = re.search(
        r"Excluding food and energy, the PCE price index\s+(?:also\s+)?"
        r"(increased|decreased|rose|fell|declined|was unchanged)(?:\s+(\d+\.\d)"
        r" percent)?",
        text,
    )
    lead_value = signed_change(*lead.groups()) if lead else None
    return period, value, lead_value, release_instant(*released.groups())


CENSUS_RELEASE_TIME = re.compile(
    r"FOR RELEASE AT\s+(\d{1,2}):(\d{2})\s+([AP])M\s+(?:EDT|EST|ET),\s+[A-Z]+,\s+"
    r"([A-Za-z]+ \d{1,2}, \d{4})",
    re.I,
)


def parse_census_construction(
    text: str, statistic: str
) -> tuple[str, Decimal, Decimal | None, str]:
    """Census/HUD New Residential Construction: starts or permits, in millions."""
    released = CENSUS_RELEASE_TIME.search(text)
    if not released:
        raise OfficialParseError("no release statement in the Census release")
    title = re.search(
        rf"MONTHLY NEW RESIDENTIAL CONSTRUCTION,\s+({MONTH_WORD})\s+(\d{{4}})",
        text,
        re.I,
    )
    if not title:
        raise OfficialParseError("New Residential Construction title not found")
    period = month_period(title.group(1), title.group(2))
    month_word = rf"{title.group(1)}"
    if statistic == "starts":
        lead = re.search(
            rf"Privately-owned housing starts in {month_word} were at a seasonally[- ]"
            r"adjusted annual rate of\s+([\d,]+)",
            text,
            re.I,
        )
        box = re.search(r"Housing Starts:\s+([\d,]+)", text)
    else:
        lead = re.search(
            rf"Privately-owned housing units authorized by building permits in "
            rf"{month_word} were at a seasonally[- ]adjusted annual rate of\s+([\d,]+)",
            text,
            re.I,
        )
        box = re.search(r"Building Permits:\s+([\d,]+)", text)
    if not lead:
        raise OfficialParseError(f"Census {statistic} lead sentence not found")
    value = to_decimal(lead.group(1)) / Decimal(1_000_000)
    second = to_decimal(box.group(1)) / Decimal(1_000_000) if box else None
    return period, value, second, release_instant(*released.groups())


def parse_census_new_home_sales(text: str) -> tuple[str, Decimal, Decimal | None, str]:
    """Census/HUD New Residential Sales: new houses sold, SAAR, in houses."""
    released = CENSUS_RELEASE_TIME.search(text)
    if not released:
        raise OfficialParseError("no release statement in the Census release")
    title = re.search(
        rf"MONTHLY NEW RESIDENTIAL SALES,\s+({MONTH_WORD})\s+(\d{{4}})", text, re.I
    )
    if not title:
        raise OfficialParseError("New Residential Sales title not found")
    period = month_period(title.group(1), title.group(2))
    lead = re.search(
        rf"Sales of new single-family houses in {title.group(1)}(?: \d{{4}})? were"
        r" at a "
        r"seasonally[- ]adjusted annual rate of\s+([\d,]+)",
        text,
        re.I,
    )
    box = re.search(r"New Houses Sold\s*\d?:\s+([\d,]+)", text)
    if not lead:
        raise OfficialParseError("New Residential Sales lead sentence not found")
    second = to_decimal(box.group(1)) if box else None
    return (
        period,
        to_decimal(lead.group(1)),
        second,
        release_instant(*released.groups()),
    )


ABS_OFFSETS = {"AEST": 10, "AEDT": 11}


def parse_abs_unemployment(text: str) -> tuple[str, Decimal, Decimal | None, str]:
    """ABS Labour Force, Australia release page: seasonally adjusted rate."""
    reference = re.search(rf"Reference period\s+({MONTH_WORD})\s+(\d{{4}})", text, re.I)
    released = re.search(
        r"Release date and time\s+(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*(am|pm)"
        r"\s+(AEST|AEDT)",
        text,
        re.I,
    )
    if not reference or not released:
        raise OfficialParseError("ABS reference period or release time not found")
    period = month_period(reference.group(1), reference.group(2))
    day, month, year, hour, minute, meridiem, zone = released.groups()
    hour_24 = int(hour) % 12 + (12 if meridiem.lower() == "pm" else 0)
    local = dt.datetime(int(year), int(month), int(day), hour_24, int(minute))
    release_at = (local - dt.timedelta(hours=ABS_OFFSETS[zone.upper()])).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    # The seasonally adjusted paragraph ends where the trend one begins; a
    # window that ran on would read the trend rate (the April 2026 page).
    opening = re.search(
        rf"In seasonally adjusted terms, in {reference.group(1)} {reference.group(2)}:",
        text,
        re.I,
    )
    paragraph = (
        text[opening.end() : opening.end() + 400].split("In trend terms")[0]
        if opening
        else ""
    )
    lead = re.search(
        r"(?:the )?unemployment rate (?:was|remained at|"
        r"(?:rose|increased|fell|decreased|declined)"
        r"(?: marginally| by [\d.]+ ?ppts?| [\d.]+ ?ppts?)? to)"
        r"\s+(\d+\.\d)%",
        paragraph,
        re.I,
    )
    if not lead:
        raise OfficialParseError(
            "ABS seasonally adjusted unemployment sentence not found"
        )
    # The key statistics tables come in either order; read the one labelled
    # seasonally adjusted, whose second column is the reference month.
    table = re.search(
        r"Key statistics - Seasonally adjusted (\w{3})-(\d{2}) (\w{3})-(\d{2})"
        r".{0,600}?Unemployment rate\s+(\d+\.\d)%\s+(\d+\.\d)%",
        text,
    )
    if table:
        if month_period(table.group(3), f"20{table.group(4)}") != period:
            raise OfficialParseError(
                "ABS table's second column is not the reference month"
            )
        second = Decimal(table.group(6))
    else:
        table = re.search(r"Unemployment rate\s+(\d+\.\d)%\s+(\d+\.\d)%", text)
        second = Decimal(table.group(2)) if table else None
    return period, Decimal(lead.group(1)), second, release_at


BLS_ARCHIVE = "https://www.bls.gov/news.release/archives/{name}_{date:%m%d%Y}.htm"
DOL_ARCHIVE = "https://oui.doleta.gov/press/{date:%Y}/{date:%m%d%y}.pdf"
BEA_RELEASE = (
    "https://www.bea.gov/news/{year}/personal-income-and-outlays-{month}-{year}"
)
CENSUS_NRC = (
    "https://www.census.gov/construction/nrc/pdf/newresconst_{year}{month:02d}.pdf"
)
CENSUS_NRS = (
    "https://www.census.gov/construction/nrs/pdf/newressales_{year}{month:02d}.pdf"
)
ABS_LABOUR_FORCE = (
    "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/"
    "labour-force-australia/{month}-{year}"
)
MONTH_SLUG = [
    "",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


@dataclasses.dataclass(frozen=True)
class Source:
    url: str
    kind: str  # html | pdf
    parse: object


def source_for(official: str, period: str, release_date: dt.date) -> Source:
    if official in ("bls_cpi_headline", "bls_cpi_core"):
        row = "headline" if official.endswith("headline") else "core"
        return Source(
            BLS_ARCHIVE.format(name="cpi", date=release_date),
            "html",
            lambda text: parse_bls_cpi(text, row),
        )
    if official in ("bls_payrolls", "bls_unemployment"):
        statistic = "payrolls" if official == "bls_payrolls" else "unemployment"
        return Source(
            BLS_ARCHIVE.format(name="empsit", date=release_date),
            "html",
            lambda text: parse_bls_empsit(text, statistic),
        )
    if official == "bls_jolts_openings":
        return Source(
            BLS_ARCHIVE.format(name="jolts", date=release_date), "html", parse_bls_jolts
        )
    if official in ("dol_initial_claims", "dol_continued_claims"):
        statistic = "initial" if official == "dol_initial_claims" else "continued"
        return Source(
            DOL_ARCHIVE.format(date=release_date),
            "pdf",
            lambda text: parse_dol_claims(text, statistic),
        )
    if official == "bea_core_pce":
        year, month = int(period[:4]), int(period[5:7])
        return Source(
            BEA_RELEASE.format(year=year, month=MONTH_SLUG[month]),
            "html",
            parse_bea_core_pce,
        )
    year, month = int(period[:4]), int(period[5:7])
    if official in ("census_starts", "census_permits"):
        statistic = "starts" if official == "census_starts" else "permits"
        return Source(
            CENSUS_NRC.format(year=year, month=month),
            "pdf",
            lambda text: parse_census_construction(text, statistic),
        )
    if official == "census_new_home_sales":
        return Source(
            CENSUS_NRS.format(year=year, month=month),
            "pdf",
            parse_census_new_home_sales,
        )
    if official == "abs_unemployment":
        return Source(
            ABS_LABOUR_FORCE.format(month=MONTH_SLUG[month][:3], year=year),
            "html",
            parse_abs_unemployment,
        )
    raise KeyError(official)


def fetch_print(
    cache: FetchCache, official: str, period: str, release_date: dt.date
) -> OfficialPrint:
    """The first print of ``official`` for ``period`` from its release document.

    ``release_date`` is only a hint for which archived document to open (the
    Kalshi market's close date); the document's own title, table header and
    embargo statement decide the period and release instant.
    """
    source = source_for(official, period, release_date)
    body = cache.get(source.url, user_agent=BROWSER_COMPATIBLE_UA, accept="*/*")
    text = pdf_text(body) if source.kind == "pdf" else html_text(body)
    parsed_period, value, second, release_at = source.parse(text)
    if parsed_period != period:
        raise OfficialParseError(
            f"{source.url} reports {parsed_period}, expected {period}"
        )
    if second is not None:
        # The JOLTS lead rounds to 0.1 million, so it can only bound the table.
        tolerance = Decimal("0.05") if official == "bls_jolts_openings" else Decimal(0)
        if abs(second - value) > tolerance:
            raise OfficialParseError(
                f"{source.url}: readings {value} and {second} differ"
            )
    return OfficialPrint(
        statistic=official,
        period=period,
        value=value,
        release_at=release_at,
        source_url=source.url,
        source_sha256=cache.sha256_of(source.url),
        table_reading=str(value),
        second_reading=None if second is None else str(second),
    )
