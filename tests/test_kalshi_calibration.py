"""Tests for the Kalshi calibration study (scripts/kalshi_calibration).

Fixtures are real data, written by ``scripts/kalshi_calibration_study.py
--write-fixtures`` from the run's stored responses:

- tests/fixtures/kalshi_calibration/settlements.json.gz: every settled event in
  the twelve series (2021-06 to 2026-10) with its official first print, or why
  it has none, and each market's rule fields and Kalshi's recorded result,
  fetched 2026-10-22 from api.elections.kalshi.com and the agencies' sites.
- tests/fixtures/kalshi_calibration/official_excerpts.json: normalized text
  excerpts of the releases whose layouts the parsers were extended for, with
  each document's URL and the SHA-256 of the full document.

Property tests state the study's invariants and run them over generated
inputs; differential tests check two readings of the same fact against each
other. ``KALSHI_CALIBRATION_CACHE`` set to the run's response store also
re-reads every official print from the full documents.
"""

from __future__ import annotations

import functools
import gzip
import json
import math
import os
import pathlib
import sys
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kalshi_calibration import calibration, history, pipeline, sensitivity  # noqa: E402
from kalshi_compare import contracts, kalshi, official, scoring  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "kalshi_calibration"
EXCERPTS = json.loads((FIXTURES / "official_excerpts.json").read_text())


@functools.lru_cache(maxsize=1)
def settlements() -> dict:
    return json.loads(gzip.decompress((FIXTURES / "settlements.json.gz").read_bytes()))


# Markets whose Kalshi settlement disagrees with the official first print,
# reviewed by reading the release: BEA's November 2024 release states core PCE
# rose 0.1 percent (table: 0.1), while Kalshi settled at 0.3.
KNOWN_DISAGREEMENTS = {"KXPCECORE-24NOV-T0.1", "KXPCECORE-24NOV-T0.2"}
# Settled events with no official outcome, and why (reviewed).
KNOWN_NO_PRINT = {
    "KXCPI-25OCT": "no official value",
    "KXCPI-25NOV": "no official value",
    "KXCPICORE-25OCT": "no official value",
    "KXCPICORE-25NOV": "no official value",
    "KXU3-25OCT": "no official value",
    "KXJOBLESSCLAIMS-25OCT02": "no DOL release",
}
KNOWN_UNREADABLE_PERIOD = {"CPI-22JUN", "KXJOBLESSCLAIMS-25JUN12"}


def spec(series: str) -> contracts.SeriesSpec:
    return history.spec_for(series)


# Differential: official prints reproduce Kalshi's settlements ---------------


def scored_events():
    return [e for e in settlements()["events"] if e["officialValue"] is not None]


def test_fixture_covers_every_series_from_its_start():
    series = {e["series"] for e in settlements()["events"]}
    assert series == set(history.SERIES)
    first = min(e["period"] for e in scored_events() if e["series"] == "KXCPI")
    assert first == "2021-06"


def test_official_print_reproduces_every_kalshi_result():
    """The print under each market's > or >= rule gives Kalshi's recorded result."""
    disagreements, checked, expected = set(), 0, 0
    for event in scored_events():
        dropped = {d["ticker"] for d in event["droppedMarkets"]}
        expected += sum(1 for m in event["markets"] if m["ticker"] not in dropped)
        value = Decimal(event["officialValue"])
        dropped = {d["ticker"] for d in event["droppedMarkets"]}
        for market in event["markets"]:
            if market["ticker"] in dropped:
                with pytest.raises(ValueError):
                    history.read_strike(market, spec(event["series"]))
                continue
            strike = history.read_strike(market, spec(event["series"]))
            yes = contracts.market_yes(
                "ladder", strike.strike_type, strike.value, value
            )
            checked += 1
            if ("yes" if yes else "no") != market["result"]:
                disagreements.add(market["ticker"])
    assert checked == expected > 2900
    assert disagreements == KNOWN_DISAGREEMENTS


