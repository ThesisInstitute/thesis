"""Mechanical baselines for the wave-2 units. No LLM, no network.

Same construction as `baselines.py` (persistence / drift points, 80% interval
from the empirical [10th, 90th] percentiles of h-step changes, scored through
`scoring.score_forecast`), with ONE deliberate difference, stated rather than
hidden: the horizon h is expressed in the series' native OBSERVATION steps.
`baselines.py` counts h in months, which is correct for the monthly corpus but
would treat the quarterly customs series' 2-quarter horizon as h=6 (six
QUARTERS of drift and 6-quarter change percentiles). Here:

  B235RC1Q027SBEA (quarterly): h = month gap / 3   (2018Q4: h=2; 2019Q2: h=4)
  B069RC1 (monthly):           h = month gap        (identical to baselines.py)

Reuses `baselines.h_step_changes` / `baselines.percentile` so the interval
convention cannot drift from the house baseline.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import baselines as B  # noqa: E402
import scoring as S  # noqa: E402

OBS_MONTHS = {"B235RC1Q027SBEA": 3, "B069RC1": 1}


def main() -> None:
    units = json.loads((HERE / "ground_truth_wave2.json").read_text())
    results = []
    for unit in units:
        hist = unit.get("history") or []
        truth = unit.get("truth", {}).get("first_print_value")
        rec: dict = {"unit_id": unit["unit_id"], "truth": truth, "corpus": "B2"}
        step = OBS_MONTHS[unit["series_id"]]
        gap = B.month_index(unit["target_month"]) - B.month_index(hist[-1]["month"])
        assert gap % step == 0, f"{unit['unit_id']}: {gap}-month gap not a multiple of obs step {step}"
        h = gap // step
        rec["horizon_months"] = gap
        rec["horizon_obs_steps"] = h

        values = [r["value"] for r in hist]
        last = values[-1]
        changes = B.h_step_changes(values, h)
        if len(changes) < 5:
            rec["error"] = f"only {len(changes)} h-step changes (h={h} obs); need >=5"
            results.append(rec)
            continue
        sc = sorted(changes)
        lo_off, hi_off = B.percentile(sc, 0.10), B.percentile(sc, 0.90)
        one_step = B.h_step_changes(values, 1)
        drift_point = last + h * st.mean(one_step)

        for name, point in (("persistence", last), ("drift", drift_point)):
            ci_low, ci_high = point + lo_off, point + hi_off
            if ci_high <= ci_low:
                rec[name] = {"error": "degenerate interval"}
                continue
            scores = S.score_forecast(point, ci_low, ci_high, truth)
            rec[name] = {
                "point": point, "ci_low": ci_low, "ci_high": ci_high,
                "crps": scores["crps"], "pit": scores["pit"],
                "covered80": scores["covered80"], "abs_error": scores["abs_error"],
            }
        results.append(rec)

    out = HERE / "baselines_wave2.json"
    out.write_text(json.dumps(results, indent=2) + "\n")

    sd = {u["unit_id"]: st.pstdev([r["value"] for r in u["history"]]) for u in units}
    print(f"{'unit':24s} {'h(obs)':>6s} {'persist CRPS':>13s} {'nCRPS':>7s} {'drift CRPS':>11s} {'nCRPS':>7s} {'truth':>9s}")
    for r in results:
        if r.get("error"):
            print(f"{r['unit_id']:24s}  ERROR: {r['error']}")
            continue
        p, d = r["persistence"], r["drift"]
        s = sd[r["unit_id"]]
        print(f"{r['unit_id']:24s} {r['horizon_obs_steps']:>6d} {p['crps']:>13.2f} {p['crps']/s:>7.3f} "
              f"{d['crps']:>11.2f} {d['crps']/s:>7.3f} {r['truth']:>9.1f}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
