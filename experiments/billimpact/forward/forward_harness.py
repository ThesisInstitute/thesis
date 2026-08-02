"""Forward-registration lanes: genuinely future forecasts over registered
Thesis ledger targets, one lane per harness configuration.

Reuses the frozen billimpact transport and parser (`harness.call_model`,
`harness.parse_forecast`) and the amendment-1 decomposed elicitation
(`extended_harness.DECOMPOSED_INSTRUCTION` / `parse_decomposed`). No repo file
is modified; everything new lives under experiments/billimpact/forward/.

Design notes (mirrors FORWARD-REGISTRATION.md):
- Targets and histories are frozen in targets_forward.json BEFORE any model
  call; every history row carries provenance there.
- 4 lanes x 12 targets x 3 repeats = 144 calls, temperature 1.0 (the repo's
  experiment default), single pass.
- Every raw response is appended to runs_forward.jsonl with ISO-8601 UTC
  timestamps; failed calls are recorded, never silently retried into cleanliness.
- Aggregation = coordinate-wise median of parsed (point, ci_low, ci_high)
  across a cell's successful repeats. No other transformation.

Usage:
  python3 forward_harness.py run          # execute the 144-call grid
  python3 forward_harness.py aggregate    # medians -> forecasts_forward.json
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))  # experiments/billimpact

import harness as H  # noqa: E402
import extended_harness as EH  # noqa: E402

TARGETS = json.loads((HERE / "targets_forward.json").read_text())["selected"]
RUNS_PATH = HERE / "runs_forward.jsonl"
PROMPTS_DIR = HERE / "artifacts" / "prompts"
RESPONSES_DIR = HERE / "artifacts" / "responses"

LANES = {
    "L1": {"lane": "L1", "model_label": "sonnet-5", "model": "claude-sonnet-5",
           "elicitation": "point_ci_json"},
    "L2": {"lane": "L2", "model_label": "sonnet-5", "model": "claude-sonnet-5",
           "elicitation": "decomposed_json"},
    "L3": {"lane": "L3", "model_label": "fable-5", "model": "claude-fable-5",
           "elicitation": "point_ci_json"},
    # The amendment grid reached haiku through its dated API id; plain
    # "claude-haiku-4.5" is not an API model id (see runs_amend.jsonl).
    "L4": {"lane": "L4", "model_label": "haiku-4.5",
           "model": "claude-haiku-4-5-20251001", "elicitation": "point_ci_json"},
}
REPEATS = 3
TEMPERATURE = 1.0

TASK_FORWARD = """You are forecasting a US public-benefit program indicator. This is a FORWARD
forecast: the target value had not been published anywhere when this prompt was
built.

TARGET
  Series: {series_desc}
  Values are in the same units as the history shown below, exactly as stated.
  Target period: {period_label}.

RESOLUTION RULE (this rule defines exactly the number you are forecasting)
{resolution_rule}

WHAT YOU KNOW
  The most recent published history available to this run is given below.
  Nothing more recent was available to this run.

HISTORY ({history_units})
{history_block}
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def format_history(target: dict) -> tuple[str, str]:
    unit = target["target"]["unit"]
    rows = []
    for r in target["history"]:
        label = r["month"]
        v = r["value"]
        if unit == "count":
            val = f"{int(v):,}" if float(v).is_integer() else f"{v}"
        else:
            val = f"{v:.3f}"
        rows.append(f"  {label}  {val}")
    units_desc = "period, value in millions" if unit != "count" else (
        "item, value; counts are persons, shares are percent as labelled")
    return "\n".join(rows), units_desc


def build_prompt(target: dict, lane: dict) -> str:
    history_block, history_units = format_history(target)
    base = TASK_FORWARD.format(
        series_desc=target["series_desc"],
        period_label=target["period_label"],
        resolution_rule=target["target"]["resolutionRule"],
        history_units=history_units,
        history_block=history_block,
    )
    if lane["elicitation"] == "decomposed_json":
        instr = EH.DECOMPOSED_INSTRUCTION
    else:
        instr = H.ELICITATION_INSTRUCTIONS[lane["elicitation"]]
    return base + "\n" + instr


