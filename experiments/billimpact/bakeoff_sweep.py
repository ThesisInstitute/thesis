"""Powered bake-off: 28 corpus-B units x {opus,fable} x {bill,none} x
{point_ci_json, decomposed_json(bill only)} x 5 reps. Reuses run_single_b."""
from __future__ import annotations
import concurrent.futures as cf, json, sys, threading, time
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import extended_harness as X

MODELS = ["claude-opus-5", "claude-fable-5"]
REPS = 5

def main() -> None:
    units = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth_B_all.json").read_text())
             if u.get("truth", {}).get("first_print_value") is not None}
    plan = []
    for uid in sorted(units):
        for rep in range(1, REPS + 1):
            for model in MODELS:
                for ctx in ("none", "operative_only"):
                    plan.append((uid, {"corpus": "B", "policy_context": ctx,
                                       "elicitation": "point_ci_json", "model": model,
                                       "magnitude": "actual"}, rep))
                plan.append((uid, {"corpus": "B", "policy_context": "operative_only",
                                   "elicitation": "decomposed_json", "model": model,
                                   "magnitude": "actual"}, rep))
                plan.append((uid, {"corpus": "B", "policy_context": "operative_only",
                                   "elicitation": "point_ci_json", "model": model,
                                   "magnitude": "actual", "effort": "max"}, rep))
    out_path = HERE / "runs_bakeoff.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try: done.add(json.loads(line)["cell_key"])
                except Exception: pass
    def key(uid, cfg, rep):
        return "|".join(["BO", uid, cfg["policy_context"], cfg["elicitation"], cfg["model"],
                         cfg.get("effort", "default"), str(rep)])
    todo = [(u, c, r) for u, c, r in plan if key(u, c, r) not in done]
    print(f"units={len(units)} planned={len(plan)} todo={len(todo)}", flush=True)
    out = out_path.open("a"); lock = threading.Lock(); n = [0]; t0 = time.time()
    def work(item):
        uid, cfg, rep = item
        try:
            rec = X.run_single_b(units[uid], cfg)
        except Exception as e:
            rec = {"unit_id": uid, "config": dict(cfg), "error": f"{type(e).__name__}: {e}"}
        rec["rep"] = rep; rec["cell_key"] = key(uid, cfg, rep)
        rec["truth"] = units[uid]["truth"]["first_print_value"]
        with lock:
            out.write(json.dumps(rec) + "\n"); out.flush(); n[0] += 1
            if n[0] % 60 == 0:
                r = n[0]/(time.time()-t0)
                print(f"[{n[0]}/{len(todo)}] {r:.1f}/s eta={(len(todo)-n[0])/r/60:.1f}min", flush=True)
    with cf.ThreadPoolExecutor(max_workers=28) as ex:
        list(ex.map(work, todo))
    out.close(); print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f}min", flush=True)

if __name__ == "__main__":
    main()
