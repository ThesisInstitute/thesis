"""Every settled event in the twelve series: contracts, periods and outcomes.

Reuses #381's Kalshi fetchers, contract readers and official parsers. The
additions here are for history #381 never needed: legacy markets with no
``strike_type`` or no number in the rule text, legacy rules that name the
month without the year, and finding a release by the agency's own archive
index rather than by the market's close date (legacy markets closed the
evening before the release).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
from decimal import Decimal

from kalshi_compare import contracts, kalshi, official
from kalshi_compare.fetch import BROWSER_COMPATIBLE_UA, FetchCache

SERIES = (
    "KXCPI",
    "KXCPICORE",
    "KXU3",
    "KXPAYROLLS",
    "KXJOBLESSCLAIMS",
    "KXCONTCLAIMS",
    "KXJOLTSOPEN",
    "KXPCECORE",
    "KXHOUSINGSTART",
    "KXBUILDPERMS",
    "KXNHSALES",
    "KXUE",
)
FAMILIES = {
    "KXCPI": "inflation",
    "KXCPICORE": "inflation",
    "KXPCECORE": "inflation",
    "KXU3": "monthly labor",
    "KXPAYROLLS": "monthly labor",
    "KXJOLTSOPEN": "monthly labor",
    "KXJOBLESSCLAIMS": "weekly claims",
    "KXCONTCLAIMS": "weekly claims",
    "KXHOUSINGSTART": "housing",
    "KXBUILDPERMS": "housing",
    "KXNHSALES": "housing",
    "KXUE": "Australian unemployment",
}
FAMILY_ORDER = (
    "inflation",
    "monthly labor",
    "weekly claims",
    "housing",
    "Australian unemployment",
)


def spec_for(series: str) -> contracts.SeriesSpec:
    return next(s for s in contracts.SPECS if s.series == series and s.kind == "ladder")


def generation(series: str, event_ticker: str) -> str:
    """``KX`` for events under the series' own ticker, ``legacy`` otherwise."""
    return "KX" if event_ticker.startswith(series + "-") else "legacy"


# Reading a contract ---------------------------------------------------------

# Legacy wordings: "is greater than 0.1%", "more than 0.50 percent%".
LEGACY_RULE_STRIKE = re.compile(
    r"(?P<word>greater than or equal to|greater than|more than|above|at least)\s+"
    r"(?P<number>-?[\d,]*\.?\d+)?\s*"
    r"(?P<suffix>%|percent|K\b|k\b|M\b|million|thousand)?",
    re.I,
)
DIRECTION = {
    "greater than or equal to": "greater_or_equal",
    "at least": "greater_or_equal",
    "greater than": "greater",
    "more than": "greater",
    "above": "greater",
}
SUB_TITLE_STRIKE = re.compile(
    r"^\s*Above\s+(?P<number>-?[\d,]*\.?\d+)\s*(?P<suffix>%|K|M)?%?\s*$", re.I
)
TICKER_STRIKE = re.compile(r"-T(?P<number>-?\d+(?:\.\d+)?)$")
FLOOR_TOLERANCE = Decimal("0.00001")


@dataclasses.dataclass(frozen=True)
class Strike:
    value: Decimal  # in the series' canonical unit
    strike_type: str  # greater | greater_or_equal
    source: str  # rule | legacy_rule | sub_title_and_ticker


