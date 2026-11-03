#!/usr/bin/env python3
"""Real-time walk-forward backtest of stanli model candidates on ALFRED series.

For every series a Thesis ALFRED adapter resolves (scripts/resolve_pending.py
ALFRED_ADAPTERS, one per FRED id and transform), the script downloads a grid of
ALFRED vintages. For each recent period it finds the grid vintage that first
contains the period's print and the vintage just before it, then:

- builds the training history from the earlier vintage (what an agent could
  see), transformed the way the resolver transforms prints
  (resolve_pending.apply_transform), keeping the last ``--window`` values;
- has every arm forecast the period one step ahead from that history, with
  sampler seeds derived from the series and period;
- scores each arm's 201-point CDF against the first print, transformed from the
  release vintage, with the site's CRPS (scoreNumericCdfDistribution, ported
  below); and
- divides CRPS by the sample standard deviation of the training window's
  one-step changes, the lab's normalization.

Arms:

- ``persistence``: the ledger baseline. The point is the last print and the
  half-width the 80th percentile of absolute one-step changes, seeded into an
  interval_anchor_v1 CDF (buildLastPrintPriorInterval).
- ``persistence-ladder``: the last print plus the window's one-step changes at
  quantiles 0.05 to 0.95, as an agent_cdf_v1 threshold ladder, so ladder arms
  have a baseline of the same shape.
- ``statsmodels``: SARIMAX(0,1,0) with drift, point and 80% interval, seeded
  into an interval_anchor_v1 CDF.
- ``statsmodels-ladder``: the same model's Gaussian quantiles at 0.05 to 0.95
  as an agent_cdf_v1 threshold ladder.
- ``stanli-*``: each built-in stanli program's median and 80% interval as an
  interval_anchor_v1 CDF (what a fast-mode agent publishes).
- ``stanli-*-ladder``: the same program's 19 posterior quantiles as an
  agent_cdf_v1 threshold ladder (what a ladder-mode agent publishes).
- ``stanli-selected`` and ``stanli-selected-ladder``, with ``--walk-forward``:
  for each target, the program that select_model picks from its walk-forward
  score over the training history's last 24 cutoffs, as both CDF shapes.
- ``stanli-selected-noskip`` and its ladder: the same rule without skipping
  programs that warn, so the summary can price the skip.

The grid samples vintages on the 1st and 16th of each month, so a "first print"
is the print as of the first grid date after release; a revision inside that
window would count as the first print. Forecasts are not rounded to the
target's reporting precision.

Usage:
  uv run --extra stan --extra experiments python \\
    scripts/backtest_stanli_candidates.py --output-dir experiments/stanli_backtest \\
    --walk-forward --jobs 4
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import pathlib
import random
import statistics
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from brier.stan_candidates import (  # noqa: E402
    QUANTILE_LEVELS,
    STAN_PROGRAMS,
    build_stanli_candidate,
    observation_grid,
    sampler_failed,
)
from brier.timeseries import build_statsmodels_local_level_candidate  # noqa: E402

ALFRED_CSV = (
    "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={ids}&vintage_date={dates}"
)
# ALFRED returns at most 12 series columns per graph.
VINTAGES_PER_REQUEST = 12
GENERATED_AT = "2026-11-02T00:00:00Z"
NORMAL_Z90 = statistics.NormalDist().inv_cdf(0.9)
# Arm pairs the summary compares head to head: the selection rule against a
# fixed program, the rule against itself without the skip, and ladder arms
# against the ladder baseline.
PAIRED_COMPARISONS = (
    ("stanli-selected-ladder", "stanli-ar1-t-ladder"),
    ("stanli-selected", "stanli-ar1-t"),
    ("stanli-selected-ladder", "stanli-selected-noskip-ladder"),
    ("stanli-selected", "stanli-selected-noskip"),
)
# Arms whose target-level spread sizes the ablation.
POWER_ARMS = (
    "stanli-ar1-t",
    "stanli-ar1-t-ladder",
    "stanli-selected",
    "stanli-selected-ladder",
)
# Training windows that start after this month leave out the 2020-21 swings.
POST_PANDEMIC_WINDOW_START = "2021-07"


# Ports of the site's scoring and baseline code. Each mirrors a named
# TypeScript function line for line. tests/test_backtest_stanli_candidates.py
# checks score_numeric_cdf against the TypeScript original and the other ports
# against hand-computed cases.


def round_distribution_number(value: float) -> float:
    """roundDistributionNumber: JavaScript Number(value.toPrecision(12)) + 0."""

    return float(format(value, ".12g")) + 0.0


def score_numeric_cdf(
    points: Sequence[dict[str, float]], observed: float
) -> tuple[float, float]:
    """scoreNumericCdfDistribution: CRPS and PIT of a piecewise-linear CDF."""

    if not math.isfinite(observed):
        raise ValueError("Observed value must be finite")
    crps = 0.0
    for index in range(1, len(points)):
        previous, current = points[index - 1], points[index]
        if previous["value"] < observed < current["value"]:
            at_observation = previous["probability"] + (
                (observed - previous["value"]) / (current["value"] - previous["value"])
            ) * (current["probability"] - previous["probability"])
            crps += integrate_squared_linear(
                observed - previous["value"], previous["probability"], at_observation
            )
            crps += integrate_squared_linear(
                current["value"] - observed,
                at_observation - 1,
                current["probability"] - 1,
            )
            continue
        indicator = 0 if current["value"] <= observed else 1
        crps += integrate_squared_linear(
            current["value"] - previous["value"],
            previous["probability"] - indicator,
            current["probability"] - indicator,
        )
    if observed < points[0]["value"]:
        crps += points[0]["value"] - observed
    if observed > points[-1]["value"]:
        crps += observed - points[-1]["value"]
    knots = [(point["value"], point["probability"]) for point in points]
    return (
        round_distribution_number(crps),
        round_distribution_number(cdf_at(observed, knots)),
    )


def integrate_squared_linear(width: float, lower: float, upper: float) -> float:
    return width * (lower**2 + lower * upper + upper**2) / 3


def cdf_at(value: float, knots: Sequence[tuple[float, float]]) -> float:
    """interpolateCdfProbability over already-sorted, distinct knots."""

    if value <= knots[0][0]:
        return knots[0][1]
    for (previous_value, previous_probability), (
        current_value,
        current_probability,
    ) in zip(knots, knots[1:]):
        if value <= current_value:
            width = current_value - previous_value
            if width <= 0:
                return current_probability
            return previous_probability + (value - previous_value) / width * (
                current_probability - previous_probability
            )
    return knots[-1][1]


def ts_quantile(values: Sequence[float], probability: float) -> float:
    """time-series-priors.ts quantile: linear interpolation, 0 when empty."""

    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return 0.0
    if len(finite) == 1:
        return finite[0]
    index = (len(finite) - 1) * probability
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return finite[lower]
    return finite[lower] + (finite[upper] - finite[lower]) * (index - lower)


def persistence_interval(history: Sequence[float]) -> tuple[float, float, float]:
    """buildLastPrintPriorInterval: last print +/- p80 of |one-step changes|."""

    point = history[-1]
    half_width = ts_quantile([abs(b - a) for a, b in zip(history, history[1:])], 0.8)
    return (
        point,
        float(format(point - half_width, ".12g")),
        float(format(point + half_width, ".12g")),
    )


# Real-time data from ALFRED.


@dataclass(frozen=True)
class SeriesSpec:
    fred: str
    transform: str
    scale: float
    digits: int | None
    stems: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.fred}:{self.transform}"


@dataclass(frozen=True)
class Target:
    series: str
    period: str
    info_vintage: str
    release_vintage: str
    history: tuple[float, ...]
    outcome: float
    window_start: str = ""


def adapter_series(adapters: dict[str, dict[str, Any]]) -> list[SeriesSpec]:
    """One spec per FRED id and transform; unit variants share dynamics."""

    grouped: dict[tuple[str, str], list[str]] = {}
    for stem, spec in adapters.items():
        grouped.setdefault((spec["fred"], spec["transform"]), []).append(stem)
    specs = []
    for (fred, transform), stems in sorted(grouped.items()):
        first = adapters[stems[0]]
        specs.append(
            SeriesSpec(
                fred=fred,
                transform=transform,
                scale=float(first.get("scale", 1)),
                digits=first.get("round"),
                stems=tuple(stems),
            )
        )
    return specs


def vintage_grid(start: dt.date, end: dt.date) -> list[dt.date]:
    """The 1st and 16th of every month from ``start`` through ``end``."""

    dates = []
    year, month = start.year, start.month
    while dt.date(year, month, 1) <= end:
        for day in (1, 16):
            date = dt.date(year, month, day)
            if start <= date <= end:
                dates.append(date)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return dates


def parse_vintage_csv(text: str) -> dict[str, dict[str, float]]:
    """Map each vintage (YYYY-MM-DD) to its {observation_date: value} rows."""

    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    if not header or header[0] != "observation_date":
        raise ValueError(f"unexpected ALFRED header {header[:3]!r}")
    vintages = []
    for column in header[1:]:
        stamp = column.rsplit("_", 1)[-1]
        vintages.append(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}")
    rows: dict[str, dict[str, float]] = {vintage: {} for vintage in vintages}
    for record in reader:
        for vintage, cell in zip(vintages, record[1:]):
            if cell not in ("", "."):
                rows[vintage][record[0]] = float(cell)
    return rows


def fetch_vintages(
    series: str,
    dates: Sequence[dt.date],
    cache_dir: pathlib.Path,
    *,
    pause: float = 0.5,
    today: dt.date | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, dict[str, float]]:
    """Download (or read cached) vintages, VINTAGES_PER_REQUEST at a time.

    A past ALFRED vintage never changes, so a cached chunk never goes stale.
    The script refuses vintage dates from today on, which can still change,
    and caches a download only after it parses and holds every vintage it
    asked for.
    """

    today = today or dt.date.today()
    if dates and max(dates) >= today:
        raise ValueError(
            f"vintage {max(dates)} may still change; end the grid before {today}"
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    vintages: dict[str, dict[str, float]] = {}
    for offset in range(0, len(dates), VINTAGES_PER_REQUEST):
        chunk = dates[offset : offset + VINTAGES_PER_REQUEST]
        path = cache_dir / f"{series}_{chunk[0]}_{chunk[-1]}_{len(chunk)}.csv"
        if path.exists():
            text = path.read_text()
        else:
            url = ALFRED_CSV.format(
                ids=",".join([series] * len(chunk)),
                dates=",".join(date.isoformat() for date in chunk),
            )
            request = urllib.request.Request(
                url, headers={"User-Agent": "thesis-stanli-backtest"}
            )
            with opener(request, timeout=90) as response:
                text = response.read().decode()
            received = sorted(parse_vintage_csv(text))
            wanted = [date.isoformat() for date in chunk]
            if received != wanted:
                raise ValueError(
                    f"ALFRED sent vintages {received} for {series}, not {wanted}"
                )
            partial = path.with_name(path.name + ".partial")
            partial.write_text(text)
            os.replace(partial, path)
            time.sleep(pause)
        vintages.update(parse_vintage_csv(text))
    return vintages


def period_type(observation_dates: Sequence[str]) -> str:
    dates = sorted(dt.date.fromisoformat(value) for value in observation_dates)
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    return "quarter" if gaps and statistics.median(gaps) >= 80 else "month"


def transformed_series(
    rows: dict[str, float],
    spec: SeriesSpec,
    kind: str,
    apply_transform: Callable[..., float | None],
) -> list[tuple[str, float]]:
    """Every period's resolver-transformed value within one vintage."""

    adapter = {"transform": spec.transform, "scale": spec.scale}
    if spec.digits is not None:
        adapter["round"] = spec.digits
    values = []
    for observation_date in sorted(rows):
        period = observation_date[:7]
        value = apply_transform(rows, adapter, kind, period)
        if value is not None:
            values.append((period, value))
    return values


