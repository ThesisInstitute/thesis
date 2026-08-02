"""Recompute the hero figure's dose-response medians from raw run records.

Reads only frozen run files (read-only). For each (arm, model, elicitation,
dose) cell: median of the parsed `forecast.point` across reps, with n.

Arms:
  named    = runs_amend3.jsonl,  period == "retro2021"  (statute named in header)
  redacted = runs_deconfound.jsonl, period == "retro2021_unnamed"
  future   = runs_amend3.jsonl,  period == "future2026" (no realized trajectory)

Doses: third=$100/wk, actual=$300/wk, tripled=$900/wk (FPUC supplement).
Series: W825RC1 (UI transfer receipts, $B SAAR). Also prints the retro unit's
realized first print from ground_truth_extra.json.

Run from experiments/billimpact/:
  python3 <path-to>/recompute_hero_medians.py
"""
import json
import statistics
from pathlib import Path

HERE = Path("/Users/davidgringras26-27/career/thesis/experiments/billimpact")
DOSE_ORDER = ["third", "actual", "tripled"]
DOSE_USD = {"third": 100, "actual": 300, "tripled": 900}


def load(path, period_filter):
    cells = {}
    for line in (HERE / path).read_text().splitlines():
        r = json.loads(line)
        if r.get("period") != period_filter:
            continue
        fc = r.get("forecast") or {}
        pt = fc.get("point")
        if pt is None:
            continue
        c = r["config"]
        key = (c["model"], c["elicitation"], c["dose"])
        cells.setdefault(key, []).append(float(pt))
    return cells


def report(name, cells):
    print(f"\n== {name} ==")
    models = sorted({k[0] for k in cells})
    elics = sorted({k[1] for k in cells})
    for m in models:
        for e in elics:
            pts = []
            for d in DOSE_ORDER:
                v = cells.get((m, e, d))
                if v:
                    pts.append((d, statistics.median(v), len(v)))
            if not pts:
                continue
            meds = [p[1] for p in pts]
            mono = all(meds[i] < meds[i + 1] for i in range(len(meds) - 1))
            cellstr = "  ".join(f"${DOSE_USD[d]}/wk: {med:.1f} (n={n})" for d, med, n in pts)
            print(f"{m:16s} {e:16s} {cellstr}   strictly monotone: {mono}")


named = load("runs_amend3.jsonl", "retro2021")
future = load("runs_amend3.jsonl", "future2026")
redacted = load("runs_deconfound.jsonl", "retro2021_unnamed")

report("NAMED retro Jan-2021 (runs_amend3, period=retro2021)", named)
report("REDACTED retro Jan-2021 (runs_deconfound)", redacted)
report("FUTURE Nov-2026 (runs_amend3, period=future2026)", future)

gt = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth_extra.json").read_text())}
u = gt["fpuc300.us.2021-01"]
print("\nrealized first print, fpuc300.us.2021-01:", u["truth"]["first_print_value"])
print("last history value before target:", u["history"][-1])
