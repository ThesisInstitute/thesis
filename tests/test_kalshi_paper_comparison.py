"""Tests for the Thesis vs Kalshi paper comparison (scripts/kalshi_compare).

Fixtures are real data, excerpted:
- tests/fixtures/kalshi_compare/official_excerpts.json: normalized text from
  the BLS CPI (2026-09-11), Employment Situation (2026-09-04) and JOLTS
  (2026-09-01) archived releases, the BEA Personal Income and Outlays release
  for July 2026, and the DOL ETA weekly claims release of 2026-08-13, each
  with its URL and the SHA-256 of the full document, fetched 2026-10-19.
- tests/fixtures/kalshi_compare/kalshi_events.json: market records (fields
  the comparison reads) for six Kalshi events, three event records, and raw
  hourly candlesticks in the live and historical response formats, fetched
  2026-10-19 from api.elections.kalshi.com.
- tests/fixtures/kalshi_compare/published_cdfs.json: eight published Thesis
  CDFs from app.thesisinstitute.org/targets/forecastDistributions, fetched
  2026-10-19, with each run's point estimate and 80% interval.

Property tests state the scoring invariants and run them over generated
inputs; differential tests check two readings of the same fact against each
other.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kalshi_compare import contracts, kalshi, official, scoring, thesis  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "kalshi_compare"
EXCERPTS = json.loads((FIXTURES / "official_excerpts.json").read_text())
KALSHI = json.loads((FIXTURES / "kalshi_events.json").read_text())
CDFS = json.loads((FIXTURES / "published_cdfs.json").read_text())


def spec(series: str) -> contracts.SeriesSpec:
    return next(s for s in contracts.SPECS if s.series == series)


# Official first prints ------------------------------------------------------


def test_cpi_table_a_and_lead_agree():
    text = EXCERPTS["bls_cpi_2026-08"]["excerpt"]
    assert official.parse_bls_cpi(text, "headline") == (
        "2026-08",
        Decimal("0.4"),
        Decimal("0.4"),
        "2026-09-11T12:30:00Z",
    )
    assert official.parse_bls_cpi(text, "core") == (
        "2026-08",
        Decimal("0.3"),
        Decimal("0.3"),
        "2026-09-11T12:30:00Z",
    )


def test_cpi_ignores_the_twelve_month_label_in_the_header():
    # The header reads "12-mos. ended Aug. 2026 Feb. 2026 ... Aug. 2026"; the
    # seventh column month must be read after dropping that label.
    text = EXCERPTS["bls_cpi_2026-08"]["excerpt"]
    assert "12-mos. ended Aug. 2026" in text
    assert official.parse_bls_cpi(text, "headline")[0] == "2026-08"


def test_cpi_rejects_a_release_for_another_month():
    text = EXCERPTS["bls_cpi_2026-08"]["excerpt"].replace(
        "CONSUMER PRICE INDEX - AUGUST 2026", "CONSUMER PRICE INDEX - JULY 2026"
    )
    with pytest.raises(official.OfficialParseError):
        official.parse_bls_cpi(text, "headline")


def test_employment_situation_tables():
    text = EXCERPTS["bls_empsit_2026-08"]["excerpt"]
    assert official.parse_bls_empsit(text, "payrolls") == (
        "2026-08",
        Decimal("162000"),
        Decimal("162000"),
        "2026-09-04T12:30:00Z",
    )
    assert official.parse_bls_empsit(text, "unemployment") == (
        "2026-08",
        Decimal("4.1"),
        Decimal("4.1"),
        "2026-09-04T12:30:00Z",
    )


def test_jolts_reads_the_thousands_level_and_ten_am_release():
    period, value, lead, release_at = official.parse_bls_jolts(
        EXCERPTS["bls_jolts_2026-07"]["excerpt"]
    )
    assert (period, value, release_at) == (
        "2026-07",
        Decimal("7.271"),
        "2026-09-01T14:00:00Z",
    )
    assert lead == Decimal("7.3")  # the lead rounds to 0.1 million


def test_bea_core_pce():
    assert official.parse_bea_core_pce(EXCERPTS["bea_pio_2026-07"]["excerpt"]) == (
        "2026-07",
        Decimal("0.2"),
        Decimal("0.2"),
        "2026-08-26T12:30:00Z",
    )


def test_dol_advance_figures_and_week_dates():
    text = EXCERPTS["dol_claims_2026-08-13"]["excerpt"]
    assert official.parse_dol_claims(text, "initial") == (
        "2026-08-08",
        Decimal("209000"),
        None,
        "2026-08-13T12:30:00Z",
    )
    assert official.parse_dol_claims(text, "continued") == (
        "2026-08-01",
        Decimal("1.777"),
        None,
        "2026-08-13T12:30:00Z",
    )


def test_release_instant_follows_daylight_saving():
    assert (
        official.release_instant("8", "30", "a", "July 16, 2026")
        == "2026-07-16T12:30:00Z"
    )
    assert (
        official.release_instant("8", "30", "a", "December 10, 2026")
        == "2026-12-10T13:30:00Z"
    )


@pytest.mark.parametrize(
    ("verb", "amount", "expected"),
    [
        ("increased", "0.4", Decimal("0.4")),
        ("fell", "0.1", Decimal("-0.1")),
        ("was unchanged", None, Decimal("0.0")),
        ("edged down", "0.2", Decimal("-0.2")),
    ],
)
def test_signed_change(verb, amount, expected):
    assert official.signed_change(verb, amount) == expected


# Contracts ------------------------------------------------------------------


def test_thesis_targets_match_the_intended_series():
    cases = {
        "bls.cpi.u.headline_mom.august_2026.first_print": [
            ("KXCPI", "2026-08"),
            ("KXECONSTATCPI", "2026-08"),
        ],
        "bls.cpi.u.core_mom.september_2026.first_print": [
            ("KXCPICORE", "2026-09"),
            ("KXECONSTATCPICORE", "2026-09"),
        ],
        "bls.ces.total_nonfarm.payroll_employment.change.sa.2026-08.first_print": [
            ("KXPAYROLLS", "2026-08")
        ],
        "bls.ces.nonfarm_payrolls.change.2026_10.first_print": [
            ("KXPAYROLLS", "2026-10")
        ],
        "us.dol.initial_claims.sa.week_2026-08-08": [("KXJOBLESSCLAIMS", "2026-08-08")],
        "dol.eta.continued_claims.sa.week_2026-09-26.first_print": [
            ("KXCONTCLAIMS", "2026-09-26")
        ],
        "bls.jolts.job_openings.july_2026.first_print": [("KXJOLTSOPEN", "2026-07")],
        "us.bea.core_pce.mom_sa.2026-08": [("KXPCECORE", "2026-08")],
        "bea.pce.core_mom.june_2026.first_print": [("KXPCECORE", "2026-06")],
    }
    for data_point, expected in cases.items():
        got = [
            (s.series, period) for s, period, _ in contracts.match_target(data_point)
        ]
        assert got == expected, data_point
    assert contracts.match_target("bls.jolts.quits_rate.2026-08.first_print") == []
    assert contracts.match_target("bls.cpi.shelter_mom.july_2026.first_print") == []


def test_event_periods_come_from_titles_and_every_rule():
    for ticker, cadence, expected in [
        ("KXCPI-26AUG", "monthly", "2026-08"),
        ("KXJOBLESSCLAIMS-26JUL16", "weekly", "2026-07-11"),
        ("KXJOLTSOPEN-26SEP01", "monthly", "2026-07"),
    ]:
        period, _ = contracts.event_period(
            KALSHI["events"][ticker], KALSHI["markets"][ticker], cadence
        )
        assert period == expected


def test_event_period_refuses_a_market_whose_rule_names_another_period():
    markets = [dict(m) for m in KALSHI["markets"]["KXCPI-26AUG"]]
    markets[0]["rules_primary"] = markets[0]["rules_primary"].replace(
        "August 2026", "July 2026"
    )
    period, reason = contracts.event_period(
        KALSHI["events"]["KXCPI-26AUG"], markets, "monthly"
    )
    assert period is None and "rules name" in reason


def test_week_ending_text_with_unusual_spaces():
    # Kalshi wrote "Mayㅤ 2, 2026" (a Hangul filler) in one event title.
    assert contracts.text_periods("for the week ending Mayㅤ 2, 2026", "weekly") == {
        "2026-05-02"
    }


def test_continuing_claims_strike_units_change_between_events():
    million = KALSHI["markets"]["KXCONTCLAIMS-26AUG27"]
    thousand = KALSHI["markets"]["KXCONTCLAIMS-26SEP03"]
    cc = spec("KXCONTCLAIMS")
    assert {contracts.strike_of(m, cc) for m in million} >= {
        Decimal("1.84"),
        Decimal("1.78"),
    }
    strikes = {contracts.strike_of(m, cc) for m in thousand}
    assert Decimal("1.750") in strikes and max(strikes) < 2


def test_strike_must_agree_with_the_rule_text():
    market = dict(KALSHI["markets"]["KXCPI-26AUG"][0])
    market["floor_strike"] = 9.9
    with pytest.raises(ValueError):
        contracts.strike_of(market, spec("KXCPI"))


def test_exact_value_markets():
    exact = spec("KXECONSTATCPI")
    values = {
        contracts.strike_of(m, exact) for m in KALSHI["markets"]["KXECONSTATCPI-26AUG"]
    }
    assert Decimal("0.4") in values and Decimal("-0.2") in values


@pytest.mark.parametrize(
    "event",
    [
        "KXCPI-26AUG",
        "KXJOBLESSCLAIMS-26JUL16",
        "KXCONTCLAIMS-26SEP03",
        "KXJOLTSOPEN-26SEP01",
    ],
)
def test_official_value_reproduces_every_kalshi_result(event):
    """Differential: the contract rule applied to the first print vs Kalshi's result."""
    first_print = {
        "KXCPI-26AUG": ("KXCPI", Decimal("0.4")),
        "KXJOBLESSCLAIMS-26JUL16": ("KXJOBLESSCLAIMS", Decimal("208000")),
        "KXCONTCLAIMS-26SEP03": ("KXCONTCLAIMS", Decimal("1.779")),
        "KXJOLTSOPEN-26SEP01": ("KXJOLTSOPEN", Decimal("7.271")),
    }[event]
    series_spec, value = spec(first_print[0]), first_print[1]
    for market in KALSHI["markets"][event]:
        strike = contracts.strike_of(market, series_spec)
        yes = contracts.market_yes("ladder", market["strike_type"], strike, value)
        assert market["result"] == ("yes" if yes else "no"), market["ticker"]


