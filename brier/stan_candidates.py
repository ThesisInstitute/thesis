"""Bayesian model candidates fit with stanli.

stanli (https://github.com/seantalts/stanli) ships the Stan compiler,
stan-math and a NUTS sampler in one shared library, so it needs no C++
toolchain and no per-model compile. Where the library embeds stanc3, as the
macOS wheel does, a program compiles in-process and stanli writes no files;
otherwise it runs a bundled stanc in a temporary directory. Nobody has fit it
in the analyst's Linux sandbox. It is an optional dependency (the ``stan``
extra) and is imported inside the builder.

Every program receives the same data: ``N``, the raw history ``y``, its
standardized form ``y_std = (y - y_loc) / y_scale``, ``y_loc``, ``y_scale`` and
``y_grid``. ``y_loc`` is the last print, ``y_scale`` a robust scale of the
one-step changes, and ``y_grid`` the increment the prints are reported on (0
when unknown). A program must define the generated quantity ``y_next``: one
posterior predictive draw of the next print, in raw units. The built-in
programs fit ``y_std`` under fixed priors, so a positive rescaling or a shift
of the history (and its grid) moves their forecast by the same rescaling or
shift.

Official prints are rounded, and rounded series repeat a print often. When
more than half of the one-step changes are exactly zero, a Student-t
likelihood grows without bound as its scale shrinks to zero, and NUTS can
return a point mass at the last print that still passes R-hat and ESS checks.
The built-in programs treat each print as the latent value plus rounding error
uniform on half a grid step either way (variance ``y_grid**2 / 12``) and add
that variance, for every print a residual involves, to the residual scale.
While ``y_grid`` is positive, that keeps the likelihood bounded. The programs
ignore the correlation that shared rounding errors induce across neighboring
residuals.
"""

from __future__ import annotations

import hashlib
import math
from decimal import Decimal
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
SAMPLER_WARNING = (
    "WARNING: sampler diagnostics failed; treat this candidate as unreliable"
)
TIE_WARNING = (
    "WARNING: posterior predictive quantiles tie, so they do not form a valid ladder"
)

_DATA_BLOCK = """data {
  int<lower=3> N;
  vector[N] y_std;
  real y_loc;
  real<lower=0> y_scale;
  real<lower=0> y_grid;
}"""

