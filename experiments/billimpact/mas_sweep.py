"""Theory-motivated structured arms. opus-5, corpus B, no bill text.
scenario_mixture / variance_auditor / persona_pool. 3 reps x 28 units."""
from __future__ import annotations
import concurrent.futures as cf, json, re, sys, threading, time
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import harness as H, extended_harness as X

def jload(text, need):
    for b in reversed(re.findall(r"\{(?:[^{}]|\{[^{}]*\})*\}", text, re.S)):
        try: o = json.loads(b)
        except Exception: continue
        if all(k in o for k in need): return o
    return None

SCEN = """Forecast via explicit scenarios. Define exactly four qualitatively different
scenarios for the target month: (A) trend continuation, (B) upside shock,
(C) downside shock, (D) reversion/other. For each give a probability (summing
to 1) and the value the series would take. Tail scenarios must carry the
probability you actually assign them, not decoration.
Respond with ONLY a JSON object:
{"scenarios": [{"name": "A", "prob": <p>, "value": <v>}, {"name": "B", "prob": <p>, "value": <v>}, {"name": "C", "prob": <p>, "value": <v>}, {"name": "D", "prob": <p>, "value": <v>}]}"""

VARAUD_AUDIT = """Below is a forecasting task and a draft forecast.

=== TASK ===
{task}

=== DRAFT ===
{draft}

You are the VARIANCE AUDITOR. Do not re-litigate the point estimate. Your only
job: is the 80% interval wide enough? Enumerate variance sources the draft
under-prices for THIS series at THIS horizon (data revisions, regime breaks,
seasonal misreads, policy events, publication quirks) and price each as a
rough percent of the level. Then output the corrected interval.
Respond with ONLY a JSON object:
{{"omitted_sources": ["<source>: <rough %>"], "point": <number>, "ci_low": <number>, "ci_high": <number>}}"""

PERSONA = """You are a {persona} forecaster. {creed}

{task}

Respond with ONLY a JSON object:
{{"point": <number>, "ci_low": <number>, "ci_high": <number>}}"""
PERSONAS = {
 "momentum": "You weight the most recent 6-12 months heavily; trends persist until something breaks them.",
 "mean-reversion": "You expect reversion toward the longer-run level; you distrust extrapolation of recent moves.",
 "base-rate": "You forecast from the distribution of historical h-step changes; statistics over stories.",
}
PSYNTH = """Three forecasters with different priors produced these 80% intervals.

=== TASK ===
{task}

=== FORECASTS ===
{fcsts}

Pool them into one predictive distribution: weigh their credibility for this
series, widen where they disagree, and give pooled percentiles.
Respond with ONLY a JSON object:
{{"p10": <number>, "p50": <number>, "p90": <number>}}"""

def task_for(u):
    return X.TASK_B.format(series_desc=X.SERIES_DESC[u["series_id"]], series_id=u["series_id"],
                           target_label=H.month_label(u["target_month"]),
                           origin_label=H.month_label(u["origin_vintage"]),
                           history_block=X.format_history_b(u["history"]))

def run_scen(u):
    res = H.call_model(task_for(u) + "\n\n" + SCEN, "claude-opus-5", max_tokens=6000, effort="max")
    if not res.ok: return {"error": res.error}
    o = jload(res.text, ["scenarios"])
    if not o: return {"final_text": res.text, "forecast": {"parse_error": "no_scenarios"}}
    sc = []
    for s in o["scenarios"]:
        p, v = H._to_float(s.get("prob")), H._to_float(s.get("value"))
        if p is not None and v is not None and p >= 0: sc.append((p, v))
    tot = sum(p for p, _ in sc)
    if tot <= 0 or len(sc) < 2: return {"final_text": res.text, "forecast": {"parse_error": "bad_scenarios"}}
    sc = [(p / tot, v) for p, v in sc]
    pts = sorted(sc, key=lambda x: x[1])
    def q(t):
        acc = 0
        for p, v in pts:
            acc += p
            if acc >= t: return v
        return pts[-1][1]
    return {"final_text": res.text, "scenarios": o["scenarios"],
            "forecast": {"point": sum(p*v for p, v in sc), "ci_low": q(0.10), "ci_high": q(0.90),
                         "parse_mode": "scenario_mixture"}}