def real_time_targets(
    spec: SeriesSpec,
    vintages: dict[str, dict[str, float]],
    *,
    window: int,
    max_targets: int,
    apply_transform: Callable[..., float | None],
    prior_period: Callable[[str, str], str],
) -> list[Target]:
    """One-step-ahead targets, each trained on the vintage before its release."""

    ordered = sorted(vintage for vintage, rows in vintages.items() if rows)
    if len(ordered) < 2:
        return []
    kind = period_type(list(vintages[ordered[-1]]))
    targets: list[Target] = []
    seen: set[str] = set()
    for earlier, later in zip(ordered, ordered[1:]):
        known = {date[:7] for date in vintages[earlier]}
        for date in sorted(vintages[later]):
            period = date[:7]
            if period in known or period in seen:
                continue
            seen.add(period)
            history = transformed_series(vintages[earlier], spec, kind, apply_transform)
            if not history or history[-1][0] != prior_period(period, kind):
                continue  # not one step ahead of the information set
            outcome = apply_transform(
                vintages[later],
                {
                    "transform": spec.transform,
                    "scale": spec.scale,
                    **({"round": spec.digits} if spec.digits is not None else {}),
                },
                kind,
                period,
            )
            if outcome is None:
                continue
            kept = history[-window:]
            targets.append(
                Target(
                    series=spec.key,
                    period=period,
                    info_vintage=earlier,
                    release_vintage=later,
                    history=tuple(value for _, value in kept),
                    outcome=outcome,
                    window_start=kept[0][0],
                )
            )
    return sorted(targets, key=lambda target: target.period)[-max_targets:]