def read_strike(market: dict, spec: contracts.SeriesSpec) -> Strike:
    """The strike and direction of a ladder market, as its own text states.

    #381's reader first. Where it fails, the legacy reader takes the direction
    from the rule's wording ("greater than" and "more than" are ``greater``,
    "at least" is ``greater_or_equal``), which must agree with
    ``strike_type`` when that is set. A rule that names no number (some 2021
    and 2022 U-3 rules read "above %") takes it from ``yes_sub_title``, which
    must equal the ticker's ``T`` suffix. ``floor_strike``, when present, must
    equal the number read.
    """
    try:
        return Strike(contracts.strike_of(market, spec), market["strike_type"], "rule")
    except ValueError as error:
        first_error = error
    rule = contracts.normalize_text(market.get("rules_primary", ""))
    found = LEGACY_RULE_STRIKE.search(rule)
    if found is None:
        raise ValueError(
            f"{market['ticker']}: no direction in the rule text ({first_error})"
        )
    expected = DIRECTION[found["word"].lower()]
    listed = market.get("strike_type")
    if listed is not None and listed != expected:
        raise first_error
    if found["number"] is not None:
        number = Decimal(found["number"].replace(",", ""))
        suffix = (found["suffix"] or "").lower()
        source = "legacy_rule"
    else:
        sub = SUB_TITLE_STRIKE.match(market.get("yes_sub_title") or "")
        tick = TICKER_STRIKE.search(market["ticker"])
        if not sub or not tick:
            raise ValueError(
                f"{market['ticker']}: no strike in rule, subtitle or ticker"
            )
        number = Decimal(sub["number"].replace(",", ""))
        if Decimal(tick["number"]) != number:
            raise ValueError(
                f"{market['ticker']}: subtitle says {number}, ticker {tick['number']}"
            )
        suffix = (sub["suffix"] or "").lower()
        source = "sub_title_and_ticker"
    if suffix == "percent":
        suffix = "%"
    factors = contracts.UNIT_FACTORS[spec.canonical_unit]
    if suffix not in factors:
        raise ValueError(
            f"{market['ticker']}: unit {suffix!r} not valid for {spec.series}"
        )
    floor = market.get("floor_strike")
    # Kalshi stored some U-3 floors as 4.099999 for a rule that says 4.1.
    if floor is not None and abs(Decimal(str(floor)) - number) > FLOOR_TOLERANCE:
        raise ValueError(
            f"{market['ticker']}: text says {number}, floor_strike {floor}"
        )
    if floor is not None and Decimal(str(floor)) != number:
        source += "_floor_rounded"
    return Strike(number * factors[suffix], expected, source)


YEAR_TEXT = contracts.YEAR_TEXT
# Legacy rules also write "in July, 2021".
MONTH_COMMA_YEAR = re.compile(
    rf"\b(?P<month>{contracts.MONTH_WORD})\.?,\s+(?P<year>20\d{{2}})\b", re.I
)


def event_period(
    event: dict, markets: list[dict], cadence: str
) -> tuple[str | None, str, bool]:
    """(period, how it was read, whether the legacy relaxation was needed).

    #381's reading first: the title names one period and every market's rule
    names it. Legacy rules ("If the CPI increases by more than 0.6% in June")
    name the month without the year; such a rule is accepted only if it names
    the title's month, no other month and no year at all.
    """
    period, check = contracts.event_period(event, markets, cadence)
    if period is not None:
        return period, check, False
    if cadence != "monthly":
        return None, check, False
    title_periods = contracts.text_periods(
        f"{event.get('title', '')} {event.get('sub_title', '')}", cadence
    )
    if len(title_periods) != 1:
        return None, check, False
    (period,) = title_periods
    month = int(period[5:7])
    for market in markets:
        rule = contracts.normalize_text(market.get("rules_primary", ""))
        if period in contracts.text_periods(rule, cadence):
            continue
        comma = {
            official.month_period(m.group("month"), m.group("year"))
            for m in MONTH_COMMA_YEAR.finditer(rule)
        }
        if comma == {period}:
            continue
        months = {
            contracts.MONTHS[m.group("month").lower()]
            for m in contracts.MONTH_ALONE.finditer(rule)
        }
        if months != {month} or YEAR_TEXT.search(rule):
            return None, f"{market['ticker']} rule does not name {period}", False
    return period, "title names the period; legacy rules name its month alone", True


# Events --------------------------------------------------------------------


