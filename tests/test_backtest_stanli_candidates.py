"""Ports and real-time target logic in scripts/backtest_stanli_candidates.py."""

from __future__ import annotations

import datetime as dt
import gzip
import importlib.util
import io
import json
import math
import random
import shutil
import statistics
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
    assert [t.window_start for t in targets] == ["2024-01", "2024-01"]
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


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def alfred_csv(dates) -> str:
    stamps = [date.isoformat().replace("-", "") for date in dates]
    header = ",".join(["observation_date", *(f"TEST_{stamp}" for stamp in stamps)])
    return f"{header}\n2024-01-01,{','.join('1.0' for _ in stamps)}\n"


def test_fetch_vintages_caches_a_download_only_after_it_parses(tmp_path):
    dates = backtest.vintage_grid(dt.date(2025, 1, 1), dt.date(2025, 2, 1))
    today = dt.date(2025, 3, 1)

    def html_page(request, timeout):
        return FakeResponse(b"<html>try again later</html>")

    with pytest.raises(ValueError, match="unexpected ALFRED header"):
        backtest.fetch_vintages(
            "TEST", dates, tmp_path, pause=0, today=today, opener=html_page
        )
    assert list(tmp_path.iterdir()) == []

    def wrong_vintages(request, timeout):
        return FakeResponse(alfred_csv(dates[:-1]).encode())

    with pytest.raises(ValueError, match="ALFRED sent vintages"):
        backtest.fetch_vintages(
            "TEST", dates, tmp_path, pause=0, today=today, opener=wrong_vintages
        )
    assert list(tmp_path.iterdir()) == []

    def good(request, timeout):
        return FakeResponse(alfred_csv(dates).encode())

    vintages = backtest.fetch_vintages(
        "TEST", dates, tmp_path, pause=0, today=today, opener=good
    )
    assert sorted(vintages) == [date.isoformat() for date in dates]
    assert [path.name for path in tmp_path.iterdir()] == [
        "TEST_2025-01-01_2025-02-01_3.csv"
    ]

    def offline(request, timeout):
        raise AssertionError("a cached chunk must not download again")

    assert (
        backtest.fetch_vintages(
            "TEST", dates, tmp_path, pause=0, today=today, opener=offline
        )
        == vintages
    )


def test_fetch_vintages_refuses_a_vintage_that_may_still_change(tmp_path):
    with pytest.raises(ValueError, match="may still change"):
        backtest.fetch_vintages(
            "TEST",
            [dt.date(2025, 3, 1)],
            tmp_path,
            today=dt.date(2025, 3, 1),
            opener=None,
        )


@given(st.lists(st.integers(min_value=-30, max_value=30), min_size=2, max_size=60))
def test_persistence_ladder_rises_strictly_from_the_last_print(steps):
    history = [4.0]
    for step in steps:
        history.append(round(history[-1] + step / 10, 1))
    rungs = backtest.persistence_ladder(history)
    changes = [b - a for a, b in zip(history, history[1:])]
    nudge = backtest.observation_grid(history) / 1000

    assert len(rungs) == len(backtest.QUANTILE_LEVELS)
    assert all(upper > lower for lower, upper in zip(rungs, rungs[1:]))
    # A rung sits at its quantile unless a tie pushed it up, and never by more
    # than a thousandth of the grid per rung below it.
    for index, (level, rung) in enumerate(zip(backtest.QUANTILE_LEVELS, rungs)):
        target = history[-1] + backtest.ts_quantile(changes, level)
        assert target - 1e-9 <= rung <= target + index * nudge + 1e-9


def test_persistence_ladder_passes_the_analyst_ladder_check():
    history = [4.0, 4.0, 4.1, 4.1, 4.1, 4.0, 4.0, 4.0, 4.2, 4.2, 4.2, 4.2]
    rungs = backtest.persistence_ladder(history)
    levels = list(backtest.QUANTILE_LEVELS)
    cell = {
        "pointEstimate": rungs[levels.index(0.5)],
        "ciLow": rungs[levels.index(0.1)],
        "ciHigh": rungs[levels.index(0.9)],
        "thresholdLadder": {"thresholds": rungs, "cumulativeProbabilities": levels},
    }

    assert analyst.ladder_validation_errors(cell) == []


