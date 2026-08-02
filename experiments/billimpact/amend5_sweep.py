"""A5 — generalisability of recall-anchoring + structure-rescue.

Statute 2: FRA s311 SNAP age caps, retro (real) vs future-moved (FY2027-29,
target Dec 2027). Dose = severe/actual/inert caps (existing machinery).
Parameter-type variation: FPUC window END DATE covering none/half/all of the
target month. opus-5 + fable-5 only; point_ci_json + decomposed_json; 5 reps.
Future arms unscored; measurand is dose-response. Committed before first run.
"""
from __future__ import annotations
import concurrent.futures as cf, datetime, json, re, sys, threading, time
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import harness as H, extended_harness as X, amend3_sweep as A3  # noqa: E402
from fetch_ground_truth import series_at_vintage  # noqa: E402

MODELS = ["claude-opus-5", "claude-fable-5"]
ELICS = ["point_ci_json", "decomposed_json"]
REPS = 5
SNAP_STATES = [("CA", "BRCA06M647NCEN"), ("OH", "BROH39M647NCEN")]

SNAP_FUTURE_DATES = [
    ("fiscal year 2023", "fiscal year 2027"),
    ("fiscal year 2024", "fiscal year 2028"),
    ("fiscal year 2025", "fiscal year 2029"),
]
FPUC_WINDOWS = {  # end-date dose: coverage of the Nov-2026 target month
    "none_of_month": [("December 26, 2026", "October 17, 2026")],
    "half_of_month": [("December 26, 2026", "November 14, 2026")],
    "full_month": [],
}

def snap_future_unit(state, sid):
    obs = series_at_vintage(sid, datetime.date.today().isoformat())
    keys = sorted(obs)[-60:]
    return {"unit_id": f"snapfut.{state.lower()}.2027-12", "state": state, "series_id": sid,
            "target_month": "2027-12-01", "origin_vintage": datetime.date.today().isoformat(),
            "history": [{"month": k, "value": obs[k]} for k in keys],
            "truth": {"first_print_value": None}}

def snap_ctx(period, dose, prov):
    text, meta = H.build_policy_context(prov, "operative_only", dose)
    if period == "future2027":
        for old, new in SNAP_FUTURE_DATES:
            text = text.replace(old, new)
        text = text.replace(
            "POLICY CONTEXT (verbatim statutory text, Fiscal Responsibility Act of 2023, Pub. L. 118-5, enacted 3 June 2023):",
            "POLICY CONTEXT (text of a bill now pending before Congress; assume it is enacted and its provisions apply as written):")
    return text, meta

def run_snap(unit, period, dose, model, elic, prov):
    ctx, meta = snap_ctx(period, dose, prov)
    base = H.BASE_TASK.format(state=unit["state"], state_name=H.STATE_NAMES[unit["state"]],
                              target_month_label=H.month_label(unit["target_month"]),
                              origin_label=H.month_label(unit["origin_vintage"]),
                              history_block=H.format_history(unit["history"]))
    instr = X.DECOMPOSED_INSTRUCTION if elic == "decomposed_json" else H.ELICITATION_INSTRUCTIONS["point_ci_json"]
    prompt = "\n\n".join([base, ctx, instr])
    res = H.call_model(prompt, model, max_tokens=6000)
    rec = {"unit_id": unit["unit_id"], "statute": "snap_agecaps", "period": period,
           "config": {"dose": dose, "model": model, "elicitation": elic},
           "context_meta": meta,
           "calls": [{"ok": res.ok, "completion_tokens": res.completion_tokens, "max_tokens": 6000, "error": res.error}]}
    if res.ok:
        rec["final_text"] = res.text
        rec["forecast"] = (X.parse_decomposed(res.text, H.history_anchor(unit))
                           if elic == "decomposed_json" else H.parse_forecast(res.text, "point_ci_json", H.history_anchor(unit)))
    else:
        rec["error"] = res.error
    return rec

def run_fpuc_window(unit, dose, model, elic):
    ctx, meta = A3.build_context_a3("future2026", "actual")
    for old, new in FPUC_WINDOWS[dose]:
        ctx = ctx.replace(old, new)
    meta = dict(meta); meta["window_dose"] = dose
    base = X.TASK_B.format(series_desc=X.SERIES_DESC["W825RC1"], series_id="W825RC1",
                           target_label=H.month_label(unit["target_month"]),
                           origin_label=H.month_label(unit["origin_vintage"]),
                           history_block=X.format_history_b(unit["history"]))
    instr = X.DECOMPOSED_INSTRUCTION if elic == "decomposed_json" else H.ELICITATION_INSTRUCTIONS["point_ci_json"]
    prompt = "\n\n".join([base, ctx, instr])
    res = H.call_model(prompt, model, max_tokens=6000)
    rec = {"unit_id": unit["unit_id"], "statute": "fpuc_window", "period": "future2026",
           "config": {"dose": dose, "model": model, "elicitation": elic}, "context_meta": meta,
           "calls": [{"ok": res.ok, "completion_tokens": res.completion_tokens, "max_tokens": 6000, "error": res.error}]}
    if res.ok:
        rec["final_text"] = res.text
        rec["forecast"] = (X.parse_decomposed(res.text, H.history_anchor(unit))
                           if elic == "decomposed_json" else H.parse_forecast(res.text, "point_ci_json", H.history_anchor(unit)))
    else:
        rec["error"] = res.error
    return rec

def main():
    prov = json.loads((HERE / "provisions.json").read_text())
    gt_a = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth.json").read_text())}
    retro_units = [gt_a["snap.ca.2023-12"], gt_a["snap.oh.2023-12"]]
    fut_units = [snap_future_unit(s, sid) for s, sid in SNAP_STATES]
    fpuc_future = json.loads((HERE / "future_unit_2026.json").read_text())

    plan = []
    for dose in ("severe", "actual", "inert"):
        for model in MODELS:
            for elic in ELICS:
                for rep in range(1, REPS + 1):
                    for u in retro_units:
                        plan.append(("snap", u, "retro2023", dose, model, elic, rep))
                    for u in fut_units:
                        plan.append(("snap", u, "future2027", dose, model, elic, rep))
    for dose in FPUC_WINDOWS:
        for model in MODELS:
            for elic in ELICS:
                for rep in range(1, REPS + 1):
                    plan.append(("fpucwin", fpuc_future, "future2026", dose, model, elic, rep))

    out = (HERE / "runs_amend5.jsonl").open("a"); lock = threading.Lock(); n=[0]; t0=time.time()
    def work(item):
        kind, unit, period, dose, model, elic, rep = item
        try:
            rec = run_snap(unit, period, dose, model, elic, prov) if kind == "snap" else run_fpuc_window(unit, dose, model, elic)
        except Exception as e:
            rec = {"unit_id": unit["unit_id"], "error": f"{type(e).__name__}: {e}",
                   "config": {"dose": dose, "model": model, "elicitation": elic}, "period": period}
        rec["rep"] = rep
        rec["cell_key"] = "|".join(["A5", kind, unit["unit_id"], period, dose, model, elic, str(rep)])
        with lock:
            out.write(json.dumps(rec) + "\n"); out.flush(); n[0] += 1
            if n[0] % 60 == 0:
                print(f"[{n[0]}/{len(plan)}] {n[0]/(time.time()-t0):.1f}/s", flush=True)
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(work, plan))
    out.close(); print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f}min", flush=True)

if __name__ == "__main__":
    main()
