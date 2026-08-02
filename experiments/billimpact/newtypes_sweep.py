"""Confirmation arms on the 8 cross-type units (4 crosstype + 4 wave2).
Tests whether the N=28 findings hold on appropriations / business-side tax /
administrative-sunset / tax-parameter-retro types. Arms per unit:
opus none | opus oper | opus oper decomposed | fable none | fable oper effort=max, 5 reps."""
from __future__ import annotations
import concurrent.futures as cf, json, sys, threading, time
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import harness as H, extended_harness as X

SERIES_DESC = {
    "B235RC1Q027SBEA": ("US federal government current tax receipts: taxes on production and imports: "
        "customs duties (quarterly, seasonally adjusted annual rate; observations dated by the first "
        "month of their quarter — the target month names a quarter; national)"),
    "B069RC1": "US personal interest payments (monthly, national)",
    "W827RC1": "US personal current transfer receipts: government social benefits to persons: other (monthly, national)",
    "PBHWYCONS": "US Census value of public construction put in place: highway and street (monthly, national)",
}
PROV = {}
for f in ("provisions_crosstype.json", "provisions_wave2.json"):
    PROV.update(json.loads((HERE / f).read_text()))

def build_ctx(policy_event, level):
    ev = PROV[policy_event]
    if level == "none": return "", {"level": "none"}
    parts = list(ev["operative"].values()) if isinstance(ev.get("operative"), dict) else []
    header = f"POLICY CONTEXT (verbatim text, {ev.get('law', policy_event)}):"
    return header + "\n\n" + "\n\n".join(parts), {"level": "operative_only", "provisions": list(ev.get("operative", {}))}

def run_one(unit, model, ctx_level, elic, effort):
    ctx, meta = build_ctx(unit["policy_event"], ctx_level)
    base = X.TASK_B.format(series_desc=SERIES_DESC[unit["series_id"]], series_id=unit["series_id"],
                           target_label=H.month_label(unit["target_month"]),
                           origin_label=H.month_label(unit["origin_vintage"]),
                           history_block=X.format_history_b(unit["history"]))
    instr = X.DECOMPOSED_INSTRUCTION if elic == "decomposed_json" else H.ELICITATION_INSTRUCTIONS["point_ci_json"]
    prompt = "\n\n".join([p for p in (base, ctx, instr) if p])
    res = H.call_model(prompt, model, max_tokens=6000, effort=effort)
    rec = {"unit_id": unit["unit_id"], "config": {"model": model, "policy_context": ctx_level,
           "elicitation": elic, "effort": effort}, "context_meta": meta,
           "calls": [{"ok": res.ok, "completion_tokens": res.completion_tokens, "error": res.error}]}
    if res.ok:
        rec["final_text"] = res.text
        rec["forecast"] = (X.parse_decomposed(res.text, H.history_anchor(unit)) if elic == "decomposed_json"
                           else H.parse_forecast(res.text, "point_ci_json", H.history_anchor(unit)))
    else:
        rec["error"] = res.error
    return rec

ARMS = [("claude-opus-5", "none", "point_ci_json", None),
        ("claude-opus-5", "operative_only", "point_ci_json", None),
        ("claude-opus-5", "operative_only", "decomposed_json", None),
        ("claude-fable-5", "none", "point_ci_json", None),
        ("claude-fable-5", "operative_only", "point_ci_json", "max")]

def main():
    units = []
    for f in ("ground_truth_crosstype.json", "ground_truth_wave2.json"):
        units += [u for u in json.loads((HERE / f).read_text())
                  if u.get("series_id") and u.get("truth", {}).get("first_print_value") is not None]
    units = {u["unit_id"]: u for u in units}
    plan = [(uid, arm, rep) for uid in sorted(units) for arm in ARMS for rep in (1, 2, 3, 4, 5)]
    out_path = HERE / "runs_newtypes.jsonl"; done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try: done.add(json.loads(line)["cell_key"])
                except Exception: pass
    def key(uid, arm, rep): return "|".join(["NT", uid, arm[0], arm[1], arm[2], str(arm[3]), str(rep)])
    todo = [x for x in plan if key(*x) not in done]
    print(f"units={len(units)} planned={len(plan)} todo={len(todo)}", flush=True)
    out = out_path.open("a"); lock = threading.Lock(); n = [0]; t0 = time.time()
    def work(item):
        uid, arm, rep = item
        try: rec = run_one(units[uid], *arm)
        except Exception as e: rec = {"unit_id": uid, "error": f"{type(e).__name__}: {e}",
                                      "config": {"model": arm[0], "policy_context": arm[1],
                                                 "elicitation": arm[2], "effort": arm[3]}}
        rec["rep"] = rep; rec["cell_key"] = key(uid, arm, rep)
        rec["truth"] = units[uid]["truth"]["first_print_value"]
        with lock:
            out.write(json.dumps(rec) + "\n"); out.flush(); n[0] += 1
            if n[0] % 40 == 0: print(f"[{n[0]}/{len(todo)}] {n[0]/(time.time()-t0):.1f}/s", flush=True)
    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(work, todo))
    out.close(); print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f}min", flush=True)

if __name__ == "__main__":
    main()
