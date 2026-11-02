"""Bayesian model candidates fit with stanli.

stanli (https://github.com/seantalts/stanli) runs Stan programs over
precompiled Stan Math kernels with Stan's own NUTS sampler. It needs no
per-model C++ compile and writes no files, so a candidate fits inside the
analyst's read-only sandbox in milliseconds. It is an optional dependency (the
``stan`` extra) and is imported inside the builder.

Every program receives the same data: ``N``, the raw history ``y``, its
standardized form ``y_std = (y - y_loc) / y_scale``, and ``y_loc`` and
``y_scale``. ``y_loc`` is the last print and ``y_scale`` a robust scale of the
one-step changes. A program must define the generated quantity ``y_next``: one
posterior predictive draw of the next print, in raw units. The built-in
programs fit ``y_std`` under fixed priors, so a positive rescaling or a shift
of the history moves their forecast by the same rescaling or shift.
"""

from __future__ import annotations

import hashlib
import math
from statistics import median
from typing import Any, Sequence

from brier.timeseries import (
    DEFAULT_GENERATED_AT,
    BacktestScore,
    ForecastInterval,
    ForecastModelCandidate,
    TimeSeriesObservation,
    candidate_id,
    ensure_strictly_brackets_point,
    normalize_history,
    package_version,
    round_values,
    utc_now,
    widen_equal_interval,
)

CHAINS = 4
WARMUP = 1000
SAMPLES_PER_CHAIN = 1000
QUANTILE_LEVELS: tuple[float, ...] = tuple(
    round(0.05 * index, 2) for index in range(1, 20)
)
BACKTEST_MAX_ROWS = 24
MAX_RHAT = 1.01
CUSTOM_MODEL = "stanli-custom"

_DATA_BLOCK = """data {
  int<lower=3> N;
  vector[N] y_std;
  real y_loc;
  real<lower=0> y_scale;
}"""

STAN_PROGRAMS: dict[str, str] = {
    # Random walk with drift and Student-t steps: the Bayesian counterpart of
    # the statsmodels local-level candidate, with heavy tails for release
    # shocks and parameter uncertainty in the predictive draws.
    "stanli-rw-drift-t": _DATA_BLOCK
    + """
transformed data {
  vector[N - 1] d = y_std[2:N] - y_std[1:(N - 1)];
}
parameters {
  real delta;
  real<lower=0> sigma;
  real<lower=1> nu;
}
model {
  delta ~ normal(0, 1);
  sigma ~ normal(0, 2);
  nu ~ gamma(2, 0.1);
  d ~ student_t(nu, delta, sigma);
}
generated quantities {
  real y_next = y_loc + y_scale * (y_std[N] + student_t_rng(nu, delta, sigma));
}
""",
    # Stationary AR(1) around a fitted mean with Student-t errors, for rates
    # and monthly changes that revert rather than wander.
    "stanli-ar1-t": _DATA_BLOCK
    + """
transformed data {
  real y_bar = mean(y_std);
  real y_spread = sd(y_std) + 1;
}
parameters {
  real m;
  real<lower=-1, upper=1> phi;
  real<lower=0> sigma;
  real<lower=1> nu;
}
model {
  m ~ normal(y_bar, 2 * y_spread);
  sigma ~ normal(0, 2 * y_spread);
  nu ~ gamma(2, 0.1);
  y_std[2:N] ~ student_t(nu, m + phi * (y_std[1:(N - 1)] - m), sigma);
}
generated quantities {
  real y_next = y_loc
                + y_scale * student_t_rng(nu, m + phi * (y_std[N] - m), sigma);
}
""",
    # AR(1) on the one-step changes with drift and Student-t errors
    # (ARIMA(1,1,0)), for levels whose changes carry momentum.
    "stanli-ar1-diff-t": _DATA_BLOCK
    + """
transformed data {
  vector[N - 1] d = y_std[2:N] - y_std[1:(N - 1)];
}
parameters {
  real delta;
  real<lower=-1, upper=1> phi;
  real<lower=0> sigma;
  real<lower=1> nu;
}
model {
  delta ~ normal(0, 1);
  sigma ~ normal(0, 2);
  nu ~ gamma(2, 0.1);
  d[2:(N - 1)] ~ student_t(nu, delta + phi * (d[1:(N - 2)] - delta), sigma);
}
generated quantities {
  real y_next = y_loc
                + y_scale * (y_std[N]
                             + student_t_rng(nu, delta + phi * (d[N - 1] - delta),
                                             sigma));
}
""",
}

MIN_OBSERVATIONS: dict[str, int] = {
    "stanli-rw-drift-t": 3,
    "stanli-ar1-t": 3,
    "stanli-ar1-diff-t": 4,
    CUSTOM_MODEL: 3,
}


