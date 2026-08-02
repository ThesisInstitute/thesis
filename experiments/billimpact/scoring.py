"""CRPS + PIT scoring, ported line-by-line from the site's scoring module.

Source of truth: `site/src/data/prediction-distribution.ts`
  - buildNumericCdfFromInterval  (interval_anchor_v1)
  - scoreNumericCdfDistribution  (CRPS + probability integral transform)

The CDF construction is not re-implemented here: it is imported from the
existing Python port at `scripts/run_thesis_analyst.py:interval_distribution`,
so this module adds only the scorer. Nothing in the repo's scoring path is
modified. `pin_against_typescript.py` checks this port against the TypeScript
original on real sweep values.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_runner_module():
    """Import scripts/run_thesis_analyst.py without importing it as a package."""
    scripts_dir = REPO_ROOT / "scripts"
    # run_thesis_analyst.py imports its siblings (canonical_json) by bare name.
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    path = scripts_dir / "run_thesis_analyst.py"
    spec = importlib.util.spec_from_file_location("_thesis_analyst_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_thesis_analyst_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


_RUNNER = None


def interval_distribution(point: float, ci_low: float, ci_high: float) -> dict[str, Any]:
    """Build the house 201-point numeric_cdf_v1 from a point + 80% interval."""
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = _load_runner_module()
    return _RUNNER.interval_distribution(
        {"pointEstimate": point, "ciLow": ci_low, "ciHigh": ci_high}
    )


def _integrate_squared_linear(width: float, err_lo: float, err_hi: float) -> float:
    """Port of integrateSquaredLinear."""
    return (width * (err_lo**2 + err_lo * err_hi + err_hi**2)) / 3


def _linear_probability_at(value: float, lo: dict, hi: dict) -> float:
    """Port of linearProbabilityAt."""
    ratio = (value - lo["value"]) / (hi["value"] - lo["value"])
    return lo["probability"] + ratio * (hi["probability"] - lo["probability"])


def _coalesce(points: list[dict]) -> list[dict]:
    out: list[dict] = []
    for p in sorted(points, key=lambda q: (q["value"], q["probability"])):
        if out and abs(out[-1]["value"] - p["value"]) < 1e-12:
            out[-1]["probability"] = max(out[-1]["probability"], p["probability"])
        else:
            out.append(dict(p))
    return out


def _interpolate_cdf_probability(value: float, raw: list[dict]) -> float:
    knots = _coalesce(raw)
    if value <= knots[0]["value"]:
        return knots[0]["probability"]
    for i in range(1, len(knots)):
        prev, cur = knots[i - 1], knots[i]
        if value <= cur["value"]:
            width = cur["value"] - prev["value"]
            if width <= 0:
                return cur["probability"]
            ratio = (value - prev["value"]) / width
            return prev["probability"] + ratio * (cur["probability"] - prev["probability"])
    return knots[-1]["probability"]


def score_numeric_cdf(distribution: dict, observed: float) -> dict[str, float]:
    """Port of scoreNumericCdfDistribution -> {crps, pit}."""
    points = distribution["points"]
    crps = 0.0
    for i in range(1, len(points)):
        prev, cur = points[i - 1], points[i]
        if prev["value"] < observed < cur["value"]:
            p_at = _linear_probability_at(observed, prev, cur)
            crps += _integrate_squared_linear(
                observed - prev["value"], prev["probability"], p_at
            )
            crps += _integrate_squared_linear(
                cur["value"] - observed, p_at - 1, cur["probability"] - 1
            )
            continue
        indicator = 0 if cur["value"] <= observed else 1
        crps += _integrate_squared_linear(
            cur["value"] - prev["value"],
            prev["probability"] - indicator,
            cur["probability"] - indicator,
        )

    lower, upper = points[0], points[-1]
    if observed < lower["value"]:
        crps += lower["value"] - observed
    if observed > upper["value"]:
        crps += observed - upper["value"]

    return {
        "crps": crps,
        "pit": _interpolate_cdf_probability(observed, points),
    }


def score_forecast(point: float, ci_low: float, ci_high: float, observed: float) -> dict[str, float]:
    """End-to-end: point + 80% interval -> house CDF -> CRPS + PIT."""
    dist = interval_distribution(point, ci_low, ci_high)
    out = score_numeric_cdf(dist, observed)
    out["covered80"] = 1.0 if ci_low <= observed <= ci_high else 0.0
    out["abs_error"] = abs(point - observed)
    out["pct_error"] = (point - observed) / observed if observed else float("nan")
    return out
