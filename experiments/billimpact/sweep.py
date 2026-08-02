"""Run the pre-registered ablation grid. Design frozen in PREREGISTRATION.md.

Arms A-D are unioned, not summed: a (unit, config, rep) cell that appears in
more than one arm is executed once and reused. Results stream to JSONL so the
sweep is resumable and a crash never loses completed work.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402

SONNET = "claude-sonnet-5"
OPUS = "claude-opus-5"
HAIKU = "claude-haiku-4-5-20251001"
FABLE = "claude-fable-5"

POLICY_CONTEXTS = ["none", "summary", "operative_only", "purpose_only", "operative_plus_purpose"]
ELICITATIONS = ["point_ci_json", "free_text", "cot_then_json", "forced_choice_bins"]
# D4 amended 2026-07-31: Fable added as a fourth tier. Strictly additive —
# haiku-4.5 is retained, so no level is dropped after seeing data. Model tier is declared exploratory in PREREGISTRATION.md.
MODELS = [OPUS, SONNET, HAIKU, FABLE]
MAGNITUDES = ["actual", "severe", "inert"]

REPS = 5


def cell_key(unit_id: str, cfg: dict, rep: int) -> str:
    return "|".join(
        [
            unit_id,
            cfg["policy_context"],
            cfg["elicitation"],
            cfg["pipeline"],
            cfg["model"],
            cfg["magnitude"],
            str(rep),
        ]
    )


def build_plan(unit_ids: list[str]) -> list[tuple[str, dict, int, list[str]]]:
    """Return [(unit_id, config, rep, arms)] with shared cells de-duplicated."""
    plan: dict[str, tuple[str, dict, int, list[str]]] = {}

    def add(unit_id: str, cfg: dict, rep: int, arm: str) -> None:
        k = cell_key(unit_id, cfg, rep)
        if k in plan:
            if arm not in plan[k][3]:
                plan[k][3].append(arm)
            return
        plan[k] = (unit_id, cfg, rep, [arm])

    for uid in unit_ids:
        for rep in range(1, REPS + 1):
            # Arm A — primary: policy_context x elicitation
            for ctx in POLICY_CONTEXTS:
                for elic in ELICITATIONS:
                    add(uid, {"policy_context": ctx, "elicitation": elic,
                              "pipeline": "single_pass", "model": SONNET,
                              "magnitude": "actual"}, rep, "A")
            # Arm B — model tier
            for model in MODELS:
                for ctx in POLICY_CONTEXTS:
                    add(uid, {"policy_context": ctx, "elicitation": "point_ci_json",
                              "pipeline": "single_pass", "model": model,
                              "magnitude": "actual"}, rep, "B")
            # Arm C — pipeline (debate)
            for ctx in POLICY_CONTEXTS:
                add(uid, {"policy_context": ctx, "elicitation": "point_ci_json",
                          "pipeline": "debate", "model": SONNET,
                          "magnitude": "actual"}, rep, "C")
            # Arm D — contamination / magnitude
            for mag in MAGNITUDES:
                add(uid, {"policy_context": "operative_only", "elicitation": "point_ci_json",
                          "pipeline": "single_pass", "model": SONNET,
                          "magnitude": mag}, rep, "D")

    return list(plan.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "runs.jsonl")
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--limit", type=int, default=0, help="cap runs (smoke mode)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gt = json.loads((HERE / "ground_truth.json").read_text())
    units = {u["unit_id"]: u for u in gt if u.get("truth", {}).get("first_print_value") is not None}
    provisions = json.loads((HERE / "provisions.json").read_text())

    plan = build_plan(sorted(units))
    if args.limit:
        plan = plan[: args.limit]

    done: set[str] = set()
    if args.out.exists():
        for line in args.out.read_text().splitlines():
            if not line.strip():
                continue
            try:
                done.add(json.loads(line)["cell_key"])
            except Exception:  # noqa: BLE001
                continue

    todo = [p for p in plan if cell_key(p[0], p[1], p[2]) not in done]
    n_calls = sum(4 if p[1]["pipeline"] == "debate" else 1 for p in todo)
    print(f"units={len(units)} planned={len(plan)} already_done={len(done)} todo={len(todo)} "
          f"est_api_calls={n_calls}", flush=True)
    if args.dry_run:
        from collections import Counter
        print(Counter(tuple(sorted(p[3])) for p in plan))
        return

    lock = threading.Lock()
    counter = {"n": 0, "ok": 0, "parse_fail": 0, "err": 0}
    start = time.time()
    fh = args.out.open("a")

    def work(item):
        unit_id, cfg, rep, arms = item
        rec = H.run_single(units[unit_id], provisions, cfg)
        rec["rep"] = rep
        rec["arms"] = arms
        rec["cell_key"] = cell_key(unit_id, cfg, rep)
        rec["truth"] = units[unit_id]["truth"]["first_print_value"]
        # drop bulky raw text for non-debate single passes to keep the file sane,
        # but always keep the final text so any parse can be re-derived later.
        rec.pop("draft_text", None) if cfg["pipeline"] == "single_pass" else None
        with lock:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            counter["n"] += 1
            if rec.get("error"):
                counter["err"] += 1
            elif "parse_error" in rec.get("forecast", {}):
                counter["parse_fail"] += 1
            else:
                counter["ok"] += 1
            if counter["n"] % 50 == 0:
                el = time.time() - start
                rate = counter["n"] / el
                left = (len(todo) - counter["n"]) / rate if rate else 0
                print(f"  [{counter['n']}/{len(todo)}] ok={counter['ok']} "
                      f"parse_fail={counter['parse_fail']} err={counter['err']} "
                      f"{rate:.1f}/s eta={left/60:.1f}min", flush=True)
        return None

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))
    fh.close()
    print(f"DONE n={counter['n']} ok={counter['ok']} parse_fail={counter['parse_fail']} "
          f"err={counter['err']} elapsed={(time.time()-start)/60:.1f}min", flush=True)


if __name__ == "__main__":
    main()
