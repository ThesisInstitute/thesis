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

# Thesis families for which the Kalshi catalog has a related series that does
# not give a scorable match. The pipeline checks each related series' events
# for the run's period and records what it found; a "same statistic" series
# that lists the period stops the run, since it would need a SeriesSpec. Series
# that share a note (older tickers) are named together in it.
SAME = "same statistic"
_REAL_WAGES = "KXREALWAGES and REALWAGES are on custom-period real wage growth"
_DEBT = (
    "KXUSDEBTMON, KXTRUFPDEBT, KXDEBTLEVEL, KXUSDEBT and the KXDEBTGROWTH and"
    " DEBTSHRINK series are on the federal debt level or its change, not the"
    " monthly deficit"
)
_DEFICIT_BY_DATE = "KXDEFICIT and KXTDEFFICITBY are on the deficit's size by a date"
_TRADE_ANNUAL = (
    "KXTRADEDEFFICIT and KXTRADEDEFICIT are on custom-period or annual deficits"
)
_CREDIT_CARD = (
    "CRED and KXCRED are on the total credit card debt level in a quarter, not"
    " the G.19 annual growth rate"
)
RELATED: tuple[tuple[re.Pattern, tuple[tuple[str, str], ...]], ...] = tuple(
    (re.compile(pattern), pairs)
    for pattern, pairs in (
        (
            r"^bls\.wp\.WPSFD4",
            (
                ("KXUSPPI", SAME),
                (
                    "KXUSPPIYOY",
                    "KXUSPPIYOY is on the 12-month change, Thesis's target on the"
                    " monthly change; converting one to the other needs the index"
                    " levels twelve months and one month before, as published at"
                    " the release and on the same seasonal basis, which this study"
                    " does not model",
                ),
            ),
        ),
        (r"^bls\.cpi\.owners_equivalent_rent", (("KXOER", SAME),)),
        (
            r"^bls\.cpi\.shelter_mom",
            (
                (
                    "KXSHELTERCPI",
                    "KXSHELTERCPI is on the seasonally adjusted index level (FRED"
                    " CUSR0000SAH1, per its rule), Thesis's target on the monthly"
                    " change; its strikes fall between the 0.1-point steps of the"
                    " published change, so scoring it would need an assumption"
                    " about values within a step",
                ),
                ("KXCPISHELTER", SAME),
                ("CPISHELTER", SAME),
            ),
        ),
        (r"^census\.m3\.durable_goods_new_orders", (("KXUSDURABLE", SAME),)),
        (r"^fed\.g17\.industrial_production", (("KXUSIPMOM", SAME),)),
        (r"^bea\.pce_price_index\.monthly_change", (("KXPCEHEAD", SAME),)),
        (r"^statcan\.cpi\.allitems\.yoy", (("KXCACPIYOY", SAME),)),
        (r"^ons\.cpi\.annual_rate", (("KXUKCPIYOY", SAME),)),
        (
            r"^statjp\.cpi\.tokyo",
            (
                (
                    "KXJPCPIYOY",
                    "KXJPCPIYOY is on national CPI, Thesis's target on Tokyo CPI",
                ),
                (
                    "KXJPMOMINF",
                    "KXJPMOMINF is on the monthly change in national CPI, Thesis's"
                    " target on the annual rate of Tokyo CPI",
                ),
            ),
        ),
        (
            r"^bea\.disposable_personal_income",
            (
                (
                    "KXUSPINCOME",
                    "KXUSPINCOME is on personal income growth, Thesis's target on"
                    " the DPI level",
                ),
            ),
        ),
        (
            r"^bls\.real_earnings\.avg_hourly_mom",
            (
                ("KXREALWAGES", _REAL_WAGES),
                ("REALWAGES", _REAL_WAGES),
                (
                    "KXWAGESBEAT",
                    "KXWAGESBEAT is on the 12-month change in real average hourly"
                    " earnings for December",
                ),
                ("KXAHEMOM", "KXAHEMOM is on nominal hourly earnings"),
                (
                    "KXAHEG",
                    "KXAHEG is on nominal wage growth above a threshold in any"
                    " month through July 2027",
                ),
            ),
        ),
        (
            r"^treasury\.mts\.monthly_deficit",
            (
                ("KXDEFICIT", _DEFICIT_BY_DATE),
                ("KXTDEFFICITBY", _DEFICIT_BY_DATE),
            )
            + tuple(
                (series, _DEBT)
                for series in (
                    "KXUSDEBTMON",
                    "KXTRUFPDEBT",
                    "KXDEBTLEVEL",
                    "KXDEBTGROWTH",
                    "KXDEBTGROWTH25",
                    "KXDEBTGROWTH26",
                    "KXDEBTSHRINK",
                    "KXNDEBTSHRINK",
                    "KXUSDEBT",
                )
            ),
        ),
        (
            r"^bea\.trade\.goods_services_deficit",
            (("KXTRADEDEFFICIT", _TRADE_ANNUAL), ("KXTRADEDEFICIT", _TRADE_ANNUAL)),
        ),
        (
            r"^census\.construction_spending\.total",
            (
                (
                    "KXDATACENTCON",
                    "KXDATACENTCON is on private data-center construction spending,"
                    " one component of the total",
                ),
                (
                    "KXMANUCON",
                    "KXMANUCON is on manufacturing construction spending, one"
                    " component of the total",
                ),
            ),
        ),
        (
            r"^bls\.productivity\.nonfarm_qoq",
            (
                (
                    "KXNFPROD",
                    "KXNFPROD is on year-over-year growth in any quarter of a year",
                ),
            ),
        ),
        (
            r"^bls\.eci\.",
            (
                (
                    "KXHEALTHCOST",
                    "KXHEALTHCOST is on the 12-month change in private employers'"
                    " health-benefit costs, one component",
                ),
            ),
        ),
        (
            r"^fed\.g19\.consumer_credit_revolving",
            (("CRED", _CREDIT_CARD), ("KXCRED", _CREDIT_CARD)),
        ),
        (
            r"^eurostat\.une_rt_m\.unemployment_rate\.belgium",
            (
                (
                    "KXUE",
                    "KXUE's events are for single countries, none for Belgium",
                ),
            ),
        ),
        (
            r"^eurostat\.unemployment_rate\.euro_area",
            (
                (
                    "KXUE",
                    "KXUE's events are for single countries, none for the euro area",
                ),
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
    "KXJOLTSOPEN": ("KXJOLTS",),
    "KXPCECORE": ("PCECORE",),
    "KXHOUSINGSTART": ("KXHOUSESTART", "HOUSESTART"),
    "KXNHSALES": ("KXHOME", "HOME"),
}


def related_series(data_point_id: str) -> tuple[tuple[str, str], ...] | None:
    for regex, pairs in RELATED:
        if regex.match(data_point_id):
            return pairs
    return None


def _ci(pattern: str) -> str:
    """Case-insensitive words; acronyms outside this stay case-sensitive."""
    return f"(?i:{pattern})"


@dataclasses.dataclass(frozen=True)
class ScreenGroup:
    label: str
    families: re.Pattern  # Thesis data point ids this group covers
    keywords: re.Pattern  # searched in Kalshi ticker, title and event text


# The catalog screen (plan changes 7 and 8). Every in-scope Thesis run with no
# scorable Kalshi event belongs to a group here, and each group names the
# words a Kalshi series on the same statistic would use. The pipeline searches
# every series in the catalog (ticker and title) and every event (ticker,
# title and subtitle) of every Economics and World series. Each hit must be a
# matched, alternate or related series, or carry a reviewed reason in
# SCREEN_VERDICTS; an unaccounted hit or an uncovered run stops the run.
# Keywords are broad on purpose: a false hit costs one reviewed line, a missed
# series costs a pair.
CATALOG_SCREEN: tuple[ScreenGroup, ...] = tuple(
    ScreenGroup(label, re.compile(families), re.compile(keywords))
    for label, families, keywords in (
        (
            "personal income and outlays",
            r"^bea\.(disposable_personal_income|government_social_benefits"
            r"|personal_current_taxes|ita\.personal_transfer_payments)",
            _ci(
                r"personal income|disposable income|social benefit|transfer payment"
                r"|personal (current )?tax|government benefit|personal spending"
                r"|personal outlays|consumer spending"
            ),
        ),
        (
            "fixed investment",
            r"^bea\.(private_nonresidential|research_and_development)_fixed_investment",
            _ci(
                r"fixed investment|business investment|nonresidential"
                r"|research and development|capital expenditure|\bcapex\b"
                r"|business spending"
            )
            + r"|\bR&D\b",
        ),
        (
            "PCE price index",
            r"^bea\.pce_price_index",
            r"\bPCE\b|" + _ci(r"personal consumption"),
        ),
        (
            "trade balance",
            r"^(bea|ons)\.trade\.",
            _ci(
                r"trade (deficit|balance|gap|surplus)|balance of trade"
                r"|goods and services|current account"
            ),
        ),
        (
            "job gains",
            r"^bls\.bed\.",
            _ci(
                r"job (gains|losses|creation|destruction)|gross job"
                r"|business employment dynamics|employment change|private payrolls"
            )
            + r"|\bADP\b",
        ),
        (
            "health care employment",
            r"^bls\.ces\.home_health",
            _ci(r"home health|health ?care (employment|jobs|workers)"),
        ),
        (
            "CPI components",
            r"^bls\.cpi\.(owners_equivalent|rent_primary|services_less|shelter)",
            _ci(
                r"shelter|owners.? equivalent|rent of primary|housing inflation"
                r"|rent (inflation|index|prices?|growth)|cpi-u index"
            )
            + r"|\bOER\b|\bCPI\b.*"
            + _ci(r"\brent\b|services|housing"),
        ),
        (
            "occupation and telework",
            r"^bls\.cps\.(employed_people_by_occupation|telework)",
            _ci(r"occupation|telework|remote work|work from home|hybrid work"),
        ),
        ("U-6", r"^bls\.cps\.u6", r"\bU-?6\b|" + _ci(r"underemploy")),
        (
            "employment cost",
            r"^bls\.(eci|ecec)\.",
            _ci(
                r"employment cost|compensation cost|labor cost"
                r"|(health|benefit)\w* (insurance )?costs?|wages and salaries"
            )
            + r"|\bECI\b",
        ),
        (
            "import and export prices",
            r"^bls\.(export_prices|import_price_index)\.",
            _ci(r"import price|export price|\bimports\b|\bexports\b"),
        ),
        (
            "JOLTS hires and quits",
            r"^bls\.jolts\.(hires|quits)",
            _ci(
                r"\bquits?\b|quit rate|\bhires\b|\bhiring rate|separations"
                r"|labor turnover|job openings"
            )
            + r"|\bJOLTS\b",
        ),
        (
            "productivity",
            r"^bls\.productivity\.",
            _ci(r"productivity|unit labor cost|output per hour"),
        ),
        (
            "QCEW",
            r"^bls\.qcew\.",
            _ci(r"aerospace|aircraft|quarterly census of employment") + r"|\bQCEW\b",
        ),
        (
            "real earnings",
            r"^bls\.real_earnings\.",
            _ci(
                r"real wage|real earnings|hourly earnings|wage growth|\bwages\b"
                r"|paychecks?"
            ),
        ),
        (
            "producer prices",
            r"^(bls\.wp\.|ons\.ppi\.)",
            r"\bPPI\b|" + _ci(r"producer price|wholesale (price|inflation)"),
        ),
        (
            "Colorado",
            r"^(bls\.laus\.colorado|co\.)",
            _ci(
                r"colorado.*(unemploy|employ|jobs|labor force|income tax|tax revenue"
                r"|revenue|budget|medicaid|caseload|permit)"
            ),
        ),
        (
            "construction spending and output",
            r"^(census\.construction_spending|eurostat\.construction)",
            _ci(r"construction (spending|outlays|output|production|put in place)"),
        ),
        (
            "housing",
            r"^(census\.housing|abs\.building_approvals|hmrc\.property_transactions"
            r"|ons\.uk_hpi|ons\.pipr)",
            _ci(
                r"housing (completion|start|units|permits?|prices?)"
                r"|(building|residential) (permit|approval)|dwelling"
                r"|new home sales|existing home|home sales|new residential"
                r"|housing inventory|home inventory|active listings"
                r"|property transaction|house price|home price|home value"
                r"|private rent|rental price"
            )
            + r"|\bHPI\b",
        ),
        (
            "durable goods",
            r"^census\.m3\.",
            _ci(
                r"durable goods|factory orders|capital goods|defense capital"
                r"|core capital|business equipment"
            ),
        ),
        ("poverty", r"^census\.spm\.", _ci(r"poverty") + r"|\bSPM\b"),
        (
            "nursing homes",
            r"^cms\.",
            _ci(r"nursing|care compare|care home|long-term care"),
        ),
        (
            "natural gas venting",
            r"^eia\.ng\.",
            _ci(r"vented|venting|flared|flaring"),
        ),
        (
            "industrial production",
            r"^(fed\.g17\.|ons\.production\.)",
            _ci(
                r"industrial (production|output)|capacity utili"
                r"|manufacturing (production|output)|factory output"
                r"|index of production|semiconductor production"
            ),
        ),
        (
            "consumer credit",
            r"^fed\.g19\.",
            _ci(
                r"consumer credit|revolving credit|nonrevolving"
                r"|credit card (debt|balance)|household debt|consumer debt"
                r"|credit.card (delinquen|charge.off|default)"
                r"|(student|auto) loan (debt|balance)|student debt"
            ),
        ),
        (
            "nutrition programs",
            r"^(fns\.wic|usda\.fns\.snap)",
            r"\bWIC\b|\bSNAP\b|"
            + _ci(r"snap benefit|food stamp|nutrition assistance|women, infants"),
        ),
        (
            "child tax credit",
            r"^irs\.actc",
            _ci(r"child tax credit") + r"|\bA?CTC\b",
        ),
        (
            "SBA disaster loans",
            r"^sba\.disaster",
            r"\bSBA\b|"
            + _ci(r"disaster (loan|assistance)|small business administration"),
        ),
        (
            "Social Security and SSI",
            r"^ssa\.",
            r"\bSSI\b|\bCOLA\b|"
            + _ci(r"supplemental security|social security|retired.worker"),
        ),
        (
            "federal and public-sector budget",
            r"^(treasury\.mts|ons\.pusf)",
            _ci(
                r"deficit|treasury statement|federal budget|budget balance"
                r"|public sector (net )?borrowing|public finances|public debt"
                r"|debt (level|growth|outstanding|increase|to gdp)|national debt"
                r"|total (us )?debt|government debt"
            ),
        ),
        (
            "federal awards",
            r"^usaspending\.",
            _ci(
                r"obligation|prime award|federal contract|government contract"
                r"|federal grant|federal spending|usaspending"
            ),
        ),
        (
            "Conservation Reserve Program",
            r"^usda\.fsa\.crp",
            r"\bCRP\b|" + _ci(r"conservation reserve"),
        ),
        ("veterans' pensions", r"^va\.", _ci(r"veteran")),
        (
            "Australia",
            r"^abs\.",
            _ci(
                r"australia.*(cpi|inflation|consumer price|price index|employ"
                r"|jobs?\b|labour|labor|building|dwelling|approval|housing)"
            )
            + r"|\bABS\b",
        ),
        (
            "Belgium",
            r"^(eurostat\.une_rt_m\.unemployment_rate\.belgium|nbb\.|statbel\.)",
            _ci(
                r"belgi.*(cpi|inflation|unemploy|jobless|confidence|barometer|gdp"
                r"|health index|growth)|statbel"
            ),
        ),
        (
            "Canada",
            r"^statcan\.",
            _ci(
                r"canad.*(cpi|inflation|price|gdp|growth|recession|pmi"
                r"|employment insurance|jobless|claims|unemploy|beneficiar|employ"
                r"|labour|jobs)|statcan|statistics canada"
            ),
        ),
        (
            "euro area",
            r"^eurostat\.unemployment_rate\.euro_area",
            _ci(
                r"(euro|\beu\b|european union|europe).*(unemploy|jobless"
                r"|construction)"
            ),
        ),
        (
            "Japan",
            r"^statjp\.",
            _ci(r"(tokyo|japan).*(cpi|inflation|consumer price|prices)"),
        ),
        (
            "United Kingdom",
            r"^(ons\.|hmrc\.)",
            _ci(
                r"(\buk\b|united kingdom|britain|british|england).*(claimant"
                r"|earnings|\bpay\b|payroll|vacanc|unemploy|labou?r|employ|rent"
                r"|producer|production|output|borrowing|budget|deficit|trade"
                r"|house price|property|cpi|inflation|ppi|hpi|gdp)"
            ),
        ),
    )
)


def screen_group(data_point_id: str) -> ScreenGroup | None:
    for group in CATALOG_SCREEN:
        if group.families.match(data_point_id):
            return group
    return None


# Reviewed reasons for screen hits that are not on a screened statistic, keyed
# by series ticker (exact) or, for events, by event ticker prefix (keys
# containing "-"; the longest matching prefix wins).
SCREEN_VERDICTS: dict[str, str] = {
    # trade
    "KXCHTRADEBAL": "China's trade balance",
    "KXJPTRADEBAL": "Japan's trade balance",
    "KXSATRADEBAL": "South Africa's trade balance",
    "KXAUTRADEBAL": "Australia's trade balance",
    "KXDETRADEBAL": "Germany's trade balance",
    "KXTRDDEFCN": "the US goods deficit with China, one bilateral component",
    "TRDDEFCN": "the US goods deficit with China, one bilateral component",
    "KXTRUMPTRADEGAP": "whether the US-China trade gap closes, a one-off question",
    "KXTDEFICITHALF": (
        "whether the trade deficit falls below a level before February 2029"
        " (title 'U.S. BOP'; its one event asks whether the deficit halves)"
    ),
    # labor
    "KXAIJOBLOSS": "announced AI-linked layoffs, not BED gross job gains",
    "KXOSHADIRECTOR": "a nomination, not a statistic",
    "KXTFP": "total factor productivity (one 2025 event), not labor productivity",
    "KXWAAEROEMP": (
        "Washington's annual-average aerospace employment, not national QCEW"
        " aircraft-manufacturing establishments"
    ),
    # prices
    "KXRTSHELTER": "a film's review score",
    "KXTRUFHOUCPI": "Truflation's daily housing index, not BLS CPI",
    "KXPPIVSCPI": "whether PPI inflation exceeds CPI inflation",
    "KXPPICPI": "whether PPI inflation exceeds CPI inflation",
    "KXLUMBERPPIHIGH": "the softwood lumber PPI",
    "KXPPISEMI": "the semiconductor PPI",
    "PPISEMI": "the semiconductor PPI",
    "KXCANEUINFL": "whether Canadian inflation exceeds euro-area inflation",
    "KXJPSGINFL": "whether Japanese inflation exceeds Singapore's",
    "KXUKEAINFL": "whether UK inflation exceeds euro-area inflation",
    "KXUSUKCOREINF": "whether US core inflation exceeds UK core inflation",
    # housing
    "KXEXUSHOME": "the US median existing-home price",
    "KXUSHOME": "the US median new-home price",
    "KXEHSALES": "US existing-home sales",
    "KXHPI": "the US FHFA house price index (2021 events)",
    "HPI": "the US FHFA house price index (no events)",
    "KXHOMEUS": "Zillow's US home price (monthly)",
    "HOMEUS": "Zillow's US home price (monthly)",
    "KXHOMEUSY": "Zillow's US home price (annual)",
    "HOMEUSY": "Zillow's US home price (annual)",
    "KXCANHOME": "Canada's average home price",
    "KXCANHOUSTART": "Canada's annual housing starts",
    "KXCOBUILDPERMITS": "Colorado's annual building permits",
    "KXCABUILDPERMITS": "California's annual building permits",
    "KXCTMFPERMITS": "Connecticut's annual multifamily building permits",
    "KXBOZPERMITS": "Bozeman's annual housing permits",
    "KXVTPERMITS": "Vermont's annual housing permits",
    "KXILHPIYOY": "a state house price index (Illinois)",
    "KXCOHPIYOY": "a state house price index (Colorado)",
    "KXCAHPIYOY": "a state house price index (California)",
    "KXRIHOMEPRICE": "a state house price index (Rhode Island)",
    "KXNVHOMEPRICE": "a state house price index (Nevada)",
    "KXUTHOMEPRICE": "a state house price index (Utah)",
    "KXNHHOMEPRICE": "a state house price index (New Hampshire)",
    "KXMTLHOME": "a Canadian city's home price (Montreal)",
    "KXOTTAWAHOME": "a Canadian city's home price (Ottawa)",
    "KXEDMHOME": "a Canadian city's home price (Edmonton)",
    "KXCALHOME": "a Canadian city's home price (Calgary)",
    # output and budgets
    "KXCHIPYOY": "China's industrial production",
    "KXCANRECESSION": "whether Canada has two negative GDP quarters",
    "KXUKGDPMOM": "UK monthly GDP, not the index of production",
    "KXUKUNRATE": (
        "the UK unemployment rate; Thesis's UK labor targets are the claimant"
        " count, vacancies, payrolled employees and regular pay"
    ),
    "KXDEFGDP": "the fiscal-year deficit as a share of GDP",
    "KXGOVBAL-27APR20GB": (
        "the UK's annual general government balance, not monthly public sector"
        " net borrowing"
    ),
    "KXGDPNOM-UK": "the UK's annual nominal GDP",
    "KXGDPNOM-CAN": "Canada's annual nominal GDP, not monthly GDP by industry",
    "KXUE-CAN": "Canada's unemployment rate; Thesis has no Canadian target on it",
    "KXUE-UK": "the UK unemployment rate; Thesis has no UK target on it",
    # programs and policy questions
    "KXSNAPRESTRICT": "a bill on what SNAP benefits can buy, not participation",
    "KXSNAPCUTS": "legislated SNAP cuts, not participation",
    "KXSNAPDELAY": (
        "whether November 2025 SNAP benefits were delayed, not participation"
    ),
    "KXCOMPANYACTIONSNAP": "Snap Inc., the company",
    "KXEARNINGSMENTIONSNAP": "Snap Inc., the company",
    "KXSSCOLA": (
        "the Social Security cost-of-living adjustment, not SSI recipients or"
        " retired-worker awards"
    ),
    "KXCTC": "whether the child tax credit is expanded, not a count of claims",
    "CTC": "whether the child tax credit is expanded, not a count of claims",
    "KXCTCS": "whether the child tax credit is expanded, not a count of claims",
    "CTCS": "whether the child tax credit is expanded, not a count of claims",
    "KXUKRENEWOB": "a UK energy policy question",
    "KXUKBUDGETTAX": "whether the UK Budget raises taxes, a policy question",
    "KXUKLABOURDEPUTY": "a Labour Party deputy leadership election",
    "KXCAGOAT": "a California wage rule question",
    "KXSECVA": "a cabinet nomination",
    # hits from the wider keywords and the event screen (r4 review)
    "KXMEDIANRENTCHI": "a city's annual rent growth (Chicago)",
    "KXMEDIANRENTHOU": "a city's annual rent growth (Houston)",
    "KXMEDIANRENTLA": "a city's annual rent growth (Los Angeles)",
    "KXMEDIANRENTMIA": "a city's annual rent growth (Miami)",
    "KXRENTNYCM": "New York City's monthly rent increase",
    "RENTNYCM": "New York City's monthly rent increase",
    "KXRENTNYCY": "New York City's yearly rent increase",
    "RENTNYCY": "New York City's yearly rent increase",
    "KXSFRENTSY": "San Francisco's yearly rent growth",
    "SFRENTSY": "San Francisco's yearly rent growth",
    "KXNYCSTAT": (
        "New York City administrative statistics (shelter stays, housing permits)"
    ),
    "KXOPENAICEOCHANGE": "a company event",
    "OPENAICEOCHANGE": "a company event",
    "KXCHINABOEING": "a Chinese aircraft order, a company event",
    "KXSOCIALSECURITYDEPLETE": "Social Security trust fund depletion",
    "KXSSTAX": "taxation of Social Security benefits, a policy question",
    "KXSTUDENTDEBT": (
        "the student loan debt level at a year's end, not the G.19 annual growth"
        " rate"
    ),
    "KXGOVBAL": (
        "annual general government budget balances by country (2026), not a"
        " monthly deficit or monthly borrowing"
    ),
    "KXAAMMCAPEX": "four companies' combined capital expenditures",
    "KXMASCIENRDEMP": "Massachusetts scientific R&D employment",
    "KXBOSHOMEVAL": "a metro's typical home value (Boston)",
    "KXDCHOMEVAL": "a metro's typical home value (Washington DC)",
    "KXDENHOMEVAL": "a metro's typical home value (Denver)",
    "KXHOUHOMEVAL": "a metro's typical home value (Houston)",
    "KXMIAHOMEVAL": "a metro's typical home value (Miami)",
    "KXPHXHOMEVAL": "a metro's typical home value (Phoenix)",
    "KXSDHOMEVAL": "a metro's typical home value (San Diego)",
    "KXSEAHOMEVAL": "a metro's typical home value (Seattle)",
    "KXSFHOMEVAL": "a metro's typical home value (San Francisco)",
    "KXUSHOMEVAL": "the US metro typical home value",
    "KXEHSHARE": "US existing-home sales",
    "KXBRAZILJOBS": "Brazil's formal job creation",
    "KXCHICKENWINGM": "a commodity's wholesale price (chicken wings)",
    "KXCOWAGE": "Colombia's minimum-wage increase minus inflation",
    # adjacent series recorded after the r5 sweeps
    "KXCPINDEX": "the headline CPI-U index level, not a component's change",
    "KXCAIVEYPMI": "a purchasing managers' survey index, not GDP by industry",
    "CREDITCDEF": "whether credit card defaults rise, not G.19 growth",
    "KXCREDITCDEF": "whether credit card defaults rise, not G.19 growth",
    "KXCCCHGOFF": "the credit-card charge-off rate, not G.19 growth",
    "KXCCDELINQ": "the credit-card delinquency rate, not G.19 growth",
    "KXUSHOMEINVENT": "US active housing listings, not completions",
    "KXCHEXPORTS": "China's export growth, not US export prices",
    "KXCHIMPORTS": "China's import growth, not US import prices",
    "KXSKEXPYOY": "South Korea's export growth, not US export prices",
    "KXCNIMPORT": "US goods imports from China (volume), not import prices",
    "KXEIACRUDEXPM": "US crude oil export volumes, not export prices",
    "KXHELIUMIMP": "US helium import volumes, not import prices",
    "KXIRANIMPORTS": "US imports from Iran (volume), not import prices",
    "KXMEXCUBOIL": "whether Mexico resumes oil exports to Cuba",
    "KXRUCRUDEX": "Russian crude export volumes",
    "KXTARIFFSGLOBAL": "a tariff policy question",
    "KXSEMIPRODH": "annual US semiconductor production, one industry",
    "SEMIPRODH": "annual US semiconductor production, one industry",
    "KXADP": "ADP's private employment change, not BLS gross job gains",
    "KXUSPSPEND": (
        "personal spending growth, not income, benefits, transfers or taxes"
    ),
    "KXSDEBT": "student debt forgiveness by law or order, a policy question",
    "SDEBT": "student debt forgiveness by law or order, a policy question",
}


def screen_verdict_reason(ticker: str, *, event: bool = False) -> str | None:
    if not event:
        return SCREEN_VERDICTS.get(ticker)
    keys = [key for key in SCREEN_VERDICTS if "-" in key and ticker.startswith(key)]
    return SCREEN_VERDICTS[max(keys, key=len)] if keys else None


# Categories whose every event is read and screened, not only the series
# title: a series such as KXUE ("Monthly Unemployment") names its countries
# only in its event titles.
EVENT_SCREEN_CATEGORIES = ("Economics", "World")


PERIOD_TOKENS = (
    (re.compile(r"week_(20\d{2})-(\d{2})-(\d{2})"), "week"),
    (re.compile(rf"(?<![a-z])({MONTH_WORD})_(20\d{{2}})"), "month_name"),
    (re.compile(r"(?<!\d)(20\d{2})[-_](\d{2})(?![-_\d])"), "year_month"),
    (re.compile(r"(?<!\d)(20\d{2})_q([1-4])(?!\d)"), "quarter"),
    (re.compile(r"(?<![\d-])(20\d{2})(?![-_\d])"), "year"),
)


def period_of(data_point_id: str) -> str | None:
    """Best-effort reference period of a Thesis data point, for the inventory.

    Years must be 20xx, so a table number such as StatCan's 36-10-0434-01 is
    never read as a period. Token kinds are tried in the order of
    PERIOD_TOKENS (week, month name, year-month, quarter, year), and within a
    kind the first in the id wins: Thesis ids put the period before suffixes
    such as a source-recovery date.
    """
    for regex, kind in PERIOD_TOKENS:
        for found in regex.finditer(data_point_id):
            if kind == "week":
                return "-".join(found.groups())
            if kind == "quarter":
                return f"{found.group(1)}-Q{found.group(2)}"
            if kind == "year":
                return found.group(1)
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


# Wider readings for the unmatched-run evidence only (text_periods with
# spans=True); the scored matching keeps the strict readings above.
DATE_TEXT = re.compile(
    rf"\b(?P<month>{MONTH_WORD})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+(?P<year>20\d{{2}})\b",
    re.I,
)
MONTH_RANGE = re.compile(
    rf"\b(?P<m1>{MONTH_WORD})\.?\s+(?P<y1>20\d{{2}})\s*(?:through|thru|to|until|-|\u2013)"
    rf"\s*(?P<m2>{MONTH_WORD})\.?\s+(?P<y2>20\d{{2}})\b",
    re.I,
)
# Capitalized month names only, so the verb "may" is not read as May.
MONTH_ALONE = re.compile(
    r"\b(?P<month>January|February|March|April|May|June|July|August|September"
    r"|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\b"
)
ANY_QUARTER = re.compile(
    r"\bany (?:(?P<y1>20\d{2}) quarter|quarter (?:of|in) (?P<y2>20\d{2}))\b", re.I
)


SPAN_END = re.compile(
    r"\b(?P<word>before|by|through|thru|until)\s+(?:the end of\s+)?(?P<year>20\d{2})\b",
    re.I,
)


def could_cover_year(text: str, year: int | None) -> bool:
    """Whether an event whose period cannot be read might cover ``year``.

    True if the text names no year, names ``year``, or names a span that
    reaches it ("before 2029" reaches 2028, "through 2027" reaches 2027).
    """
    if year is None:
        return True
    text = normalize_text(text)
    spans = list(SPAN_END.finditer(text))
    # Years named outside a span phrase ("before 2026" does not name 2026).
    years = {int(y) for y in YEAR_TEXT.findall(SPAN_END.sub(" ", text))}
    if (not years and not spans) or year in years:
        return True
    for m in spans:
        end = int(m["year"]) - (1 if m["word"].lower() == "before" else 0)
        if end >= year:
            return True
    return False


def _months_between(y1: int, m1: int, y2: int, m2: int) -> set[str]:
    months, year, month = set(), y1, m1
    while (year, month) <= (y2, m2) and len(months) < 60:
        months.add(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


QUARTER_TEXT = re.compile(
    r"\bQ(?P<q1>[1-4])\s*,?\s*(?P<y1>20\d{2})\b"
    r"|\b(?P<y2>20\d{2})\s*-?\s*Q(?P<q2>[1-4])\b"
    r"|\b(?P<word>first|second|third|fourth) quarter(?: of)?,?\s+(?P<y3>20\d{2})\b",
    re.I,
)
QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
YEAR_TEXT = re.compile(r"(?<![\d.])(20\d{2})(?![\d.])")


def text_periods(text: str, cadence: str, *, spans: bool = False) -> set[str]:
    """Reference periods a Kalshi title names, in ``cadence``.

    With ``spans`` (used only for the unmatched-run evidence, never for
    scoring), it also reads day dates ("July 31, 2026"), month ranges
    ("August 2026 through July 2027"), "any 2026 quarter", and a lone month
    word with a lone year ("in October" / "UE 2026").
    """
    text = normalize_text(text)
    if cadence == "quarterly":
        periods = set()
        for m in QUARTER_TEXT.finditer(text):
            if m["word"]:
                periods.add(f"{m['y3']}-Q{QUARTER_WORDS[m['word'].lower()]}")
            else:
                periods.add(f"{m['y1'] or m['y2']}-Q{m['q1'] or m['q2']}")
        if spans:
            for m in ANY_QUARTER.finditer(text):
                periods |= {f"{m['y1'] or m['y2']}-Q{q}" for q in range(1, 5)}
        return periods
    if cadence == "monthly" and spans:
        periods = text_periods(text, "monthly")
        for m in DATE_TEXT.finditer(text):
            periods.add(f"{int(m['year']):04d}-{MONTHS[m['month'].lower()]:02d}")
        for m in MONTH_RANGE.finditer(text):
            periods |= _months_between(
                int(m["y1"]),
                MONTHS[m["m1"].lower()],
                int(m["y2"]),
                MONTHS[m["m2"].lower()],
            )
        if not periods:
            months = {MONTHS[m["month"].lower()] for m in MONTH_ALONE.finditer(text)}
            years = set(YEAR_TEXT.findall(text))
            if len(months) == 1 and len(years) == 1:
                periods.add(f"{years.pop()}-{months.pop():02d}")
        return periods
    if cadence == "annual":
        return set(YEAR_TEXT.findall(text))
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


def period_cadence(period: str) -> str:
    """The cadence a period_of() value is written in."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", period):
        return "weekly"
    if re.fullmatch(r"\d{4}-Q[1-4]", period):
        return "quarterly"
    if re.fullmatch(r"\d{4}", period):
        return "annual"
    return "monthly"


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
