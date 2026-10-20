"""Which Thesis targets match which Kalshi series, and what each contract means.

Each spec states the Kalshi series, the reporting grid of the published value
in the contract's strike units, the conversion from Thesis's unit to those
units, and which official release resolves it. Reference periods are read from
Kalshi's own event and rule text, never from ticker spelling alone.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
import unicodedata
from decimal import Decimal

MONTHS = {
    name: index
    for index, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
MONTH_WORD = r"(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")"


@dataclasses.dataclass(frozen=True)
class ThesisPattern:
    regex: re.Pattern
    units: tuple[str, ...]  # accepted Thesis units
    to_strike: Decimal  # multiply a Thesis value by this to get strike units


@dataclasses.dataclass(frozen=True)
class SeriesSpec:
    series: str
    statistic: str
    cadence: str  # monthly | weekly
    patterns: tuple[ThesisPattern, ...]
    grid: Decimal  # reporting grid of the published value, in strike units
    official: str  # key into official.PARSERS
    kind: str  # ladder | exact
    primary: bool
    release_hour_et: tuple[int, int]
    canonical_unit: str = "percent"  # percent | persons | millions (strike units)
    event_prefix: str | None = None  # for multi-country series such as KXUE

    def match(self, data_point_id: str) -> tuple[str, ThesisPattern] | None:
        for pattern in self.patterns:
            found = pattern.regex.match(data_point_id)
            if found:
                return period_from_groups(found.groupdict(), self.cadence), pattern
        return None


def _p(regex: str, units: tuple[str, ...], to_strike: str = "1") -> ThesisPattern:
    return ThesisPattern(re.compile(regex), units, Decimal(to_strike))


PCT = ("percent_growth", "percent")
MONTH_NAME = r"(?P<month>[a-z]+)_(?P<year>\d{4})"

CPI_HEADLINE = (_p(rf"^bls\.cpi\.u\.headline_mom\.{MONTH_NAME}\.first_print$", PCT),)
CPI_CORE = (_p(rf"^bls\.cpi\.u\.core_mom\.{MONTH_NAME}\.first_print$", PCT),)
UNEMPLOYMENT = (_p(rf"^bls\.cps\.unemployment_rate\.{MONTH_NAME}\.first_print$", PCT),)

SPECS: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "KXCPI",
        "CPI-U all items, SA % change",
        "monthly",
        CPI_HEADLINE,
        Decimal("0.1"),
        "bls_cpi_headline",
        "ladder",
        True,
        (8, 30),
    ),
    SeriesSpec(
        "KXCPICORE",
        "CPI-U less food and energy, SA % change",
        "monthly",
        CPI_CORE,
        Decimal("0.1"),
        "bls_cpi_core",
        "ladder",
        True,
        (8, 30),
    ),
    SeriesSpec(
        "KXU3",
        "U-3 unemployment rate",
        "monthly",
        UNEMPLOYMENT,
        Decimal("0.1"),
        "bls_unemployment",
        "ladder",
        True,
        (8, 30),
    ),
    SeriesSpec(
        "KXPAYROLLS",
        "Total nonfarm payroll change",
        "monthly",
        (
            _p(
                r"^bls\.ces\.total_nonfarm\.payroll_employment\.change\.sa\."
                r"(?P<year>\d{4})-(?P<mm>\d{2})\.first_print$",
                ("thousands",),
                "1000",
            ),
            _p(
                r"^bls\.ces\.nonfarm_payrolls\.change\.(?P<year>\d{4})_(?P<mm>\d{2})"
                r"\.first_print$",
                ("thousands",),
                "1000",
            ),
            _p(
                rf"^bls\.ces\.total_nonfarm_payroll_change\.{MONTH_NAME}\.first_print$",
                ("thousands",),
                "1000",
            ),
        ),
        Decimal("1000"),
        "bls_payrolls",
        "ladder",
        True,
        (8, 30),
        "persons",
    ),
    SeriesSpec(
        "KXJOBLESSCLAIMS",
        "Initial claims, SA advance",
        "weekly",
        (
            _p(
                r"^us\.dol\.initial_claims\.sa\.week_(?P<week>\d{4}-\d{2}-\d{2})$",
                ("thousands",),
                "1000",
            ),
            _p(
                r"^dol\.eta\.initial_claims\.sa\.week_ending_(?P<y>\d{4})_(?P<m>\d{2})"
                r"_(?P<d>\d{2})$",
                ("thousands",),
                "1000",
            ),
        ),
        Decimal("1000"),
        "dol_initial_claims",
        "ladder",
        True,
        (8, 30),
        "persons",
    ),
    SeriesSpec(
        "KXCONTCLAIMS",
        "Insured unemployment (continuing claims), SA advance",
        "weekly",
        (
            _p(
                r"^dol\.eta\.continued_claims\.sa\.week_(?P<week>\d{4}-\d{2}-\d{2})"
                r"\.first_print$",
                ("millions",),
            ),
        ),
        Decimal("0.001"),
        "dol_continued_claims",
        "ladder",
        True,
        (8, 30),
        "millions",
    ),
    SeriesSpec(
        "KXJOLTSOPEN",
        "JOLTS job openings, SA",
        "monthly",
        (
            _p(
                rf"^bls\.jolts\.job_openings\.{MONTH_NAME}\.first_print$", ("millions",)
            ),
            _p(
                r"^bls\.jolts\.job_openings\.(?P<year>\d{4})_(?P<mm>\d{2})\.first_print$",
                ("millions",),
            ),
            _p(
                rf"^bls\.jolts\.job_openings_total\.{MONTH_NAME}\.first_print$",
                ("thousands",),
                "0.001",
            ),
        ),
        Decimal("0.001"),
        "bls_jolts_openings",
        "ladder",
        True,
        (10, 0),
        "millions",
    ),
    SeriesSpec(
        "KXPCECORE",
        "PCE price index less food and energy, % change",
        "monthly",
        (
            _p(r"^us\.bea\.core_pce\.mom_sa\.(?P<year>\d{4})-(?P<mm>\d{2})$", PCT),
            _p(rf"^bea\.pce\.core_mom\.{MONTH_NAME}\.first_print$", PCT),
        ),
        Decimal("0.1"),
        "bea_core_pce",
        "ladder",
        True,
        (8, 30),
    ),
    SeriesSpec(
        "KXHOUSINGSTART",
        "Housing starts, SAAR",
        "monthly",
        (
            _p(
                r"^census\.housing_starts\.saar\.(?P<year>\d{4})-(?P<mm>\d{2})"
                r"\.first_print$",
                ("millions",),
            ),
        ),
        Decimal("0.001"),
        "census_starts",
        "ladder",
        True,
        (8, 30),
        "millions",
    ),
    SeriesSpec(
        "KXBUILDPERMS",
        "Building permits, SAAR",
        "monthly",
        (
            _p(
                r"^census\.housing\.permits_saar\.(?P<year>\d{4})_(?P<mm>\d{2})"
                r"\.first_print$",
                ("thousands",),
                "0.001",
            ),
        ),
        Decimal("0.001"),
        "census_permits",
        "ladder",
        True,
        (8, 30),
        "millions",
    ),
    SeriesSpec(
        "KXNHSALES",
        "New single-family houses sold, SAAR",
        "monthly",
        (
            _p(
                r"^census\.new_residential_sales\.new_single_family_houses_sold_saar\."
                r"(?P<year>\d{4})_(?P<mm>\d{2})\.first_print$",
                ("thousands",),
                "1000",
            ),
        ),
        Decimal("1000"),
        "census_new_home_sales",
        "ladder",
        True,
        (10, 0),
        "persons",
    ),
    SeriesSpec(
        "KXUE",
        "Australia unemployment rate, SA",
        "monthly",
        (
            _p(
                r"^abs\.labour\.unemployment_rate\.(?P<year>\d{4})_(?P<mm>\d{2})"
                r"\.first_print$",
                PCT,
            ),
            _p(
                rf"^abs\.labour\.unemployment_rate\.australia\.{MONTH_NAME}"
                r"\.first_print$",
                PCT,
            ),
        ),
        Decimal("0.1"),
        "abs_unemployment",
        "ladder",
        True,
        (11, 30),
        "percent",
        "KXUE-AUS",
    ),
    SeriesSpec(
        "KXECONSTATCPI",
        "CPI-U all items, SA % change (exact value)",
        "monthly",
        CPI_HEADLINE,
        Decimal("0.1"),
        "bls_cpi_headline",
        "exact",
        False,
        (8, 30),
    ),
    SeriesSpec(
        "KXECONSTATCPICORE",
        "Core CPI-U, SA % change (exact value)",
        "monthly",
        CPI_CORE,
        Decimal("0.1"),
        "bls_cpi_core",
        "exact",
        False,
        (8, 30),
    ),
    SeriesSpec(
        "KXECONSTATU3",
        "U-3 unemployment rate (exact value)",
        "monthly",
        UNEMPLOYMENT,
        Decimal("0.1"),
        "bls_unemployment",
        "exact",
        False,
        (8, 30),
    ),
)

# Thesis families for which the Kalshi catalog (screened 2026-10-20) has a
# related series that does not give a scorable match. The pipeline checks
# each related series' events for the run's period and records what it found.
RELATED: tuple[tuple[re.Pattern, tuple[str, ...], str], ...] = tuple(
    (re.compile(pattern), series, note)
    for pattern, series, note in (
        (r"^bls\.wp\.WPSFD4", ("KXUSPPI",), "same statistic"),
        (r"^bls\.cpi\.owners_equivalent_rent", ("KXOER",), "same statistic"),
        (
            r"^bls\.cpi\.shelter_mom",
            ("KXSHELTERCPI",),
            (
                "Kalshi's market is on the index level, Thesis's target on the monthly"
                " change"
            ),
        ),
        (r"^census\.m3\.durable_goods_new_orders", ("KXUSDURABLE",), "same statistic"),
        (r"^fed\.g17\.industrial_production", ("KXUSIPMOM",), "same statistic"),
        (r"^bea\.pce_price_index\.monthly_change", ("KXPCEHEAD",), "same statistic"),
        (r"^statcan\.cpi\.allitems\.yoy", ("KXCACPIYOY",), "same statistic"),
        (r"^ons\.cpi\.annual_rate", ("KXUKCPIYOY",), "same statistic"),
        (
            r"^statjp\.cpi\.tokyo",
            ("KXJPCPIYOY",),
            "Kalshi's market is national CPI, Thesis's target is Tokyo CPI",
        ),
        (
            r"^bea\.disposable_personal_income",
            ("KXUSPINCOME",),
            "Kalshi's market is personal income growth, Thesis's target the DPI level",
        ),
        (
            r"^bls\.real_earnings\.avg_hourly_mom",
            ("KXREALWAGES", "KXAHEMOM"),
            "Kalshi's markets are custom-period real wage growth and nominal earnings",
        ),
        (
            r"^treasury\.mts\.monthly_deficit",
            ("KXDEFICIT", "KXUSDEBTMON"),
            "Kalshi's markets are on deficit size by date and the debt level",
        ),
        (
            r"^bea\.trade\.goods_services_deficit",
            ("KXTRADEDEFFICIT", "KXTRADEDEFICIT"),
            "Kalshi's markets are custom-period and annual",
        ),
        (
            r"^bls\.productivity\.nonfarm_qoq",
            ("KXNFPROD",),
            "Kalshi's market is year-over-year growth in any quarter of a year",
        ),
        (
            r"^eurostat\.une_rt_m\.unemployment_rate\.belgium",
            ("KXUE",),
            "KXUE's events for that month are for single countries, none for Belgium",
        ),
        (
            r"^eurostat\.unemployment_rate\.euro_area",
            ("KXUE",),
            (
                "KXUE's events for that month are for single countries, none for the"
                " euro area"
            ),
        ),
    )
)


# Other Kalshi series on statistics already matched above (older tickers and
# second venues). The pipeline lists their events for every matched period so
# a second venue is never silently ignored.
ALTERNATE_VENUES: dict[str, tuple[str, ...]] = {
    "KXCPI": ("CPI",),
    "KXCPICORE": ("CPICORE",),
    "KXU3": ("U3",),
    "KXPAYROLLS": ("KXUSNFP", "PAYROLLS", "KXPROLLS", "PROLLS"),
    "KXJOBLESSCLAIMS": ("KXJOBLESS", "JOBLESS"),
    "KXPCECORE": ("PCECORE",),
    "KXHOUSINGSTART": ("KXHOUSESTART", "HOUSESTART"),
    "KXNHSALES": ("KXHOME", "HOME"),
}


def related_series(data_point_id: str) -> tuple[tuple[str, ...], str] | None:
    for regex, series, note in RELATED:
        if regex.match(data_point_id):
            return series, note
    return None


PERIOD_TOKENS = (
    (re.compile(r"week_(\d{4})-(\d{2})-(\d{2})"), "week"),
    (re.compile(rf"(?<![a-z])({MONTH_WORD})_(\d{{4}})"), "month_name"),
    (re.compile(r"(?<!\d)(\d{4})[-_](\d{2})(?![-_\d])"), "year_month"),
    (re.compile(r"(?<!\d)(\d{4})_q([1-4])(?!\d)"), "quarter"),
)


def period_of(data_point_id: str) -> str | None:
    """Best-effort reference period of a Thesis data point, for the inventory."""
    for regex, kind in PERIOD_TOKENS:
        found = regex.search(data_point_id)
        if not found:
            continue
        if kind == "week":
            return "-".join(found.groups())
        if kind == "quarter":
            return f"{found.group(1)}-Q{found.group(2)}"
        if kind == "month_name":
            return f"{int(found.group(2)):04d}-{MONTHS[found.group(1)]:02d}"
        year, month = int(found.group(1)), int(found.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    return None


# Invisible characters Unicode classes as letters (Kalshi titled one event
# "May\u3164 2, 2026", with a Hangul filler where a space belongs).
INVISIBLE_LETTERS = {"\u115f", "\u1160", "\u3164", "\uffa0"}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(
        (
            " "
            if c in INVISIBLE_LETTERS or unicodedata.category(c).startswith(("Z", "C"))
            else c
        )
        for c in text
    )
    return re.sub(r"\s+", " ", text).strip()


def period_from_groups(groups: dict, cadence: str) -> str:
    if cadence == "weekly":
        if groups.get("week"):
            return groups["week"]
        return f"{groups['y']}-{groups['m']}-{groups['d']}"
    year = int(groups["year"])
    if groups.get("mm"):
        month = int(groups["mm"])
    else:
        month = MONTHS[groups["month"]]
    return f"{year:04d}-{month:02d}"


WEEK_ENDING = re.compile(
    r"week"
    rf" ending\s+(?P<month>{MONTH_WORD})\.?\s+(?P<day>\d{{1,2}})"
    r"(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})",
    re.I,
)
# Older weekly titles: "Initial jobless claims, Sep 18 to 24, 2022?"
WEEK_RANGE = re.compile(
    rf"(?P<month>{MONTH_WORD})\.?\s+\d{{1,2}}\s*(?:-|to)\s*(?P<day>\d{{1,2}}),?\s+"
    r"(?P<year>\d{4})",
    re.I,
)
MONTH_YEAR = re.compile(rf"\b(?P<month>{MONTH_WORD})\.?\s+(?P<year>20\d{{2}})\b", re.I)


def text_periods(text: str, cadence: str) -> set[str]:
    text = normalize_text(text)
    if cadence == "weekly":
        found = list(WEEK_ENDING.finditer(text)) or list(WEEK_RANGE.finditer(text))
        return {
            f"{int(m['year']):04d}-{MONTHS[m['month'].lower()]:02d}-{int(m['day']):02d}"
            for m in found
        }
    return {
        f"{int(m['year']):04d}-{MONTHS[m['month'].lower()]:02d}"
        for m in MONTH_YEAR.finditer(text)
    }


def event_period(
    event: dict, markets: list[dict], cadence: str
) -> tuple[str | None, str]:
    """Reference period agreed by the event title and every market's rules."""
    title_periods = text_periods(
        f"{event.get('title', '')} {event.get('sub_title', '')}", cadence
    )
    if len(title_periods) != 1:
        return None, f"event title names {sorted(title_periods) or 'no'} period"
    (period,) = title_periods
    for market in markets:
        rule_periods = text_periods(market.get("rules_primary", ""), cadence)
        if period not in rule_periods:
            return None, f"{market['ticker']} rules name {sorted(rule_periods)}"
    return period, "title and every market's rules agree"