STAN_PROGRAMS: dict[str, str] = {
    # Random walk with drift and Student-t steps: the Bayesian counterpart of
    # the statsmodels local-level candidate, with heavy tails for release
    # shocks and parameter uncertainty in the predictive draws.
    "stanli-rw-drift-t": _DATA_BLOCK
    + """
transformed data {
  vector[N - 1] d = y_std[2:N] - y_std[1:(N - 1)];
  // Rounding variance of one print, in standardized units.
  real round_var = square(y_grid / y_scale) / 12;
}
parameters {
  real delta;
  real<lower=0> sigma;
  real<lower=1> nu;
}
transformed parameters {
  // A one-step change carries the rounding errors of two prints.
  real<lower=0> tau = sqrt(square(sigma) + 2 * round_var);
}
model {
  delta ~ normal(0, 1);
  sigma ~ normal(0, 2);
  nu ~ gamma(2, 0.1);
  d ~ student_t(nu, delta, tau);
}
generated quantities {
  real y_next = y_loc + y_scale * (y_std[N] + student_t_rng(nu, delta, tau));
}
""",
    # AR(1) around a fitted mean with Student-t errors, for rates and monthly
    # changes that revert rather than wander. phi stays inside (-1, 1), but as
    # it nears 1 the mean drops out and the program approaches a random walk
    # without drift, so trending levels suit stanli-rw-drift-t or
    # stanli-ar1-diff-t better.
    "stanli-ar1-t": _DATA_BLOCK
    + """
transformed data {
  real y_bar = mean(y_std);
  real y_spread = sd(y_std) + 1;
  real round_var = square(y_grid / y_scale) / 12;
}
parameters {
  real m;
  real<lower=-1, upper=1> phi;
  real<lower=0> sigma;
  real<lower=1> nu;
}
transformed parameters {
  // The residual carries this print's rounding error and phi times the last.
  real<lower=0> tau = sqrt(square(sigma) + (1 + square(phi)) * round_var);
}
model {
  m ~ normal(y_bar, 2 * y_spread);
  sigma ~ normal(0, 2 * y_spread);
  nu ~ gamma(2, 0.1);
  y_std[2:N] ~ student_t(nu, m + phi * (y_std[1:(N - 1)] - m), tau);
}
generated quantities {
  real y_next = y_loc
                + y_scale * student_t_rng(nu, m + phi * (y_std[N] - m), tau);
}
""",
    # AR(1) on the one-step changes with drift and Student-t errors
    # (ARIMA(1,1,0)), for levels whose changes carry momentum.
    "stanli-ar1-diff-t": _DATA_BLOCK
    + """
transformed data {
  vector[N - 1] d = y_std[2:N] - y_std[1:(N - 1)];
  real round_var = square(y_grid / y_scale) / 12;
}
parameters {
  real delta;
  real<lower=-1, upper=1> phi;
  real<lower=0> sigma;
  real<lower=1> nu;
}
transformed parameters {
  // The residual carries r[t] - (1 + phi) r[t-1] + phi r[t-2] of rounding
  // errors r.
  real<lower=0> tau
      = sqrt(square(sigma) + (1 + square(1 + phi) + square(phi)) * round_var);
}
model {
  delta ~ normal(0, 1);
  sigma ~ normal(0, 2);
  nu ~ gamma(2, 0.1);
  d[2:(N - 1)] ~ student_t(nu, delta + phi * (d[1:(N - 2)] - delta), tau);
}
generated quantities {
  real y_next = y_loc
                + y_scale * (y_std[N]
                             + student_t_rng(nu, delta + phi * (d[N - 1] - delta),
                                             tau));
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


def observation_grid(values: Sequence[float]) -> float:
    """Infer the increment the prints are reported on.

    The grid is ``10**-d`` for the most decimal places any print shows, trailing
    zeros dropped, once every print is rounded to 12 significant digits at the
    scale of the largest. Whole-number prints give 1, and float noise such as
    ``0.1 + 0.2`` or ``0.3 - (0.1 + 0.2)`` does not shrink the grid.
    """

    finite = [float(value) for value in values if math.isfinite(value)]
    largest = max((abs(value) for value in finite), default=0.0)
    if largest == 0:
        return 1.0
    keep = 11 - math.floor(math.log10(largest))
    places = 0
    for value in finite:
        exponent = Decimal(repr(round(value, keep))).normalize().as_tuple().exponent
        if isinstance(exponent, int):
            places = max(places, -exponent)
    return 10.0**-places


def stanli_seed(identifier: str) -> int:
    """Derive a stable sampler seed from a candidate id."""

    digest = hashlib.sha256(identifier.encode()).hexdigest()
    return int(digest[:8], 16) % (2**31 - 1) + 1


def model_key(model: str, source: str) -> str:
    """The model name a candidate id hashes; a custom program adds its hash."""

    return model if model != CUSTOM_MODEL else f"{model}.{program_sha256(source)}"


def build_stanli_candidate(
    *,
    model: str,
    target_data_point_id: str,
    target_period: str,
    history: Sequence[TimeSeriesObservation | dict[str, Any]],
    generated_at: str | None = None,
    round_increment: float | None = None,
    program: str | None = None,
    grid: float | None = None,
    backtest: bool = True,
) -> ForecastModelCandidate:
    """Fit a stanli program and summarize its posterior predictive draws.

    ``model`` names a built-in program, or ``stanli-custom`` with ``program``
    holding Stan source that follows the module's data contract. ``grid`` is
    the increment the history is reported on; by default it is inferred from
    the prints' decimal places.
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
        model_key(model, source),
        normalized_history,
    )
    seed = stanli_seed(identifier)
    values = [observation.value for observation in normalized_history]
    loc, scale = standardization(values)
    grid_inferred = grid is None
    if grid is None:
        grid = observation_grid(values)
    elif not (math.isfinite(grid) and grid >= 0):
        raise ValueError("grid must be a finite non-negative increment")
    draws, sampler = sample_next(
        source, normalized_history, loc=loc, scale=scale, grid=grid, seed=seed
    )

    quantiles = {level: empirical_quantile(draws, level) for level in QUANTILE_LEVELS}
    point, p10, p90, p05, p95 = rounded_summary(quantiles, round_increment)

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
            backtest_stanli(
                model,
                normalized_history,
                program=source,
                grid=grid,
                target_data_point_id=f"{target_data_point_id}:{target_period}",
            )
            if backtest
            else None
        ),
        diagnostics=tuple(
            diagnostic_lines(model, seed, len(draws), sampler, quantiles)
        ),
        posterior_predictive={
            "draws": len(draws),
            "chains": CHAINS,
            "warmup": WARMUP,
            "samplesPerChain": SAMPLES_PER_CHAIN,
            "seed": seed,
            "quantiles": quantile_rows(quantiles),
            "standardization": {
                "yLoc": loc,
                "yScale": scale,
                "yGrid": grid,
                "gridInferred": grid_inferred,
            },
            "roundIncrement": round_increment,
            "sampler": sampler,
            "program": {
                "name": model,
                "sha256": program_sha256(source),
                "source": source,
            },
        },
    )


