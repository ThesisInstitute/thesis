"""Sensitivity only: #381's comparisons with a recalibrated Kalshi baseline.

#381's frozen results are read, never rewritten. For each scored pair, a map
fitted on this study's binary markets at the matching fixed horizon, using only
markets released before the pair's horizon instant, is applied to Kalshi's
repaired ladder; Thesis's brackets are unchanged. #381's own ``build_pairs``
and ``summarize_pairs`` then recompute every summary.
"""

from __future__ import annotations

import math
from typing import Any

from kalshi_compare import kalshi, scoring
from kalshi_compare import pipeline as compare_pipeline

from . import calibration

LEAD_EDGES = (math.sqrt(30 * 7), math.sqrt(7 * 1))  # 14.5 and 2.65 days


def horizon_class(score: dict) -> str:
    """The study's fixed horizon whose maps a #381 pair uses."""
    if score["horizon"] == "release_minus_7d":
        return "anchor_7d"
    if score["horizon"] == "release_minus_1d":
        return "anchor_1d"
    lead = (
        kalshi.to_ts(score["releaseAt"]) - kalshi.to_ts(score["horizonAt"])
    ) / 86_400
    if lead >= LEAD_EDGES[0]:
        return "anchor_30d"
    if lead >= LEAD_EDGES[1]:
        return "anchor_7d"
    return "anchor_1d"


def training_table(binary_rows: list[dict], horizon: str, before: int) -> dict:
    return calibration.aggregate(
        (r["p"], r["yOfficial"])
        for r in binary_rows
        if r["horizon"] == horizon and r["hasOfficial"] and r["releaseTs"] < before
    )


def recalibrated_score(score: dict, mapping: calibration.Map, floor: float) -> dict:
    """A #381 score row with Kalshi's ladder passed through ``mapping``."""
    ladder = calibration.recalibrated_ladder(score["kalshiRepairedPrices"], mapping)
    brackets = scoring.ladder_to_brackets(ladder)
    realized = score["realizedBracket"]
    # A ladder market is YES exactly when its strike lies below the realized
    # bracket, under either > or >= wording.
    outcomes = [index < realized for index in range(len(ladder))]
    floored = scoring.floor_renormalize(brackets, floor)
    return {
        **score,
        "kalshiBrackets": brackets,
        "kalshiRecalibratedPrices": ladder,
        "kalshiRealizedProb": brackets[realized],
        "kalshiFloored": brackets[realized] < floor,
        "kalshiLog": scoring.log_score(floored, realized),
        "kalshiBrier": scoring.brier_score(brackets, realized),
        "kalshiLadderBrier": (
            None
            if score.get("kalshiLadderBrier") is None
            else scoring.ladder_brier(ladder, outcomes)
        ),
    }


STATEMENT_SPECS = (
    "primary",
    "liquid_markets_only",
    "last_trade_price",
    "literal_cdf_reading",
    "floor_0.01",
)
STATEMENT_SUBSETS = (
    "pooled",
    "excludingKalshiFloorHits",
    "originalSeries",
    "sameEventsAsRegistration",
)


# The numbers #381's report quotes in its Summary
# (~/reviews/thesis-vs-kalshi-2026-10/results/REPORT.md), as quoted.
QUOTED_IN_381_SUMMARY = {
    ("primary", "at_registration", "pooled", "deltaLog"): "+0.61 [-0.07, +1.66]",
    ("primary", "at_registration", "pooled", "deltaBrier"): "+0.04 [-0.08, +0.21]",
    ("primary", "at_registration", "excludingKalshiFloorHits", "deltaLog"): "+0.01",
    (
        "liquid_markets_only",
        "at_registration",
        "pooled",
        "deltaLog",
    ): "+0.05 [-0.03, +0.17]",
    ("primary", "release_minus_7d", "pooled", "deltaLog"): "-0.17 [-0.40, +0.05]",
    (
        "primary",
        "release_minus_7d",
        "originalSeries",
        "deltaLog",
    ): "-0.28 [-0.54, -0.02]",
    ("primary", "release_minus_1d", "pooled", "deltaLog"): "-0.12 [-0.46, +0.32]",
    ("primary", "release_minus_1d", "pooled", "deltaBrier"): "-0.02 [-0.09, +0.05]",
    (
        "primary",
        "release_minus_1d",
        "excludingKalshiFloorHits",
        "deltaLog",
    ): "-0.35 [-0.59, -0.12]",
    (
        "primary",
        "release_minus_1d",
        "sameEventsAsRegistration",
        "deltaLog",
    ): "-0.27 [-0.53, -0.01]",
    (
        "liquid_markets_only",
        "release_minus_1d",
        "pooled",
        "deltaLog",
    ): "-0.35 [-0.59, -0.11]",
    (
        "liquid_markets_only",
        "release_minus_1d",
        "pooled",
        "deltaBrier",
    ): "-0.07 [-0.14, +0.01]",
    (
        "last_trade_price",
        "release_minus_1d",
        "pooled",
        "deltaLog",
    ): "+0.15 [-0.30, +0.65]",
    (
        "last_trade_price",
        "release_minus_1d",
        "excludingKalshiFloorHits",
        "deltaLog",
    ): "-0.36 [-0.62, -0.09]",
}
SPEC_WORDS = {
    "primary": "midpoint prices",
    "liquid_markets_only": "books quoted within 20 cents",
    "last_trade_price": "last traded prices",
    "literal_cdf_reading": "the literal CDF reading",
    "floor_0.01": "a 0.01 log-score floor",
}
HORIZON_WORDS = {
    "at_registration": "at Thesis's registration time",
    "release_minus_7d": "seven days before release",
    "release_minus_1d": "one day before release",
}
SUBSET_WORDS = {
    "pooled": "all events",
    "excludingKalshiFloorHits": (
        "events where Kalshi did not price the outcome at the floor"
    ),
    "originalSeries": "the eight original series",
    "sameEventsAsRegistration": "the events also scored at registration",
}
METRIC_WORDS = {"deltaLog": "log-score difference", "deltaBrier": "Brier difference"}