@pytest.mark.parametrize(
    ("strike_type", "value", "expected"),
    [
        ("greater", Decimal("0.4"), False),
        ("greater", Decimal("0.5"), True),
        ("greater_or_equal", Decimal("205000"), True),
        ("greater_or_equal", Decimal("204000"), False),
    ],
)
def test_boundary_values_follow_the_contract_wording(strike_type, value, expected):
    strike = Decimal("0.4") if strike_type == "greater" else Decimal("205000")
    assert contracts.market_yes("ladder", strike_type, strike, value) is expected
    bracket = scoring.realized_ladder_bracket(value, [strike], strike_type)
    assert bracket == (1 if expected else 0)


# Kalshi candles -------------------------------------------------------------


def test_live_and_historical_candles_normalize():
    live = [
        kalshi.normalize_candle(c) for c in KALSHI["candles"]["live"]["candlesticks"]
    ]
    hist = [
        kalshi.normalize_candle(c)
        for c in KALSHI["candles"]["historical"]["candlesticks"]
    ]
    for candle in live + hist:
        assert candle.bid is not None and candle.ask is not None
        assert 0.0 <= candle.bid <= candle.ask <= 1.0
        assert candle.volume >= 0


def test_state_at_never_reads_a_later_candle():
    candles = [
        kalshi.normalize_candle(c) for c in KALSHI["candles"]["live"]["candlesticks"]
    ]
    for index in range(1, len(candles)):
        at = candles[index].end - 1
        state = kalshi.state_at(candles, at)
        assert state.candle_end is not None and state.candle_end <= at
        assert state.candle_end == candles[index - 1].end
    assert kalshi.state_at(candles, candles[0].end - 1).candle_end is None