def rounded_summary(
    quantiles: dict[float, float], round_increment: float | None
) -> tuple[float, float, float, float, float]:
    """Round the predictive quantiles a candidate publishes.

    Returns ``(point, p10, p90, p05, p95)`` from the median and the 10th, 90th,
    5th and 95th percentiles, with ``p05 <= p10 < point < p90 <= p95``.
    """

    point, p10, p90, p05, p95 = round_values(
        [
            quantiles[0.5],
            quantiles[0.1],
            quantiles[0.9],
            quantiles[0.05],
            quantiles[0.95],
        ],
        round_increment,
    )
    if p10 == p90:
        p10, p90 = widen_equal_interval(point, round_increment)
    p10, p90 = ensure_strictly_brackets_point(point, p10, p90, round_increment)
    p05, p95 = ensure_strictly_brackets_point(point, p05, p95, round_increment)
    return point, p10, p90, min(p05, p10), max(p95, p90)


def quantile_rows(quantiles: dict[float, float]) -> list[dict[str, float]]:
    return [
        {"probability": level, "value": quantiles[level]} for level in QUANTILE_LEVELS
    ]


def sampler_failed(sampler: dict[str, Any]) -> bool:
    """Whether a fit's diagnostics fail: a divergence, or an R-hat too high
    or not finite on a parameter that varies across draws."""

    return (
        sampler["divergences"] > 0
        or sampler["nonFiniteRhat"] > 0
        or (sampler["maxRhat"] is not None and sampler["maxRhat"] > MAX_RHAT)
    )


