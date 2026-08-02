"""Amendment-3 runner: period-moved FPUC dose-response. Design frozen in
PREREG-AMENDMENT-3.md. The future arm is never scored for accuracy — no truth
exists; the measurand is dose-response."""
from __future__ import annotations

import concurrent.futures as cf
import datetime
import json
import re
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
import extended_harness as X  # noqa: E402
from fetch_ground_truth import series_at_vintage  # noqa: E402

MODELS = ["claude-sonnet-5", "claude-opus-5", "claude-fable-5"]
DOSES = ["third", "actual", "tripled"]
ELICS = ["point_ci_json", "derivation_json"]
REPS = 5

DERIVATION_INSTRUCTION = """Derive the forecast mechanically before you state it:
1. RATE: state the weekly supplement amount in dollars exactly as written in
   the bill text supplied.
2. VOLUME: estimate the average weekly number of claimants (in millions) who
   would receive the supplement during the target month, from the history.
3. MECHANICAL CONTRIBUTION: compute the supplement's contribution to the
   target month's value of this series, in the same units as the history
   (note the series is a seasonally adjusted annual rate: a weekly payment
   flow appears at roughly 52 x weekly total).
4. BASELINE: the target month's value with no supplement.
5. point = baseline + contribution, with an 80% central credible interval.

Respond with ONLY a JSON object, no prose before or after:
{"supplement_weekly_rate_usd": <number>, "est_weekly_claimants_millions": <number>, "mechanical_contribution": <number>, "baseline_no_policy": <number>, "point": <number>, "ci_low": <number>, "ci_high": <number>, "rationale": "<one sentence>"}"""

FUTURE_DATE_SUBS = [
    # move the three operative dates of s203 into the 2026 window
    ("March 14, 2021", "December 26, 2026"),
    ("December 26, 2020", "September 4, 2026"),
    ("March 14, 2021.", "December 26, 2026."),
]


def build_future_unit() -> dict:
    today = datetime.date.today().isoformat()
    obs = series_at_vintage("W825RC1", today)
    keys = sorted(obs)[-60:]
    return {
        "unit_id": "fpuc_future.us.2026-11",
        "policy_event": X.FPUC_EVENT,
        "state": "US",
        "series_id": "W825RC1",
        "target_month": "2026-11-01",
        "origin_vintage": today,
        "history": [{"month": k, "value": obs[k]} for k in keys],
        "truth": {"first_print_value": None},
    }


def build_context_a3(period: str, dose: str) -> tuple[str, dict]:
    ev = X.PROVISIONS_B[X.FPUC_EVENT]
    text = "\n\n".join(ev["operative"].values())
    meta = {"period": period, "dose": dose, "substitutions": 0}
    if period == "future2026":
        for old, new in FUTURE_DATE_SUBS:
            text, k = re.subn(re.escape(old), new, text)
            meta["substitutions"] += k
    dosed, k = X.apply_dollar_magnitude(text, dose)
    meta["substitutions"] += k
    if period == "future2026":
        header = ("POLICY CONTEXT (text of a bill now pending before Congress; "
                  "assume it is enacted and in force through the target month):")
    else:
        header = f"POLICY CONTEXT (verbatim statutory text, {ev['law']}):"
    return header + "\n\n" + dosed, meta


def run_one(unit: dict, period: str, dose: str, model: str, elic: str) -> dict:
    ctx, meta = build_context_a3(period, dose)
    base = X.TASK_B.format(
        series_desc=X.SERIES_DESC["W825RC1"],
        series_id="W825RC1",
        target_label=H.month_label(unit["target_month"]),
        origin_label=H.month_label(unit["origin_vintage"]),
        history_block=X.format_history_b(unit["history"]),
    )
    instr = DERIVATION_INSTRUCTION if elic == "derivation_json" else H.ELICITATION_INSTRUCTIONS["point_ci_json"]
    prompt = "\n\n".join([base, ctx, instr])
    rec = {
        "unit_id": unit["unit_id"], "period": period,
        "config": {"dose": dose, "model": model, "elicitation": elic},
        "context_meta": meta, "prompt_chars": len(prompt),
        "parser_version": H.PARSER_VERSION,
    }
    res = H.call_model(prompt, model, max_tokens=6000)
    rec["calls"] = [{"ok": res.ok, "completion_tokens": res.completion_tokens,
                     "max_tokens": 6000, "error": res.error}]
    if not res.ok:
        rec["error"] = res.error
        return rec
    rec["final_text"] = res.text
    anchor = H.history_anchor(unit)
    obj = H._last_json_object(res.text)
    if elic == "derivation_json" and obj is not None and "point" in obj:
        fc = {}
        for k in ("supplement_weekly_rate_usd", "est_weekly_claimants_millions",
                  "mechanical_contribution", "baseline_no_policy", "point",
                  "ci_low", "ci_high"):
            v = H._to_float(obj.get(k))
            if v is not None:
                fc[k] = v
        if {"point", "ci_low", "ci_high"} <= set(fc):
            fc["parse_mode"] = "derivation_json"
            rec["forecast"] = fc
            return rec
    rec["forecast"] = H.parse_forecast(res.text, "point_ci_json", anchor)
    return rec


def main() -> None:
    retro = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth_extra.json").read_text())}["fpuc300.us.2021-01"]
    future = build_future_unit()
    (HERE / "future_unit_2026.json").write_text(json.dumps(future, indent=2))
    print(f"future history: {future['history'][0]['month'][:7]} .. "
          f"{future['history'][-1]['month'][:7]} last={future['history'][-1]['value']}")

    plan = []
    for period, unit in (("retro2021", retro), ("future2026", future)):
        for dose in DOSES:
            for model in MODELS:
                for elic in ELICS:
                    for rep in range(1, REPS + 1):
                        plan.append((unit, period, dose, model, elic, rep))
    out = (HERE / "runs_amend3.jsonl").open("a")
    lock = threading.Lock()
    n = [0]
    t0 = time.time()

    def work(item):
        unit, period, dose, model, elic, rep = item
        rec = run_one(unit, period, dose, model, elic)
        rec["rep"] = rep
        rec["cell_key"] = "|".join(["A3", period, dose, model, elic, str(rep)])
        with lock:
            out.write(json.dumps(rec) + "\n")
            out.flush()
            n[0] += 1
            if n[0] % 40 == 0:
                print(f"[{n[0]}/{len(plan)}] {n[0]/(time.time()-t0):.1f}/s", flush=True)

    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(work, plan))
    out.close()
    print(f"DONE {n[0]} runs in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
