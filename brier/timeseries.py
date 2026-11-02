"""Time-series model candidates for Thesis forecasts.

This module is intentionally small and dependency-light on import. Open-source
model adapters are imported inside their builders so the base package can still
load without experiment extras installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Literal, Sequence

SCHEMA_VERSION = "thesis_model_candidate_v1"
CANDIDATE_SET_SCHEMA_VERSION = "thesis_model_candidate_set_v1"
DEFAULT_GENERATED_AT = "1970-01-01T00:00:00Z"

IntervalMethod = Literal[
    "native_state_space",
    "residual_quantile",
    "fallback_prior",
    "posterior_predictive",
]


@dataclass(frozen=True)
class TimeSeriesObservation:
    """One official historical observation used for model fitting."""

    period: str
    value: float

    def as_dict(self) -> dict[str, Any]:
        return {"period": self.period, "value": self.value}


@dataclass(frozen=True)
class ForecastInterval:
    """Prediction interval at a stated central coverage level."""

    lower: float
    upper: float
    level: float

    def as_dict(self) -> dict[str, Any]:
        return {"lower": self.lower, "upper": self.upper, "level": self.level}


@dataclass(frozen=True)
class BacktestScore:
    """Walk-forward score for a model candidate when enough history exists."""

    method: str
    rows: int
    mean_absolute_error: float
    interval80_coverage: float | None = None
    mean_interval80_width: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "rows": self.rows,
            "meanAbsoluteError": self.mean_absolute_error,
            "interval80Coverage": self.interval80_coverage,
            "meanInterval80Width": self.mean_interval80_width,
        }


@dataclass(frozen=True)
class ForecastModelCandidate:
    """Common candidate schema consumed by agents and site exporters."""

    candidate_id: str
    target_data_point_id: str
    target_period: str
    generated_at: str
    train_cutoff: str
    library: str
    library_version: str
    model_name: str
    point_estimate: float
    p10: float
    p50: float
    p90: float
    interval80: ForecastInterval
    interval90: ForecastInterval
    interval_method: IntervalMethod
    calibration_n: int
    history: tuple[TimeSeriesObservation, ...]
    diagnostics: tuple[str, ...]
    backtest_score: BacktestScore | None = None
    # Bayesian candidates only: predictive quantile grid, sampler settings and
    # diagnostics, and the Stan program source, so anyone can replay the fit.
    posterior_predictive: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "candidateId": self.candidate_id,
            "targetDataPointId": self.target_data_point_id,
            "targetPeriod": self.target_period,
            "generatedAt": self.generated_at,
            "trainCutoff": self.train_cutoff,
            "library": self.library,
            "libraryVersion": self.library_version,
            "modelName": self.model_name,
            "pointEstimate": self.point_estimate,
            "quantiles": {
                "p10": self.p10,
                "p50": self.p50,
                "p90": self.p90,
            },
            "interval80": self.interval80.as_dict(),
            "interval90": self.interval90.as_dict(),
            "intervalMethod": self.interval_method,
            "calibrationN": self.calibration_n,
            "history": [point.as_dict() for point in self.history],
            "backtestScore": (
                self.backtest_score.as_dict() if self.backtest_score else None
            ),
            "diagnostics": list(self.diagnostics),
        }
        if self.posterior_predictive is not None:
            payload["posteriorPredictive"] = self.posterior_predictive
        return payload


def build_candidate_set(
    *,
    target_data_point_id: str,
    target_period: str,
    history: Sequence[TimeSeriesObservation | dict[str, Any]],
    models: Sequence[str] = ("persistence", "statsmodels-local-level"),
    generated_at: str | None = None,
    round_increment: float | None = None,
    stan_program: str | None = None,
) -> dict[str, Any]:
    """Build model candidates under the common Thesis candidate-set schema.

    ``stan_program`` is the Stan source for the ``stanli-custom`` model; see
    :mod:`brier.stan_candidates` for its data contract.
    """

    normalized_history = normalize_history(history)
    effective_generated_at = generated_at or utc_now()
    candidates: list[ForecastModelCandidate] = []
    for model in models:
        if model == "persistence":
            candidates.append(
                build_persistence_candidate(
                    target_data_point_id=target_data_point_id,
                    target_period=target_period,
                    history=normalized_history,
                    generated_at=effective_generated_at,
                    round_increment=round_increment,
                )
            )
        elif model == "statsmodels-local-level":
            candidates.append(
                build_statsmodels_local_level_candidate(
                    target_data_point_id=target_data_point_id,
                    target_period=target_period,
                    history=normalized_history,
                    generated_at=effective_generated_at,
                    round_increment=round_increment,
                )
            )
        elif model.startswith("stanli-"):
            from brier.stan_candidates import build_stanli_candidate

            candidates.append(
                build_stanli_candidate(
                    model=model,
                    target_data_point_id=target_data_point_id,
                    target_period=target_period,
                    history=normalized_history,
                    generated_at=effective_generated_at,
                    round_increment=round_increment,
                    program=stan_program if model == "stanli-custom" else None,
                )
            )
        else:
            raise ValueError(f"Unsupported model candidate {model!r}")

    return {
        "schemaVersion": CANDIDATE_SET_SCHEMA_VERSION,
        "targetDataPointId": target_data_point_id,
        "targetPeriod": target_period,
        "generatedAt": effective_generated_at,
        "candidateCount": len(candidates),
        "candidates": [candidate.as_dict() for candidate in candidates],
    }


def build_persistence_candidate(
    *,
    target_data_point_id: str,
    target_period: str,
    history: Sequence[TimeSeriesObservation | dict[str, Any]],
    generated_at: str | None = None,
    round_increment: float | None = None,
) -> ForecastModelCandidate:
    """Last-print persistence with residual empirical intervals."""

    normalized_history = normalize_history(history)
    values = [point.value for point in normalized_history]
    latest = normalized_history[-1]
    residuals = [values[index] - values[index - 1] for index in range(1, len(values))]
    if len(residuals) >= 2:
        p10_residual = quantile(residuals, 0.10)
        p90_residual = quantile(residuals, 0.90)
        p05_residual = quantile(residuals, 0.05)
        p95_residual = quantile(residuals, 0.95)
        interval_method: IntervalMethod = "residual_quantile"
        diagnostics = (
            f"last-print persistence from {latest.period}",
            f"empirical residual intervals from {len(residuals)} one-step moves",
        )
    else:
        scale = max(abs(latest.value) * 0.10, 1.0)
        p10_residual = -scale
        p90_residual = scale
        p05_residual = -1.25 * scale
        p95_residual = 1.25 * scale
        interval_method = "fallback_prior"
        diagnostics = (
            f"last-print persistence from {latest.period}",
            "fallback interval because fewer than 2 one-step residuals exist",
        )

    point = latest.value
    interval80_lower = min(point, latest.value + p10_residual)
    interval80_upper = max(point, latest.value + p90_residual)
    interval90_lower = min(point, latest.value + p05_residual)
    interval90_upper = max(point, latest.value + p95_residual)
    point, interval80_lower, interval80_upper, interval90_lower, interval90_upper = (
        round_values(
            [
                point,
                interval80_lower,
                interval80_upper,
                interval90_lower,
                interval90_upper,
            ],
            round_increment,
        )
    )

    if interval80_lower == interval80_upper:
        interval80_lower, interval80_upper = widen_equal_interval(
            point, round_increment
        )
    if interval90_lower == interval90_upper:
        interval90_lower, interval90_upper = widen_equal_interval(
            point, round_increment
        )
    interval80_lower, interval80_upper = ensure_strictly_brackets_point(
        point, interval80_lower, interval80_upper, round_increment
    )
    interval90_lower, interval90_upper = ensure_strictly_brackets_point(
        point, interval90_lower, interval90_upper, round_increment
    )

    p10, p90, p05, p95 = (
        interval80_lower,
        interval80_upper,
        interval90_lower,
        interval90_upper,
    )

    return ForecastModelCandidate(
        candidate_id=candidate_id(
            target_data_point_id,
            target_period,
            "brier",
            "persistence.last_print",
            normalized_history,
        ),
        target_data_point_id=target_data_point_id,
        target_period=target_period,
        generated_at=generated_at or utc_now(),
        train_cutoff=latest.period,
        library="brier",
        library_version=package_version("brier"),
        model_name="persistence.last_print",
        point_estimate=point,
        p10=p10,
        p50=point,
        p90=p90,
        interval80=ForecastInterval(
            lower=min(p10, p90), upper=max(p10, p90), level=0.8
        ),
        interval90=ForecastInterval(
            lower=min(p05, p95), upper=max(p05, p95), level=0.9
        ),
        interval_method=interval_method,
        calibration_n=max(len(residuals), 0),
        history=tuple(normalized_history),
        backtest_score=backtest_persistence(normalized_history),
        diagnostics=diagnostics,
    )


def build_statsmodels_local_level_candidate(
    *,
    target_data_point_id: str,
    target_period: str,
    history: Sequence[TimeSeriesObservation | dict[str, Any]],
    generated_at: str | None = None,
    round_increment: float | None = None,
    backtest: bool = True,
) -> ForecastModelCandidate:
    """Statsmodels random-walk-with-drift candidate with native intervals.

    ``backtest=False`` skips the walk-forward score. The backtest itself builds
    its per-cutoff candidates that way: a nested backtest at every cutoff made
    a history of n points cost 2**(n - 3) fits.
    """

    normalized_history = normalize_history(history)
    if len(normalized_history) < 3:
        raise ValueError("statsmodels-local-level needs at least 3 observations")

    try:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "statsmodels is not installed; install the brier experiments extra "
            "or request only the persistence model"
        ) from exc

    values = [point.value for point in normalized_history]
    model = SARIMAX(
        values,
        order=(0, 1, 0),
        trend="c",
        enforce_stationarity=False,
        enforce_invertibility=False,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = model.fit(disp=False)
    forecast = fit.get_forecast(steps=1)
    predicted_mean = as_sequence(forecast.predicted_mean)[-1]
    ci80 = forecast_interval_from_conf_int(forecast.conf_int(alpha=0.2), 0.8)
    ci90 = forecast_interval_from_conf_int(forecast.conf_int(alpha=0.1), 0.9)
    point, p10, p90, p05, p95 = round_values(
        [
            predicted_mean,
            ci80.lower,
            ci80.upper,
            ci90.lower,
            ci90.upper,
        ],
        round_increment,
    )

    latest = normalized_history[-1]
    return ForecastModelCandidate(
        candidate_id=candidate_id(
            target_data_point_id,
            target_period,
            "statsmodels",
            "sarimax_local_level_drift",
            normalized_history,
        ),
        target_data_point_id=target_data_point_id,
        target_period=target_period,
        generated_at=generated_at or utc_now(),
        train_cutoff=latest.period,
        library="statsmodels",
        library_version=package_version("statsmodels"),
        model_name="sarimax_local_level_drift",
        point_estimate=point,
        p10=p10,
        p50=point,
        p90=p90,
        interval80=ForecastInterval(
            lower=min(p10, p90), upper=max(p10, p90), level=0.8
        ),
        interval90=ForecastInterval(
            lower=min(p05, p95), upper=max(p05, p95), level=0.9
        ),
        interval_method="native_state_space",
        calibration_n=max(len(normalized_history) - 1, 0),
        history=tuple(normalized_history),
        backtest_score=(
            backtest_statsmodels_local_level(normalized_history) if backtest else None
        ),
        diagnostics=(
            "statsmodels SARIMAX(0,1,0) with drift",
            "intervals from statsmodels state-space forecast covariance",
        ),
    )


def normalize_history(
    history: Sequence[TimeSeriesObservation | dict[str, Any]],
) -> tuple[TimeSeriesObservation, ...]:
    """Coerce history into validated observations while preserving order."""

    if not history:
        raise ValueError("history must contain at least one observation")

    normalized: list[TimeSeriesObservation] = []
    for point in history:
        if isinstance(point, TimeSeriesObservation):
            period = point.period
            value = point.value
        else:
            period = str(point["period"])
            value = float(point["value"])
        if not math.isfinite(value):
            raise ValueError(f"non-finite value for period {period!r}")
        normalized.append(TimeSeriesObservation(period=period, value=value))
    return tuple(normalized)


def forecast_interval_from_conf_int(conf_int: Any, level: float) -> ForecastInterval:
    """Read a statsmodels conf_int result regardless of ndarray/dataframe shape."""

    rows = getattr(conf_int, "values", conf_int)
    last_row = rows[-1]
    return ForecastInterval(
        lower=float(last_row[0]), upper=float(last_row[1]), level=level
    )


def backtest_persistence(
    history: Sequence[TimeSeriesObservation],
) -> BacktestScore | None:
    if len(history) < 2:
        return None
    errors = [
        abs(history[index].value - history[index - 1].value)
        for index in range(1, len(history))
    ]
    return BacktestScore(
        method="walk_forward_1_step",
        rows=len(errors),
        mean_absolute_error=mean(errors),
    )


def backtest_statsmodels_local_level(
    history: Sequence[TimeSeriesObservation],
    *,
    min_train: int = 3,
) -> BacktestScore | None:
    if len(history) <= min_train:
        return None

    errors: list[float] = []
    interval_hits: list[bool] = []
    interval_widths: list[float] = []

    for cutoff in range(min_train, len(history)):
        train = history[:cutoff]
        actual = history[cutoff].value
        try:
            candidate = build_statsmodels_local_level_candidate(
                target_data_point_id="_backtest",
                target_period=history[cutoff].period,
                history=train,
                generated_at=DEFAULT_GENERATED_AT,
                backtest=False,
            )
        except Exception:
            continue
        errors.append(abs(actual - candidate.point_estimate))
        interval_hits.append(
            candidate.interval80.lower <= actual <= candidate.interval80.upper
        )
        interval_widths.append(candidate.interval80.upper - candidate.interval80.lower)

    if not errors:
        return None

    return BacktestScore(
        method="walk_forward_1_step",
        rows=len(errors),
        mean_absolute_error=mean(errors),
        interval80_coverage=sum(interval_hits) / len(interval_hits),
        mean_interval80_width=mean(interval_widths),
    )


def candidate_id(
    target_data_point_id: str,
    target_period: str,
    library: str,
    model_name: str,
    history: Sequence[TimeSeriesObservation],
) -> str:
    payload = {
        "targetDataPointId": target_data_point_id,
        "targetPeriod": target_period,
        "library": library,
        "modelName": model_name,
        "trainCutoff": history[-1].period,
        "historyLength": len(history),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"model_candidate.{digest[:16]}"


def as_sequence(values: Any) -> list[float]:
    raw = getattr(values, "values", values)
    return [float(value) for value in raw]


def quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot take a quantile of an empty sequence")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def round_values(
    values: Iterable[float],
    increment: float | None,
) -> tuple[float, ...]:
    if increment is None:
        return tuple(float(value) for value in values)
    if increment <= 0:
        raise ValueError("round_increment must be positive")
    places = decimal_places(increment)
    return tuple(
        float(f"{(round(value / increment) * increment):.{places}f}")
        for value in values
    )


def widen_equal_interval(point: float, increment: float | None) -> tuple[float, float]:
    step = increment if increment is not None else max(abs(point) * 0.01, 1.0)
    return point - step, point + step


def ensure_strictly_brackets_point(
    point: float,
    lower: float,
    upper: float,
    increment: float | None,
) -> tuple[float, float]:
    step = increment if increment is not None else max(abs(point) * 0.01, 1.0)
    if lower >= point:
        lower = point - step
    if upper <= point:
        upper = point + step
    return lower, upper


def decimal_places(value: float) -> int:
    text = str(value).lower()
    if "e-" in text:
        return int(text.split("e-")[1])
    if "." not in text:
        return 0
    return len(text.split(".")[1])


def package_version(package: str) -> str:
    if package == "brier":
        try:
            from brier import __version__

            return __version__
        except Exception:
            return "unknown"
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "not_installed"


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        import sys

        argv = sys.argv[1:]
    if any(arg.split("=", 1)[0] == "--print-stan-program" for arg in argv):
        from brier.stan_candidates import STAN_PROGRAMS

        printer = argparse.ArgumentParser(
            description="Print a built-in stanli program to start a custom one.",
        )
        printer.add_argument("--print-stan-program", choices=sorted(STAN_PROGRAMS))
        print(STAN_PROGRAMS[printer.parse_args(argv).print_stan_program], end="")
        return 0

    parser = argparse.ArgumentParser(
        description="Emit Thesis time-series model candidates with intervals.",
    )
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--target-period", required=True)
    parser.add_argument(
        "--history-json",
        help='JSON array of {"period": "...", "value": number} observations.',
    )
    parser.add_argument("--history-file", type=Path)
    parser.add_argument(
        "--models",
        default="persistence,statsmodels-local-level",
        help=(
            "Comma-separated candidate models: persistence, "
            "statsmodels-local-level, stanli-rw-drift-t, stanli-ar1-t, "
            "stanli-ar1-diff-t, or stanli-custom with --stan-file."
        ),
    )
    parser.add_argument(
        "--stan-file",
        type=Path,
        help="Stan program for the stanli-custom model; it must define y_next.",
    )
    parser.add_argument("--round-increment", type=float)
    parser.add_argument("--generated-at")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if bool(args.history_json) == bool(args.history_file):
        parser.error("provide exactly one of --history-json or --history-file")
    models = [model.strip() for model in args.models.split(",") if model.strip()]
    if ("stanli-custom" in models) != (args.stan_file is not None):
        parser.error("--stan-file and the stanli-custom model go together")

    raw_history = (
        json.loads(args.history_json)
        if args.history_json
        else json.loads(args.history_file.read_text())
    )
    candidate_set = build_candidate_set(
        target_data_point_id=args.target_id,
        target_period=args.target_period,
        history=raw_history,
        models=models,
        generated_at=args.generated_at,
        round_increment=args.round_increment,
        stan_program=args.stan_file.read_text() if args.stan_file else None,
    )
    output = json.dumps(candidate_set, indent=2)
    if args.output:
        args.output.write_text(output + "\n")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