# Arms.


def interval_cdf(point: float, low: float, high: float, interval_distribution):
    return interval_distribution({"pointEstimate": point, "ciLow": low, "ciHigh": high})


def ladder_cdf(
    quantiles: Sequence[float], levels: Sequence[float], ladder_distribution
):
    median = quantiles[levels.index(0.5)]
    return ladder_distribution(
        {
            "pointEstimate": median,
            "ciLow": quantiles[levels.index(0.1)],
            "ciHigh": quantiles[levels.index(0.9)],
            "thresholdLadder": {
                "thresholds": list(quantiles),
                "cumulativeProbabilities": list(levels),
            },
        }
    )


def persistence_ladder(history: Sequence[float]) -> list[float]:
    """The last print plus each quantile of the window's one-step changes.

    Rounded series repeat changes, so quantiles tie. A tied rung moves to a
    thousandth of the print grid above the rung below, so the ladder rises
    strictly, as the analyst's ladder check requires.
    """

    changes = [b - a for a, b in zip(history, history[1:])]
    nudge = observation_grid(history) / 1000
    rungs: list[float] = []
    for level in QUANTILE_LEVELS:
        rung = history[-1] + ts_quantile(changes, level)
        if rungs and rung <= rungs[-1]:
            rung = rungs[-1] + nudge
        rungs.append(rung)
    return rungs


def select_model(scores: dict[str, dict[str, Any]], *, skip_warned: bool = True) -> str:
    """Apply the draft pack skill's rule to each model's walk-forward score.

    Skip a model whose diagnostics warn, take the lowest walk-forward MAE, and
    break exact ties by coverage nearest 0.8, then by name. When every model
    warns, the rule has nothing left, so it considers them all.
    ``skip_warned=False`` drops the skip.
    """

    usable = (
        {model: score for model, score in scores.items() if not score["warned"]}
        if skip_warned
        else {}
    ) or scores
    return min(
        usable,
        key=lambda model: (
            usable[model]["meanAbsoluteError"],
            abs(usable[model]["coverage80"] - 0.8),
            model,
        ),
    )


