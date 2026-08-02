"""Amendment 4: reasoning-effort x period x dose (opus-5, fable-5 only).

Question: A3 showed directed-derivation SCHEMA rescues dose-tracking in the
memorized period. Does raw reasoning EFFORT (adaptive thinking, low->max) do
the same at default point+CI elicitation? Distinguishes compute from structure.
Committed before first run; measurand is dose-response, future arm unscored.
"""
from __future__ import annotations
import concurrent.futures as cf, json, sys, threading, time
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import harness as H, amend3_sweep as A3  # noqa: E402

MODELS = ["claude-opus-5", "claude-fable-5"]
EFFORTS = ["low", "medium", "high", "max"]
DOSES = ["third", "actual", "tripled"]
REPS = 5

def main() -> None:
    retro = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth_extra.json").read_text())}["fpuc300.us.2021-01"]
    future = json.loads((HERE / "future_unit_2026.json").read_text())
    plan = [(unit, period, dose, model, eff, rep)
            for period, unit in (("retro2021", retro), ("future2026", future))
            for dose in DOSES for model in MODELS for eff in EFFORTS
            for rep in range(1, REPS + 1)]
    out = (HERE / "runs_amend4.jsonl").open("a"); lock = threading.Lock(); n=[0]; t0=time.time()
    def work(item):
        unit, period, dose, model, eff, rep = item
        ctx, meta = A3.build_context_a3(period, dose)
        base = A3.X.TASK_B.format(
            series_desc=A3.X.SERIES_DESC["W825RC1"], series_id="W825RC1",
            target_label=H.month_label(unit["target_month"]),
            origin_label=H.month_label(unit["origin_vintage"]),
            history_block=A3.X.format_history_b(unit["history"]))
        prompt = "\n\n".join([base, ctx, H.ELICITATION_INSTRUCTIONS["point_ci_json"]])
        res = H.call_model(prompt, model, max_tokens=6000, effort=eff)
        rec = {"unit_id": unit["unit_id"], "period": period,
               "config": {"dose": dose, "model": model, "effort": eff},
               "context_meta": meta, "rep": rep,
               "cell_key": "|".join(["A4", period, dose, model, eff, str(rep)]),
               "calls": [{"ok": res.ok, "completion_tokens": res.completion_tokens,
                          "max_tokens": 6000, "effort": eff, "error": res.error}]}
        if res.ok:
            rec["final_text"] = res.text
            rec["forecast"] = H.parse_forecast(res.text, "point_ci_json", H.history_anchor(unit))
        else:
            rec["error"] = res.error
        with lock:
            out.write(json.dumps(rec) + "\n"); out.flush(); n[0]+=1
            if n[0] % 40 == 0: print(f"[{n[0]}/{len(plan)}] {n[0]/(time.time()-t0):.1f}/s", flush=True)
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(work, plan))
    out.close(); print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f} min")

if __name__ == "__main__":
    main()