def test_state_at_midpoint_and_volume_window():
    candles = [
        kalshi.normalize_candle(c) for c in KALSHI["candles"]["live"]["candlesticks"]
    ]
    last = candles[-1]
    state = kalshi.state_at(candles, last.end)
    assert state.mid == pytest.approx((last.bid + last.ask) / 2)
    assert state.spread == pytest.approx(last.ask - last.bid)
    assert state.volume_7d == pytest.approx(sum(c.volume for c in candles))


# Published Thesis CDFs ------------------------------------------------------


@pytest.mark.parametrize("run", CDFS["runs"], ids=lambda r: r["dataPointId"])
def test_published_cdf_matches_the_documented_transform(run):
    """Differential: published points vs the interval_anchor_v1 port."""
    points = [tuple(p) for p in run["points"]]
    thesis.validate_cdf(run["runId"], points)
    record = thesis.ThesisRun(
        run_id=run["runId"],
        slug="",
        data_point_id=run["dataPointId"],
        label="",
        agent="",
        model=None,
        recorded_at="",
        registration=None,
        unit="",
        country="US",
        point=run["pointEstimate"],
        ci_low=run["interval80"][0],
        ci_high=run["interval80"][1],
        provenance=run["provenance"],
        transform_version="",
        resolution_date=None,
        cdf=points,
    )
    check = thesis.rebuild_check(record)
    if run["provenance"] == "interval_seeded":
        assert check == "rebuilt_exact"
        assert thesis.cdf_at(points, run["pointEstimate"]) == pytest.approx(
            0.5, abs=0.01
        )
    else:
        assert check.startswith("summary_knots")