def stanli_model_names() -> tuple[str, ...]:
    return (*STAN_PROGRAMS, CUSTOM_MODEL)


def standardization(values: Sequence[float]) -> tuple[float, float]:
    """Return ``(y_loc, y_scale)``: the last print and a robust step scale.

    The scale is 1.4826 times the median absolute deviation of the one-step
    changes. Rounded series often repeat a print, which can zero the MAD, so
    the mean absolute deviation (times sqrt(pi/2)) backs it up, then 1% of the
    last print, then 1.
    """

    loc = float(values[-1])
    diffs = [values[index] - values[index - 1] for index in range(1, len(values))]
    if diffs:
        center = median(diffs)
        scale = 1.4826 * median(abs(diff - center) for diff in diffs)
        if not scale > 0:
            average = sum(diffs) / len(diffs)
            scale = math.sqrt(math.pi / 2) * (
                sum(abs(diff - average) for diff in diffs) / len(diffs)
            )
    else:
        scale = 0.0
    if not scale > 0:
        scale = abs(loc) * 0.01 if loc != 0 else 1.0
    return loc, scale


def stanli_seed(identifier: str) -> int:
    """Derive a stable sampler seed from a candidate id."""

    digest = hashlib.sha256(identifier.encode()).hexdigest()
    return int(digest[:8], 16) % (2**31 - 1) + 1


def build_stanli_candidate(
    *,
    model: str,
    target_data_point_id: str,
    target_period: str,
    history: Sequence[TimeSeriesObservation | dict[str, Any]],
    generated_at: str | None = None,
    round_increment: float | None = None,
    program: str | None = None,
    backtest: bool = True,
) -> ForecastModelCandidate:
    """Fit a stanli program and summarize its posterior predictive draws.

    ``model`` names a built-in program, or ``stanli-custom`` with ``program``
    holding Stan source that follows the module's data contract.
    """

    source = resolve_program(model, program)
    normalized_history = normalize_history(history)
    minimum = MIN_OBSERVATIONS[model]
    if len(normalized_history) < minimum:
        raise ValueError(f"{model} needs at least {minimum} observations")

    identifier = candidate_id(
        target_data_point_id,
        target_period,
        "stanli",
        model if model != CUSTOM_MODEL else f"{model}.{program_sha256(source)}",
        normalized_history,
    )
    seed = stanli_seed(identifier)
    loc, scale = standardization([observation.value for observation in normalized_history])
    draws, sampler = sample_next(
        source, normalized_history, loc=loc, scale=scale, seed=seed
    )

    quantiles = {level: empirical_quantile(draws, level) for level in QUANTILE_LEVELS}
    point, p10, p90, p05, p95 = round_values(
        [quantiles[0.5], quantiles[0.1], quantiles[0.9], quantiles[0.05], quantiles[0.95]],
        round_increment,
    )
    if p10 == p90:
        p10, p90 = widen_equal_interval(point, round_increment)
    p10, p90 = ensure_strictly_brackets_point(point, p10, p90, round_increment)
    p05, p95 = ensure_strictly_brackets_point(point, p05, p95, round_increment)
    p05, p95 = min(p05, p10), max(p95, p90)

    diagnostics = [
        f"stanli {model}: NUTS, {CHAINS} chains x {SAMPLES_PER_CHAIN} draws "
        f"after {WARMUP} warmup, seed {seed}",
        f"posterior predictive quantiles from {len(draws)} draws of y_next",
        (
            f"sampler: {sampler['divergences']} divergent transitions; "
            f"max R-hat {sampler['maxRhat']:.3f}; "
            f"min bulk ESS {sampler['minEssBulk']:.0f}"
        ),
    ]
    if sampler["divergences"] > 0 or sampler["maxRhat"] > MAX_RHAT:
        diagnostics.append(
            "WARNING: sampler diagnostics failed; treat this candidate as unreliable"
        )

    latest = normalized_history[-1]
    return ForecastModelCandidate(
        candidate_id=identifier,
        target_data_point_id=target_data_point_id,
        target_period=target_period,
        generated_at=generated_at or utc_now(),
        train_cutoff=latest.period,
        library="stanli",
        library_version=package_version("stanli"),
        model_name=model,
        point_estimate=point,
        p10=p10,
        p50=point,
        p90=p90,
        interval80=ForecastInterval(lower=p10, upper=p90, level=0.8),
        interval90=ForecastInterval(lower=p05, upper=p95, level=0.9),
        interval_method="posterior_predictive",
        calibration_n=len(normalized_history),
        history=tuple(normalized_history),
        backtest_score=(
            backtest_stanli(model, normalized_history, program=source)
            if backtest
            else None
        ),
        diagnostics=tuple(diagnostics),
        posterior_predictive={
            "draws": len(draws),
            "chains": CHAINS,
            "warmup": WARMUP,
            "samplesPerChain": SAMPLES_PER_CHAIN,
            "seed": seed,
            "quantiles": [
                {"probability": level, "value": quantiles[level]}
                for level in QUANTILE_LEVELS
            ],
            "standardization": {"yLoc": loc, "yScale": scale},
            "sampler": sampler,
            "program": {
                "name": model,
                "sha256": program_sha256(source),
                "source": source,
            },
        },
    )