def test_events_without_an_official_outcome_are_the_reviewed_ones():
    no_print = {
        e["eventTicker"]: e["officialNote"]
        for e in settlements()["events"]
        if e["period"] and e["officialValue"] is None
    }
    assert set(no_print) == set(KNOWN_NO_PRINT)
    for ticker, reason in KNOWN_NO_PRINT.items():
        assert reason in no_print[ticker]
    unreadable = {e["eventTicker"] for e in settlements()["events"] if not e["period"]}
    assert unreadable == KNOWN_UNREADABLE_PERIOD


@pytest.mark.skipif(
    not os.environ.get("KALSHI_CALIBRATION_CACHE"),
    reason="set KALSHI_CALIBRATION_CACHE to the run's response store",
)
def test_full_documents_reproduce_every_fixture_print():
    from kalshi_compare.fetch import FetchCache

    cache = FetchCache(
        pathlib.Path(os.environ["KALSHI_CALIBRATION_CACHE"]), offline=True
    )
    for expected in settlements()["events"]:
        if not expected["period"]:
            continue
        dropped = {d["ticker"] for d in expected["droppedMarkets"]}
        event = history.Event(
            expected["series"],
            spec(expected["series"]),
            {"event_ticker": expected["eventTicker"]},
            [m for m in expected["markets"] if m["ticker"] not in dropped],
        )
        event.period = expected["period"]
        history.locate_print(cache, event)
        got = None if event.official is None else str(event.official.value)
        assert got == expected["officialValue"], expected["eventTicker"]


# Contract reading -------------------------------------------------------------


def market(**fields):
    base = {"strike_type": None, "floor_strike": None, "yes_sub_title": None}
    return {**base, **fields}


def test_legacy_rule_with_no_number_reads_subtitle_and_ticker():
    m = market(
        ticker="U3-22MAY-T3.4",
        rules_primary=(
            "If the unemployment rate (U-3) is above % in May 2022 then the "
            "market resolves to Yes."
        ),
        yes_sub_title="Above 3.4%",
    )
    strike = history.read_strike(m, spec("KXU3"))
    assert (strike.value, strike.strike_type, strike.source) == (
        Decimal("3.4"),
        "greater",
        "sub_title_and_ticker",
    )


def test_legacy_subtitle_must_match_ticker():
    m = market(
        ticker="U3-22MAY-T3.5",
        rules_primary=(
            "If the unemployment rate (U-3) is above % in May 2022 then the "
            "market resolves to Yes."
        ),
        yes_sub_title="Above 3.4%",
    )
    with pytest.raises(ValueError):
        history.read_strike(m, spec("KXU3"))


def test_legacy_greater_than_and_percent_words():
    core = market(
        ticker="CPICORE-22DEC-T0.1",
        strike_type="greater",
        floor_strike=0.1,
        rules_primary=(
            "If the signed one-month percent change in the seasonally adjusted Consumer"
            " Price Index for All Urban Consumers: All Items less Food and Energy for"
            " December 2022, as published by the Bureau of Labor Statistics, is greater"
            " than 0.1%, then the market resolves to Yes."
        ),
    )
    assert history.read_strike(core, spec("KXCPICORE")).value == Decimal("0.1")
    headline = market(
        ticker="CPI-21OCT-T0.5",
        rules_primary=(
            "If the CPI increases by more than 0.50 percent% in October 2021, "
            "then the market resolves to Yes."
        ),
        yes_sub_title="Above 0.5%",
    )
    strike = history.read_strike(headline, spec("KXCPI"))
    assert (strike.value, strike.strike_type) == (Decimal("0.50"), "greater")


