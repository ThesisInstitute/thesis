from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from brier.timeseries import (
    SCHEMA_VERSION,
    build_candidate_set,
    build_persistence_candidate,
    build_statsmodels_local_level_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_time_series_models.py"


SAMPLE_HISTORY = [
    {"period": "2020", "value": 100},
    {"period": "2021", "value": 103},
    {"period": "2022", "value": 107},
    {"period": "2023", "value": 110},
    {"period": "2024", "value": 114},
    {"period": "2025", "value": 119},
]


def test_persistence_candidate_has_required_interval_schema():
    candidate = build_persistence_candidate(
        target_data_point_id="test.series.2026",
        target_period="2026",
        history=SAMPLE_HISTORY,
        generated_at="2026-06-26T00:00:00Z",
        round_increment=0.1,
    ).as_dict()

    assert candidate["schemaVersion"] == SCHEMA_VERSION
    assert candidate["library"] == "brier"
    assert candidate["modelName"] == "persistence.last_print"
    assert candidate["pointEstimate"] == 119
    assert candidate["interval80"]["lower"] < candidate["pointEstimate"]
    assert candidate["interval80"]["upper"] > candidate["pointEstimate"]
    assert candidate["interval90"]["level"] == 0.9
    assert candidate["quantiles"]["p10"] == candidate["interval80"]["lower"]
    assert candidate["quantiles"]["p90"] == candidate["interval80"]["upper"]
    assert candidate["intervalMethod"] == "residual_quantile"
    assert candidate["backtestScore"]["rows"] == len(SAMPLE_HISTORY) - 1


@pytest.mark.skipif(
    find_spec("statsmodels") is None, reason="statsmodels extra missing"
)
def test_statsmodels_candidate_uses_native_interval_metadata():
    candidate = build_statsmodels_local_level_candidate(
        target_data_point_id="test.series.2026",
        target_period="2026",
        history=SAMPLE_HISTORY,
        generated_at="2026-06-26T00:00:00Z",
        round_increment=0.1,
    ).as_dict()

    assert candidate["library"] == "statsmodels"
    assert candidate["libraryVersion"] != "not_installed"
    assert candidate["modelName"] == "sarimax_local_level_drift"
    assert candidate["intervalMethod"] == "native_state_space"
    assert candidate["interval80"]["lower"] < candidate["pointEstimate"]
    assert candidate["interval80"]["upper"] > candidate["pointEstimate"]
    assert candidate["calibrationN"] == len(SAMPLE_HISTORY) - 1
    assert candidate["backtestScore"]["method"] == "walk_forward_1_step"
    # Pinned from the recursive backtest this replaced (origin/main 6c9704eb):
    # skipping the nested backtests changes no score. The fit reads
    # 0.9444455 on macOS and 0.9444467 on CI's ubuntu, so the pins allow 1e-4.
    assert candidate["backtestScore"]["rows"] == 3
    assert candidate["backtestScore"]["meanAbsoluteError"] == pytest.approx(
        0.9444455381418541, rel=1e-4
    )
    assert candidate["backtestScore"]["interval80Coverage"] == pytest.approx(1 / 3)
    assert candidate["backtestScore"]["meanInterval80Width"] == pytest.approx(
        0.8299296295780513, rel=1e-4
    )


def count_sarimax_fits():
    """Return a patch of SARIMAX.fit that counts calls, and the call list."""

    from statsmodels.tsa.statespace.sarimax import SARIMAX

    calls: list[int] = []
    original = SARIMAX.fit

    def counting_fit(self, *args, **kwargs):
        calls.append(len(self.endog))
        return original(self, *args, **kwargs)

    return mock.patch.object(SARIMAX, "fit", counting_fit), calls


def random_walk(steps: list[float], start: float = 100.0) -> list[dict]:
    values = [start]
    for step in steps:
        values.append(values[-1] + step)
    return [
        {"period": f"p{index:03d}", "value": value}
        for index, value in enumerate(values)
    ]


@pytest.mark.skipif(
    find_spec("statsmodels") is None, reason="statsmodels extra missing"
)
@settings(max_examples=10, deadline=None)
@given(
    steps=st.lists(
        st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=23,
    )
)
def test_statsmodels_backtest_fits_once_per_cutoff(steps):
    # Invariant: n observations cost 1 + max(n - 3, 0) fits (the candidate plus
    # one per backtest cutoff), never a nested backtest per cutoff.
    history = random_walk(steps)
    patch, calls = count_sarimax_fits()
    with patch:
        candidate = build_statsmodels_local_level_candidate(
            target_data_point_id="test.series",
            target_period="next",
            history=history,
            generated_at="2026-06-26T00:00:00Z",
        )
    assert len(calls) == 1 + max(len(history) - 3, 0)
    if candidate.backtest_score is not None:
        assert candidate.backtest_score.rows <= len(history) - 3


@pytest.mark.skipif(
    find_spec("statsmodels") is None, reason="statsmodels extra missing"
)
@settings(max_examples=10, deadline=None)
@given(
    steps=st.lists(
        st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=12,
    ),
    round_increment=st.sampled_from([None, 0.1, 1.0]),
)
def test_statsmodels_backtest_flag_changes_only_the_backtest_score(
    steps, round_increment
):
    history = random_walk(steps)
    kwargs = dict(
        target_data_point_id="test.series",
        target_period="next",
        history=history,
        generated_at="2026-06-26T00:00:00Z",
        round_increment=round_increment,
    )
    with_backtest = build_statsmodels_local_level_candidate(**kwargs).as_dict()
    without_backtest = build_statsmodels_local_level_candidate(
        **kwargs, backtest=False
    ).as_dict()

    assert without_backtest.pop("backtestScore") is None
    with_backtest.pop("backtestScore")
    assert with_backtest == without_backtest


@pytest.mark.skipif(
    find_spec("statsmodels") is None, reason="statsmodels extra missing"
)
def test_default_models_stay_linear_on_a_long_history():
    # 60 prints took 2**57 fits before the backtest stopped recursing; the
    # analyst runner's default model list must finish on long monthly series.
    history = random_walk([0.1 * ((index % 7) - 3) for index in range(59)])
    patch, calls = count_sarimax_fits()
    with patch:
        candidate_set = build_candidate_set(
            target_data_point_id="test.series",
            target_period="next",
            history=history,
            generated_at="2026-06-26T00:00:00Z",
        )

    assert len(calls) == 1 + (len(history) - 3)
    statsmodels_candidate = candidate_set["candidates"][1]
    assert statsmodels_candidate["library"] == "statsmodels"
    assert statsmodels_candidate["backtestScore"]["rows"] == len(history) - 3


def test_candidate_set_can_emit_persistence_without_optional_extras():
    candidate_set = build_candidate_set(
        target_data_point_id="test.series.2026",
        target_period="2026",
        history=SAMPLE_HISTORY[:2],
        models=["persistence"],
        generated_at="2026-06-26T00:00:00Z",
    )

    assert candidate_set["schemaVersion"] == "thesis_model_candidate_set_v1"
    assert candidate_set["candidateCount"] == 1
    assert candidate_set["candidates"][0]["intervalMethod"] == "fallback_prior"


def test_time_series_model_script_outputs_candidate_json():
    # The script imports brier from the repo root; keep that importable even
    # when the suite runs without the package installed (uv --no-project).
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), *filter(None, [env.get("PYTHONPATH")])]
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--target-id",
            "test.series.2026",
            "--target-period",
            "2026",
            "--history-json",
            json.dumps(SAMPLE_HISTORY[:2]),
            "--models",
            "persistence",
            "--generated-at",
            "2026-06-26T00:00:00Z",
            "--round-increment",
            "0.1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["schemaVersion"] == "thesis_model_candidate_set_v1"
    assert payload["targetDataPointId"] == "test.series.2026"
    assert payload["candidates"][0]["schemaVersion"] == SCHEMA_VERSION