@dataclasses.dataclass
class Event:
    series: str
    spec: contracts.SeriesSpec
    event: dict
    markets: list[dict]
    period: str | None = None
    period_check: str = ""
    period_relaxed: bool = False
    strikes: dict[str, Strike] = dataclasses.field(default_factory=dict)
    dropped: list[dict] = dataclasses.field(default_factory=list)
    settled: bool = False
    official: official.OfficialPrint | None = None
    official_note: str = ""
    official_delayed: bool = False
    candidates_tried: list[str] = dataclasses.field(default_factory=list)
    event_markets_raw: list[dict] = dataclasses.field(default_factory=list)

    @property
    def ticker(self) -> str:
        return self.event["event_ticker"]

    @property
    def family(self) -> str:
        return FAMILIES[self.series]

    @property
    def generation(self) -> str:
        return generation(self.series, self.ticker)

    @property
    def strike_type(self) -> str | None:
        kinds = {s.strike_type for s in self.strikes.values()}
        return next(iter(kinds)) if len(kinds) == 1 else None

    @property
    def last_close(self) -> int:
        return max(kalshi.to_ts(m["close_time"]) for m in self.markets)

    @property
    def first_open(self) -> int:
        return min(kalshi.to_ts(m["open_time"]) for m in self.markets)

    @property
    def anchor(self) -> int | None:
        """The release instant, or the last market close if that is earlier."""
        if self.official is None:
            return None
        return min(kalshi.to_ts(self.official.release_at), self.last_close)

    @property
    def release_date(self) -> str | None:
        return None if self.official is None else self.official.release_at[:10]


def scoped_events(cache: FetchCache, series: str) -> tuple[list[dict], list[dict]]:
    """(events in scope, events of the series outside scope)."""
    spec = spec_for(series)
    inside, outside = [], []
    for event in kalshi.series_events(cache, series):
        if spec.event_prefix and not event["event_ticker"].startswith(
            spec.event_prefix
        ):
            outside.append(event)
        else:
            inside.append(event)
    return inside, outside


def build_event(cache: FetchCache, series: str, raw: dict) -> Event:
    spec = spec_for(series)
    markets = kalshi.event_markets(cache, raw["event_ticker"])
    event = Event(series, spec, raw, markets, event_markets_raw=list(markets))
    event.settled = bool(markets) and all(
        m.get("result") not in (None, "") for m in markets
    )
    if not event.settled:
        return event
    kept = []
    for market in markets:
        if market.get("result") not in ("yes", "no"):
            event.dropped.append(
                {
                    "ticker": market["ticker"],
                    "reason": f"result {market.get('result')!r}",
                }
            )
            continue
        try:
            event.strikes[market["ticker"]] = read_strike(market, spec)
        except ValueError as error:
            event.dropped.append({"ticker": market["ticker"], "reason": str(error)})
            continue
        kept.append(market)
    event.markets = kept
    if not kept:
        event.settled = False
        return event
    event.period, event.period_check, event.period_relaxed = event_period(
        raw, kept, spec.cadence
    )
    return event


# Official first prints -------------------------------------------------------

BLS_INDEX = "https://www.bls.gov/bls/news-release/{name}.htm"
BLS_NAMES = {
    "bls_cpi_headline": "cpi",
    "bls_cpi_core": "cpi",
    "bls_payrolls": "empsit",
    "bls_unemployment": "empsit",
    "bls_jolts_openings": "jolts",
}
ARCHIVE_LINK = re.compile(
    r"/news\.release/archives/(?P<name>[a-z]+)_(?P<date>\d{8})\.htm"
)
SEARCH_DAYS = 150


def period_end(period: str) -> dt.date:
    if len(period) == 10:
        return dt.date.fromisoformat(period)
    year, month = int(period[:4]), int(period[5:7])
    following = dt.date(year + (month == 12), month % 12 + 1, 1)
    return following - dt.timedelta(days=1)


def close_date_et(market: dict) -> dt.date:
    instant = dt.datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
    return instant.astimezone(official.ET).date()


def bls_archive_dates(cache: FetchCache, name: str) -> list[dt.date]:
    body = cache.get(
        BLS_INDEX.format(name=name), user_agent=BROWSER_COMPATIBLE_UA, accept="*/*"
    )
    dates = set()
    for found in ARCHIVE_LINK.finditer(body.decode("utf-8", "replace")):
        if found["name"] == name:
            dates.add(dt.datetime.strptime(found["date"], "%m%d%Y").date())
    return sorted(dates)