def forecast_arms(
    history: Sequence[float],
    *,
    target_id: str = "backtest",
    stan_models: Sequence[str],
    interval_distribution,
    ladder_distribution,
    walk_forward: bool = False,
) -> dict[str, dict[str, Any]]:
    """Each arm's CDF and 80% interval for the next print.

    ``target_id`` names the target, so every target draws its own sampler
    seeds.
    """

    observations = [
        {"period": f"t{index:03d}", "value": value}
        for index, value in enumerate(history)
    ]
    levels = list(QUANTILE_LEVELS)
    arms: dict[str, dict[str, Any]] = {}

    point, low, high = persistence_interval(history)
    arms["persistence"] = {
        "cdf": interval_cdf(point, low, high, interval_distribution),
        "interval80": (low, high),
    }
    rungs = persistence_ladder(history)
    arms["persistence-ladder"] = {
        "cdf": ladder_cdf(rungs, levels, ladder_distribution),
        "interval80": (rungs[levels.index(0.1)], rungs[levels.index(0.9)]),
        "quantiles": rungs,
    }

    sarimax = build_statsmodels_local_level_candidate(
        target_data_point_id="backtest",
        target_period="next",
        history=observations,
        generated_at=GENERATED_AT,
        backtest=False,
    )
    low, high = sarimax.interval80.lower, sarimax.interval80.upper
    arms["statsmodels"] = {
        "cdf": interval_cdf(sarimax.point_estimate, low, high, interval_distribution),
        "interval80": (low, high),
    }
    sd = (high - low) / (2 * NORMAL_Z90)
    if sd > 0:
        gaussian = [
            sarimax.point_estimate + sd * statistics.NormalDist().inv_cdf(level)
            for level in levels
        ]
        arms["statsmodels-ladder"] = {
            "cdf": ladder_cdf(gaussian, levels, ladder_distribution),
            "interval80": (low, high),
            "quantiles": gaussian,
        }

    scores: dict[str, dict[str, Any]] = {}
    for model in stan_models:
        candidate = build_stanli_candidate(
            model=model,
            target_data_point_id=target_id,
            target_period="next",
            history=observations,
            generated_at=GENERATED_AT,
            backtest=walk_forward,
        )
        quantiles = [
            row["value"] for row in candidate.posterior_predictive["quantiles"]
        ]
        low = quantiles[levels.index(0.1)]
        high = quantiles[levels.index(0.9)]
        score = candidate.backtest_score
        shared = {
            "interval80": (low, high),
            "sampler": candidate.posterior_predictive["sampler"],
            "warned": any(line.startswith("WARNING") for line in candidate.diagnostics),
            **(
                {
                    "walkForwardMae": score.mean_absolute_error,
                    "walkForwardCoverage80": score.interval80_coverage,
                }
                if score
                else {}
            ),
        }
        arms[model] = {
            "cdf": interval_cdf(
                quantiles[levels.index(0.5)], low, high, interval_distribution
            ),
            **shared,
        }
        arms[f"{model}-ladder"] = {
            "cdf": ladder_cdf(quantiles, levels, ladder_distribution),
            "quantiles": quantiles,
            **shared,
        }
        scores[model] = {
            "warned": shared["warned"],
            "meanAbsoluteError": score.mean_absolute_error if score else math.inf,
            "coverage80": score.interval80_coverage if score else math.inf,
        }
    if walk_forward and scores:
        for suffix, skip_warned in (("", True), ("-noskip", False)):
            selected = select_model(scores, skip_warned=skip_warned)
            arms[f"stanli-selected{suffix}"] = {**arms[selected], "selected": selected}
            arms[f"stanli-selected{suffix}-ladder"] = {
                **arms[f"{selected}-ladder"],
                "selected": selected,
            }
    return arms


def step_sd(history: Sequence[float]) -> float | None:
    changes = [b - a for a, b in zip(history, history[1:])]
    if len(history) < 3 or len(changes) < 2:
        return None
    sd = statistics.stdev(changes)
    return sd if sd > 0 else None


def score_target(target: Target, arms: dict[str, dict[str, Any]]) -> list[dict]:
    scale = step_sd(target.history)
    rows = []
    for arm, forecast in arms.items():
        crps, pit = score_numeric_cdf(forecast["cdf"]["points"], target.outcome)
        low, high = forecast["interval80"]
        rows.append(
            {
                "series": target.series,
                "period": target.period,
                "arm": arm,
                "infoVintage": target.info_vintage,
                "releaseVintage": target.release_vintage,
                "windowStart": target.window_start,
                "historyLength": len(target.history),
                "outcome": target.outcome,
                "crps": crps,
                "normalizedCrps": crps / scale if scale else None,
                "pit": pit,
                "covered80": low <= target.outcome <= high,
                "samplerFailed": bool(
                    forecast.get("sampler") and sampler_failed(forecast["sampler"])
                ),
                **{
                    key: forecast[key]
                    for key in (
                        "warned",
                        "selected",
                        "walkForwardMae",
                        "walkForwardCoverage80",
                    )
                    if key in forecast
                },
            }
        )
    return rows


