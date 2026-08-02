"""Mechanical baselines for the bake-off (PREREG-AMENDMENT-1 §D). No LLM.

Two baselines per unit, both computed only from the unit's frozen pre-origin
history (no lookahead):

  persistence — point = last observed value; 80% interval = point + empirical
      [10th, 90th] percentiles of h-step changes over the history, where h is
      the unit's forecast horizon in months.
  drift — point = last value + h × (mean 1-step change); same interval method,
      centred on the drift point.

Both are scored through the identical CRPS machinery as the model runs
(`scoring.score_forecast`), so the comparison is like-for-like. If a unit's
history is too short to give at least 5 h-step changes, the baseline is
reported as null with the reason — not silently narrowed.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import scoring as S  # noqa: E402


def month_index(iso: str) -> int:
    y, m = int(iso[:4]), int(iso[5:7])
    return y * 12 + (m - 1)


def h_step_changes(values: list[float], h: int) -> list[float]:
    return [values[i + h] - values[i] for i in range(len(values) - h)]


def percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile (same convention as statistics.quantiles n=10)."""
    if not sorted_vals:
        raise ValueError("empty")
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def baseline_forecasts(unit: dict) -> dict:
    hist = unit.get("history") or []
    truth = unit.get("truth", {}).get("first_print_value")
    out: dict = {"unit_id": unit["unit_id"], "truth": truth}
    if not hist or truth is None:
        out["error"] = "missing history or truth"
        return out

    values = [r["value"] for r in hist]
    last = values[-1]
    h = month_index(unit["target_month"]) - month_index(hist[-1]["month"])
    out["horizon_months"] = h

    changes = h_step_changes(values, h)
    if len(changes) < 5:
        out["error"] = f"only {len(changes)} h-step changes in history (h={h}); need >=5"
        return out
    sc = sorted(changes)
    lo_off, hi_off = percentile(sc, 0.10), percentile(sc, 0.90)

    one_step = h_step_changes(values, 1)
    drift_point = last + h * st.mean(one_step)

    for name, point in (("persistence", last), ("drift", drift_point)):
        ci_low, ci_high = point + lo_off, point + hi_off
        if ci_high <= ci_low:  # degenerate flat history
            out[name] = {"error": "degenerate interval"}
            continue
        scores = S.score_forecast(point, ci_low, ci_high, truth)
        out[name] = {
            "point": point, "ci_low": ci_low, "ci_high": ci_high,
            "crps": scores["crps"], "pit": scores["pit"],
            "covered80": scores["covered80"], "abs_error": scores["abs_error"],
        }
    return out


def main() -> None:
    results = []
    for path in ("ground_truth.json", "ground_truth_extra.json"):
        for unit in json.loads((HERE / path).read_text()):
            r = baseline_forecasts(unit)
            r["corpus"] = "A" if path == "ground_truth.json" else "B"
            results.append(r)
    out_path = HERE / "baselines.json"
    out_path.write_text(json.dumps(results, indent=2))

    print(f"{'unit':22s} {'h':>3s} {'persist CRPS':>13s} {'drift CRPS':>11s} {'truth':>12s}")
    for r in results:
        if r.get("error"):
            print(f"{r['unit_id']:22s}  ERROR: {r['error']}")
            continue
        p, d = r["persistence"], r["drift"]
        pc = f"{p['crps']:,.1f}" if "crps" in p else "n/a"
        dc = f"{d['crps']:,.1f}" if "crps" in d else "n/a"
        print(f"{r['unit_id']:22s} {r['horizon_months']:3d} {pc:>13s} {dc:>11s} {r['truth']:>12,.1f}")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