class NoOfficialValueError(LookupError):
    """No release published a value for the period."""


def _parse(cache: FetchCache, source: official.Source):
    body = cache.get(
        source.url, user_agent=BROWSER_COMPATIBLE_UA, accept="*/*", allow_404=True
    )
    if body is None:
        return None
    text = official.pdf_text(body) if source.kind == "pdf" else official.html_text(body)
    return text, source.parse(text)


def _print(
    cache: FetchCache, key: str, period: str, url: str, value, second, release_at
) -> official.OfficialPrint:
    if second is not None:
        tolerance = Decimal("0.05") if key == "bls_jolts_openings" else Decimal(0)
        if abs(second - value) > tolerance:
            raise official.OfficialParseError(
                f"{url}: readings {value} and {second} differ"
            )
    return official.OfficialPrint(
        statistic=key,
        period=period,
        value=value,
        release_at=release_at,
        source_url=url,
        source_sha256=cache.sha256_of(url),
        table_reading=str(value),
        second_reading=None if second is None else str(second),
    )


def locate_print(cache: FetchCache, event: Event) -> None:
    """Find the period's first print; sets ``event.official`` or the note."""
    key, period = event.spec.official, event.period
    hint = max(close_date_et(m) for m in event.markets)
    try:
        if key in BLS_NAMES:
            found = _bls_print(cache, event, key, period, hint)
        elif key in ("dol_initial_claims", "dol_continued_claims"):
            found = _dol_print(cache, event, key, period, hint)
        elif key == "bea_core_pce":
            found = _bea_print(cache, event, key, period)
        else:
            source = official.source_for(key, period, hint)
            event.candidates_tried.append(source.url)
            parsed = _parse(cache, source)
            if parsed is None:
                raise official.OfficialParseError(f"404 for {source.url}")
            got_period, value, second, release_at = parsed[1]
            if got_period != period:
                raise official.OfficialParseError(
                    f"{source.url} reports {got_period}, expected {period}"
                )
            found = _print(cache, key, period, source.url, value, second, release_at)
    except (NoOfficialValueError, official.NoValuePublishedError) as error:
        event.official_note = f"no official value: {error}"
        return
    except (official.OfficialParseError, ValueError, KeyError) as error:
        event.official_note = f"{type(error).__name__}: {error}"
        return
    event.official = found


BLS_TITLES = {
    "cpi": "CONSUMER PRICE INDEX",
    "empsit": "THE EMPLOYMENT SITUATION",
    "jolts": "JOB OPENINGS AND LABOR TURNOVER",
}


def bls_title_period(text: str, name: str) -> str | None:
    found = re.search(
        rf"{BLS_TITLES[name]}\s*\W+\s*({contracts.MONTH_WORD})\s+(\d{{4}})", text, re.I
    )
    return None if not found else official.month_period(found.group(1), found.group(2))


def _bls_print(cache, event, key, period, hint):
    """The first archived release that publishes the period's value.

    Candidates are every archive date in the agency's index from the period's
    end to 150 days later, plus the market's close date. A release titled for
    the period is its first print; if the first release titled for a later
    month comes first, the period's column there is (a delayed release).
    """
    name = BLS_NAMES[key]
    end = period_end(period)
    dates = sorted(
        {
            d
            for d in bls_archive_dates(cache, name)
            if end < d <= end + dt.timedelta(SEARCH_DAYS)
        }
        | {hint}
    )
    for date in dates:
        source = official.source_for(key, period, date)
        event.candidates_tried.append(source.url)
        body = cache.get(
            source.url, user_agent=BROWSER_COMPATIBLE_UA, accept="*/*", allow_404=True
        )
        if body is None:
            continue
        text = official.html_text(body)
        titled = bls_title_period(text, name)
        if titled is None:
            raise official.OfficialParseError(f"{source.url}: no release title")
        if titled < period:
            continue
        if titled == period:
            try:
                got, value, second, release_at = source.parse(text)
            except official.NoValuePublishedError as error:
                raise NoOfficialValueError(f"{source.url}: {error}") from error
            return _print(cache, key, period, source.url, value, second, release_at)
        event.official_delayed = True
        value = prior_column_value(text, key, period)
        if value is None:
            raise NoOfficialValueError(
                f"{source.url} (for {titled}) is the first later release and"
                f" publishes no {period} value"
            )
        return _print(
            cache, key, period, source.url, value, None, official.bls_release_at(text)
        )
    raise official.OfficialParseError(f"no BLS release found for {period}")


