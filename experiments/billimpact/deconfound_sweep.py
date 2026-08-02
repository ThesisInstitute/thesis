"""A3 deconfound arm: retro2021 doses with the statute name redacted,
matching the future arm's framing. Registered before run."""
from __future__ import annotations
import concurrent.futures as cf, json, re, sys, threading, time
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import harness as H, extended_harness as X, amend3_sweep as A3

MODELS = ["claude-opus-5", "claude-fable-5"]
def build_ctx_unnamed(dose):
    ctx, meta = A3.build_context_a3("retro2021", dose)
    # strip the identifying header line and any Pub. L. reference
    ctx = re.sub(r"POLICY CONTEXT \(.*?\):",
                 "POLICY CONTEXT (verbatim text of a statute; assume it is in force through the target month):", ctx, count=1, flags=re.S)
    ctx = re.sub(r"Pub\. L\. [0-9–-]+", "the statute", ctx)
    meta = dict(meta); meta["name_redacted"] = True
    # Match the FUTURE arm's anonymization delta exactly: header identity removed;
    # body's internal CARES-act references stay (they were present in the future
    # arm too). Assert only the header identifiers are gone.
    assert "116-260" not in ctx and "Consolidated Appropriations" not in ctx, ctx[:200]
    return ctx, meta

def main():
    retro = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth_extra.json").read_text())}["fpuc300.us.2021-01"]
    plan = [(d, m, e, r) for d in ("third", "actual", "tripled") for m in MODELS
            for e in ("point_ci_json", "derivation_json") for r in (1, 2, 3, 4, 5)]
    out = (HERE / "runs_deconfound.jsonl").open("a"); lock = threading.Lock(); n=[0]; t0=time.time()
    def work(item):
        dose, model, elic, rep = item
        ctx, meta = build_ctx_unnamed(dose)
        base = X.TASK_B.format(series_desc=X.SERIES_DESC["W825RC1"], series_id="W825RC1",
                               target_label=H.month_label(retro["target_month"]),
                               origin_label=H.month_label(retro["origin_vintage"]),
                               history_block=X.format_history_b(retro["history"]))
        instr = A3.DERIVATION_INSTRUCTION if elic == "derivation_json" else H.ELICITATION_INSTRUCTIONS["point_ci_json"]
        prompt = "\n\n".join([base, ctx, instr])
        res = H.call_model(prompt, model, max_tokens=6000)
        rec = {"unit_id": retro["unit_id"], "period": "retro2021_unnamed",
               "config": {"dose": dose, "model": model, "elicitation": elic}, "rep": rep,
               "context_meta": meta, "cell_key": f"DC|{dose}|{model}|{elic}|{rep}",
               "calls": [{"ok": res.ok, "completion_tokens": res.completion_tokens, "error": res.error}]}
        if res.ok:
            rec["final_text"] = res.text
            if elic == "derivation_json":
                obj = H._last_json_object(res.text)
                if obj and "point" in obj:
                    pt, lo, hi = (H._to_float(obj.get(k)) for k in ("point", "ci_low", "ci_high"))
                    if None not in (pt, lo, hi):
                        rec["forecast"] = {"point": pt, "ci_low": min(lo, hi), "ci_high": max(lo, hi), "parse_mode": "derivation_json"}
            if "forecast" not in rec:
                rec["forecast"] = H.parse_forecast(res.text, "point_ci_json", H.history_anchor(retro))
        else: rec["error"] = res.error
        with lock:
            out.write(json.dumps(rec) + "\n"); out.flush(); n[0] += 1
            if n[0] % 20 == 0: print(f"[{n[0]}/{len(plan)}]", flush=True)
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(work, plan))
    out.close(); print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f}min", flush=True)

if __name__ == "__main__":
    main()