def test_cdf_at_is_zero_below_and_one_above_support():
    points = [tuple(p) for p in CDFS["runs"][0]["points"]]
    assert thesis.cdf_at(points, points[0][0] - 10) == 0.0
    assert thesis.cdf_at(points, points[-1][0] + 10) == 1.0


# Scoring invariants -------------------------------------------------------------

unit_floats = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


@st.composite
def monotone_cdf(draw):
    xs = sorted(
        draw(
            st.lists(
                st.floats(-5, 5, allow_nan=False), min_size=2, max_size=8, unique=True
            )
        )
    )
    ps = sorted(draw(st.lists(unit_floats, min_size=len(xs), max_size=len(xs))))
    ps[0], ps[-1] = 0.0, 1.0
    points = list(zip(xs, ps))
    return lambda x: thesis.cdf_at(points, x)


strike_sets = st.lists(
    st.integers(-40, 40).map(lambda i: Decimal(i) / 10),
    min_size=1,
    max_size=12,
    unique=True,
).map(sorted)


@given(
    monotone_cdf(),
    strike_sets,
    st.sampled_from(["greater", "greater_or_equal"]),
    st.sampled_from(["rounded", "literal"]),
)
def test_thesis_brackets_are_a_distribution(cdf, strikes, strike_type, reading):
    yes = scoring.thesis_ladder(
        cdf, strikes, strike_type, Decimal("0.1"), Decimal(1), reading
    )
    assert all(a >= b - 1e-12 for a, b in zip(yes, yes[1:]))
    brackets = scoring.ladder_to_brackets(yes)
    assert len(brackets) == len(strikes) + 1
    assert all(b >= 0 for b in brackets)
    assert math.isclose(sum(brackets), 1.0, abs_tol=1e-9)


@given(st.lists(unit_floats, min_size=1, max_size=20))
def test_isotonic_repair(values):
    fit = scoring.isotonic_nonincreasing(values)
    assert len(fit) == len(values)
    assert all(a >= b - 1e-12 for a, b in zip(fit, fit[1:]))
    assert math.isclose(sum(fit), sum(values), abs_tol=1e-9)
    assert scoring.isotonic_nonincreasing(fit) == pytest.approx(fit)
    if scoring.ladder_violations(values) == 0:
        assert fit == pytest.approx(list(values))


@given(st.lists(unit_floats, min_size=2, max_size=15), st.sampled_from([0.001, 0.01]))
def test_floor_renormalize(probs, floor):
    if sum(probs) == 0 or floor * len(probs) >= 1:
        return
    out = scoring.floor_renormalize(probs, floor)
    assert math.isclose(sum(out), 1.0, abs_tol=1e-9)
    assert min(out) >= floor - 1e-12


