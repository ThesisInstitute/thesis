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
