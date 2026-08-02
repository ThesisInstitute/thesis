"""Amendment 7: booking-profile elicitation on the leading arm."""
from __future__ import annotations
import concurrent.futures as cf, json, re, sys, threading, time
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import harness as H, extended_harness as X

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

BOOKING = """Derive the forecast in four explicit steps:
1. BASELINE: the target month's value absent the policy, from the history.
2. EVENT: what the policy does, in its own natural units (dollars per person,
   appropriated totals, eligibility changes), taken from the text supplied.
3. BOOKING: how THIS series records such an event. Name the convention that
   applies: seasonally-adjusted-annual-rate scaling of monthly flows, a
   lump-sum booked in a specific month, an appropriations-to-outlays lag
   spread over months or years, an enrollment stock adjusting gradually, or
   revision practice. Then state the contribution actually booked in the
   TARGET month, in the series' units — a large event can book near zero in
   the target month if its timing or accounting puts it elsewhere.
4. COMPOSE: point = baseline + booked contribution, with an 80% interval
   reflecting both baseline and booking uncertainty.

Respond with ONLY a JSON object:
{"baseline": <n>, "event_natural_units": "<one sentence>", "booking_convention": "<one sentence>", "booked_contribution": <n>, "point": <n>, "ci_low": <n>, "ci_high": <n>}"""

def run_one(unit, rep):
    ev = PROV[unit["policy_event"]]
    parts = list(ev["operative"].values()) if isinstance(ev.get("operative"), dict) else []
    ctx = f"POLICY CONTEXT (verbatim text, {ev.get('law', unit['policy_event'])}):\n\n" + "\n\n".join(parts)
    base = X.TASK_B.format(series_desc=SERIES_DESC[unit["series_id"]], series_id=unit["series_id"],
                           target_label=H.month_label(unit["target_month"]),
                           origin_label=H.month_label(unit["origin_vintage"]),
                           history_block=X.format_history_b(unit["history"]))
    prompt = "\n\n".join([base, ctx, BOOKING])
    res = H.call_model(prompt, "claude-fable-5", max_tokens=6000, effort="max")
    rec = {"unit_id": unit["unit_id"], "rep": rep,
           "config": {"model": "claude-fable-5", "policy_context": "operative_only",
                      "elicitation": "booking_json", "effort": "max"},
           "cell_key": f"BK|{unit['unit_id']}|{rep}",
           "truth": unit["truth"]["first_print_value"],
           "calls": [{"ok": res.ok, "completion_tokens": res.completion_tokens, "error": res.error}]}
    if not res.ok:
        rec["error"] = res.error; return rec
    rec["final_text"] = res.text
    obj = None
    for b in reversed(re.findall(r"\{(?:[^{}]|\{[^{}]*\})*\}", res.text, re.S)):
        try:
            o = json.loads(b)
            if all(k in o for k in ("point", "ci_low", "ci_high")): obj = o; break
        except Exception: continue
    if obj:
        pt, lo, hi = (H._to_float(obj.get(k)) for k in ("point", "ci_low", "ci_high"))
        if None not in (pt, lo, hi):
            if lo > hi: lo, hi = hi, lo
            rec["forecast"] = {"point": pt, "ci_low": lo, "ci_high": hi, "parse_mode": "booking_json"}
            rec["booking"] = {k: obj.get(k) for k in ("baseline", "event_natural_units",
                                                      "booking_convention", "booked_contribution")}
            return rec
    rec["forecast"] = H.parse_forecast(res.text, "point_ci_json", H.history_anchor(unit))
    return rec

def main():
    units = []
    for f in ("ground_truth_B_all.json", "ground_truth_crosstype.json", "ground_truth_wave2.json"):
        units += [u for u in json.loads((HERE / f).read_text())
                  if u.get("series_id") and u.get("truth", {}).get("first_print_value") is not None]
    units = {u["unit_id"]: u for u in units}
    plan = [(uid, rep) for uid in sorted(units) for rep in (1, 2, 3)]
    out_path = HERE / "runs_booking.jsonl"; done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try:
                    rr = json.loads(line)
                    if not rr.get("error"): done.add(rr["cell_key"])
                except Exception: pass
    todo = [x for x in plan if f"BK|{x[0]}|{x[1]}" not in done]
    print(f"planned={len(plan)} todo={len(todo)}", flush=True)
    out = out_path.open("a"); lock = threading.Lock(); n = [0]; t0 = time.time()
    def work(x):
        uid, rep = x
        rec = run_one(units[uid], rep)
        with lock:
            out.write(json.dumps(rec) + "\n"); out.flush(); n[0] += 1
            if n[0] % 20 == 0: print(f"[{n[0]}/{len(todo)}] {n[0]/(time.time()-t0):.2f}/s", flush=True)
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(work, todo))
    out.close(); print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f}min", flush=True)

if __name__ == "__main__":
    main()
