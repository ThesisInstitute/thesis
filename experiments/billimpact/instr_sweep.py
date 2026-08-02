"""Instruction-variant accuracy test: opus-5, effort=max, corpus B, no bill
text (the measured-best base), 4 instruction styles x 3 reps x 28 units."""
from __future__ import annotations
import concurrent.futures as cf, json, sys, threading, time
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import harness as H, extended_harness as X

INSTR = {
 "plain": H.ELICITATION_INSTRUCTIONS["point_ci_json"],
 "reference_class": """Before forecasting, explicitly establish the reference class: what does this
series do over comparable horizons in the history shown (typical drift, typical
month-to-month variation, largest observed swings)? Anchor on that base rate,
then adjust only for what you can justify. State the base rate you used.
Then respond with ONLY a JSON object on the final line:
{"point": <number>, "ci_low": <number>, "ci_high": <number>, "rationale": "<one sentence>"}
where [ci_low, ci_high] is your 80% central credible interval.""",
 "premortem": """Make a first-pass forecast. Then conduct a premortem: assume your forecast
missed badly — list the two most plausible reasons why (direction and rough
size). Revise your point and widen or shift your interval accordingly.
Then respond with ONLY a JSON object on the final line:
{"point": <number>, "ci_low": <number>, "ci_high": <number>, "rationale": "<one sentence>"}
where [ci_low, ci_high] is your 80% central credible interval.""",
 "quantiles": """Give your 10th, 50th and 90th percentile forecasts for the target month —
values such that you judge a 10%, 50% and 90% chance the outcome falls below
each. Respond with ONLY a JSON object:
{"p10": <number>, "p50": <number>, "p90": <number>, "rationale": "<one sentence>"}""",
}

def parse(text, style, anchor):
    if style == "quantiles":
        obj = H._last_json_object(text.replace('"p50"', '"point"'))
        import re, json as J
        for b in reversed(re.findall(r"\{[^{}]*\}", text)):
            try: o = J.loads(b)
            except Exception: continue
            if all(k in o for k in ("p10", "p50", "p90")):
                p10, p50, p90 = (H._to_float(o[k]) for k in ("p10", "p50", "p90"))
                if None not in (p10, p50, p90):
                    return {"point": p50, "ci_low": p10, "ci_high": p90, "parse_mode": "quantiles"}
        return {"parse_error": "no_quantiles", "parse_mode": "failed"}
    return H.parse_forecast(text, "point_ci_json", anchor)

def main():
    units = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth_B_all.json").read_text())}
    plan = [(uid, style, rep) for uid in sorted(units) for style in INSTR for rep in (1, 2, 3)]
    out_path = HERE / "runs_instr.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try: done.add(json.loads(line)["cell_key"])
                except Exception: pass
    todo = [p for p in plan if f"IN|{p[0]}|{p[1]}|{p[2]}" not in done]
    print(f"planned={len(plan)} todo={len(todo)}", flush=True)
    out = out_path.open("a"); lock = threading.Lock(); n = [0]; t0 = time.time()
    def work(item):
        uid, style, rep = item
        u = units[uid]
        base = X.TASK_B.format(series_desc=X.SERIES_DESC[u["series_id"]], series_id=u["series_id"],
                               target_label=H.month_label(u["target_month"]),
                               origin_label=H.month_label(u["origin_vintage"]),
                               history_block=X.format_history_b(u["history"]))
        prompt = "\n\n".join([base, INSTR[style]])
        res = H.call_model(prompt, "claude-opus-5", max_tokens=6000, effort="max")
        rec = {"unit_id": uid, "style": style, "rep": rep,
               "cell_key": f"IN|{uid}|{style}|{rep}",
               "truth": u["truth"]["first_print_value"],
               "calls": [{"ok": res.ok, "completion_tokens": res.completion_tokens, "error": res.error}]}
        if res.ok:
            rec["final_text"] = res.text
            rec["forecast"] = parse(res.text, style, H.history_anchor(u))
        else:
            rec["error"] = res.error
        with lock:
            out.write(json.dumps(rec) + "\n"); out.flush(); n[0] += 1
            if n[0] % 40 == 0:
                print(f"[{n[0]}/{len(todo)}] {n[0]/(time.time()-t0):.1f}/s", flush=True)
    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(work, todo))
    out.close(); print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f}min", flush=True)

if __name__ == "__main__":
    main()
