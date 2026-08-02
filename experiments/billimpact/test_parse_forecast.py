"""Pins on harness.parse_forecast (v2).

Every assertion here was negative-tested: each one fails against the v1 parser
that shipped before 2026-07-31, so a green run means the tests executed rather
than that they were vacuous. Run:

    python3 -m pytest experiments/billimpact/test_parse_forecast.py -q

The prose cases are VERBATIM tails of stored responses in `runs_api.jsonl`, not
invented text. The point of the fix is that the parser now reads what the model
actually wrote, so the fixture has to be what the model actually wrote.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402

# California, June 2021 — the last observed value in the supplied history for
# the snap.ca.* units. Used as the scale anchor throughout.
CA_ANCHOR = 4237518.0
PA_ANCHOR = 1771130.0
NY_ANCHOR = 2842019.0


# ---------------------------------------------------------------------------
# the defect itself: calendar years must never become forecasts
# ---------------------------------------------------------------------------

YEAR_HEAVY = (
    "Based on the historical pattern through mid-2021 (last available data point at "
    "4,237,518 in June 2021), and accounting for typical trends in California's SNAP "
    "caseload through mid-2023 — including the wind-down of pandemic-era emergency "
    "allotments (which ended in California in March 2023), and the new work-requirement "
    "policy changes taking effect only for new applications starting September 2023 — I "
    "estimate the December 2023 SNAP recipient count in California to be approximately "
    "4,900,000 persons. My 80% credible interval is approximately 4,650,000 to 5,150,000 "
    "persons, reflecting substantial uncertainty due to the nearly two-year gap."
)


def test_year_heavy_prose_does_not_return_a_year():
    """v1 returned {point: 2023, ci_low: 2021, ci_high: 2023} for this response."""
    got = H.parse_forecast(YEAR_HEAVY, "free_text", CA_ANCHOR)
    assert "parse_error" not in got
    for field in ("point", "ci_low", "ci_high"):
        assert not (1900 <= got[field] <= 2100), f"{field} is year-shaped: {got[field]}"


def test_year_heavy_prose_extracts_the_stated_forecast():
    got = H.parse_forecast(YEAR_HEAVY, "free_text", CA_ANCHOR)
    assert got["point"] == 4_900_000
    assert got["ci_low"] == 4_650_000
    assert got["ci_high"] == 5_150_000
    assert got["parse_mode"] == "prose_cued"


def test_no_degenerate_interval():
    """9 stored runs came back with ci_low == ci_high, i.e. no interval at all."""
    got = H.parse_forecast(YEAR_HEAVY, "free_text", CA_ANCHOR)
    assert got["ci_low"] < got["ci_high"]


def test_point_lies_inside_its_own_interval():
    got = H.parse_forecast(YEAR_HEAVY, "free_text", CA_ANCHOR)
    assert got["ci_low"] <= got["point"] <= got["ci_high"]
    assert "point_outside_interval" not in got


# ---------------------------------------------------------------------------
# ordering: prose reasons first and answers last
# ---------------------------------------------------------------------------

POINT_AFTER_INTERVAL = (
    "Extrapolating this trajectory to December 2023, I expect the New York SNAP caseload "
    "to be modestly higher than the June 2021 level of 2,842,019, likely in the range of "
    "about 2.85 million to 3.05 million persons, with a central estimate of approximately "
    "2,950,000 recipients."
)


def test_point_stated_after_the_interval():
    got = H.parse_forecast(POINT_AFTER_INTERVAL, "free_text", NY_ANCHOR)
    assert got["point"] == 2_950_000
    assert (got["ci_low"], got["ci_high"]) == (2_850_000, 3_050_000)


INTERIM_RANGE_THEN_ANSWER = (
    "Applying the historic trend (~-0.15%/month) over ~33 months from June 2021 gives "
    "roughly 1,680,000-1,720,000, adjusted slightly upward for the exemption-expansion "
    "effect, yielding a point estimate near 1,705,000. Given the substantial data gap, "
    "the 80% credible interval is wide: 1,620,000 to 1,790,000 persons."
)


def test_last_interval_wins_over_an_interim_calculation():
    """v1 took the FIRST matching window, i.e. the working, not the answer."""
    got = H.parse_forecast(INTERIM_RANGE_THEN_ANSWER, "free_text", PA_ANCHOR)
    assert got["point"] == 1_705_000
    assert (got["ci_low"], got["ci_high"]) == (1_620_000, 1_790_000)


# ---------------------------------------------------------------------------
# scale words
# ---------------------------------------------------------------------------

def test_scale_words_and_inherited_scale_on_the_low_bound():
    text = ("My central estimate is approximately 4.9 million persons, with an 80% "
            "credible interval of 4.65 to 5.15 million.")
    got = H.parse_forecast(text, "free_text", CA_ANCHOR)
    assert got["point"] == pytest.approx(4_900_000)
    assert got["ci_low"] == pytest.approx(4_650_000)
    assert got["ci_high"] == pytest.approx(5_150_000)


# ---------------------------------------------------------------------------
# the JSON path must not move
# ---------------------------------------------------------------------------

def test_strict_json_unchanged():
    text = ('{"point": 4950000, "ci_low": 4650000, "ci_high": 5250000, '
            '"rationale": "extrapolated"}')
    got = H.parse_forecast(text, "point_ci_json", CA_ANCHOR)
    assert got == {"point": 4950000.0, "ci_low": 4650000.0, "ci_high": 5250000.0,
                   "parse_mode": "json"}


def test_forced_choice_bin_is_preserved():
    text = '{"bin": "C", "point": 1740000, "ci_low": 1700000, "ci_high": 1780000}'
    got = H.parse_forecast(text, "forced_choice_bins", PA_ANCHOR)
    assert got["bin"] == "C"
    assert got["parse_mode"] == "json"


def test_json_path_ignores_the_scale_band():
    """D5 magnitude_elasticity runs at point_ci_json; a band there would mute it.

    A genuine order-of-magnitude forecast must survive the JSON path untouched,
    even though the prose path would reject it as off-scale.
    """
    text = '{"point": 400000, "ci_low": 350000, "ci_high": 450000}'
    got = H.parse_forecast(text, "point_ci_json", CA_ANCHOR)
    assert got["point"] == 400000.0
    assert got["parse_mode"] == "json"


def test_json_beats_prose_when_both_are_present():
    text = ("I reason that the level was near 4,237,518 in June 2021 and drifts to a range "
            "of 4,650,000 to 5,150,000.\n"
            '{"point": 4950000, "ci_low": 4650000, "ci_high": 5250000}')
    got = H.parse_forecast(text, "cot_then_json", CA_ANCHOR)
    assert got["parse_mode"] == "json"
    assert got["point"] == 4950000.0


# ---------------------------------------------------------------------------
# key-scan recovery for JSON that will not parse
# ---------------------------------------------------------------------------

def test_keyscan_recovers_a_truncated_trailing_object():
    """Truncated at max_tokens: numbers intact, closing brace gone."""
    text = ('Reasoning omitted.\n{"point": 1705000, "ci_low": 1620000, "ci_high": 1790000, '
            '"rationale": "Extrapolating the pre-pandemic downward trend from')
    got = H.parse_forecast(text, "cot_then_json", PA_ANCHOR)
    assert got["parse_mode"] == "json_keyscan"
    assert (got["point"], got["ci_low"], got["ci_high"]) == (1705000.0, 1620000.0, 1790000.0)


def test_keyscan_recovers_an_object_broken_by_a_doubled_quote():
    text = ('{"point": 1885000, "ci_low": 1780000, "ci_high": 1990000, '
            '"rationale": "the 2023 eligibility ""unwinding"" reduced caseloads"}')
    got = H.parse_forecast(text, "cot_then_json", PA_ANCHOR)
    assert got["parse_mode"] == "json_keyscan"
    assert got["point"] == 1885000.0


def test_keyscan_refuses_a_partial_object():
    """Two of three keys is a failure, not an invitation to infer the third."""
    text = '{"point": 1705000, "ci_low": 1620000, "rationale": "cut off here'
    got = H.parse_forecast(text, "cot_then_json", PA_ANCHOR)
    assert got["parse_mode"] != "json_keyscan"


# ---------------------------------------------------------------------------
# the parser extracts; it never imputes
# ---------------------------------------------------------------------------

def test_truncated_prose_fails_rather_than_guessing():
    text = ("Weighing the pre-2021 downward trend against the observed 2022-2023 rebound "
            "in caseloads from a base of 1,771,130, I expect Pennsylvania's SNAP recipient "
            "count in March 2024 to be notice")
    got = H.parse_forecast(text, "free_text", PA_ANCHOR)
    assert "parse_error" in got
    assert got["parse_mode"] == "failed"


def test_interval_without_a_point_is_not_filled_with_a_midpoint():
    text = ("My 80% credible interval for December 2023 is 4,650,000 to 5,150,000 persons.")
    got = H.parse_forecast(text, "free_text", CA_ANCHOR)
    assert "parse_error" in got
    assert got["parse_error"] == "interval_without_point"
    assert "point" not in got


def test_no_numbers_at_all():
    got = H.parse_forecast("I decline to forecast this series.", "free_text", CA_ANCHOR)
    assert got["parse_error"] == "no_scale_candidates"


# ---------------------------------------------------------------------------
# the anchor is a scale filter, not an accuracy filter
# ---------------------------------------------------------------------------

def test_a_large_but_real_move_still_parses():
    """A forecast 2.5x the last observation is wrong, not unparseable."""
    text = ("My central estimate is approximately 10,500,000 persons, with an 80% credible "
            "interval of 9,800,000 to 11,200,000.")
    got = H.parse_forecast(text, "free_text", CA_ANCHOR)
    assert got["point"] == 10_500_000
    assert got["parse_mode"] == "prose_cued"


def test_anchor_is_optional():
    """Without an anchor the parser is weaker but must still reject years."""
    got = H.parse_forecast(YEAR_HEAVY, "free_text", None)
    assert got["point"] == 4_900_000


def test_history_anchor_reads_the_supplied_history_not_the_truth():
    unit = {"history": [{"month": "2021-05-01", "value": 4200000},
                        {"month": "2021-06-01", "value": CA_ANCHOR}],
            "truth": {"first_print_value": 5318809.0}}
    assert H.history_anchor(unit) == CA_ANCHOR
    assert H.history_anchor({"history": []}) is None
