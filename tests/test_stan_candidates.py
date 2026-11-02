"""stanli model candidates: schema, invariants and agreement with statsmodels."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import random
import statistics
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from brier import stan_candidates
from brier.stan_candidates import (
    CUSTOM_MODEL,
    MIN_OBSERVATIONS,
    QUANTILE_LEVELS,
    STAN_PROGRAMS,
    backtest_stanli,
    build_stanli_candidate,
    observation_grid,
    resolve_program,
    standardization,
)
from brier.timeseries import (
    build_candidate_set,
    build_statsmodels_local_level_candidate,
    main,
    normalize_history,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_time_series_models.py"
GENERATED_AT = "2026-11-02T00:00:00Z"

requires_stanli = pytest.mark.skipif(
    find_spec("stanli") is None, reason="stan extra missing"
)
requires_statsmodels = pytest.mark.skipif(
    find_spec("statsmodels") is None, reason="statsmodels extra missing"
)


def as_history(values: list[float]) -> list[dict]:
    return [
        {"period": f"t{index:03d}", "value": value}
        for index, value in enumerate(values)
    ]


def rounded_walk(length: int = 60, seed: int = 4) -> list[dict]:
    """A monthly rate printed on a 0.1 grid, so prints often repeat."""

    rng = random.Random(seed)
    value = 4.0
    values = []
    for _ in range(length):
        value += rng.gauss(0, 0.1)
        values.append(round(value, 1))
    return as_history(values)


def tied_walk(length: int = 48, seed: int = 1) -> list[dict]:
    """A 0.1-grid series whose print repeats in 40 of its 47 changes."""

    rng = random.Random(seed)
    value = 4.0
    values = []
    for _ in range(length):
        if rng.random() > 0.85:
            value += rng.choice([-1, 1]) * 0.1 * rng.choice([1, 1, 2])
        values.append(round(value, 1))
    return as_history(values)


def dyadic_walk(steps: list[int]) -> list[float]:
    """Prints on a 1/8 grid: every shift and power-of-two scaling is exact."""

    values = [16.0]
    for step in steps:
        values.append(values[-1] + step / 8)
    return values


def build(model: str = "stanli-rw-drift-t", history=None, **kwargs):
    return build_stanli_candidate(
        model=model,
        target_data_point_id="test.series",
        target_period="next",
        history=rounded_walk() if history is None else history,
        generated_at=GENERATED_AT,
        **kwargs,
    )


def predictive_quantiles(candidate) -> list[float]:
    return [row["value"] for row in candidate.posterior_predictive["quantiles"]]


# Pure-Python pieces: these run without the stan extra.


def test_observation_grid_reads_the_finest_decimal_place():
    assert observation_grid([3.9, 4.0, 4.1]) == pytest.approx(0.1)
    assert observation_grid([150.0, 160.0, 171.0]) == 1.0
    assert observation_grid([1.25, 1.5, 2.0]) == pytest.approx(0.01)
    assert observation_grid([0.00001, 0.00002]) == pytest.approx(1e-5)
    assert observation_grid([0.1 + 0.2]) < 1e-15


@given(
    places=st.integers(min_value=0, max_value=6),
    units=st.lists(
        st.integers(min_value=-(10**6), max_value=10**6), min_size=1, max_size=20
    ),
)
def test_observation_grid_divides_every_print(places, units):
    values = [float(f"{unit / 10**places:.{places}f}") for unit in units]
    grid = observation_grid(values)

    assert grid >= 10.0**-places * (1 - 1e-12)
    for value in values:
        assert abs(value - round(value / grid) * grid) <= 1e-9 * max(1, abs(value))


@given(
    units=st.lists(
        st.integers(min_value=-(2**20), max_value=2**20), min_size=1, max_size=30
    ),
    power=st.integers(min_value=-8, max_value=8),
)
def test_standardization_is_positive_and_scales_exactly(units, power):
    values = [unit / 1024 for unit in units]
    loc, scale = standardization(values)
    assert loc == values[-1]
    assert scale > 0 and math.isfinite(scale)

    factor = 2.0**power
    scaled_loc, scaled_scale = standardization([factor * value for value in values])
    assert scaled_loc == factor * loc
    if any(values):
        assert scaled_scale == factor * scale


def test_resolve_program_guards_custom_and_builtin_names():
    with pytest.raises(ValueError, match="needs a Stan program"):
        resolve_program(CUSTOM_MODEL, None)
    with pytest.raises(ValueError, match="needs a Stan program"):
        resolve_program(CUSTOM_MODEL, "   ")
    with pytest.raises(ValueError, match="built-in program"):
        resolve_program("stanli-rw-drift-t", "data {}")
    with pytest.raises(ValueError, match="Unsupported stanli model"):
        resolve_program("stanli-nope", None)
    assert resolve_program("stanli-ar1-t", None) == STAN_PROGRAMS["stanli-ar1-t"]


@pytest.mark.parametrize("model", sorted(STAN_PROGRAMS))
def test_builtin_programs_declare_the_shared_data_and_y_next(model):
    source = STAN_PROGRAMS[model]
    for declaration in (
        "int<lower=3> N;",
        "vector[N] y_std;",
        "real y_loc;",
        "real<lower=0> y_scale;",
        "real<lower=0> y_grid;",
        "real y_next",
    ):
        assert declaration in source


@pytest.mark.parametrize("model", sorted(MIN_OBSERVATIONS))
def test_short_histories_fail_before_sampling(model):
    minimum = MIN_OBSERVATIONS[model]
    program = STAN_PROGRAMS["stanli-rw-drift-t"] if model == CUSTOM_MODEL else None
    with pytest.raises(ValueError, match=f"at least {minimum} observations"):
        build(model, history=rounded_walk(minimum - 1), program=program)


def test_grid_must_be_a_finite_non_negative_increment():
    for grid in (-0.1, math.inf, math.nan):
        with pytest.raises(ValueError, match="grid"):
            build(history=rounded_walk(8), grid=grid, backtest=False)


def test_missing_stanli_raises_an_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "stanli", None)
    with pytest.raises(RuntimeError, match="stan extra"):
        build(history=rounded_walk(8), backtest=False)


def test_default_models_leave_stanli_opt_in():
    default = inspect.signature(build_candidate_set).parameters["models"].default
    assert default == ("persistence", "statsmodels-local-level")


def test_cli_prints_a_builtin_program(capsys):
    assert main(["--print-stan-program", "stanli-ar1-t"]) == 0
    assert capsys.readouterr().out == STAN_PROGRAMS["stanli-ar1-t"]
    assert main(["--print-stan-program=stanli-rw-drift-t"]) == 0
    assert capsys.readouterr().out == STAN_PROGRAMS["stanli-rw-drift-t"]


@pytest.mark.parametrize(
    "extra",
    [
        ["--models", "stanli-custom"],
        ["--models", "persistence", "--stan-file", "program.stan"],
    ],
)
def test_cli_pairs_stan_file_with_the_custom_model(extra, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "--target-id",
                "test.series",
                "--target-period",
                "next",
                "--history-json",
                "[]",
                *extra,
            ]
        )
    assert exit_info.value.code == 2
    assert "--stan-file and the stanli-custom model go together" in (
        capsys.readouterr().err
    )


# Sampling: these need the stan extra.


@requires_stanli
@pytest.mark.parametrize("model", sorted(STAN_PROGRAMS))
def test_candidate_reports_ordered_posterior_predictive_quantiles(model):
    candidate = build(model)
    payload = json.loads(json.dumps(candidate.as_dict()))
    posterior = payload["posteriorPredictive"]
    quantiles = [row["value"] for row in posterior["quantiles"]]

    assert [row["probability"] for row in posterior["quantiles"]] == list(
        QUANTILE_LEVELS
    )
    assert quantiles == sorted(quantiles)
    assert payload["library"] == "stanli"
    assert payload["libraryVersion"] == "0.25.0"
    assert payload["intervalMethod"] == "posterior_predictive"
    # Unrounded, the point is the predictive median and the 80% interval its
    # 10th and 90th percentiles.
    assert payload["pointEstimate"] == quantiles[QUANTILE_LEVELS.index(0.5)]
    assert payload["interval80"]["lower"] == quantiles[QUANTILE_LEVELS.index(0.1)]
    assert payload["interval80"]["upper"] == quantiles[QUANTILE_LEVELS.index(0.9)]
    assert (
        payload["interval90"]["lower"]
        <= payload["interval80"]["lower"]
        < payload["pointEstimate"]
        < payload["interval80"]["upper"]
        <= payload["interval90"]["upper"]
    )
    assert posterior["draws"] == 4000
    assert posterior["standardization"]["yGrid"] == pytest.approx(0.1)
    assert posterior["program"]["source"] == STAN_PROGRAMS[model]
    assert (
        posterior["program"]["sha256"]
        == hashlib.sha256(STAN_PROGRAMS[model].encode()).hexdigest()
    )
    assert payload["backtestScore"]["rows"] == 24


@requires_stanli
def test_rounded_candidates_strictly_bracket_the_point():
    candidate = build(history=tied_walk(), round_increment=0.1, backtest=False)
    for value in (candidate.point_estimate, candidate.p10, candidate.p90):
        assert value == round(value, 1)
    assert candidate.p10 < candidate.point_estimate < candidate.p90
    assert candidate.interval90.lower <= candidate.p10
    assert candidate.interval90.upper >= candidate.p90


@requires_stanli
def test_same_inputs_give_identical_candidates():
    assert build(backtest=False).as_dict() == build(backtest=False).as_dict()


@requires_stanli
@settings(max_examples=8, deadline=None)
@given(
    steps=st.lists(st.integers(min_value=-8, max_value=8), min_size=5, max_size=30),
    power=st.integers(min_value=-4, max_value=4),
    model=st.sampled_from(sorted(STAN_PROGRAMS)),
)
def test_scaling_history_and_grid_scales_the_forecast_exactly(steps, power, model):
    values = dyadic_walk(steps)
    factor = 2.0**power
    base = build(model, history=as_history(values), grid=0.125, backtest=False)
    scaled = build(
        model,
        history=as_history([factor * value for value in values]),
        grid=factor * 0.125,
        backtest=False,
    )

    assert predictive_quantiles(scaled) == [
        factor * value for value in predictive_quantiles(base)
    ]


@requires_stanli
@settings(max_examples=8, deadline=None)
@given(
    steps=st.lists(st.integers(min_value=-8, max_value=8), min_size=5, max_size=30),
    shift=st.integers(min_value=-1000, max_value=1000),
    model=st.sampled_from(sorted(STAN_PROGRAMS)),
)
def test_shifting_history_shifts_the_forecast(steps, shift, model):
    values = dyadic_walk(steps)
    base = build(model, history=as_history(values), grid=0.125, backtest=False)
    shifted = build(
        model,
        history=as_history([value + shift for value in values]),
        grid=0.125,
        backtest=False,
    )

    for original, moved in zip(
        predictive_quantiles(base), predictive_quantiles(shifted)
    ):
        assert moved == pytest.approx(
            original + shift, rel=0, abs=1e-9 * (1 + abs(original) + abs(shift))
        )


@requires_stanli
@pytest.mark.parametrize("model", sorted(STAN_PROGRAMS))
def test_repeated_prints_do_not_collapse_the_forecast(model):
    # 40 of 47 changes repeat the print. Without the rounding term the
    # Student-t likelihood is unbounded as its scale goes to zero, and the
    # programs returned a point mass at the last print or stopped mixing.
    history = tied_walk()
    values = [row["value"] for row in history]
    assert sum(a == b for a, b in zip(values, values[1:])) == 40

    candidate = build(model, history=history, backtest=False)
    quantiles = dict(zip(QUANTILE_LEVELS, predictive_quantiles(candidate)))
    sampler = candidate.posterior_predictive["sampler"]

    assert quantiles[0.95] - quantiles[0.05] >= 0.1
    assert sampler["divergences"] == 0
    assert sampler["maxRhat"] <= stan_candidates.MAX_RHAT


@requires_stanli
@requires_statsmodels
@pytest.mark.parametrize("seed", [7, 8, 9])
def test_random_walk_program_agrees_with_sarimax_on_gaussian_steps(seed):
    # On 150 Gaussian steps with drift, the Student-t random walk should
    # reproduce SARIMAX(0,1,0)'s forecast. Tolerances are about three Monte
    # Carlo standard errors of a 4000-draw quantile.
    rng = random.Random(seed)
    values = [50.0]
    for _ in range(149):
        values.append(values[-1] + 0.2 + rng.gauss(0, 1))
    history = as_history(values)
    step_sd = statistics.stdev([b - a for a, b in zip(values, values[1:])])

    stan = build(history=history, backtest=False)
    sarimax = build_statsmodels_local_level_candidate(
        target_data_point_id="test.series",
        target_period="next",
        history=history,
        generated_at=GENERATED_AT,
        backtest=False,
    )
    quantiles = dict(zip(QUANTILE_LEVELS, predictive_quantiles(stan)))

    assert quantiles[0.5] == pytest.approx(sarimax.point_estimate, abs=0.1 * step_sd)
    assert quantiles[0.1] == pytest.approx(sarimax.interval80.lower, abs=0.15 * step_sd)
    assert quantiles[0.9] == pytest.approx(sarimax.interval80.upper, abs=0.15 * step_sd)


@requires_stanli
def test_custom_program_runs_and_records_its_source():
    source = STAN_PROGRAMS["stanli-ar1-t"]
    custom = build(CUSTOM_MODEL, program=source, backtest=False)
    builtin = build("stanli-ar1-t", backtest=False)

    assert custom.model_name == CUSTOM_MODEL
    assert custom.posterior_predictive["program"]["source"] == source
    assert custom.candidate_id != builtin.candidate_id
    assert custom.posterior_predictive["seed"] != builtin.posterior_predictive["seed"]


CUSTOM_PARAMETERS = """
parameters {
  real mu;
}
model {
  mu ~ normal(0, 1);
}
"""


@requires_stanli
@pytest.mark.parametrize(
    "source, message",
    [
        (stan_candidates._DATA_BLOCK + CUSTOM_PARAMETERS, "must define"),
        ("data { int N; } parameters { real mu } model { }", "failed to compile"),
        (
            "data { int K; }" + CUSTOM_PARAMETERS + "generated quantities "
            "{ real y_next = mu; }",
            "missing data for K",
        ),
        (
            stan_candidates._DATA_BLOCK
            + CUSTOM_PARAMETERS
            + "generated quantities { real y_next = positive_infinity(); }",
            "must all be finite",
        ),
        (
            stan_candidates._DATA_BLOCK
            + CUSTOM_PARAMETERS
            + "generated quantities { vector[2] y_next = [mu, mu]'; }",
            "must be a scalar",
        ),
    ],
)
def test_bad_custom_programs_raise_value_errors(source, message):
    with pytest.raises(ValueError, match=message):
        build(CUSTOM_MODEL, history=rounded_walk(8), program=source, backtest=False)


@requires_stanli
def test_backtest_walks_the_last_24_cutoffs():
    score = build(history=rounded_walk(40)).backtest_score

    assert score.method == "walk_forward_1_step"
    assert score.rows == 24
    assert 0 <= score.interval80_coverage <= 1
    assert score.mean_absolute_error >= 0
    assert score.mean_interval80_width > 0


def test_backtest_needs_a_held_out_print():
    history = normalize_history(rounded_walk(3))
    assert backtest_stanli("stanli-rw-drift-t", history) is None


@requires_stanli
def test_cli_emits_stanli_candidates(tmp_path):
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps(rounded_walk(30)))
    stan_file = tmp_path / "custom.stan"
    stan_file.write_text(STAN_PROGRAMS["stanli-ar1-diff-t"])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), *filter(None, [env.get("PYTHONPATH")])]
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--target-id",
            "test.series",
            "--target-period",
            "next",
            "--history-file",
            str(history_file),
            "--models",
            "persistence,stanli-rw-drift-t,stanli-custom",
            "--stan-file",
            str(stan_file),
            "--round-increment",
            "0.1",
            "--generated-at",
            GENERATED_AT,
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    payload = json.loads(result.stdout)

    assert [candidate["modelName"] for candidate in payload["candidates"]] == [
        "persistence.last_print",
        "stanli-rw-drift-t",
        CUSTOM_MODEL,
    ]
    for candidate in payload["candidates"][1:]:
        assert candidate["intervalMethod"] == "posterior_predictive"
        assert candidate["posteriorPredictive"]["draws"] == 4000
        assert candidate["pointEstimate"] == round(candidate["pointEstimate"], 1)


@requires_stanli
@pytest.mark.parametrize(
    "model, program",
    [
        *[(model, None) for model in STAN_PROGRAMS],
        (CUSTOM_MODEL, STAN_PROGRAMS["stanli-ar1-t"]),
    ],
)
def test_replay_reproduces_every_quantile_from_the_json_alone(model, program):
    # A rounded forecast still records unrounded quantiles, and the JSON round
    # trip stands in for reading the candidate back out of a trace.
    candidate = build(
        model,
        history=rounded_walk(30),
        program=program,
        round_increment=0.1,
        backtest=False,
    )
    record = json.loads(json.dumps(candidate.as_dict()))

    assert (
        stan_candidates.replay_stanli_candidate(record)
        == record["posteriorPredictive"]["quantiles"]
    )


@requires_stanli
@pytest.mark.parametrize(
    "tamper",
    [
        lambda record: record["posteriorPredictive"].update(
            seed=record["posteriorPredictive"]["seed"] + 1
        ),
        lambda record: record["history"][-1].update(
            value=record["history"][-1]["value"] + 0.1
        ),
        lambda record: record["posteriorPredictive"]["standardization"].update(
            yGrid=0.5
        ),
    ],
    ids=["seed", "data", "grid"],
)
def test_replay_detects_a_changed_seed_or_data(tamper):
    record = json.loads(
        json.dumps(build(history=rounded_walk(30), backtest=False).as_dict())
    )
    tamper(record)

    assert (
        stan_candidates.replay_stanli_candidate(record)
        != record["posteriorPredictive"]["quantiles"]
    )


@requires_stanli
def test_replay_refuses_a_source_that_does_not_match_its_hash():
    record = json.loads(
        json.dumps(build(history=rounded_walk(30), backtest=False).as_dict())
    )
    record["posteriorPredictive"]["program"]["source"] += "\n"

    with pytest.raises(ValueError, match="does not match its recorded hash"):
        stan_candidates.replay_stanli_candidate(record)


@requires_stanli
def test_cli_replays_a_candidate_set_and_flags_a_changed_record(tmp_path, capsys):
    candidate_set = build_candidate_set(
        target_data_point_id="test.series",
        target_period="next",
        history=rounded_walk(30),
        models=["persistence", "stanli-rw-drift-t", "stanli-ar1-t"],
        generated_at=GENERATED_AT,
    )
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(candidate_set))

    assert main(["--replay-stanli", str(path)]) == 0
    assert capsys.readouterr().out.count("replayed exactly") == 2

    candidate_set["candidates"][1]["posteriorPredictive"]["seed"] += 1
    path.write_text(json.dumps(candidate_set))

    assert main([f"--replay-stanli={path}"]) == 1
    assert capsys.readouterr().out.count("MISMATCH") == 1


def test_cli_replay_says_when_a_file_holds_no_stanli_candidate(tmp_path, capsys):
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps({"candidates": [{"library": "statsmodels"}]}))

    assert main(["--replay-stanli", str(path)]) == 1
    assert "no stanli candidates" in capsys.readouterr().out