def test_floor_strike_noise_is_tolerated_but_a_real_conflict_is_not():
    noisy = market(
        ticker="KXU3-25MAY-T4.1",
        strike_type="greater",
        floor_strike=4.099999,
        rules_primary=(
            "If the seasonally adjusted unemployment rate (U-3) reported by the Bureau"
            " of Labor Statistics in the Employment Situation Report is above 4.1% in"
            " May 2025, then the market resolves to Yes."
        ),
    )
    strike = history.read_strike(noisy, spec("KXU3"))
    assert strike.value == Decimal("4.1") and strike.source.endswith("floor_rounded")
    conflict = market(
        ticker="PCECORE-22NOV-TN0.1",
        strike_type="greater",
        floor_strike=0.1,
        rules_primary=(
            "If the (single-decimal) month-over-month percent change in the Personal"
            " Consumption Expenditures Price Index excluding food and energy is above"
            " -0.1% in November 2022, then the market resolves to Yes."
        ),
    )
    with pytest.raises(ValueError):
        history.read_strike(conflict, spec("KXPCECORE"))


def test_rule_direction_must_agree_with_strike_type():
    m = market(
        ticker="X-T200000",
        strike_type="greater",
        floor_strike=200000,
        rules_primary=(
            "If there are at least 200000 initial jobless claims for the week "
            "ending Sep 27, 2025, then the market resolves to Yes."
        ),
    )
    with pytest.raises(ValueError):
        history.read_strike(m, spec("KXJOBLESSCLAIMS"))


def test_legacy_rule_periods():
    event = {"title": "CPI in June 2021?", "sub_title": ""}
    month_only = [
        {
            "ticker": "CPI-21JUN-T0.6",
            "rules_primary": (
                "If the CPI increases by more than 0.6% in June, then the "
                "market resolves to Yes."
            ),
        }
    ]
    assert history.event_period(event, month_only, "monthly") == (
        "2021-06",
        "title names the period; legacy rules name its month alone",
        True,
    )
    comma = [
        {
            "ticker": "CPI-21JUL-T0.7",
            "rules_primary": (
                "If the CPI increases by more than 0.7% in July, 2021, then "
                "the market resolves to Yes."
            ),
        }
    ]
    assert (
        history.event_period({"title": "CPI in July 2021?"}, comma, "monthly")[0]
        == "2021-07"
    )
    other_month = [
        {
            "ticker": "CPI-22JUN-T0.2",
            "rules_primary": (
                "If the Consumer Price Index (CPI) increases by more "
                "than 0.2% in July 2022, then the market resolves to Yes."
            ),
        }
    ]
    assert (
        history.event_period({"title": "CPI in June 2022?"}, other_month, "monthly")[0]
        is None
    )


# Official parsers on older and shutdown-era layouts -----------------------------


def text(key: str) -> str:
    return EXCERPTS[key]["excerpt"]


def test_cpi_2021_layout_with_split_header_and_short_decimals():
    period, value, lead, release = official.parse_bls_cpi(
        text("bls_cpi_2021-06"), "headline"
    )
    assert (period, value, release) == (
        "2021-06",
        Decimal("0.9"),
        "2021-07-13T12:30:00Z",
    )
    assert lead in (None, value)


def test_cpi_embargo_line_without_weekday():
    assert (
        official.parse_bls_cpi(text("bls_cpi_2022-07"), "headline")[3]
        == "2022-08-10T12:30:00Z"
    )


def test_cpi_shutdown_months_have_no_value():
    with pytest.raises(official.NoValuePublishedError):
        official.parse_bls_cpi(text("bls_cpi_2025-11"), "headline")
    assert (
        history._cpi_prior_column(
            text("bls_cpi_2025-11"), "bls_cpi_headline", "2025-10"
        )
        is None
    )
    # December 2025 reads its own column past the October and November dashes.
    period, value, _, _ = official.parse_bls_cpi(text("bls_cpi_2025-12"), "core")
    assert period == "2025-12" and value is not None


def test_employment_situation_with_a_dash_column():
    t = text("bls_empsit_2025-11")
    assert official.parse_bls_empsit(t, "unemployment")[1] == Decimal("4.6")
    assert official.parse_bls_empsit(t, "payrolls")[1] == Decimal("64000")
    # October 2025's payroll change was first published here, a month late.
    assert history.prior_column_value(t, "bls_payrolls", "2025-10") == Decimal(
        "-105000"
    )
    # October 2025's unemployment rate was never published.
    assert history.prior_column_value(t, "bls_unemployment", "2025-10") is None
    assert official.parse_bls_empsit(text("bls_empsit_2025-12"), "unemployment")[
        1
    ] == Decimal("4.4")