def run_series(
    spec: SeriesSpec,
    *,
    dates: Sequence[dt.date],
    cache_dir: pathlib.Path,
    window: int,
    max_targets: int,
    stan_models: Sequence[str],
    walk_forward: bool,
) -> tuple[list[dict], int]:
    """Every arm's scored rows for one series, and its target count."""

    import resolve_pending
    import run_thesis_analyst

    targets = real_time_targets(
        spec,
        fetch_vintages(spec.fred, dates, cache_dir),
        window=window,
        max_targets=max_targets,
        apply_transform=resolve_pending.apply_transform,
        prior_period=resolve_pending.prior_period_date,
    )
    rows: list[dict] = []
    for target in targets:
        arms = forecast_arms(
            target.history,
            target_id=f"backtest.{target.series}.{target.period}",
            stan_models=stan_models,
            interval_distribution=run_thesis_analyst.interval_distribution,
            ladder_distribution=run_thesis_analyst.ladder_distribution,
            walk_forward=walk_forward,
        )
        rows.extend(score_target(target, arms))
    return rows, len(targets)


# Summaries.


def series_sums(
    rows: Sequence[dict], baseline: str = "persistence"
) -> dict[tuple[str, str], dict[str, float]]:
    """Per arm and series, the paired sums that the bootstrap recombines."""

    by_key: dict[tuple[str, str], dict[str, dict]] = {}
    for row in rows:
        by_key.setdefault((row["series"], row["period"]), {})[row["arm"]] = row
    sums: dict[tuple[str, str], dict[str, float]] = {}
    for (series, _), by_arm in by_key.items():
        base = by_arm.get(baseline)
        if base is None:
            continue
        for arm, row in by_arm.items():
            total = sums.setdefault(
                (arm, series),
                dict.fromkeys(
                    (
                        "targets",
                        "beats",
                        "covered",
                        "samplerFailed",
                        "normalizedTargets",
                        "normalized",
                        "difference",
                        "ratioTargets",
                        "logRatio",
                    ),
                    0.0,
                ),
            )
            total["targets"] += 1
            total["beats"] += row["crps"] < base["crps"]
            total["covered"] += row["covered80"]
            total["samplerFailed"] += row["samplerFailed"]
            if row["normalizedCrps"] is not None and base["normalizedCrps"] is not None:
                total["normalizedTargets"] += 1
                total["normalized"] += row["normalizedCrps"]
                total["difference"] += row["normalizedCrps"] - base["normalizedCrps"]
            if row["crps"] > 0 and base["crps"] > 0:
                total["ratioTargets"] += 1
                total["logRatio"] += math.log(row["crps"] / base["crps"])
    return sums


def combine(totals: Sequence[dict[str, float]]) -> dict[str, float]:
    """Target-weighted statistics from per-series sums."""

    def total(key: str) -> float:
        return sum(item[key] for item in totals)

    def ratio(numerator: float, denominator: float) -> float:
        return numerator / denominator if denominator else math.nan

    return {
        "meanNormalizedCrps": ratio(total("normalized"), total("normalizedTargets")),
        "meanNormalizedCrpsDifference": ratio(
            total("difference"), total("normalizedTargets")
        ),
        "geometricMeanCrpsRatio": math.exp(
            ratio(total("logRatio"), total("ratioTargets"))
        ),
        "shareBeatingBaseline": ratio(total("beats"), total("targets")),
        "coverage80": ratio(total("covered"), total("targets")),
    }


def arm_statistics(
    by_series: dict[str, dict[str, float]], samples: Sequence[Sequence[str]]
) -> dict[str, Any]:
    """One arm's paired statistics, with 95% intervals over the series resamples."""

    point = combine(list(by_series.values()))
    boot: dict[str, list[float]] = {key: [] for key in point}
    for sample in samples:
        values = combine(
            [by_series[series] for series in sample if series in by_series]
        )
        for key, value in values.items():
            if math.isfinite(value):
                boot[key].append(value)

    def count(key: str) -> int:
        return int(sum(item[key] for item in by_series.values()))

    return {
        "targets": count("targets"),
        "ratioTargets": count("ratioTargets"),
        "series": len(by_series),
        "samplerFailures": count("samplerFailed"),
        **point,
        "interval95": {
            key: [percentile(values, 0.025), percentile(values, 0.975)]
            for key, values in boot.items()
            if values
        },
    }


def compare(
    rows: Sequence[dict],
    *,
    baseline: str = "persistence",
    arms: Sequence[str] | None = None,
    draws: int = 2000,
) -> dict[str, dict[str, Any]]:
    """Each arm (or each of ``arms``) paired against ``baseline``.

    The 95% intervals come from a bootstrap that resamples whole series with
    replacement, so they reflect that targets within a series share a model
    and a history.
    """

    sums = series_sums(rows, baseline)
    present = {arm for arm, _ in sums}
    names = sorted(present if arms is None else present & set(arms))
    series_ids = sorted({series for _, series in sums})
    rng = random.Random(20261102)
    samples = [[rng.choice(series_ids) for _ in series_ids] for _ in range(draws)]
    return {
        arm: arm_statistics(
            {
                series: sums[(arm, series)]
                for series in series_ids
                if (arm, series) in sums
            },
            samples,
        )
        for arm in names
    }