def signed(x: float) -> str:
    return f"{x:+.3f}"


def interval(ci) -> str:
    return f"[{signed(ci[0])}, {signed(ci[1])}]"


def describe(row: dict) -> str:
    """One #381 statement and how recalibration moves it, in words."""
    key = (row["spec"], row["horizon"], row["subset"], row["metric"])
    what = (
        f"the {METRIC_WORDS[row['metric']]} {HORIZON_WORDS[row['horizon']]} "
        f"({SPEC_WORDS[row['spec']]}, {SUBSET_WORDS[row['subset']]}, "
        f"{row['nBefore']} events)"
    )
    before = f"{signed(row['meanBefore'])} {interval(row['ciBefore'])}"
    after = f"{signed(row['meanAfter'])} {interval(row['ciAfter'])}"
    how = []
    if row.get("signFlips"):
        how.append("its mean changes sign")
    if row.get("zeroInclusionChanges"):
        how.append(
            "its interval now includes zero"
            if includes_zero(row["ciAfter"])
            else "its interval no longer includes zero"
        )
    quoted = " (quoted in #381's Summary)" if key in QUOTED_IN_381_SUMMARY else ""
    return f"{what}{quoted} moves from {before} to {after}: {' and '.join(how)}"


def statements(summary: dict) -> list[dict]:
    """Every pooled number of the kind #381's Summary quotes, flattened."""
    out = []
    head = summary["thesis_headline"]
    for spec in STATEMENT_SPECS:
        for horizon in compare_pipeline.HORIZONS:
            block = head[spec][horizon]
            for subset in STATEMENT_SUBSETS:
                pooled = block["pooled"] if subset == "pooled" else block[subset]
                for metric in ("deltaLog", "deltaBrier"):
                    value = pooled.get(metric)
                    if not value:
                        continue
                    out.append(
                        {
                            "spec": spec,
                            "horizon": horizon,
                            "subset": subset,
                            "metric": metric,
                            "n": value["n"],
                            "mean": value["mean"],
                            "ci95ReleaseClustered": value["ci95ReleaseClustered"],
                        }
                    )
    return out


def includes_zero(interval) -> bool:
    return interval[0] <= 0 <= interval[1]


def compare(original: list[dict], recalibrated: list[dict]) -> list[dict]:
    index = {
        (s["spec"], s["horizon"], s["subset"], s["metric"]): s for s in recalibrated
    }
    rows = []
    for before in original:
        key = (before["spec"], before["horizon"], before["subset"], before["metric"])
        after = index.get(key)
        row = {
            **{k: before[k] for k in ("spec", "horizon", "subset", "metric")},
            "nBefore": before["n"],
            "meanBefore": before["mean"],
            "ciBefore": before["ci95ReleaseClustered"],
        }
        if after is None:
            row["change"] = "missing after recalibration"
        else:
            row.update(
                {
                    "nAfter": after["n"],
                    "meanAfter": after["mean"],
                    "ciAfter": after["ci95ReleaseClustered"],
                }
            )
            flips = (before["mean"] > 0) != (after["mean"] > 0)
            zero_changes = includes_zero(
                before["ci95ReleaseClustered"]
            ) != includes_zero(after["ci95ReleaseClustered"])
            row["signFlips"] = flips
            row["zeroInclusionChanges"] = zero_changes
            row["changes"] = flips or zero_changes
        rows.append(row)
    return rows


def run(results_381: dict, binary_rows: list[dict]) -> dict[str, Any]:
    """Recompute #381's summaries with logistic and with beta recalibration."""
    scores = results_381["scores"]
    # Differential: #381's own code on its frozen scores reproduces its summary.
    rebuilt = compare_pipeline.summarize_pairs(compare_pipeline.build_pairs(scores))
    reproduces = _jsonable(rebuilt) == _jsonable(results_381["summary"])
    original = statements(results_381["summary"])
    out: dict[str, Any] = {"reproducesFrozenSummary": reproduces, "models": {}}
    maps_cache: dict[tuple, calibration.Map] = {}
    for model, fitter in calibration.FITTERS.items():
        new_scores, maps_used = [], []
        for score in scores:
            horizon = horizon_class(score)
            before = kalshi.to_ts(score["horizonAt"])
            key = (model, horizon, before)
            if key not in maps_cache:
                maps_cache[key] = fitter(training_table(binary_rows, horizon, before))
            mapping = maps_cache[key]
            floor = compare_pipeline.SENSITIVITY_SPECS[score["spec"]]["floor"]
            if score.get("kalshiLadderBrier") is None:
                # Exact-value markets (secondary, never pooled) keep their prices.
                new_scores.append(score)
            else:
                new_scores.append(recalibrated_score(score, mapping, floor))
            maps_used.append(
                {
                    "eventKey": score["eventKey"],
                    "horizon": score["horizon"],
                    "spec": score["spec"],
                    "runId": score["runId"],
                    "mapHorizon": horizon,
                    "trainedBefore": score["horizonAt"],
                    "params": mapping.params,
                }
            )
        summary = compare_pipeline.summarize_pairs(
            compare_pipeline.build_pairs(new_scores)
        )
        comparison = compare(original, statements(summary))
        out["models"][model] = {
            "summary": summary,
            "comparison": comparison,
            "changes": [row for row in comparison if row.get("changes")],
            "maps": maps_used,
        }
    return out


def _jsonable(value):
    import json

    return json.loads(json.dumps(value, default=str))