@pytest.mark.parametrize(
    "key,period,value,how",
    [
        ("bea_pio_2022-11", "2022-11", "0.2", "five-column table"),
        ("bea_pio_2024-11", "2024-11", "0.1", "five-column table"),
        ("bea_pio_2024-12", "2024-12", "0.2", "release text (no table on the page)"),
        ("bea_pio_2025-03", "2025-03", "0.0", "from-to table"),
        ("bea_pio_2025-10-11", "2025-10", "0.2", "two-column table"),
        ("bea_pio_2025-10-11", "2025-11", "0.2", "two-column table"),
        ("bea_pio_2026-03", "2026-03", "0.3", "two-column table"),
    ],
)
def test_bea_layouts(key, period, value, how):
    got, second, release, read = history.bea_core_pce(text(key), period)
    assert (got, read) == (Decimal(value), how)
    assert second in (None, got)
    assert release.endswith("Z")


def test_bea_release_for_another_month_is_refused():
    with pytest.raises(official.OfficialParseError):
        history.bea_core_pce(text("bea_pio_2026-03"), "2026-02")


@pytest.mark.parametrize(
    "key,value", [("abs_lf_2026-02", "4.3"), ("abs_lf_2026-04", "4.5")]
)
def test_abs_reads_the_seasonally_adjusted_paragraph_and_table(key, value):
    period, lead, second, _ = official.parse_abs_unemployment(text(key))
    assert lead == second == Decimal(value)


# Invariants -----------------------------------------------------------------

unit = st.floats(0, 1, allow_nan=False)
grid = st.integers(1, 199).map(lambda c: c / 200)  # Kalshi midpoints, half cents


@st.composite
def training_tables(draw):
    ps = draw(st.lists(grid, min_size=2, max_size=40, unique=True))
    table = {}
    for p in ps:
        n = draw(st.integers(1, 30))
        table[p] = [float(n), float(draw(st.integers(0, n)))]
    return table


@settings(max_examples=150, deadline=None)
@given(training_tables(), st.sampled_from(["logistic", "beta"]))
def test_recalibration_maps_are_monotone(table, model):
    mapping = calibration.FITTERS[model](table)
    probe = [i / 400 for i in range(401)]
    values = [mapping(p) for p in probe]
    assert all(0 <= v <= 1 for v in values)
    assert all(b >= a - 1e-12 for a, b in zip(values, values[1:]))
    if model == "beta":
        assert mapping.params[1] >= 0 and mapping.params[2] >= 0
    else:
        assert mapping.params[1] >= 0


@settings(max_examples=200, deadline=None)
@given(
    st.lists(unit, min_size=1, max_size=15),
    st.floats(-3, 3),
    st.floats(0, 4),
    st.floats(0, 4),
    st.sampled_from([0.001, 0.01]),
)
def test_recalibrated_brackets_are_a_distribution(raw, c, a, b, floor):
    ladder = scoring.isotonic_nonincreasing(raw)
    for mapping in (
        calibration.Map("logistic", (c, a)),
        calibration.Map("beta", (c, a, b)),
        calibration.IDENTITY,
    ):
        recal = calibration.recalibrated_ladder(ladder, mapping)
        assert all(y <= x + 1e-12 for x, y in zip(recal, recal[1:]))
        brackets = scoring.ladder_to_brackets(recal)
        assert all(p >= 0 for p in brackets)
        assert math.isclose(sum(brackets), 1.0, abs_tol=1e-9)
        if floor * len(brackets) < 1:
            floored = scoring.floor_renormalize(brackets, floor)
            assert math.isclose(sum(floored), 1.0, abs_tol=1e-9)
            assert min(floored) >= floor - 1e-12