def summarize(
    rows: Sequence[dict], *, baseline: str = "persistence", draws: int = 2000
) -> dict[str, Any]:
    """Per-arm accuracy paired against the baseline, with a bootstrap over series."""

    return {"baseline": baseline, "arms": compare(rows, baseline=baseline, draws=draws)}


def paired_comparisons(
    rows: Sequence[dict],
    pairs: Sequence[tuple[str, str]] = PAIRED_COMPARISONS,
    *,
    draws: int = 2000,
) -> dict[str, dict[str, Any]]:
    """Each pair's statistics with its second arm as the baseline."""

    table: dict[str, dict[str, Any]] = {}
    for arm, baseline in pairs:
        stats = compare(rows, baseline=baseline, arms=[arm], draws=draws).get(arm)
        if stats:
            table[f"{arm} vs {baseline}"] = stats
    return table


def percentile(values: Sequence[float], probability: float) -> float:
    return ts_quantile(values, probability)


def per_series(rows: Sequence[dict], baseline: str = "persistence") -> dict:
    """Each series' geometric-mean CRPS ratio against the baseline, by arm."""

    table: dict[str, dict[str, float]] = {}
    by_key: dict[tuple[str, str], dict[str, dict]] = {}
    for row in rows:
        by_key.setdefault((row["series"], row["period"]), {})[row["arm"]] = row
    logs: dict[tuple[str, str], list[float]] = {}
    for (series, _), by_arm in by_key.items():
        base = by_arm.get(baseline)
        if not base or base["crps"] <= 0:
            continue
        for arm, row in by_arm.items():
            if arm != baseline and row["crps"] > 0:
                logs.setdefault((series, arm), []).append(
                    math.log(row["crps"] / base["crps"])
                )
    for (series, arm), values in sorted(logs.items()):
        table.setdefault(series, {})[arm] = math.exp(statistics.fmean(values))
    return table


def by_transform(rows: Sequence[dict], baseline: str = "persistence") -> dict:
    """Each arm's statistics within each transform (the series key's suffix)."""

    grouped: dict[str, dict[str, list[dict[str, float]]]] = {}
    for (arm, series), total in series_sums(rows, baseline).items():
        transform = series.split(":", 1)[1]
        grouped.setdefault(transform, {}).setdefault(arm, []).append(total)
    return {
        transform: {
            arm: {
                "series": len(totals),
                "targets": int(sum(item["targets"] for item in totals)),
                **combine(totals),
            }
            for arm, totals in sorted(arms.items())
        }
        for transform, arms in sorted(grouped.items())
    }


def leave_one_series_out(rows: Sequence[dict], baseline: str = "persistence") -> dict:
    """How far dropping any one series moves each arm's CRPS ratio."""

    by_arm: dict[str, dict[str, dict[str, float]]] = {}
    for (arm, series), total in series_sums(rows, baseline).items():
        by_arm.setdefault(arm, {})[series] = total
    table: dict[str, dict[str, Any]] = {}
    for arm, totals in sorted(by_arm.items()):
        ratios = {
            dropped: combine(
                [total for series, total in totals.items() if series != dropped]
            )["geometricMeanCrpsRatio"]
            for dropped in totals
            if len(totals) > 1
        }
        if ratios:
            highest = max(sorted(ratios), key=ratios.__getitem__)
            lowest = min(sorted(ratios), key=ratios.__getitem__)
            table[arm] = {
                "highestRatio": ratios[highest],
                "highestRatioDrops": highest,
                "lowestRatio": ratios[lowest],
                "lowestRatioDrops": lowest,
            }
    return table


def selection_counts(rows: Sequence[dict]) -> dict[str, int]:
    """How often select_model picked each program."""

    counts: dict[str, int] = {}
    for row in rows:
        if row["arm"] == "stanli-selected":
            counts[row["selected"]] = counts.get(row["selected"], 0) + 1
    return dict(sorted(counts.items()))


def targets_by_key(rows: Sequence[dict]) -> dict[tuple[str, str], dict[str, dict]]:
    by_key: dict[tuple[str, str], dict[str, dict]] = {}
    for row in rows:
        by_key.setdefault((row["series"], row["period"]), {})[row["arm"]] = row
    return by_key


def warning_split(rows: Sequence[dict], baseline: str = "persistence") -> dict:
    """Every arm's CRPS ratio on the targets where each program warned or not.

    Keyed by program, then arm, then ``warned`` or ``clean``, so the table
    shows how each arm fared on the targets a program's diagnostics flagged.
    """

    logs: dict[tuple[str, str, bool], list[float]] = {}
    for by_arm in targets_by_key(rows).values():
        base = by_arm.get(baseline)
        if base is None or base["crps"] <= 0:
            continue
        for program in STAN_PROGRAMS:
            flagged = by_arm.get(program)
            if flagged is None or "warned" not in flagged:
                continue
            for arm, row in by_arm.items():
                if arm != baseline and row["crps"] > 0:
                    logs.setdefault((program, arm, flagged["warned"]), []).append(
                        math.log(row["crps"] / base["crps"])
                    )
    table: dict[str, dict[str, dict[str, Any]]] = {}
    for (program, arm, warned), values in sorted(logs.items()):
        table.setdefault(program, {}).setdefault(arm, {})[
            "warned" if warned else "clean"
        ] = {
            "targets": len(values),
            "geometricMeanCrpsRatio": math.exp(statistics.fmean(values)),
        }
    return table