@given(SCORES)
def test_select_model_without_the_skip_takes_the_lowest_error_overall(scores):
    picked = backtest.select_model(scores, skip_warned=False)

    assert scores[picked]["meanAbsoluteError"] == min(
        score["meanAbsoluteError"] for score in scores.values()
    )


@pytest.mark.skipif(find_spec("stanli") is None, reason="stan extra missing")
@pytest.mark.skipif(find_spec("statsmodels") is None, reason="statsmodels missing")
def test_each_target_draws_its_own_seeds_and_rows_carry_the_selection_inputs():
    history = [round(4.0 + 0.1 * ((index * 7) % 5 - 2), 1) for index in range(10)]

    def arms(target_id):
        return backtest.forecast_arms(
            history,
            target_id=target_id,
            stan_models=["stanli-rw-drift-t", "stanli-ar1-t"],
            interval_distribution=analyst.interval_distribution,
            ladder_distribution=analyst.ladder_distribution,
            walk_forward=True,
        )

    first, again, other = arms("a"), arms("a"), arms("b")
    assert first["stanli-ar1-t"]["cdf"] == again["stanli-ar1-t"]["cdf"]
    assert first["stanli-ar1-t"]["cdf"] != other["stanli-ar1-t"]["cdf"]
    assert first["persistence"]["cdf"] == other["persistence"]["cdf"]
    assert {"stanli-selected-noskip", "stanli-selected-noskip-ladder"} <= set(first)

    target = backtest.Target(
        series="TEST:level",
        period="2025-01",
        info_vintage="2025-01-16",
        release_vintage="2025-02-01",
        history=tuple(history),
        outcome=4.1,
        window_start="2024-03",
    )
    rows = {row["arm"]: row for row in backtest.score_target(target, first)}
    program = rows["stanli-ar1-t"]
    assert program["windowStart"] == "2024-03"
    assert program["warned"] in (True, False)
    assert program["walkForwardMae"] >= 0
    assert 0 <= program["walkForwardCoverage80"] <= 1
    assert "warned" not in rows["persistence"]
    assert rows["stanli-selected"]["selected"] in ("stanli-rw-drift-t", "stanli-ar1-t")


def arm_rows(
    ratios: dict[tuple[str, str], dict[str, float]],
    extra: dict[tuple[str, str, str], dict] | None = None,
) -> list[dict]:
    """Rows for persistence (CRPS 1) and each arm at its ratio, per target."""

    extra = extra or {}

    rows = []
    for (series, period), by_arm in ratios.items():
        for arm, crps in {"persistence": 1.0, **by_arm}.items():
            rows.append(
                {
                    "series": series,
                    "period": period,
                    "arm": arm,
                    "crps": crps,
                    "normalizedCrps": crps,
                    "covered80": True,
                    "samplerFailed": False,
                    **extra.get((series, period, arm), {}),
                }
            )
    return rows


def test_compare_pairs_two_arms_and_counts_the_ratio_targets():
    rows = arm_rows(
        {
            ("A", "2025-01"): {"x": 0.5, "y": 1.0},
            ("A", "2025-02"): {"x": 0.5, "y": 0.0},
            ("B", "2025-01"): {"x": 2.0, "y": 1.0},
        }
    )
    stats = backtest.compare(rows, baseline="y", arms=["x"], draws=20)["x"]

    # The zero-CRPS target drops out of the ratio but not out of the count.
    assert (stats["targets"], stats["ratioTargets"]) == (3, 2)
    assert stats["geometricMeanCrpsRatio"] == pytest.approx(1.0)
    pairs = backtest.paired_comparisons(rows, [("x", "y")], draws=20)
    assert pairs["x vs y"]["geometricMeanCrpsRatio"] == pytest.approx(1.0)