@st.composite
def candle_histories(draw):
    ends = sorted(draw(st.sets(st.integers(0, 2000), min_size=0, max_size=30)))
    candles = []
    for end in ends:
        traded = draw(st.booleans())
        candles.append(
            kalshi.Candle(
                end=end * 3600,
                bid=draw(st.none() | grid),
                ask=draw(st.none() | grid),
                trade_close=draw(grid) if traded else None,
                trade_previous=draw(st.none() | grid),
                volume=1.0 if traded else 0.0,
                open_interest=None,
            )
        )
    return candles


@settings(max_examples=300, deadline=None)
@given(candle_histories(), st.integers(-10, 2100))
def test_no_candle_after_the_horizon(candles, hour):
    at = hour * 3600
    state = kalshi.state_at(candles, at)
    if state.candle_end is not None:
        assert state.candle_end <= at
        later = [c for c in candles if c.end > at]
        assert all(c.end != state.candle_end for c in later)
    else:
        assert all(c.end > at for c in candles)


def synthetic_item(candles_by_ticker, open_ts, close_ts, anchor):
    markets = []
    strikes = {}
    for index, ticker in enumerate(sorted(candles_by_ticker)):
        markets.append(
            {
                "ticker": ticker,
                "open_time": kalshi.iso(open_ts[index]),
                "close_time": kalshi.iso(close_ts[index]),
                "result": "yes" if index == 0 else "no",
            }
        )
        strikes[ticker] = history.Strike(Decimal(index), "greater", "rule")
    event = history.Event("KXCPI", spec("KXCPI"), {"event_ticker": "T"}, markets)
    event.strikes = strikes
    event.period = "2026-01"
    event.settled = True
    return pipeline.Scored(
        event, candles_by_ticker, {}, False, anchor, anchor, "2026-01-01", True
    )


@settings(max_examples=100, deadline=None)
@given(
    st.lists(candle_histories(), min_size=1, max_size=4),
    st.data(),
)
def test_every_horizon_reads_only_earlier_candles(histories, data):
    tickers = [f"M{i}" for i in range(len(histories))]
    opens = [data.draw(st.integers(0, 500)) * 3600 for _ in tickers]
    closes = [o + data.draw(st.integers(1, 1500)) * 3600 for o in opens]
    anchor = max(closes)
    item = synthetic_item(dict(zip(tickers, histories)), opens, closes, anchor)
    for name, kind, value in pipeline.HORIZONS:
        at = pipeline.event_instant(item, name)
        if kind == "fixed":
            assert at == anchor - value
        else:
            assert item.event.first_open <= at <= anchor
        quotes, _ = pipeline.quotes_at(item, at)
        assert all(q.state.candle_end <= at for q in quotes)
        assert all(kalshi.to_ts(q.market["open_time"]) <= at for q in quotes)
        exclusions = []
        rows = pipeline.paper_rows(
            item, pipeline.base_row(item), name, kind, value, at, exclusions
        )
        for row in rows:
            assert (
                kalshi.state_at(item.candles[row["ticker"]], row["at"]).candle_end
                <= row["at"]
            )
            if kind == "life":
                start = pipeline.first_trade_start(item.candles[row["ticker"]])
                market = next(
                    m for m in item.event.markets if m["ticker"] == row["ticker"]
                )
                assert start <= row["at"] <= pipeline.market_end(item, market)
                assert row["at"] <= item.release_ts


@settings(max_examples=300, deadline=None)
@given(
    st.integers(-300, 300).map(lambda v: Decimal(v) / 10),
    st.lists(st.integers(-300, 300), min_size=1, max_size=12, unique=True).map(
        lambda xs: sorted(Decimal(x) / 10 for x in xs)
    ),
    st.sampled_from(["greater", "greater_or_equal"]),
)
def test_realized_bracket_follows_each_contract_rule(value, strikes, strike_type):
    realized = scoring.realized_ladder_bracket(value, strikes, strike_type)
    for index, strike in enumerate(strikes):
        yes = contracts.market_yes("ladder", strike_type, strike, value)
        assert yes == (index < realized)
    # The sensitivity's outcome rule (index < realized) is the same statement.
    outcomes = [i < realized for i in range(len(strikes))]
    assert outcomes == [
        contracts.market_yes("ladder", strike_type, s, value) for s in strikes
    ]