@given(st.lists(unit_floats, min_size=2, max_size=8), st.integers(0, 7))
def test_score_bounds(raw, realized):
    if sum(raw) == 0:
        return
    probs = [p / sum(raw) for p in raw]
    realized %= len(probs)
    floored = scoring.floor_renormalize(probs, 0.001)
    assert scoring.log_score(floored, realized) <= 1e-12
    assert 0.0 <= scoring.brier_score(probs, realized) <= 2.0 + 1e-12


@settings(max_examples=200)
@given(
    st.lists(st.floats(0.01, 1.0), min_size=2, max_size=6),
    st.lists(st.floats(0.01, 1.0), min_size=2, max_size=6),
)
def test_scores_are_proper(truth_raw, other_raw):
    """Reporting the true distribution maximizes expected log and Brier skill."""
    k = min(len(truth_raw), len(other_raw))
    p = [x / sum(truth_raw[:k]) for x in truth_raw[:k]]
    q = [x / sum(other_raw[:k]) for x in other_raw[:k]]
    expected = lambda f, r: sum(p[i] * f(r, i) for i in range(k))  # noqa: E731
    assert expected(scoring.log_score, p) >= expected(scoring.log_score, q) - 1e-12
    assert expected(scoring.brier_score, p) <= expected(scoring.brier_score, q) + 1e-12


@given(
    st.integers(-60, 60).map(lambda i: Decimal(i) / 10),
    strike_sets,
    st.sampled_from(["greater", "greater_or_equal"]),
)
def test_realized_bracket_agrees_with_market_outcomes(value, strikes, strike_type):
    realized = scoring.realized_ladder_bracket(value, strikes, strike_type)
    outcomes = [contracts.market_yes("ladder", strike_type, s, value) for s in strikes]
    assert realized == sum(outcomes)
    assert outcomes == sorted(outcomes, reverse=True)


def test_rounded_reading_on_a_uniform_latent_value():
    # L ~ U[0, 1], published to 0.1: P(Y > 0.2) = P(L >= 0.25) = 0.75 and
    # P(Y >= 0.2) = P(L >= 0.15) = 0.85.
    def uniform(x):
        return min(1.0, max(0.0, x))

    above = scoring.thesis_ladder(
        uniform, [Decimal("0.2")], "greater", Decimal("0.1"), Decimal(1)
    )
    at_least = scoring.thesis_ladder(
        uniform, [Decimal("0.2")], "greater_or_equal", Decimal("0.1"), Decimal(1)
    )
    literal = scoring.thesis_ladder(
        uniform, [Decimal("0.2")], "greater", Decimal("0.1"), Decimal(1), "literal"
    )
    assert above == pytest.approx([0.75])
    assert at_least == pytest.approx([0.85])
    assert literal == pytest.approx([0.8])


def test_unit_conversion_for_thousands_to_persons():
    # Thesis forecasts payrolls in thousands; Kalshi strikes are persons.
    def cdf(x):
        return min(1.0, max(0.0, (x + 100) / 300))  # U[-100, 200] thousand

    yes = scoring.thesis_ladder(
        cdf, [Decimal("50000")], "greater", Decimal("1000"), Decimal("1000")
    )
    assert yes == pytest.approx([1 - (50.5 + 100) / 300])


@given(st.lists(unit_floats, min_size=1, max_size=10))
def test_exact_value_brackets(mids):
    brackets = scoring.market_exact(mids)
    assert math.isclose(sum(brackets), 1.0, abs_tol=1e-9)
    assert all(b >= 0 for b in brackets)


# Inference ------------------------------------------------------------------


def test_sign_flip_exact_small_cases():
    assert scoring.sign_flip_p([1.0, 1.0, 1.0]) == pytest.approx(2 / 8)
    assert scoring.sign_flip_p([1.0, -1.0]) == pytest.approx(1.0)


@settings(max_examples=50)
@given(st.lists(st.floats(-3, 3, allow_nan=False), min_size=1, max_size=10))
def test_sign_flip_is_symmetric_and_a_probability(values):
    p = scoring.sign_flip_p(values)
    assert 0 < p <= 1
    assert p == pytest.approx(scoring.sign_flip_p([-v for v in values]))