def run_varaud(u):
    t = task_for(u)
    d = H.call_model(t + "\n\n" + H.ELICITATION_INSTRUCTIONS["point_ci_json"], "claude-opus-5",
                     max_tokens=6000, effort="max")
    if not d.ok: return {"error": d.error}
    a = H.call_model(VARAUD_AUDIT.format(task=t, draft=d.text), "claude-opus-5",
                     max_tokens=6000, effort="max")
    if not a.ok: return {"error": a.error}
    o = jload(a.text, ["point", "ci_low", "ci_high"])
    if not o: return {"final_text": a.text, "forecast": {"parse_error": "no_audit_json"}}
    p, lo, hi = (H._to_float(o.get(k)) for k in ("point", "ci_low", "ci_high"))
    if None in (p, lo, hi): return {"final_text": a.text, "forecast": {"parse_error": "bad_audit_nums"}}
    if lo > hi: lo, hi = hi, lo
    return {"draft_text": d.text, "final_text": a.text, "omitted_sources": o.get("omitted_sources"),
            "forecast": {"point": p, "ci_low": lo, "ci_high": hi, "parse_mode": "varaud"}}

def run_ppool(u):
    t = task_for(u); fs = []
    for name, creed in PERSONAS.items():
        r = H.call_model(PERSONA.format(persona=name, creed=creed, task=t), "claude-opus-5",
                         max_tokens=3000, effort="low")
        if not r.ok: return {"error": r.error}
        o = jload(r.text, ["point", "ci_low", "ci_high"])
        if not o: return {"forecast": {"parse_error": f"persona_{name}"}}
        fs.append((name, o))
    ftxt = "\n".join(f"  {n}: point {o['point']} interval [{o['ci_low']}, {o['ci_high']}]" for n, o in fs)
    s = H.call_model(PSYNTH.format(task=t, fcsts=ftxt), "claude-opus-5", max_tokens=6000, effort="max")
    if not s.ok: return {"error": s.error}
    o = jload(s.text, ["p10", "p50", "p90"])
    if not o: return {"final_text": s.text, "forecast": {"parse_error": "no_pool_json"}}
    p10, p50, p90 = (H._to_float(o.get(k)) for k in ("p10", "p50", "p90"))
    if None in (p10, p50, p90): return {"final_text": s.text, "forecast": {"parse_error": "bad_pool_nums"}}
    return {"personas": {n: o2 for n, o2 in fs}, "final_text": s.text,
            "forecast": {"point": p50, "ci_low": p10, "ci_high": p90, "parse_mode": "persona_pool"}}

ARMS = {"scenario_mixture": run_scen, "variance_auditor": run_varaud, "persona_pool": run_ppool}

def main():
    units = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth_B_all.json").read_text())}
    plan = [(uid, arm, rep) for uid in sorted(units) for arm in ARMS for rep in (1, 2, 3)]
    out_path = HERE / "runs_mas.jsonl"; done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try: done.add(json.loads(line)["cell_key"])
                except Exception: pass
    todo = [x for x in plan if f"MAS|{x[0]}|{x[1]}|{x[2]}" not in done]
    print(f"planned={len(plan)} todo={len(todo)}", flush=True)
    out = out_path.open("a"); lock = threading.Lock(); n = [0]; t0 = time.time()
    def work(item):
        uid, arm, rep = item
        try: rec = ARMS[arm](units[uid])
        except Exception as e: rec = {"error": f"{type(e).__name__}: {e}"}
        rec.update({"unit_id": uid, "arm": arm, "rep": rep, "cell_key": f"MAS|{uid}|{arm}|{rep}",
                    "truth": units[uid]["truth"]["first_print_value"]})
        with lock:
            out.write(json.dumps(rec) + "\n"); out.flush(); n[0] += 1
            if n[0] % 25 == 0: print(f"[{n[0]}/{len(todo)}] {n[0]/(time.time()-t0):.2f}/s", flush=True)
    with cf.ThreadPoolExecutor(max_workers=15) as ex:
        list(ex.map(work, todo))
    out.close(); print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f}min", flush=True)

if __name__ == "__main__":
    main()