@settings(max_examples=150, deadline=None)
@given(
    st.lists(st.integers(0, 15), min_size=1, max_size=60),
    st.data(),
)
def test_forward_folds_never_train_on_later_outcomes(cluster_ids, data):
    clusters = [f"d{c:02d}" for c in cluster_ids]
    # Releases follow the cluster's day; instants come before the release.
    releases = [c * 100 + data.draw(st.integers(0, 50)) for c in cluster_ids]
    instants = [r - data.draw(st.integers(0, 400)) for r in releases]
    folds, skipped = calibration.forward_folds(
        clusters, instants, releases, min_clusters=2
    )
    assert {f.cluster for f in folds} | set(skipped) == set(clusters)
    for fold in folds:
        assert all(clusters[i] == fold.cluster for i in fold.test)
        assert fold.first_instant == min(instants[i] for i in fold.test)
        assert all(releases[i] < fold.first_instant for i in fold.train)
        assert not set(fold.train) & set(fold.test)


def test_logistic_fit_recovers_known_parameters():
    # Expected counts under logit q = 0.3 + 1.6 logit p, on a price grid.
    table = {}
    for c in range(5, 200, 5):
        p = c / 200
        q = calibration.expit(0.3 + 1.6 * calibration.logit(p))
        table[p] = [1000.0, 1000.0 * q]
    mapping = calibration.fit_logistic(table)
    assert mapping.converged
    assert mapping.params[0] == pytest.approx(0.3, abs=1e-6)
    assert mapping.params[1] == pytest.approx(1.6, abs=1e-6)
    beta = calibration.fit_beta(table)
    assert beta.converged


def test_beta_fit_of_calibrated_prices_is_near_identity():
    table = {c / 200: [2000.0, 2000.0 * c / 200] for c in range(2, 199, 2)}
    mapping = calibration.fit_beta(table)
    for p in (0.05, 0.3, 0.5, 0.8, 0.97):
        assert mapping(p) == pytest.approx(p, abs=0.002)


def test_compression_verdicts():
    assert calibration.verdict([1.1, 1.4]) == "compressed toward 50%"
    assert calibration.verdict([0.6, 0.9]) == "too extreme"
    assert calibration.verdict([0.9, 1.2]) == "neither shown"


def test_bootstrap_is_deterministic_and_resamples_clusters():
    values = {"a": [1.0, 1.0, 1.0], "b": [0.0], "c": [2.0]}
    first = calibration.bootstrap_mean(values, draws=500)
    second = calibration.bootstrap_mean(values, draws=500)
    assert first == second
    assert first["mean"] == pytest.approx(1.0)
    # Whole clusters move together: a draw of only "a" has mean exactly 1.
    assert first["ci95"][0] >= 0.0 and first["ci95"][1] <= 2.0


def test_reliability_summary_identities():
    rows = [(0.05, 0), (0.05, 1), (0.42, 0), (0.42, 1), (0.42, 1), (0.91, 1)]
    stats = calibration.cluster_stats(rows)
    summary = calibration.summary_of(stats)
    brier = sum((p - y) ** 2 for p, y in rows) / len(rows)
    assert summary["brier"] == pytest.approx(brier)
    assert summary["brier"] == pytest.approx(
        summary["reliability"]
        - summary["resolution"]
        + summary["uncertainty"]
        + summary["withinBin"]
    )
    below = [(p, y) for p, y in rows if p < 0.5]
    assert summary["belowHalf"] == pytest.approx(
        sum(y - p for p, y in below) / len(below)
    )


# Sensitivity for #381 -----------------------------------------------------------


def score_row(**overrides):
    row = {
        "eventKey": "KXCPI:2026-08",
        "series": "KXCPI",
        "horizon": "release_minus_1d",
        "horizonAt": "2026-09-10T12:30:00Z",
        "releaseAt": "2026-09-11T12:30:00Z",
        "spec": "primary",
        "kalshiRepairedPrices": [0.97, 0.8, 0.41, 0.12, 0.02],
        "realizedBracket": 3,
        "kalshiLog": None,
        "kalshiBrier": None,
        "kalshiLadderBrier": 0.0,
    }
    row.update(overrides)
    return row