def week_ending_date(period: str) -> dt.date:
    return dt.date.fromisoformat(period)


RULE_STRIKE = re.compile(
    r"(?P<word>more than|above|at least|exactly)\s+(?P<number>-?[\d,]*\.?\d+)\s*"
    r"(?P<suffix>%|K\b|k\b|M\b|million|thousand)?",
    re.I,
)
UNIT_FACTORS = {
    # canonical unit -> {suffix as written in the rule: factor to canonical}
    "percent": {"%": Decimal(1)},
    "persons": {"": Decimal(1), "k": Decimal(1000), "thousand": Decimal(1000)},
    "millions": {
        "m": Decimal(1),
        "million": Decimal(1),
        "k": Decimal("0.001"),
        "thousand": Decimal("0.001"),
    },
}


def strike_of(market: dict, spec: "SeriesSpec") -> Decimal:
    """The strike in the series' canonical unit, as the market's rule states it.

    Kalshi has changed a series' strike unit between events (continuing claims
    moved from "1.84 million" to "1750K" in September 2026), so the unit is
    read from each market's own rule text and checked against ``floor_strike``
    (or, for exact-value markets, the "Exactly X" subtitle).
    """
    rule = normalize_text(market.get("rules_primary", ""))
    found = RULE_STRIKE.search(rule)
    if not found:
        raise ValueError(f"{market['ticker']}: no strike in the rule text")
    number = Decimal(found["number"].replace(",", ""))
    suffix = (found["suffix"] or "").lower()
    factors = UNIT_FACTORS[spec.canonical_unit]
    if suffix not in factors:
        raise ValueError(
            f"{market['ticker']}: unit {suffix!r} not valid for {spec.series}"
        )
    if spec.kind == "ladder":
        if market.get("strike_type") not in ("greater", "greater_or_equal"):
            raise ValueError(
                f"{market['ticker']}: unexpected strike_type"
                f" {market.get('strike_type')}"
            )
        listed = Decimal(str(market["floor_strike"]))
    else:
        exact = re.search(
            r"Exactly\s+(-?\d+(?:\.\d+)?)", market.get("yes_sub_title") or ""
        )
        if not exact:
            raise ValueError(f"{market['ticker']}: cannot read the exact value")
        listed = Decimal(exact.group(1))
    word = found["word"].lower()
    expected = {
        "more than": "greater",
        "above": "greater",
        "at least": "greater_or_equal",
        "exactly": None,
    }[word]
    if spec.kind == "ladder" and market.get("strike_type") != expected:
        raise ValueError(
            f"{market['ticker']}: rule says {word!r} but strike_type is "
            f"{market.get('strike_type')}"
        )
    if listed != number:
        raise ValueError(
            f"{market['ticker']}: rule says {number}, strike field says {listed}"
        )
    return number * factors[suffix]


def market_yes(kind: str, strike_type: str, strike: Decimal, value: Decimal) -> bool:
    """Whether a market settles YES for the published value, per its rule."""
    if kind == "exact":
        return value == strike
    if strike_type == "greater":
        return value > strike
    if strike_type == "greater_or_equal":
        return value >= strike
    raise ValueError(strike_type)


def match_target(data_point_id: str) -> list[tuple[SeriesSpec, str, ThesisPattern]]:
    out = []
    for spec in SPECS:
        found = spec.match(data_point_id)
        if found:
            out.append((spec, found[0], found[1]))
    return out