def diagnostic_lines(
    model: str,
    seed: int,
    draw_count: int,
    sampler: dict[str, Any],
    quantiles: dict[float, float],
) -> list[str]:
    if sampler["maxRhat"] is None and not sampler["nonFiniteRhat"]:
        convergence = "no parameter varies across draws"
    else:
        convergence = "max R-hat " + (
            "n/a" if sampler["maxRhat"] is None else f"{sampler['maxRhat']:.3f}"
        )
        if sampler["nonFiniteRhat"]:
            convergence += (
                f" (not finite on {sampler['nonFiniteRhat']} varying parameters)"
            )
        convergence += "; min bulk ESS " + (
            "n/a" if sampler["minEssBulk"] is None else f"{sampler['minEssBulk']:.0f}"
        )
    lines = [
        f"stanli {model}: NUTS, {CHAINS} chains x {SAMPLES_PER_CHAIN} draws "
        f"after {WARMUP} warmup, seed {seed}",
        f"posterior predictive quantiles from {draw_count} draws of y_next",
        f"sampler: {sampler['divergences']} divergent transitions; {convergence}",
    ]
    if sampler_failed(sampler):
        lines.append(SAMPLER_WARNING)
    values = [quantiles[level] for level in QUANTILE_LEVELS]
    if any(upper <= lower for lower, upper in zip(values, values[1:])):
        lines.append(TIE_WARNING)
    return lines


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
    grid: float,
    seed: int,
) -> tuple[list[float], dict[str, Any]]:
    """Sample ``y_next`` and return its draws with sampler diagnostics.

    R-hat and bulk ESS cover the parameters that vary across draws, other
    than ``y_next`` and the sampler's own columns. stanli reports NaN for a
    constant column, such as a transformed parameter fixed by the data, so
    those columns drop out; a non-finite R-hat on a varying parameter counts
    as a failure.
    """

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
        "y_grid": grid,
    }
    try:
        stan_model = stanli.Model(stan_code=source, data=data, seed=seed)
    except RuntimeError as exc:
        # stanli raises RuntimeError for a parse or type error and for data that
        # does not match the data block.
        raise ValueError(f"Stan program failed to compile or bind data: {exc}") from exc
    fit = stan_model.sample(
        chains=CHAINS,
        seed=seed,
        warmup=WARMUP,
        samples=SAMPLES_PER_CHAIN,
        refresh=0,
    )
    if "y_next" not in fit.variables:
        raise ValueError("Stan program must define the generated quantity y_next")
    if tuple(fit.variables["y_next"]) != ():
        raise ValueError("y_next must be a scalar, one draw of the next print")
    draws = [float(value) for value in fit["y_next"]]
    if not draws or not all(math.isfinite(value) for value in draws):
        raise ValueError("y_next draws must all be finite")

    summary = fit.summary()
    # (chains, draws, columns), in the summary's column order. A column
    # holding a NaN counts as varying, so its NaN R-hat fails the fit.
    columns = fit.draws()
    varying = [
        index
        for index, name in enumerate(summary.names)
        if name != "y_next"
        and not name.endswith("__")
        and not columns[:, :, index].min() == columns[:, :, index].max()
    ]
    r_hats = [float(summary.r_hat[index]) for index in varying]
    ess_bulk = [float(summary.ess_bulk[index]) for index in varying]
    sampler = {
        "divergences": int(sum(int(count) for count in fit.divergences)),
        "maxRhat": max(
            (value for value in r_hats if math.isfinite(value)), default=None
        ),
        "minEssBulk": min(
            (value for value in ess_bulk if math.isfinite(value)), default=None
        ),
        "nonFiniteRhat": sum(1 for value in r_hats if not math.isfinite(value)),
    }
    return draws, sampler