def resolve_program(model: str, program: str | None) -> str:
    if model == CUSTOM_MODEL:
        if not program or not program.strip():
            raise ValueError(f"{CUSTOM_MODEL} needs a Stan program")
        return program
    if program is not None:
        raise ValueError(f"{model} is a built-in program; pass {CUSTOM_MODEL} instead")
    if model not in STAN_PROGRAMS:
        raise ValueError(f"Unsupported stanli model {model!r}")
    return STAN_PROGRAMS[model]


def program_sha256(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def sample_next(
    source: str,
    history: Sequence[TimeSeriesObservation],
    *,
    loc: float,
    scale: float,
    seed: int,
) -> tuple[list[float], dict[str, Any]]:
    """Sample ``y_next`` and return its draws with sampler diagnostics."""

    try:
        import stanli
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "stanli is not installed; install the brier stan extra "
            "or request a non-stanli model"
        ) from exc

    values = [point.value for point in history]
    data = {
        "N": len(values),
        "y": values,
        "y_std": [(value - loc) / scale for value in values],
        "y_loc": loc,
        "y_scale": scale,
    }
    try:
        stan_model = stanli.Model(stan_code=source, data=data, seed=seed)
    except RuntimeError as exc:
        raise ValueError(f"Stan program failed to compile: {exc}") from exc
    fit = stan_model.sample(
        chains=CHAINS,
        seed=seed,
        warmup=WARMUP,
        samples=SAMPLES_PER_CHAIN,
        refresh=0,
    )
    if "y_next" not in fit.variables:
        raise ValueError("Stan program must define the generated quantity y_next")
    draws = [float(value) for value in fit["y_next"]]
    if not draws or not all(math.isfinite(value) for value in draws):
        raise ValueError("y_next draws must all be finite")

    summary = fit.summary()
    parameter_rows = [
        index
        for index, name in enumerate(summary.names)
        if name != "y_next" and not name.endswith("__")
    ]
    r_hats = [float(summary.r_hat[index]) for index in parameter_rows]
    ess_bulk = [float(summary.ess_bulk[index]) for index in parameter_rows]
    sampler = {
        "divergences": int(sum(int(count) for count in fit.divergences)),
        "maxRhat": max((value for value in r_hats if math.isfinite(value)), default=1.0),
        "minEssBulk": min(
            (value for value in ess_bulk if math.isfinite(value)), default=float(len(draws))
        ),
    }
    return draws, sampler


def empirical_quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def backtest_stanli(
    model: str,
    history: Sequence[TimeSeriesObservation],
    *,
    program: str | None = None,
    max_rows: int = BACKTEST_MAX_ROWS,
) -> BacktestScore | None:
    """Walk forward one step over the most recent ``max_rows`` cutoffs."""

    minimum = MIN_OBSERVATIONS[model]
    first_cutoff = max(minimum, len(history) - max_rows)
    if first_cutoff >= len(history):
        return None

    errors: list[float] = []
    interval_hits: list[bool] = []
    interval_widths: list[float] = []
    for cutoff in range(first_cutoff, len(history)):
        actual = history[cutoff].value
        candidate = build_stanli_candidate(
            model=model,
            target_data_point_id="_backtest",
            target_period=history[cutoff].period,
            history=history[:cutoff],
            generated_at=DEFAULT_GENERATED_AT,
            program=program if model == CUSTOM_MODEL else None,
            backtest=False,
        )
        errors.append(abs(actual - candidate.point_estimate))
        interval_hits.append(
            candidate.interval80.lower <= actual <= candidate.interval80.upper
        )
        interval_widths.append(candidate.interval80.upper - candidate.interval80.lower)

    return BacktestScore(
        method="walk_forward_1_step",
        rows=len(errors),
        mean_absolute_error=sum(errors) / len(errors),
        interval80_coverage=sum(interval_hits) / len(interval_hits),
        mean_interval80_width=sum(interval_widths) / len(interval_widths),
    )