def anchor_for(target: dict) -> float:
    # Last numeric history value on the target's own scale. For the CA count
    # targets the first row is the count-level anchor (later rows are shares).
    if target["target"]["unit"] == "count":
        return float(target["history"][0]["value"])
    return float(target["history"][-1]["value"])


_WRITE_LOCK = threading.Lock()


def append_run(record: dict) -> None:
    with _WRITE_LOCK:
        with RUNS_PATH.open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")


def one_run(target: dict, lane: dict, repeat: int) -> dict:
    prompt = build_prompt(target, lane)
    prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()
    prompt_path = PROMPTS_DIR / f"{target['id']}__{lane['lane']}.txt"
    if not prompt_path.exists():
        with _WRITE_LOCK:
            if not prompt_path.exists():
                prompt_path.write_text(prompt)
    max_tokens = 6000 if lane["elicitation"] == "decomposed_json" else 4000
    started_at = utc_now()
    res = H.call_model(prompt, lane["model"], temperature=TEMPERATURE,
                       max_tokens=max_tokens)
    run_at = utc_now()
    record = {
        "dataPointId": target["target"]["dataPointId"],
        "targetId": target["id"],
        "lane": lane["lane"],
        "agent": f"billimpact.lane.{lane['lane']}",
        "config": {
            "model": lane["model"],
            "model_label": lane["model_label"],
            "elicitation": lane["elicitation"],
            "pipeline": "single_pass",
            "temperature": TEMPERATURE,
            "max_tokens": max_tokens,
        },
        "repeat": repeat,
        "prompt_sha256": prompt_sha,
        "prompt_path": str(prompt_path.relative_to(HERE)),
        "startedAt": started_at,
        "runAt": run_at,
        "ok": res.ok,
        "duration_s": round(res.duration_s, 2),
        "prompt_tokens": res.prompt_tokens,
        "completion_tokens": res.completion_tokens,
        "error": res.error,
        "parser_version": H.PARSER_VERSION,
    }
    if res.ok:
        record["raw_text"] = res.text
        resp_path = RESPONSES_DIR / f"{target['id']}__{lane['lane']}__r{repeat}.txt"
        resp_path.write_text(res.text)
        record["response_path"] = str(resp_path.relative_to(HERE))
        anchor = anchor_for(target)
        if lane["elicitation"] == "decomposed_json":
            record["forecast"] = EH.parse_decomposed(res.text, anchor)
        else:
            record["forecast"] = H.parse_forecast(
                res.text, lane["elicitation"], anchor)
    append_run(record)
    return record


def cmd_run() -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [
        (t, lane, r)
        for t in TARGETS
        for lane in LANES.values()
        for r in range(1, REPEATS + 1)
    ]
    print(f"{len(jobs)} calls: {len(TARGETS)} targets x {len(LANES)} lanes x "
          f"{REPEATS} repeats")
    done = ok = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(one_run, t, lane, r): (t["id"], lane["lane"], r)
                   for t, lane, r in jobs}
        for fut in as_completed(futures):
            tid, lane_id, r = futures[fut]
            try:
                rec = fut.result()
                done += 1
                ok += 1 if rec["ok"] else 0
                status = "ok" if rec["ok"] else f"ERROR {rec['error']}"
                parsed = rec.get("forecast", {})
                pt = parsed.get("point")
                print(f"[{done:3}/{len(jobs)}] {tid} {lane_id} r{r}: {status}"
                      f" point={pt}")
            except Exception as e:  # noqa: BLE001
                done += 1
                print(f"[{done:3}/{len(jobs)}] {tid} {lane_id} r{r}: "
                      f"DRIVER EXCEPTION {type(e).__name__}: {e}")
    print(f"complete: {ok}/{len(jobs)} ok")


