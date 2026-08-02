"""Amendment 6: harness-sensitivity envelope of the registered S.3596 deltas.
4 contexts x 2 elicitations x 2 models x 3 reps x 2 targets. Spread only."""
from __future__ import annotations
import concurrent.futures as cf, json, re, sys, threading, time
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import harness as H

BILL = (HERE / "bills" / "S3596-stronger-start.clean.txt").read_text()
PE = json.loads((HERE / "corpus_ctc.json").read_text())
PE_ROWS = "\n".join(
    f"  earnings ${c['earnings']:>7,} | {c['children']} children | current-law refundable CTC "
    f"${c['truth']['refundable_ctc_current_law']:>8,.2f} | under the bill ${c['truth']['refundable_ctc_reform']:>8,.2f} "
    f"| delta ${c['truth']['delta']:>6,.2f}" for c in PE)

CONTEXTS = {
    "full_bill": "THE BILL (full text, currently pending)\n" + BILL + "\n\nMECHANICAL LEG (PolicyEngine-US, exact for the statutory arithmetic):\n" + PE_ROWS,
    "summary": ("THE BILL (operational description): A pending Senate bill lowers the refundable "
                "Child Tax Credit's earned-income phase-in threshold from $2,500 to $1, effective "
                "for taxable years beginning after December 31, 2025. No other CTC parameter changes."),
    "parameter_only": "THE POLICY CHANGE: gov.irs.credits.ctc.refundable.phase_in.threshold: 2500 -> 1, from tax year 2026.",
    "named_only": 'THE BILL: S.3596, the "Stronger Start for Working Families Act" (119th Congress).',
}
TARGETS = {
 "census.spm.child_poverty_rate.2027": {
   "desc": "US SPM child poverty rate, children under 18, calendar year 2027, percent",
   "rule": "Official Census SPM child poverty rate for CY2027 (report expected September 2028), first print.",
   "hist": "  2021  5.2   (expanded monthly CTC in effect)\n  2022  12.4\n  2023  13.7\n  2024  13.4"},
 "irs.soi.ctc.qualifying_children.ty2026": {
   "desc": "Qualifying children claimed for the federal CTC, tax year 2026, millions",
   "rule": "First IRS SOI table reporting CTC qualifying-child counts for TY2026, first print.",
   "hist": "  TY2019  48\n  TY2021  61\n  TY2022  49"},
}
PAIRED = """Produce BOTH scenarios for the target.
Respond with ONLY a JSON object:
{"current_law": {"point": <n>, "ci_low": <n>, "ci_high": <n>},
 "enacted": {"point": <n>, "ci_low": <n>, "ci_high": <n>},
 "delta": <n>, "mechanism": "<one sentence>"}"""
DECOMP = """First state the no-policy baseline for the target, then the policy delta implied by
the context supplied (zero is a valid answer), then compose.
Respond with ONLY a JSON object:
{"baseline": <n>, "policy_delta": <n>, "current_law": {"point": <n>}, "enacted": {"point": <n>}, "delta": <n>}"""

def jload(text):
    for b in reversed(re.findall(r"\{(?:[^{}]|\{[^{}]*\})*\}", text, re.S)):
        try:
            o = json.loads(b)
            if "delta" in o: return o
        except Exception: continue
    return None

def main():
    plan = [(dp, ctx, elic, model, rep)
            for dp in TARGETS for ctx in CONTEXTS
            for elic in ("paired", "decomposed")
            for model in ("claude-opus-5", "claude-fable-5") for rep in (1, 2, 3)]
    out_path = HERE / "runs_envelope.jsonl"; done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try: done.add(json.loads(line)["cell_key"])
                except Exception: pass
    todo = [x for x in plan if "|".join(["EV", *map(str, x)]) not in done]
    print(f"planned={len(plan)} todo={len(todo)}", flush=True)
    out = out_path.open("a"); lock = threading.Lock(); n = [0]; t0 = time.time()
    def work(item):
        dp, ctx, elic, model, rep = item
        t = TARGETS[dp]
        prompt = "\n\n".join([
            f"You are producing a bill-conditional forecast.\n\nTARGET\n  {t['desc']}\n  Resolution rule: {t['rule']}\n\nHISTORY (as published)\n{t['hist']}",
            CONTEXTS[ctx], PAIRED if elic == "paired" else DECOMP])
        res = H.call_model(prompt, model, max_tokens=6000)
        rec = {"dataPointId": dp, "context": ctx, "elicitation": elic, "model": model, "rep": rep,
               "cell_key": "|".join(["EV", dp, ctx, elic, model, str(rep)]),
               "runAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "ok": res.ok, "error": res.error}
        if res.ok:
            rec["final_text"] = res.text
            rec["parsed"] = jload(res.text)
        with lock:
            out.write(json.dumps(rec) + "\n"); out.flush(); n[0] += 1
            if n[0] % 24 == 0: print(f"[{n[0]}/{len(todo)}]", flush=True)
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(work, todo))
    out.close(); print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f}min", flush=True)

if __name__ == "__main__":
    main()