def test_identity_map_reproduces_kalshi_scores():
    row = score_row()
    brackets = scoring.ladder_to_brackets(row["kalshiRepairedPrices"])
    out = sensitivity.recalibrated_score(row, calibration.IDENTITY, 0.001)
    assert out["kalshiBrackets"] == brackets
    assert out["kalshiLog"] == scoring.log_score(
        scoring.floor_renormalize(brackets, 0.001), 3
    )
    assert out["kalshiBrier"] == scoring.brier_score(brackets, 3)
    outcomes = [True, True, True, False, False]
    assert out["kalshiLadderBrier"] == scoring.ladder_brier(
        row["kalshiRepairedPrices"], outcomes
    )


@pytest.mark.parametrize(
    "horizon,lead_days,expected",
    [
        ("release_minus_7d", 7, "anchor_7d"),
        ("release_minus_1d", 1, "anchor_1d"),
        ("at_registration", 40, "anchor_30d"),
        ("at_registration", 14.6, "anchor_30d"),
        ("at_registration", 14.4, "anchor_7d"),
        ("at_registration", 2.7, "anchor_7d"),
        ("at_registration", 2.6, "anchor_1d"),
    ],
)
def test_registration_pairs_use_the_nearest_fixed_horizon(horizon, lead_days, expected):
    release = kalshi.to_ts("2026-09-11T12:30:00Z")
    row = score_row(
        horizon=horizon, horizonAt=kalshi.iso(int(release - lead_days * 86400))
    )
    assert sensitivity.horizon_class(row) == expected


def test_sensitivity_trains_only_on_earlier_releases():
    rows = [
        {
            "horizon": "anchor_1d",
            "hasOfficial": True,
            "releaseTs": 100,
            "p": 0.2,
            "yOfficial": 0,
        },
        {
            "horizon": "anchor_1d",
            "hasOfficial": True,
            "releaseTs": 200,
            "p": 0.2,
            "yOfficial": 1,
        },
        {
            "horizon": "anchor_7d",
            "hasOfficial": True,
            "releaseTs": 50,
            "p": 0.3,
            "yOfficial": 1,
        },
    ]
    assert sensitivity.training_table(rows, "anchor_1d", 150) == {0.2: [1.0, 0.0]}
    assert sensitivity.training_table(rows, "anchor_1d", 100) == {}


FROZEN_381 = (
    pathlib.Path.home() / "reviews/thesis-vs-kalshi-2026-10/results/results.json"
)


@pytest.mark.skipif(
    not FROZEN_381.exists(), reason="#381's frozen results are local only"
)
def test_quoted_381_numbers_are_the_frozen_summary():
    frozen = json.loads(FROZEN_381.read_text())["summary"]["thesis_headline"]
    for (
        spec_name,
        horizon,
        subset,
        metric,
    ), quoted in sensitivity.QUOTED_IN_381_SUMMARY.items():
        block = frozen[spec_name][horizon]
        value = (block["pooled"] if subset == "pooled" else block[subset])[metric]
        mean, (lo, hi) = value["mean"], value["ci95ReleaseClustered"]
        expected = (
            f"{mean:+.2f}"
            if "[" not in quoted
            else f"{mean:+.2f} [{lo:+.2f}, {hi:+.2f}]"
        )
        assert expected == quoted, (spec_name, horizon, subset, metric)


@pytest.mark.skipif(
    not FROZEN_381.exists(), reason="#381's frozen results are local only"
)
def test_381_code_reproduces_its_frozen_summary():
    from kalshi_compare import pipeline as compare_pipeline

    frozen = json.loads(FROZEN_381.read_text())
    rebuilt = compare_pipeline.summarize_pairs(
        compare_pipeline.build_pairs(frozen["scores"])
    )
    assert json.loads(json.dumps(rebuilt)) == frozen["summary"]