def test_bootstrap_is_deterministic_and_brackets_the_mean():
    values = [0.3, -0.1, 0.5, 0.2, -0.4, 0.1]
    first = scoring.bootstrap_ci(values)
    assert first == scoring.bootstrap_ci(values)
    assert first[0] <= scoring.mean(values) <= first[1]
    clustered = scoring.bootstrap_ci(values, ["a", "a", "b", "b", "c", "c"])
    assert clustered[0] <= scoring.mean(values) <= clustered[1]
    assert scoring.bootstrap_ci([0.2] * 5) == (pytest.approx(0.2), pytest.approx(0.2))


# Added after review r1 ------------------------------------------------------------


def test_census_construction_release():
    text = EXCERPTS["census_nrc_2026-07"]["excerpt"]
    assert official.parse_census_construction(text, "starts") == (
        "2026-07",
        Decimal("1.239"),
        Decimal("1.239"),
        "2026-08-18T12:30:00Z",
    )
    assert official.parse_census_construction(text, "permits")[1] == Decimal("1.443")


def test_census_new_home_sales_release():
    # The lead writes "seasonally-adjusted" with a hyphen; the release is 10:00 ET.
    assert official.parse_census_new_home_sales(
        EXCERPTS["census_nrs_2026-07"]["excerpt"]
    ) == ("2026-07", Decimal("607000"), Decimal("607000"), "2026-08-25T14:00:00Z")


def test_abs_labour_force_release_in_canberra_time():
    assert official.parse_abs_unemployment(EXCERPTS["abs_lf_2026-07"]["excerpt"]) == (
        "2026-07",
        Decimal("4.5"),
        Decimal("4.5"),
        "2026-08-20T01:30:00Z",
    )


@pytest.mark.parametrize(
    ("event", "series", "value"),
    [
        ("KXHOUSINGSTART-26AUG18", "KXHOUSINGSTART", Decimal("1.239")),
        ("KXBUILDPERMS-26AUG18", "KXBUILDPERMS", Decimal("1.443")),
        ("KXNHSALES-26AUG25", "KXNHSALES", Decimal("607000")),
        ("KXUE-AUS26JUL", "KXUE", Decimal("4.5")),
    ],
)
def test_added_series_reproduce_kalshi_results(event, series, value):
    series_spec = spec(series)
    period, _ = contracts.event_period(
        KALSHI["events"][event], KALSHI["markets"][event], "monthly"
    )
    assert period == "2026-07"
    for market in KALSHI["markets"][event]:
        strike = contracts.strike_of(market, series_spec)
        yes = contracts.market_yes("ladder", market["strike_type"], strike, value)
        assert market["result"] == ("yes" if yes else "no"), market["ticker"]


NEW_HOME_SALES_TARGET = (
    "census.new_residential_sales.new_single_family_houses_sold_saar.2026_07"
    ".first_print"
)


def test_added_thesis_targets_match():
    cases = {
        "census.housing_starts.saar.2026-07.first_print": ("KXHOUSINGSTART", "1"),
        "census.housing.permits_saar.2026_07.first_print": ("KXBUILDPERMS", "0.001"),
        NEW_HOME_SALES_TARGET: (
            "KXNHSALES",
            "1000",
        ),
        "abs.labour.unemployment_rate.2026_08.first_print": ("KXUE", "1"),
        "abs.labour.unemployment_rate.australia.july_2026.first_print": ("KXUE", "1"),
    }
    for data_point, (series, scale) in cases.items():
        ((found, _period, pattern),) = contracts.match_target(data_point)
        assert found.series == series and pattern.to_strike == Decimal(scale)
    assert spec("KXUE").event_prefix == "KXUE-AUS"


def test_rule_direction_must_match_strike_type():
    market = dict(KALSHI["markets"]["KXCPI-26AUG"][0])
    market["strike_type"] = "greater_or_equal"
    with pytest.raises(ValueError, match="strike_type"):
        contracts.strike_of(market, spec("KXCPI"))