def replay_stanli_candidate(record: dict[str, Any]) -> dict[str, Any]:
    """Refit a stanli candidate from its own JSON and rebuild its forecast.

    The record carries everything the fit depends on: the program source, the
    history, the grid and the rounding increment. Replay derives the candidate
    id, the seed and the standardization from the record itself, refits, and
    returns every field the fit determines, keyed as :func:`recorded_fields`
    keys them. It raises a ``ValueError`` for a record no build could have
    produced: a source that does not match its recorded hash, quantile levels
    other than the 19, or a candidate id, seed, standardization or inferred
    grid that does not follow from the record.
    """

    block = record["posteriorPredictive"]
    source = block["program"]["source"]
    if program_sha256(source) != block["program"]["sha256"]:
        raise ValueError("recorded Stan source does not match its recorded hash")
    levels = tuple(row["probability"] for row in block["quantiles"])
    if levels != QUANTILE_LEVELS:
        raise ValueError("recorded quantiles must list the 19 levels 0.05 to 0.95")
    model = record["modelName"]
    if block["program"]["name"] != model:
        raise ValueError("recorded program name does not match the model name")
    history = normalize_history(record["history"])
    identifier = candidate_id(
        record["targetDataPointId"],
        record["targetPeriod"],
        "stanli",
        model_key(model, source),
        history,
    )
    if identifier != record["candidateId"]:
        raise ValueError("candidate id does not follow from the record")
    seed = stanli_seed(identifier)
    if block["seed"] != seed:
        raise ValueError("seed does not follow from the candidate id")
    values = [observation.value for observation in history]
    loc, scale = standardization(values)
    scaling = block["standardization"]
    if (scaling["yLoc"], scaling["yScale"]) != (loc, scale):
        raise ValueError("standardization does not follow from the history")
    grid = scaling["yGrid"]
    if scaling["gridInferred"] and grid != observation_grid(values):
        raise ValueError("inferred grid does not follow from the history")
    if not (math.isfinite(grid) and grid >= 0):
        raise ValueError("grid must be a finite non-negative increment")

    draws, sampler = sample_next(
        source, history, loc=loc, scale=scale, grid=grid, seed=seed
    )
    quantiles = {level: empirical_quantile(draws, level) for level in QUANTILE_LEVELS}
    point, p10, p90, p05, p95 = rounded_summary(quantiles, block["roundIncrement"])
    return {
        "pointEstimate": point,
        "quantiles": {"p10": p10, "p50": point, "p90": p90},
        "interval80": ForecastInterval(lower=p10, upper=p90, level=0.8).as_dict(),
        "interval90": ForecastInterval(lower=p05, upper=p95, level=0.9).as_dict(),
        "diagnostics": diagnostic_lines(model, seed, len(draws), sampler, quantiles),
        "posteriorPredictive.draws": len(draws),
        "posteriorPredictive.quantiles": quantile_rows(quantiles),
        "posteriorPredictive.sampler": sampler,
    }


def recorded_fields(record: dict[str, Any]) -> dict[str, Any]:
    """The fields of a stanli record that replay rebuilds, keyed alike."""

    block = record["posteriorPredictive"]
    return {
        "pointEstimate": record["pointEstimate"],
        "quantiles": record["quantiles"],
        "interval80": record["interval80"],
        "interval90": record["interval90"],
        "diagnostics": record["diagnostics"],
        "posteriorPredictive.draws": block["draws"],
        "posteriorPredictive.quantiles": block["quantiles"],
        "posteriorPredictive.sampler": block["sampler"],
    }


def replay_mismatches(record: dict[str, Any]) -> list[str]:
    """Replay a stanli record and name each field that came out different."""

    replayed = replay_stanli_candidate(record)
    recorded = recorded_fields(record)
    return [field for field in replayed if replayed[field] != recorded[field]]


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
    grid: float | None = None,
    max_rows: int = BACKTEST_MAX_ROWS,
    target_data_point_id: str = "_backtest",
) -> BacktestScore | None:
    """Walk forward one step over the most recent ``max_rows`` cutoffs.

    Every cutoff fits with the full history's grid when ``grid`` is None.
    Each cutoff's seed comes from ``target_data_point_id`` and the cutoff, so
    two targets with the same history length draw different seeds.
    """

    if grid is None:
        grid = observation_grid([observation.value for observation in history])

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
            target_data_point_id=f"{target_data_point_id}:walk-forward",
            target_period=history[cutoff].period,
            history=history[:cutoff],
            generated_at=DEFAULT_GENERATED_AT,
            program=program if model == CUSTOM_MODEL else None,
            grid=grid,
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