def prior_column_value(text: str, key: str, period: str) -> Decimal | None:
    """The period's value in a later release's table column, or None."""
    if key == "bls_payrolls":
        table = re.search(
            r"Summary table B\. Establishment data, seasonally adjusted Category (.*?) "
            r"EMPLOYMENT BY SELECTED INDUSTRY \(Over-the-month change, in thousands\) "
            r"Total nonfarm\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
            text,
        )
        header_at, first = 1, 2
        scale = Decimal(1000)
    elif key == "bls_unemployment":
        table = re.search(
            r"Summary table A\. Household data, seasonally adjusted \[Numbers in"
            r" thousands\] Category (.*?) Employment status .*? Unemployment"
            r" rate\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
            text,
        )
        header_at, first = 1, 2
        scale = Decimal(1)
    elif key in ("bls_cpi_headline", "bls_cpi_core"):
        return _cpi_prior_column(text, key, period)
    else:
        return None
    if not table:
        return None
    header = re.findall(
        rf"({contracts.MONTH_WORD})\.?\s+(20\d\d)", table.group(header_at), re.I
    )
    columns = [official.month_period(*h) for h in header]
    if period not in columns:
        return None
    cell = table.group(first + columns.index(period)).rstrip("()p")
    try:
        return official.to_decimal(cell) * scale
    except ArithmeticError:
        return None


def _cpi_prior_column(text: str, key: str, period: str) -> Decimal | None:
    """A month's CPI change from a later release's Table A, or None for a dash."""
    start = text.find("Table A. Percent changes in CPI for All Urban Consumers")
    if start < 0:
        return None
    table = re.sub(
        rf"12-mos\.?\s+ended\s+{contracts.MONTH_WORD}\.?\s+20\d\d",
        " ",
        text[start : start + 6000],
        flags=re.I,
    )
    header = [
        official.month_period(*h)
        for h in re.findall(
            rf"({contracts.MONTH_WORD})\.?\s+(20\d\d)", table[:600], re.I
        )
    ][:7]
    if period not in header:
        return None
    label = (
        "All items" if key == "bls_cpi_headline" else "All items less food and energy"
    )
    cell = r"(?:-?\d*\.\d|-(?=\s))"
    values = re.search(rf"\b{re.escape(label)}\.*\s+((?:{cell}\s+){{7}}{cell})", table)
    if not values:
        return None
    token = values.group(1).split()[header.index(period)]
    return None if token == "-" else Decimal(token)


def _dol_print(cache, event, key, period, hint):
    errors = []
    for offset in (0, -1, 1, -2, 2, -3, 3, 4, 5, 6, 7):
        date = hint + dt.timedelta(days=offset)
        source = official.source_for(key, period, date)
        event.candidates_tried.append(source.url)
        try:
            parsed = _parse(cache, source)
        except official.OfficialParseError as error:
            errors.append(f"{source.url}: {error}")
            continue
        if parsed is None:
            continue
        got_period, value, second, release_at = parsed[1]
        if got_period == period:
            return _print(cache, key, period, source.url, value, second, release_at)
    raise official.OfficialParseError(
        f"no DOL release found for week ending {period}; {'; '.join(errors)}"
    )