@pytest.mark.parametrize(
    ("data_point", "period"),
    [
        ("bls.wp.WPSFD4.2026_07.first_print", "2026-07"),
        ("bls.cpi.owners_equivalent_rent_mom.july_2026.first_print", "2026-07"),
        ("us.dol.initial_claims.sa.week_2026-08-08", "2026-08-08"),
        ("census.housing_starts.saar.2026-07.first_print", "2026-07"),
        ("irs.actc.total_claims.2027.first_print.current_law", None),
        ("bls.productivity.nonfarm_qoq_prelim.2026_q3.first_print", "2026-Q3"),
    ],
)
def test_period_of(data_point, period):
    assert contracts.period_of(data_point) == period


class FakeCache:
    """Serves canned Kalshi /events pages for unmatched_rows."""

    def __init__(self, events):
        self.events = events

    def get_json(self, url, **_):
        return {"events": self.events, "cursor": ""}


def thesis_run(data_point: str, country: str = "US") -> thesis.ThesisRun:
    return thesis.ThesisRun(
        run_id=f"run.{data_point}",
        slug="",
        data_point_id=data_point,
        label="Headline",
        agent="thesis.analyst",
        model=None,
        recorded_at="2026-07-20T00:00:00Z",
        registration=None,
        unit="",
        country=country,
        point=0.0,
        ci_low=0.0,
        ci_high=0.0,
        provenance="",
        transform_version="",
        resolution_date=None,
    )


def test_unmatched_rows_cite_kalshi_evidence():
    from kalshi_compare import pipeline

    cache = FakeCache(
        [
            {
                "event_ticker": "KXUSPPI-26SEP10",
                "title": "PPI MoM in August",
                "sub_title": "August 2026",
            },
        ]
    )
    rows = pipeline.unmatched_rows(
        cache,
        [
            thesis_run("bls.wp.WPSFD4.2026_07.first_print"),
            thesis_run("fns.wic.total_participation.2026_09.first_print"),
        ],
    )
    ppi, wic = rows
    assert ppi["reason"] == "Kalshi's related series has no event for this period"
    assert "KXUSPPI: 2026-08" in ppi["kalshiEvidence"]
    assert wic["reason"].startswith("no Kalshi series")


def test_unmatched_rows_refuse_an_unhandled_match():
    from kalshi_compare import pipeline

    cache = FakeCache(
        [
            {
                "event_ticker": "KXUSPPI-26AUG",
                "title": "PPI MoM in July",
                "sub_title": "July 2026",
            }
        ]
    )
    with pytest.raises(ValueError, match="add a SeriesSpec"):
        pipeline.unmatched_rows(
            cache, [thesis_run("bls.wp.WPSFD4.2026_07.first_print")]
        )


def test_state_at_reaches_back_to_an_old_candle():
    # A book that last changed weeks before the horizon is still its state.
    old = kalshi.Candle(
        end=1_000,
        bid=0.4,
        ask=0.5,
        trade_close=None,
        trade_previous=0.45,
        volume=3.0,
        open_interest=10.0,
    )
    state = kalshi.state_at([old], 1_000 + 40 * 24 * 3600)
    assert state.candle_end == 1_000 and state.mid == pytest.approx(0.45)
    assert state.volume_7d == 0


def test_two_stage_interval_is_wider_than_fixed_strata():
    from kalshi_compare import pipeline

    groups = {"a": [1.0, 1.1], "b": [-1.0, -0.9], "c": [0.2, 0.3]}
    lo, hi = pipeline.two_stage_ci(groups)
    balanced = sum(sum(v) / len(v) for v in groups.values()) / len(groups)
    assert lo <= balanced <= hi
    assert hi - lo > 1.0  # between-series spread dominates


@pytest.mark.parametrize(
    "phrase",
    [
        "the unemployment rate increased 0.2ppt to 4.5%",
        "the unemployment rate rose to 4.5%",
        "the unemployment rate increased marginally to 4.5%",
    ],
)
def test_abs_unemployment_verb_variants(phrase):
    # ABS wrote "increased 0.2ppt to 4.6%" for August 2026.
    text = EXCERPTS["abs_lf_2026-07"]["excerpt"].replace(
        "the unemployment rate was 4.5%", phrase, 1
    )
    assert official.parse_abs_unemployment(text)[1] == Decimal("4.5")