def test_warning_split_scores_every_arm_where_each_program_warned():
    rows = arm_rows(
        {
            ("A", "2025-01"): {"stanli-ar1-t": 0.5, "z": 0.25},
            ("A", "2025-02"): {"stanli-ar1-t": 2.0, "z": 4.0},
        },
        {
            ("A", "2025-01", "stanli-ar1-t"): {"warned": True},
            ("A", "2025-02", "stanli-ar1-t"): {"warned": False},
        },
    )
    split = backtest.warning_split(rows)["stanli-ar1-t"]

    assert split["stanli-ar1-t"]["warned"] == {
        "targets": 1,
        "geometricMeanCrpsRatio": pytest.approx(0.5),
    }
    assert split["z"]["warned"]["geometricMeanCrpsRatio"] == pytest.approx(0.25)
    assert split["z"]["clean"]["geometricMeanCrpsRatio"] == pytest.approx(4.0)


def test_period_halves_and_late_windows_split_the_targets():
    rows = arm_rows(
        {
            ("A", "2025-01"): {"x": 0.5},
            ("A", "2025-02"): {"x": 0.5},
            ("A", "2025-03"): {"x": 2.0},
            ("A", "2025-04"): {"x": 2.0},
        },
        {
            ("A", period, "persistence"): {"windowStart": start}
            for period, start in (
                ("2025-01", "2020-01"),
                ("2025-02", "2020-02"),
                ("2025-03", "2021-07"),
                ("2025-04", "2021-08"),
            )
        },
    )
    halves = backtest.by_period_half(rows)

    assert halves["laterHalfFrom"] == "2025-03"
    assert halves["earlier"]["x"]["geometricMeanCrpsRatio"] == pytest.approx(0.5)
    assert halves["later"]["x"]["geometricMeanCrpsRatio"] == pytest.approx(2.0)
    late = backtest.windows_starting_from(rows, "2021-07")["arms"]["x"]
    assert (late["targets"], late["geometricMeanCrpsRatio"]) == (
        2,
        pytest.approx(2.0),
    )


def test_ablation_power_matches_a_hand_computed_design_effect():
    # Three series of two targets with log ratios (0, 0), (1, 1), (2, 2): all the
    # spread is between series, so the ICC is 1 and the design effect 2.
    ratios = {}
    for series, log_ratio in (("A", 0.0), ("B", 1.0), ("C", 2.0)):
        for period in ("p1", "p2"):
            ratios[(series, period)] = {"x": math.exp(log_ratio)}
    power = backtest.ablation_power(arm_rows(ratios), "x")

    z = statistics.NormalDist().inv_cdf(0.975) + statistics.NormalDist().inv_cdf(0.8)
    independent = (z * statistics.stdev([0, 0, 1, 1, 2, 2]) / -math.log(0.9)) ** 2
    assert power["intraclassCorrelation"] == pytest.approx(1.0)
    assert power["designEffect"] == pytest.approx(2.0)
    assert power["independentTargetsNeeded"] == pytest.approx(independent)
    assert power["clusteredTargetsNeeded"] == pytest.approx(2 * independent)
    assert power["seriesNeeded"] == pytest.approx((z * 1.0 / -math.log(0.9)) ** 2)


@given(
    st.lists(
        st.lists(st.floats(min_value=-2, max_value=2), min_size=1, max_size=6),
        min_size=3,
        max_size=8,
    )
)
def test_ablation_power_keeps_the_icc_in_range(groups):
    ratios = {
        (f"S{group}", f"p{index}"): {"x": math.exp(value)}
        for group, values in enumerate(groups)
        for index, value in enumerate(values)
    }
    power = backtest.ablation_power(arm_rows(ratios), "x")
    if power is None:
        assert sum(len(values) for values in groups) <= len(groups)
        return

    assert 0 <= power["intraclassCorrelation"] <= 1
    assert power["designEffect"] >= 1
    assert power["clusteredTargetsNeeded"] >= power["independentTargetsNeeded"]


def test_written_rows_round_trip_and_repeat_byte_for_byte(tmp_path):
    rows = [{"arm": "persistence", "crps": 0.5}, {"arm": "x", "crps": None}]
    first, second = tmp_path / "a.jsonl.gz", tmp_path / "b.jsonl.gz"
    backtest.write_rows(first, rows)
    backtest.write_rows(second, rows)

    assert first.read_bytes() == second.read_bytes()
    with gzip.open(first, "rt") as handle:
        assert [json.loads(line) for line in handle] == rows