def cmd_aggregate() -> None:
    runs = [json.loads(line) for line in RUNS_PATH.read_text().splitlines()]
    by_cell: dict[tuple[str, str], list[dict]] = {}
    for r in runs:
        by_cell.setdefault((r["dataPointId"], r["lane"]), []).append(r)
    out = []
    for t in TARGETS:
        for lane_id, lane in LANES.items():
            key = (t["target"]["dataPointId"], lane_id)
            cell_runs = sorted(by_cell.get(key, []), key=lambda r: r["repeat"])
            parsed = [r for r in cell_runs
                      if r.get("ok") and "point" in (r.get("forecast") or {})]
            entry = {
                "dataPointId": t["target"]["dataPointId"],
                "targetId": t["id"],
                "lane": lane_id,
                "agent": f"billimpact.lane.{lane_id}",
                "config": {
                    "model": lane["model"],
                    "model_label": lane["model_label"],
                    "elicitation": lane["elicitation"],
                    "pipeline": "single_pass",
                    "temperature": TEMPERATURE,
                },
                "n_runs": len(cell_runs),
                "n_parsed": len(parsed),
                "repeat_points": [r["forecast"]["point"] for r in parsed],
                "repeat_ci_low": [r["forecast"]["ci_low"] for r in parsed],
                "repeat_ci_high": [r["forecast"]["ci_high"] for r in parsed],
                "repeat_rationales": [
                    (r.get("forecast") or {}).get("rationale") for r in parsed],
                "repeat_run_ats": [r["runAt"] for r in parsed],
                "response_paths": [r.get("response_path") for r in parsed],
                "prompt_path": cell_runs[0]["prompt_path"] if cell_runs else None,
                "prompt_sha256": cell_runs[0]["prompt_sha256"] if cell_runs else None,
            }
            if lane["elicitation"] == "decomposed_json":
                entry["repeat_baseline_no_policy"] = [
                    (r["forecast"].get("baseline_no_policy")) for r in parsed]
                entry["repeat_policy_delta"] = [
                    (r["forecast"].get("policy_delta")) for r in parsed]
            if parsed:
                entry["point"] = statistics.median(entry["repeat_points"])
                entry["ci_low"] = statistics.median(entry["repeat_ci_low"])
                entry["ci_high"] = statistics.median(entry["repeat_ci_high"])
                entry["runAt"] = max(entry["repeat_run_ats"])
                entry["bracket_ok"] = bool(
                    entry["ci_low"] <= entry["point"] <= entry["ci_high"]
                    and entry["ci_low"] < entry["ci_high"])
            else:
                entry["point"] = entry["ci_low"] = entry["ci_high"] = None
                entry["runAt"] = max((r["runAt"] for r in cell_runs), default=None)
                entry["bracket_ok"] = False
            out.append(entry)
    # rationale field only exists on the JSON elicitation paths; scrub Nones
    for e in out:
        e["repeat_rationales"] = [x for x in e["repeat_rationales"] if x]
    agg = {
        "aggregatedAt": utc_now(),
        "method": "coordinate-wise median of parsed repeats per (target, lane)",
        "cells": out,
    }
    (HERE / "forecasts_forward.json").write_text(json.dumps(agg, indent=2))
    n_ok = sum(1 for e in out if e["point"] is not None)
    print(f"aggregated {n_ok}/{len(out)} cells -> forecasts_forward.json")
    bad = [e for e in out if e["point"] is not None and not e["bracket_ok"]]
    for e in bad:
        print(f"  BRACKET VIOLATION {e['dataPointId']} {e['lane']}: "
              f"point={e['point']} ci=[{e['ci_low']}, {e['ci_high']}]")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        cmd_run()
    elif cmd == "aggregate":
        cmd_aggregate()
    else:
        raise SystemExit(f"unknown command: {cmd}")
