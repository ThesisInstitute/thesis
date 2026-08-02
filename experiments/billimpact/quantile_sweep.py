"""Experiment 1 runner: model-authored CDFs via direct 5-quantile elicitation.

Design (CALIBRATION_LAB.md): the existing pipeline elicits point + 80% interval
and builds the scoring CDF with the repo's fixed interval_anchor transform, so
the CDF's *shape* is the transform's, not the model's. This sweep elicits
p5/p25/p50/p75/p95 directly — the measured-best base config otherwise held
fixed: claude-opus-5, effort="max", corpus B (ground_truth_B_all.json), NO bill
text, TASK_B verbatim from extended_harness. 3 reps x 28 units = 84 calls.

The scoring CDF is built later (calibration_analysis.py) from the model's own
five knots; this file only runs and records. Non-monotone quantile sets are
RECORDED with a flag and rejected at scoring time — never sorted or repaired.

Writes runs_quantile.jsonl (append, resumable by cell_key). Touches no existing
file.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
import extended_harness as X  # noqa: E402

MODEL = "claude-opus-5"
EFFORT = "max"
REPS = (1, 2, 3)
OUT = HERE / "runs_quantile.jsonl"

QKEYS = ("p5", "p25", "p50", "p75", "p95")

QUANTILE_INSTRUCTION = """Give your 5th, 25th, 50th, 75th and 95th percentile forecasts for the target
month — values such that you judge a 5%, 25%, 50%, 75% and 95% chance the
outcome falls below each. The five values must be strictly increasing
(p5 < p25 < p50 < p75 < p95). Respond with ONLY a JSON object:
{"p5": <number>, "p25": <number>, "p50": <number>, "p75": <number>, "p95": <number>, "rationale": "<one sentence>"}"""


def parse_quantiles(text: str) -> dict:
    """Extract the five quantiles from the LAST JSON object carrying all of them.

    Strictly extractive: a response missing any key fails; a non-monotone set is
    flagged, not reordered. `monotone` means strictly increasing across all
    five, which is the sanity gate calibration_analysis.py scores on.
    """
    for blob in reversed(re.findall(r"\{[^{}]*\}", text)):
        try:
            obj = json.loads(blob)
        except Exception:  # noqa: BLE001
            continue
        if all(k in obj for k in QKEYS):
            vals = [H._to_float(obj[k]) for k in QKEYS]
            if any(v is None for v in vals):
                return {"parse_error": "non_numeric_quantile", "parse_mode": "failed"}
            out = dict(zip(QKEYS, vals))
            out["monotone"] = all(a < b for a, b in zip(vals, vals[1:]))
            out["parse_mode"] = "quantiles5"
            return out
    return {"parse_error": "no_quantile_object", "parse_mode": "failed"}


def build_prompt(unit: dict) -> str:
    base = X.TASK_B.format(
        series_desc=X.SERIES_DESC[unit["series_id"]],
        series_id=unit["series_id"],
        target_label=H.month_label(unit["target_month"]),
        origin_label=H.month_label(unit["origin_vintage"]),
        history_block=X.format_history_b(unit["history"]),
    )
    return "\n\n".join([base, QUANTILE_INSTRUCTION])


def main() -> None:
    units = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth_B_all.json").read_text())}
    plan = [(uid, rep) for uid in sorted(units) for rep in REPS]
    done: set[str] = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                    # Only a SUCCESSFUL call is done: error records (e.g. the
                    # 2026-07-31 workspace usage cap, HTTP 400) stay in the
                    # file as evidence but are retried on the next invocation.
                    # calibration_analysis.py dedupes by cell_key, preferring
                    # the successful attempt.
                    if rec["calls"][0]["ok"]:
                        done.add(rec["cell_key"])
                except Exception:  # noqa: BLE001
                    pass
    todo = [p for p in plan if f"Q5|{p[0]}|{p[1]}" not in done]
    print(f"planned={len(plan)} done={len(done)} todo={len(todo)}", flush=True)
    if not todo:
        return
    out = OUT.open("a")
    lock = threading.Lock()
    n = [0]
    t0 = time.time()

    def work(item: tuple[str, int]) -> None:
        uid, rep = item
        u = units[uid]
        prompt = build_prompt(u)
        res = H.call_model(prompt, MODEL, max_tokens=6000, effort=EFFORT)
        rec = {
            "unit_id": uid,
            "rep": rep,
            "cell_key": f"Q5|{uid}|{rep}",
            "model": MODEL,
            "effort": EFFORT,
            "truth": u["truth"]["first_print_value"],
            "prompt_chars": len(prompt),
            "calls": [{"ok": res.ok, "duration_s": round(res.duration_s, 2),
                       "prompt_tokens": res.prompt_tokens,
                       "completion_tokens": res.completion_tokens,
                       "error": res.error}],
        }
        if res.ok:
            rec["final_text"] = res.text
            rec["forecast"] = parse_quantiles(res.text)
        else:
            rec["error"] = res.error
        with lock:
            out.write(json.dumps(rec) + "\n")
            out.flush()
            n[0] += 1
            if n[0] % 10 == 0:
                print(f"[{n[0]}/{len(todo)}] {(time.time()-t0)/60:.1f}min", flush=True)

    with cf.ThreadPoolExecutor(max_workers=14) as ex:
        list(ex.map(work, todo))
    out.close()
    print(f"DONE {n[0]} in {(time.time()-t0)/60:.1f}min", flush=True)


if __name__ == "__main__":
    main()
