"""Versioned exact CDF scoring independent of storage, website and adapters."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .contracts import NumericCdf

SCORING_VERSION = "piecewise_linear_crps_v1"


def round_distribution_number(value: float) -> float:
    return float(format(value, ".12g")) + 0.0


@dataclass(frozen=True)
class NumericCdfScore:
    crps: float
    probability_integral_transform: float

    @property
    def pit(self) -> float:
        return self.probability_integral_transform

    def as_json(self) -> dict[str, float]:
        return {"crps": self.crps, "probabilityIntegralTransform": self.pit}


def _points(distribution: NumericCdf | Mapping[str, Any]) -> list[tuple[float, float]]:
    raw = (
        distribution.model_dump(mode="json", by_alias=True)
        if isinstance(distribution, NumericCdf)
        else distribution
    )
    points = [(p["value"], p["probability"]) for p in raw["points"]]
    if len(points) < 2 or raw.get("pointCount") != len(points):
        raise ValueError("Malformed numeric CDF point count")
    for index, (value, probability) in enumerate(points):
        if (
            type(value) not in (int, float)
            or type(probability) not in (int, float)
            or not math.isfinite(value)
            or not math.isfinite(probability)
        ):
            raise ValueError("Malformed numeric CDF non-finite coordinate")
        if not -1e-9 <= probability <= 1 + 1e-9:
            raise ValueError("Malformed numeric CDF probability")
        if index and (
            value <= points[index - 1][0] or probability < points[index - 1][1]
        ):
            raise ValueError("Malformed numeric CDF non-monotone coordinates")
    if abs(points[0][1]) > 1e-9 or abs(points[-1][1] - 1) > 1e-9:
        raise ValueError("Malformed numeric CDF endpoints")
    return points


def _coalesce(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for x, p in sorted(points):
        if result and abs(result[-1][0] - x) < 1e-12:
            result[-1] = (result[-1][0], max(result[-1][1], p))
        else:
            result.append((x, p))
    return result


def _interpolate(value: float, raw: Sequence[tuple[float, float]]) -> float:
    points = _coalesce(raw)
    if value <= points[0][0]:
        return points[0][1]
    for (x0, p0), (x1, p1) in zip(points, points[1:]):
        if value <= x1:
            return p0 + (value - x0) / (x1 - x0) * (p1 - p0)
    return points[-1][1]


def _integral(width: float, left: float, right: float) -> float:
    return width * (left**2 + left * right + right**2) / 3


def score_numeric_cdf_distribution(
    distribution: NumericCdf | Mapping[str, Any], observed_value: float
) -> NumericCdfScore:
    """Legacy-compatible integrator; native ingestion separately requires 201 points."""
    points = _points(distribution)
    if type(observed_value) not in (int, float) or not math.isfinite(observed_value):
        raise ValueError("observation must be finite")
    crps = 0.0
    for (x0, p0), (x1, p1) in zip(points, points[1:]):
        if x0 < observed_value < x1:
            py = p0 + (observed_value - x0) / (x1 - x0) * (p1 - p0)
            crps += _integral(observed_value - x0, p0, py)
            crps += _integral(x1 - observed_value, py - 1, p1 - 1)
        else:
            indicator = 0 if x1 <= observed_value else 1
            crps += _integral(x1 - x0, p0 - indicator, p1 - indicator)
    if observed_value < points[0][0]:
        crps += points[0][0] - observed_value
    if observed_value > points[-1][0]:
        crps += observed_value - points[-1][0]
    pit = _interpolate(observed_value, points)
    if not math.isfinite(crps) or not math.isfinite(pit):
        raise ValueError("score exceeds finite numeric range")
    return NumericCdfScore(
        round_distribution_number(crps), round_distribution_number(pit)
    )


score_distribution = score_numeric_cdf_distribution


def build_interval_distribution(
    point_estimate: float, ci_low: float, ci_high: float
) -> NumericCdf:
    """The preserved interval_anchor_v1 transform for new baseline submissions."""
    if not all(
        type(x) in (int, float) and math.isfinite(x)
        for x in (point_estimate, ci_low, ci_high)
    ):
        raise ValueError("interval coordinates must be finite")
    if not ci_low <= point_estimate <= ci_high:
        raise ValueError("interval must contain point estimate")
    lower_spread = max(abs(point_estimate - ci_low), 1e-9)
    upper_spread = max(abs(ci_high - point_estimate), 1e-9)
    lower, upper = ci_low - lower_spread * 1.5, ci_high + upper_spread * 1.5
    if not math.isfinite(lower) or not math.isfinite(upper):
        lower, upper = point_estimate - 1, point_estimate + 1
    if upper <= lower:
        spread = max(abs(point_estimate), 1) * 0.1
        lower, upper = point_estimate - spread, point_estimate + spread
    knots = [
        (lower, 0.0),
        (ci_low, 0.1),
        (point_estimate, 0.5),
        (ci_high, 0.9),
        (upper, 1.0),
    ]
    points = []
    for index in range(201):
        value = upper if index == 200 else lower + (upper - lower) / 200 * index
        points.append(
            {
                "value": round_distribution_number(value),
                "probability": round_distribution_number(_interpolate(value, knots)),
            }
        )
    return NumericCdf.model_validate_json(
        json.dumps(
            {
                "format": "numeric_cdf_v1",
                "pointCount": 201,
                "support": {
                    "lower": round_distribution_number(lower),
                    "upper": round_distribution_number(upper),
                },
                "points": points,
                "summary": {
                    "pointEstimate": point_estimate + 0.0,
                    "median": point_estimate + 0.0,
                    "interval80": {"lower": ci_low + 0.0, "upper": ci_high + 0.0},
                },
                "provenance": "interval_seeded",
                "transformVersion": "interval_anchor_v1",
            }
        )
    )