def subset_statistics(
    rows: Sequence[dict],
    keep: Callable[[dict], bool],
    baseline: str = "persistence",
) -> dict[str, dict[str, Any]]:
    """Each arm's statistics over the targets whose baseline row ``keep`` accepts."""

    keys = {
        (row["series"], row["period"])
        for row in rows
        if row["arm"] == baseline and keep(row)
    }
    chosen = [row for row in rows if (row["series"], row["period"]) in keys]
    grouped: dict[str, list[dict[str, float]]] = {}
    for (arm, _), total in series_sums(chosen, baseline).items():
        grouped.setdefault(arm, []).append(total)
    return {
        arm: {
            "series": len(totals),
            "targets": int(sum(item["targets"] for item in totals)),
            **combine(totals),
        }
        for arm, totals in sorted(grouped.items())
    }


def by_period_half(rows: Sequence[dict], baseline: str = "persistence") -> dict:
    """Each arm's statistics on the earlier and the later half of the targets."""

    periods = sorted(row["period"] for row in rows if row["arm"] == baseline)
    if not periods:
        return {}
    cut = periods[len(periods) // 2]
    return {
        "laterHalfFrom": cut,
        "earlier": subset_statistics(rows, lambda row: row["period"] < cut, baseline),
        "later": subset_statistics(rows, lambda row: row["period"] >= cut, baseline),
    }


def windows_starting_from(
    rows: Sequence[dict],
    start: str = POST_PANDEMIC_WINDOW_START,
    baseline: str = "persistence",
) -> dict:
    """Each arm's statistics on targets whose training window starts at ``start``
    or later."""

    return {
        "windowStartFrom": start,
        "arms": subset_statistics(
            rows, lambda row: row.get("windowStart", "") >= start, baseline
        ),
    }


def ablation_power(
    rows: Sequence[dict],
    arm: str,
    *,
    baseline: str = "persistence",
    change: float = 0.10,
    power: float = 0.80,
) -> dict[str, Any] | None:
    """Matched targets needed to detect a ``change`` in the CRPS ratio.

    The spread of ``arm``'s per-target log CRPS ratio to ``baseline`` stands in
    for the paired difference between two agents, with a two-sided 5% test.
    Targets within a series share a history, so a one-way ANOVA estimate of
    the intraclass correlation (ICC) inflates the independent-target count by
    the design effect 1 + (m - 1) * ICC, where m is the mean number of targets
    per series. ``seriesNeeded`` repeats the count with each series' mean log
    ratio as one observation.
    """

    by_series: dict[str, list[float]] = {}
    for (series, _), by_arm in targets_by_key(rows).items():
        base, row = by_arm.get(baseline), by_arm.get(arm)
        if base and row and base["crps"] > 0 and row["crps"] > 0:
            by_series.setdefault(series, []).append(
                math.log(row["crps"] / base["crps"])
            )
    values = [value for logs in by_series.values() for value in logs]
    groups, total = len(by_series), len(values)
    if groups < 3 or total <= groups:
        return None
    grand = statistics.fmean(values)
    means = {series: statistics.fmean(logs) for series, logs in by_series.items()}
    between_square = sum(
        len(logs) * (means[series] - grand) ** 2 for series, logs in by_series.items()
    ) / (groups - 1)
    within_square = sum(
        (value - means[series]) ** 2
        for series, logs in by_series.items()
        for value in logs
    ) / (total - groups)
    typical_size = (
        total - sum(len(logs) ** 2 for logs in by_series.values()) / total
    ) / (groups - 1)
    between = max(0.0, (between_square - within_square) / typical_size)
    icc = between / (between + within_square) if between + within_square > 0 else 0.0
    z = statistics.NormalDist().inv_cdf(0.975) + statistics.NormalDist().inv_cdf(power)
    effect = -math.log(1 - change)
    spread = statistics.stdev(values)
    independent = (z * spread / effect) ** 2
    per_series = total / groups
    design = 1 + (per_series - 1) * icc
    series_spread = statistics.stdev(means.values())
    return {
        "change": change,
        "power": power,
        "targets": total,
        "series": groups,
        "sdLogRatio": spread,
        "intraclassCorrelation": icc,
        "meanTargetsPerSeries": per_series,
        "designEffect": design,
        "independentTargetsNeeded": independent,
        "clusteredTargetsNeeded": independent * design,
        "sdSeriesMeanLogRatio": series_spread,
        "seriesNeeded": (z * series_spread / effect) ** 2,
    }


def markdown_table(summary: dict[str, Any]) -> str:
    lines = [
        "| arm | targets | mean normalized CRPS | difference vs persistence "
        "(95% CI) | CRPS ratio vs persistence (95% CI) | beats persistence | "
        "80% coverage |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, stats in sorted(
        summary["arms"].items(), key=lambda item: item[1]["meanNormalizedCrps"]
    ):
        ci = stats["interval95"]
        difference = ci.get("meanNormalizedCrpsDifference", [math.nan, math.nan])
        ratio = ci.get("geometricMeanCrpsRatio", [math.nan, math.nan])
        lines.append(
            f"| {arm} | {stats['targets']} | {stats['meanNormalizedCrps']:.3f} | "
            f"{stats['meanNormalizedCrpsDifference']:+.3f} "
            f"({difference[0]:+.3f}, {difference[1]:+.3f}) | "
            f"{stats['geometricMeanCrpsRatio']:.3f} "
            f"({ratio[0]:.3f}, {ratio[1]:.3f}) | "
            f"{stats['shareBeatingBaseline']:.0%} | {stats['coverage80']:.0%} |"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument(
        "--cache-dir",
        type=pathlib.Path,
        default=pathlib.Path.home() / ".cache" / "thesis-stanli-backtest",
    )
    parser.add_argument("--grid-start", default="2024-06-01")
    parser.add_argument("--grid-end", default="2026-11-01")
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--max-targets", type=int, default=24)
    parser.add_argument("--series", help="Comma-separated FRED ids to run alone.")
    parser.add_argument(
        "--stan-models",
        default=",".join(STAN_PROGRAMS),
        help="Comma-separated built-in stanli programs.",
    )
    parser.add_argument("--bootstrap-draws", type=int, default=2000)
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Score every program's last 24 cutoffs per target and add the "
        "stanli-selected arms (72 more fits per target).",
    )
    parser.add_argument("--jobs", type=int, default=1, help="Series run in parallel.")
    args = parser.parse_args(argv)

    import resolve_pending

    specs = adapter_series(resolve_pending.ALFRED_ADAPTERS)
    if args.series:
        wanted = {value.strip() for value in args.series.split(",")}
        specs = [spec for spec in specs if spec.fred in wanted]
    stan_models = [model for model in args.stan_models.split(",") if model]
    dates = vintage_grid(
        dt.date.fromisoformat(args.grid_start), dt.date.fromisoformat(args.grid_end)
    )

    failures: dict[str, str] = {}
    outcomes: dict[str, list[dict]] = {}
    started = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(
                run_series,
                spec,
                dates=dates,
                cache_dir=args.cache_dir,
                window=args.window,
                max_targets=args.max_targets,
                stan_models=stan_models,
                walk_forward=args.walk_forward,
            ): spec
            for spec in specs
        }
        for number, future in enumerate(
            concurrent.futures.as_completed(futures), start=1
        ):
            spec = futures[future]
            try:
                outcomes[spec.key], target_count = future.result()
                print(
                    f"[{number}/{len(specs)}] {spec.key}: {target_count} targets "
                    f"({time.perf_counter() - started:.0f}s)",
                    file=sys.stderr,
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - record and keep going
                failures[spec.key] = f"{type(exc).__name__}: {exc}"
                print(f"[{number}/{len(specs)}] {spec.key}: {exc}", file=sys.stderr)
    # Series order, not completion order, so the output does not depend on --jobs.
    rows = [row for spec in specs for row in outcomes.get(spec.key, [])]

    summary = summarize(rows, draws=args.bootstrap_draws)
    summary.update(
        {
            "config": {
                "gridStart": args.grid_start,
                "gridEnd": args.grid_end,
                "vintageDates": len(dates),
                "window": args.window,
                "maxTargets": args.max_targets,
                "stanModels": stan_models,
                "bootstrapDraws": args.bootstrap_draws,
                "stanliChains": 4,
                "walkForward": args.walk_forward,
            },
            "series": [{"key": spec.key, "stems": list(spec.stems)} for spec in specs],
            "failures": failures,
            "perSeriesCrpsRatio": per_series(rows),
            "byTransform": by_transform(rows),
            "leaveOneSeriesOut": leave_one_series_out(rows),
            "selectionCounts": selection_counts(rows),
            "selectionCountsWithoutSkip": selection_counts(
                [
                    {**row, "arm": "stanli-selected"}
                    for row in rows
                    if row["arm"] == "stanli-selected-noskip"
                ]
            ),
            "pairedComparisons": paired_comparisons(rows, draws=args.bootstrap_draws),
            "versusPersistenceLadder": compare(
                rows, baseline="persistence-ladder", draws=args.bootstrap_draws
            ),
            "warningSplit": warning_split(rows),
            "byPeriodHalf": by_period_half(rows),
            "windowsFrom": windows_starting_from(rows),
            "ablationPower": {arm: ablation_power(rows, arm) for arm in POWER_ARMS},
        }
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    table = markdown_table(summary)
    (args.output_dir / "table.md").write_text(table + "\n")
    write_rows(args.output_dir / "targets.jsonl.gz", rows)
    print(table)
    return 0


def write_rows(path: pathlib.Path, rows: Sequence[dict]) -> None:
    """Write one JSON row per line, gzipped with no name or time in the header,
    so the same rows always give the same bytes."""

    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle,
    ):
        for row in rows:
            handle.write((json.dumps(row, sort_keys=True) + "\n").encode())


if __name__ == "__main__":
    raise SystemExit(main())
