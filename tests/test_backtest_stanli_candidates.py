"""Ports and real-time target logic in scripts/backtest_stanli_candidates.py."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import random
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve string annotations through sys.modules.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


backtest = load_script("backtest_stanli_candidates")
analyst = load_script("run_thesis_analyst")
resolver = load_script("resolve_pending")

UNIFORM = [{"value": index / 200, "probability": index / 200} for index in range(201)]


@given(st.floats(min_value=-2, max_value=3, allow_nan=False))
def test_crps_of_a_uniform_cdf_matches_the_closed_form(observed):
    if observed < 0:
        expected = 1 / 3 - observed
    elif observed > 1:
        expected = 1 / 3 + observed - 1
    else:
        expected = observed**2 - observed + 1 / 3
    crps, pit = backtest.score_numeric_cdf(UNIFORM, observed)

    assert crps == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert pit == pytest.approx(min(max(observed, 0), 1), abs=1e-12)


@pytest.mark.skipif(shutil.which("bun") is None, reason="bun missing")
def test_crps_port_matches_the_site_scorer(tmp_path):
    # Differential: score the same CDFs and outcomes with the TypeScript
    # scoreNumericCdfDistribution and with the Python port.
    rng = random.Random(11)
    cases = []
    for _ in range(40):
        point = rng.uniform(-50, 50)
        low = point - rng.uniform(0, 5)
        high = point + rng.uniform(0, 5)
        cdf = analyst.interval_distribution(
            {"pointEstimate": point, "ciLow": low, "ciHigh": high}
        )
        support = cdf["support"]
        span = support["upper"] - support["lower"]
        for observed in (
            rng.uniform(support["lower"] - span, support["upper"] + span),
            cdf["points"][rng.randrange(201)]["value"],
            point,
        ):
            cases.append({"distribution": cdf, "observed": observed})
    harness = tmp_path / "score.ts"
    module = (ROOT / "site/src/data/prediction-distribution.ts").as_posix()
    harness.write_text(
        f'import {{ scoreNumericCdfDistribution }} from "{module}";\n'
        "const cases = JSON.parse(await Bun.stdin.text());\n"
        "console.log(JSON.stringify(cases.map((c: any) =>\n"
        "  scoreNumericCdfDistribution(c.distribution, c.observed))));\n"
    )
    result = subprocess.run(
        ["bun", "run", str(harness)],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        check=True,
    )
    expected = json.loads(result.stdout)

    for case, site in zip(cases, expected, strict=True):
        crps, pit = backtest.score_numeric_cdf(
            case["distribution"]["points"], case["observed"]
        )
        assert crps == site["crps"]
        assert pit == site["probabilityIntegralTransform"]


def test_persistence_interval_uses_the_80th_percentile_absolute_change():
    # |changes| = 1, 2, 4, 8: the 0.8 quantile interpolates 4 and 8 at 0.4.
    point, low, high = backtest.persistence_interval([0, 1, 3, 7, 15])
    assert (point, low, high) == (15, 15 - 5.6, 15 + 5.6)
    assert backtest.ts_quantile([], 0.8) == 0.0
    assert backtest.ts_quantile([3.0], 0.8) == 3.0


def test_vintage_grid_takes_the_first_and_sixteenth():
    dates = backtest.vintage_grid(dt.date(2024, 11, 16), dt.date(2025, 1, 1))
    assert [date.isoformat() for date in dates] == [
        "2024-11-16",
        "2024-12-01",
        "2024-12-16",
        "2025-01-01",
    ]


def test_parse_vintage_csv_reads_each_vintage_column():
    text = (
        "observation_date,UNRATE_20260801,UNRATE_20261001\n"
        "2026-06-01,4.2,4.2\n"
        "2026-07-01,.,4.1\n"
        "2026-08-01,,4.1\n"
    )
    assert backtest.parse_vintage_csv(text) == {
        "2026-08-01": {"2026-06-01": 4.2},
        "2026-10-01": {"2026-06-01": 4.2, "2026-07-01": 4.1, "2026-08-01": 4.1},
    }


def test_adapter_series_dedupes_unit_variants():
    specs = backtest.adapter_series(resolver.ALFRED_ADAPTERS)
    keys = [spec.key for spec in specs]

    assert len(keys) == len(set(keys))
    assert keys.count("JTSJOL:level") == 1
    assert keys.count("PCEPILFE:pct_change_1d") == 1
    assert len(specs) == len(
        {
            (spec["fred"], spec["transform"])
            for spec in resolver.ALFRED_ADAPTERS.values()
        }
    )


def real_time(transform: str, vintages: dict) -> list:
    spec = backtest.SeriesSpec(
        fred="TEST", transform=transform, scale=1.0, digits=None, stems=("t",)
    )
    return backtest.real_time_targets(
        spec,
        vintages,
        window=60,
        max_targets=24,
        apply_transform=resolver.apply_transform,
        prior_period=resolver.prior_period_date,
    )


VINTAGES = {
    "2024-03-16": {"2024-01-01": 1.0, "2024-02-01": 2.0},
    # March's first print arrives with a revision to February.
    "2024-04-16": {"2024-01-01": 1.0, "2024-02-01": 2.1, "2024-03-01": 3.5},
    # Two new months at once: April is one step ahead of the information set
    # (which ends in March) and May is two steps ahead, so it is skipped.
    "2024-06-16": {
        "2024-01-01": 1.0,
        "2024-02-01": 2.1,
        "2024-03-01": 3.5,
        "2024-04-01": 4.0,
        "2024-05-01": 4.4,
    },
}


def test_targets_train_on_the_vintage_before_release():
    targets = real_time("level", VINTAGES)

    assert [(t.period, t.history, t.outcome) for t in targets] == [
        ("2024-03", (1.0, 2.0), 3.5),
        ("2024-04", (1.0, 2.1, 3.5), 4.0),
    ]
    assert [(t.info_vintage, t.release_vintage) for t in targets] == [
        ("2024-03-16", "2024-04-16"),
        ("2024-04-16", "2024-06-16"),
    ]


def test_differenced_targets_use_the_release_vintage_for_both_months():
    vintages = dict(VINTAGES)
    vintages["2024-05-16"] = {
        **VINTAGES["2024-04-16"],
        "2024-04-01": 4.0,
    }
    targets = real_time("mom_diff", vintages)

    by_period = {t.period: t for t in targets}
    # March's change comes from the release vintage, which revised February.
    assert by_period["2024-03"].outcome == pytest.approx(3.5 - 2.1)
    assert by_period["2024-03"].history == (pytest.approx(1.0),)
    assert by_period["2024-04"].outcome == pytest.approx(0.5)
    assert by_period["2024-05"].outcome == pytest.approx(0.4)


def test_period_type_reads_quarterly_spacing():
    assert backtest.period_type(["2024-01-01", "2024-04-01", "2024-07-01"]) == (
        "quarter"
    )
    assert backtest.period_type(["2024-01-01", "2024-02-01", "2024-03-01"]) == ("month")


def test_summary_pairs_each_arm_with_persistence():
    rows = []
    for series in ("A", "B"):
        for period in ("p1", "p2"):
            for arm, crps in (("persistence", 2.0), ("half", 1.0)):
                rows.append(
                    {
                        "series": series,
                        "period": period,
                        "arm": arm,
                        "crps": crps,
                        "normalizedCrps": crps / 4,
                        "covered80": arm == "half",
                        "samplerFailed": False,
                    }
                )
    summary = backtest.summarize(rows, draws=50)

    half = summary["arms"]["half"]
    assert half["geometricMeanCrpsRatio"] == pytest.approx(0.5)
    assert half["meanNormalizedCrpsDifference"] == pytest.approx(-0.25)
    assert half["shareBeatingBaseline"] == 1.0
    assert half["coverage80"] == 1.0
    assert half["interval95"]["geometricMeanCrpsRatio"] == [
        pytest.approx(0.5),
        pytest.approx(0.5),
    ]
    assert summary["arms"]["persistence"]["geometricMeanCrpsRatio"] == 1.0


@pytest.mark.skipif(find_spec("stanli") is None, reason="stan extra missing")
@pytest.mark.skipif(find_spec("statsmodels") is None, reason="statsmodels missing")
def test_stanli_quantiles_form_a_valid_analyst_ladder():
    history = [4.0 + 0.1 * ((index * 7) % 5 - 2) for index in range(40)]
    arms = backtest.forecast_arms(
        [round(value, 1) for value in history],
        stan_models=["stanli-rw-drift-t"],
        interval_distribution=analyst.interval_distribution,
        ladder_distribution=analyst.ladder_distribution,
    )
    ladder = arms["stanli-rw-drift-t-ladder"]
    points = ladder["cdf"]["points"]
    quantiles = ladder["quantiles"]
    levels = list(backtest.QUANTILE_LEVELS)

    assert ladder["cdf"]["transformVersion"] == "agent_cdf_v1"
    assert points[0]["probability"] == 0 and points[-1]["probability"] == 1
    assert all(b["value"] > a["value"] for a, b in zip(points, points[1:]))
    assert all(b["probability"] >= a["probability"] for a, b in zip(points, points[1:]))
    cell = {
        "pointEstimate": quantiles[levels.index(0.5)],
        "ciLow": quantiles[levels.index(0.1)],
        "ciHigh": quantiles[levels.index(0.9)],
        "thresholdLadder": {
            "thresholds": quantiles,
            "cumulativeProbabilities": levels,
        },
    }
    assert analyst.ladder_validation_errors(cell) == []


SCORES = st.dictionaries(
    st.sampled_from(["a", "b", "c", "d"]),
    st.fixed_dictionaries(
        {
            "warned": st.booleans(),
            "meanAbsoluteError": st.floats(min_value=0, max_value=5),
            "coverage80": st.sampled_from([0.0, 0.5, 0.75, 0.8, 0.875, 1.0]),
        }
    ),
    min_size=1,
)


@given(SCORES)
def test_select_model_takes_the_lowest_error_among_models_without_warnings(scores):
    picked = backtest.select_model(scores)
    usable = {m: s for m, s in scores.items() if not s["warned"]} or scores

    assert picked in usable
    assert usable[picked]["meanAbsoluteError"] == min(
        score["meanAbsoluteError"] for score in usable.values()
    )


def test_select_model_breaks_ties_by_coverage_then_name():
    tied = {"warned": False, "meanAbsoluteError": 1.0}
    assert (
        backtest.select_model(
            {
                "a": {**tied, "coverage80": 1.0},
                "b": {**tied, "coverage80": 0.75},
                "c": {**tied, "coverage80": 0.75},
            }
        )
        == "b"
    )


def test_select_model_falls_back_when_every_model_warns():
    assert (
        backtest.select_model(
            {
                "a": {"warned": True, "meanAbsoluteError": 2.0, "coverage80": 0.8},
                "b": {"warned": True, "meanAbsoluteError": 1.0, "coverage80": 0.8},
            }
        )
        == "b"
    )


@pytest.mark.skipif(find_spec("stanli") is None, reason="stan extra missing")
@pytest.mark.skipif(find_spec("statsmodels") is None, reason="statsmodels missing")
def test_selected_arms_copy_the_picked_program_and_leave_the_others_alone():
    history = [round(4.0 + 0.1 * ((index * 7) % 5 - 2), 1) for index in range(10)]
    models = ["stanli-rw-drift-t", "stanli-ar1-t"]

    def arms(walk_forward):
        return backtest.forecast_arms(
            history,
            stan_models=models,
            interval_distribution=analyst.interval_distribution,
            ladder_distribution=analyst.ladder_distribution,
            walk_forward=walk_forward,
        )

    fixed = arms(False)
    selected = arms(True)
    picked = selected["stanli-selected"]["selected"]

    assert "stanli-selected" not in fixed
    assert picked in models
    assert selected["stanli-selected-ladder"]["selected"] == picked
    assert selected["stanli-selected"]["cdf"] == selected[picked]["cdf"]
    assert (
        selected["stanli-selected-ladder"]["cdf"] == selected[f"{picked}-ladder"]["cdf"]
    )
    # Seeds derive from the candidate id, so the walk-forward fits cannot move
    # the forecast the arm itself publishes.
    for arm, forecast in fixed.items():
        assert selected[arm]["cdf"] == forecast["cdf"]


def transform_rows():
    rows = []
    for series, ratio, count in (
        ("A:level", 0.5, 2),
        ("B:level", 1.0, 2),
        ("C:mom_diff", 2.0, 4),
    ):
        for period in range(count):
            for arm, crps in (("persistence", 2.0), ("half", 2.0 * ratio)):
                rows.append(
                    {
                        "series": series,
                        "period": f"p{period}",
                        "arm": arm,
                        "crps": crps,
                        "normalizedCrps": crps / 4,
                        "covered80": series == "A:level",
                        "samplerFailed": False,
                    }
                )
    return rows


def test_by_transform_recombines_the_series_in_each_transform():
    table = backtest.by_transform(transform_rows())

    assert set(table) == {"level", "mom_diff"}
    level = table["level"]["half"]
    assert (level["series"], level["targets"]) == (2, 4)
    assert level["geometricMeanCrpsRatio"] == pytest.approx(0.5**0.5)
    assert level["coverage80"] == 0.5
    assert table["mom_diff"]["half"]["geometricMeanCrpsRatio"] == pytest.approx(2.0)


def test_leave_one_series_out_names_the_series_that_moves_the_ratio_most():
    table = backtest.leave_one_series_out(transform_rows())["half"]

    # Dropping the 0.5 series leaves the 1.0 and 2.0 series; dropping the 2.0
    # series leaves the 0.5 and 1.0 series.
    assert table["highestRatioDrops"] == "A:level"
    assert table["highestRatio"] == pytest.approx(2 ** (4 / 6))
    assert table["lowestRatioDrops"] == "C:mom_diff"
    assert table["lowestRatio"] == pytest.approx(0.5**0.5)


def test_leave_one_series_out_skips_an_arm_with_one_series():
    rows = [row for row in transform_rows() if row["series"] == "C:mom_diff"]
    assert backtest.leave_one_series_out(rows) == {}


def test_selection_counts_read_the_selected_arm_alone():
    rows = [
        {"arm": "stanli-selected", "selected": "b"},
        {"arm": "stanli-selected", "selected": "a"},
        {"arm": "stanli-selected", "selected": "b"},
        {"arm": "stanli-selected-ladder", "selected": "b"},
        {"arm": "persistence"},
    ]
    assert backtest.selection_counts(rows) == {"a": 1, "b": 2}
