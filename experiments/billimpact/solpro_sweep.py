"""Ceiling probe: gpt-5.6-sol-pro (the lab's own agent family) under our
harness. Arms: {naive, bill}+effort=max x 36 units x 3 reps, plus the FPUC
dose-response signature (retro vs future). OpenRouter transport."""
from __future__ import annotations
import concurrent.futures as cf, json, sys, threading, time
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import harness as H, extended_harness as X, amend3_sweep as A3

MODEL = "openai/gpt-5.6-sol-pro"
SERIES_DESC = dict(X.SERIES_DESC)
SERIES_DESC.update({
    "B235RC1Q027SBEA": "US federal customs duties receipts (quarterly, SAAR; observations dated by first month of quarter; national)",
    "B069RC1": "US personal interest payments (monthly, national)",
    "W827RC1": "US personal current transfer receipts: government social benefits to persons: other (monthly, national)",
    "PBHWYCONS": "US Census value of public construction put in place: highway and street (monthly, national)",
})
PROV = dict(X.PROVISIONS_B)
for f in ("provisions_crosstype.json", "provisions_wave2.json"):
    PROV.update(json.loads((HERE / f).read_text()))

def build_ctx(ev_key, level):
    if level == "none": return ""
    ev = PROV[ev_key]
    parts = list(ev["operative"].values()) if isinstance(ev.get("operative"), dict) else []
    return f"POLICY CONTEXT (verbatim text, {ev.get('law', ev_key)}):\n\n" + "\n\n".join(parts)

def run_acc(unit, ctx_level, rep):
    ctx = build_ctx(unit["policy_event"], ctx_level) if unit.get("policy_event") else ""
    base = X.TASK_B.format(series_desc=SERIES_DESC[unit["series_id"]], series_id=unit["series_id"],
                           target_label=H.month_label(unit["target_month"]),
                           origin_label=H.month_label(unit["origin_vintage"]),
                           history_block=X.format_history_b(unit["history"]))
    prompt = "\n\n".join(p for p in (base, ctx, H.ELICITATION_INSTRUCTIONS["point_ci_json"]) if p)
    res = H.call_model(prompt, MODEL, max_tokens=6000, effort="max", timeout=600.0, retries=2)
    rec = {"unit_id": unit["unit_id"], "config": {"model": MODEL, "policy_context": ctx_level,
           "elicitation": "point_ci_json", "effort": "max"}, "rep": rep,
           "cell_key": f"SP|{unit['unit_id']}|{ctx_level}|{rep}",
           "truth": unit["truth"]["first_print_value"],
           "calls": [{"ok": res.ok, "completion_tokens": res.completion_tokens, "error": res.error}]}
    if res.ok:
        rec["final_text"] = res.text
        rec["forecast"] = H.parse_forecast(res.text, "point_ci_json", H.history_anchor(unit))
    else: rec["error"] = res.error
    return rec

def run_dose(unit, period, dose, rep):
    ctx, meta = A3.build_context_a3(period, dose)
    base = X.TASK_B.format(series_desc=X.SERIES_DESC["W825RC1"], series_id="W825RC1",
                           target_label=H.month_label(unit["target_month"]),
                           origin_label=H.month_label(unit["origin_vintage"]),
                           history_block=X.format_history_b(unit["history"]))
    prompt = "\n\n".join([base, ctx, H.ELICITATION_INSTRUCTIONS["point_ci_json"]])
    res = H.call_model(prompt, MODEL, max_tokens=6000, effort="max", timeout=600.0, retries=2)
    rec = {"unit_id": unit["unit_id"], "period": period,
           "config": {"model": MODEL, "dose": dose, "effort": "max"}, "rep": rep,
           "cell_key": f"SPD|{period}|{dose}|{rep}", "context_meta": meta,
           "calls": [{"ok": res.ok, "completion_tokens": res.completion_tokens, "error": res.error}]}
    if res.ok:
        rec["final_text"] = res.text
        rec["forecast"] = H.parse_forecast(res.text, "point_ci_json", H.history_anchor(unit))
    else: rec["error"] = res.error
    return rec

def main():
    units = {}
    for f in ("ground_truth_B_all.json", "ground_truth_crosstype.json", "ground_truth_wave2.json"):
        for u in json.loads((HERE / f).read_text()):
            if u.get("series_id") and u.get("truth", {}).get("first_print_value") is not None:
                units[u["unit_id"]] = u
    retro = json.loads((HERE / "ground_truth_extra.json").read_text())
    retro = {u["unit_id"]: u for u in retro}["fpuc300.us.2021-01"]
    future = json.loads((HERE / "future_unit_2026.json").read_text())
    plan = [("acc", uid, ctx, rep) for uid in sorted(units) for ctx in ("none", "operative_only") for rep in (1, 2, 3)]
    plan += [("dose", period, dose, rep) for period in ("retro2021", "future2026")
             for dose in ("third", "actual", "tripled") for rep in (1, 2, 3)]
    out_path = HERE / "runs_solpro.jsonl"; done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try:
                    rr = json.loads(line)
                    if not rr.get("error"): done.add(rr["cell_key"])
                except Exception: pass
    out = out_path.open("a"); lock = threading.Lock(); n = [0]; t0 = time.time()
    def work(item):
        if item[0] == "acc":
            _, uid, ctx, rep = item
            if f"SP|{uid}|{ctx}|{rep}" in done: return
            rec = run_acc(units[uid], ctx, rep)
        else:
            _, period, dose, rep = item
            if f"SPD|{period}|{dose}|{rep}" in done: return
            rec = run_dose(retro if period == "retro2021" else future, period, dose, rep)
        with lock:
            out.write(json.dumps(rec) + "\n"); out.flush(); n[0] += 1
            if n[0] % 30 == 0: print(f"[{n[0]}] {n[0]/(time.time()-t0):.1f}/s", flush=True)
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(work, plan))
    out.close(); print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f}min", flush=True)

if __name__ == "__main__":
    main()