BEA_RELEASE = "https://www.bea.gov/news/{year}/personal-income-and-outlays-{slug}"
_MW = contracts.MONTH_WORD
BEA_EMBARGO = re.compile(
    r"EMBARGOED UNTIL RELEASE AT\s+(\d{1,2}):(\d{2})\s+([ap])\.m\.\s+(?:EDT|EST|ET),"
    r"\s+[A-Za-z]+,?\s+([A-Za-z]+ \d{1,2}, \d{4})",
    re.I,
)
BEA_TITLE = re.compile(
    rf"Personal Income and Outlays,\s+({_MW})(?:\s+and\s+({_MW}))?\s+(\d{{4}})", re.I
)
CORE_ROW = r"PCE price index,? excluding food and energy"
BEA_TWO_COLUMNS = re.compile(
    rf"Related Measures \[Percent change from preceding month\]\s+({_MW})\s+({_MW})"
    rf"\s+.{{0,600}}?{CORE_ROW}\s+(-?\d+\.\d)\s+(-?\d+\.\d)",
    re.I,
)
BEA_FROM_TO = re.compile(
    rf"Related Measures \[Percent change from ({_MW})\.? to ({_MW})\.?\]"
    rf"\s+.{{0,600}}?{CORE_ROW}\s+(-?\d+\.\d)",
    re.I,
)
# 2022-2024 pages: "2022 July Aug. Sept. Oct. Nov. Percent change from
# preceding month ... PCE, excluding food and energy 0.1 0.6 0.5 0.3 0.2".
BEA_FIVE_COLUMNS = re.compile(
    rf"((?:(?:{_MW})\.?\s+|20\d\d\s+){{5,7}})Percent change from preceding month"
    r" .{0,700}?PCE, excluding food and energy\s+((?:-?\d+\.\d\s+){4}-?\d+\.\d)",
    re.I,
)
BEA_LEAD = re.compile(
    r"Excluding food and energy, the PCE price index\s+(?:also\s+)?"
    r"(increased|decreased|rose|fell|declined|was unchanged)"
    r"(?:\s+(\d+\.\d) percent)?(?P<rest>[^.]{0,60})",
    re.I,
)


def bea_core_pce(text: str, period: str) -> tuple[Decimal, Decimal | None, str, str]:
    """(value, second reading, release instant, how it was read) for a month.

    BEA's release pages have used four layouts for the month's core PCE
    change: a two-column table "[Percent change from preceding month]" (with
    or without a comma before "excluding"), a one-column "[Percent Change From
    July to August]" table, a combined "October and November 2025" release
    whose two columns are those months, and 2022-2023 pages with no table, which
    state the change only in the text. The monthly lead sentence is the second
    reading where it names one month's change.
    """
    released = BEA_EMBARGO.search(text)
    title = BEA_TITLE.search(text)
    if not released or not title:
        raise official.OfficialParseError("BEA embargo statement or title not found")
    year = title.group(3)
    titled = [official.month_period(title.group(1), year)]
    if title.group(2):
        titled.append(official.month_period(title.group(2), year))
    if period not in titled:
        raise official.OfficialParseError(f"BEA release is for {titled}, not {period}")
    month = int(period[5:7])
    leads = [
        official.signed_change(m.group(1), m.group(2))
        for m in BEA_LEAD.finditer(text)
        if "year ago" not in m.group("rest") and "same month" not in m.group("rest")
    ]
    monthly_lead = leads[0] if leads and len(titled) == 1 else None
    if len(titled) == 2 and re.search(
        r"Excluding food and energy, the PCE price index\s+(?:also\s+)?increased"
        r" (\d+\.\d) percent in both months",
        text,
    ):
        monthly_lead = Decimal(
            re.search(r"increased (\d+\.\d) percent in both months", text).group(1)
        )
    two = BEA_TWO_COLUMNS.search(text)
    if two:
        columns = [contracts.MONTHS[two.group(i).lower()] for i in (1, 2)]
        if month not in columns:
            raise official.OfficialParseError(
                "BEA table columns do not include the month"
            )
        value = Decimal(two.group(3 + columns.index(month)))
        if len(titled) == 1 and columns[1] != month:
            raise official.OfficialParseError(
                "BEA table's second column is not the month"
            )
        how = "two-column table"
    elif (one := BEA_FROM_TO.search(text)) is not None:
        if contracts.MONTHS[one.group(2).lower()] != month:
            raise official.OfficialParseError("BEA table is not for the month")
        value, how = Decimal(one.group(3)), "from-to table"
    elif (five := BEA_FIVE_COLUMNS.search(text)) is not None:
        months = re.findall(_MW, five.group(1), re.I)
        if len(months) != 5 or contracts.MONTHS[months[-1].lower()] != month:
            raise official.OfficialParseError(
                "BEA table's last column is not the month"
            )
        value, how = Decimal(five.group(2).split()[-1]), "five-column table"
    elif monthly_lead is not None:
        others = leads[1:]
        value, how = monthly_lead, "release text (no table on the page)"
        monthly_lead = others[0] if others else None
    else:
        raise official.OfficialParseError("BEA core PCE change not found")
    return value, monthly_lead, official.release_instant(*released.groups()), how


def _bea_slugs(period: str) -> list[tuple[int, str]]:
    year, month = int(period[:4]), int(period[5:7])
    name = official.MONTH_SLUG[month]
    slugs = [f"{name}-{year}"]
    if month > 1:
        slugs.append(f"{official.MONTH_SLUG[month - 1]}-and-{name}-{year}")
    if month < 12:
        slugs.append(f"{name}-and-{official.MONTH_SLUG[month + 1]}-{year}")
    return [(release_year, slug) for slug in slugs for release_year in (year, year + 1)]


def _bea_print(cache, event, key, period):
    for release_year, slug in _bea_slugs(period):
        url = BEA_RELEASE.format(year=release_year, slug=slug)
        event.candidates_tried.append(url)
        body = cache.get(
            url, user_agent=BROWSER_COMPATIBLE_UA, accept="*/*", allow_404=True
        )
        if body is None:
            continue
        value, second, release_at, how = bea_core_pce(official.html_text(body), period)
        event.official_note = f"BEA {how}"
        event.official_delayed = "-and-" in slug
        return _print(cache, key, period, url, value, second, release_at)
    raise official.OfficialParseError(f"no BEA release page found for {period}")


def settlement_agreement(event: Event) -> list[dict]:
    """One row per market: the official print under its rule vs Kalshi's result."""
    rows = []
    for market in event.markets:
        strike = event.strikes[market["ticker"]]
        row = {
            "eventTicker": event.ticker,
            "ticker": market["ticker"],
            "strike": str(strike.value),
            "strikeType": strike.strike_type,
            "strikeSource": strike.source,
            "kalshiResult": market["result"],
            "kalshiExpirationValue": market.get("expiration_value"),
        }
        if event.official is not None:
            yes = contracts.market_yes(
                "ladder", strike.strike_type, strike.value, event.official.value
            )
            row["officialValue"] = str(event.official.value)
            row["officialResult"] = "yes" if yes else "no"
            row["agrees"] = row["officialResult"] == market["result"]
        rows.append(row)
    return rows


EXPIRATION_NUMBER = re.compile(r"^\s*(-?[\d,]*\.?\d+)\s*%?\s*$")
EXPIRATION_SCALES = (
    Decimal(1),
    Decimal(1000),
    Decimal("0.001"),
    Decimal(10) ** 6,
    Decimal(10) ** -6,
)


def expiration_value(event: Event) -> Decimal | None:
    """Kalshi's recorded underlying value, if every market records the same number.

    The field holds the number as Kalshi wrote it (".9%", "119,000", "4.4",
    "1710000" or "1701" for continuing claims in millions).
    """
    values = set()
    for market in event.markets:
        found = EXPIRATION_NUMBER.match(market.get("expiration_value") or "")
        if not found:
            return None
        values.add(Decimal(found.group(1).replace(",", "")))
    return values.pop() if len(values) == 1 else None


def expiration_agrees(event: Event) -> bool | None:
    """Whether Kalshi's recorded value equals the official print, up to x1,000 steps.

    None when there is no official print or no single numeric recorded value.
    """
    recorded = expiration_value(event)
    if recorded is None or event.official is None:
        return None
    return any(recorded * scale == event.official.value for scale in EXPIRATION_SCALES)
