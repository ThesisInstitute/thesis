"""Run Amendment-1 arms H/I/J/K. Plan frozen in PREREG-AMENDMENT-1.md §E."""
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

import extended_harness as X  # noqa: E402

SONNET = "claude-sonnet-5"
OPUS = "claude-opus-5"
FABLE = "claude-fable-5"
HAIKU = "claude-haiku-4-5-20251001"

CTX_B = ["none", "summary", "operative_only"]
REPS = 5


def cell_key(uid: str, cfg: dict, rep: int) -> str:
    return "|".join([cfg.get("corpus", "B"), uid, cfg["policy_context"], cfg["elicitation"],
                     cfg["model"], cfg.get("magnitude", "actual"), str(rep)])


def build_plan(units_b: list[str], units_a: list[str]) -> list[tuple]:
    plan: dict[str, tuple] = {}

    def add(uid, cfg, rep, arm):
        k = cell_key(uid, cfg, rep)
        if k in plan:
            if arm not in plan[k][3]:
                plan[k][3].append(arm)
            return
        plan[k] = (uid, cfg, rep, [arm])

    fpuc_units = [u for u in units_b if u.startswith("fpuc")]
    for rep in range(1, REPS + 1):
        # H — dispersion + skill on Corpus B
        for uid in units_b:
            for ctx in CTX_B:
                for elic in ("point_ci_json", "decomposed_json"):
                    add(uid, {"corpus": "B", "policy_context": ctx, "elicitation": elic,
                              "model": SONNET, "magnitude": "actual"}, rep, "H")
        # I — model breadth incl. the frozen bake-off selection (fable)
        for uid in units_b:
            for model in (OPUS, FABLE, HAIKU):
                for ctx in ("none", "operative_only"):
                    add(uid, {"corpus": "B", "policy_context": ctx,
                              "elicitation": "point_ci_json", "model": model,
                              "magnitude": "actual"}, rep, "I")
        # J — FPUC dollar perturbation
        for uid in fpuc_units:
            for mag in ("actual", "tripled", "third"):
                for elic in ("point_ci_json", "decomposed_json"):
                    add(uid, {"corpus": "B", "policy_context": "operative_only",
                              "elicitation": elic, "model": SONNET,
                              "magnitude": mag}, rep, "J")
                add(uid, {"corpus": "B", "policy_context": "operative_only",
                          "elicitation": "point_ci_json", "model": FABLE,
                          "magnitude": mag}, rep, "J")
        # K — decomposed unmasking on the SNAP magnitude arm
        for uid in units_a:
            for mag in ("actual", "severe", "inert"):
                add(uid, {"corpus": "A", "policy_context": "operative_only",
                          "elicitation": "decomposed_json", "model": SONNET,
                          "magnitude": mag}, rep, "K")
    return list(plan.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "runs_amend.jsonl")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gt_b = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth_extra.json").read_text())
            if u.get("truth", {}).get("first_print_value") is not None}
    gt_a = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth.json").read_text())
            if u.get("truth", {}).get("first_print_value") is not None}
    units = {**gt_b, **gt_a}

    plan = build_plan(sorted(gt_b), sorted(gt_a))
    if args.limit:
        plan = plan[: args.limit]

    done: set[str] = set()
    if args.out.exists():
        for line in args.out.read_text().splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["cell_key"])
                except Exception:  # noqa: BLE001
                    pass
    todo = [p for p in plan if cell_key(p[0], p[1], p[2]) not in done]
    print(f"units B={len(gt_b)} A={len(gt_a)} planned={len(plan)} done={len(done)} todo={len(todo)}",
          flush=True)
    if args.dry_run:
        from collections import Counter
        print(Counter(tuple(sorted(p[3])) for p in plan))
        return

    lock = threading.Lock()
    counter = {"n": 0, "ok": 0, "parse_fail": 0, "err": 0}
    start = time.time()
    fh = args.out.open("a")

    def work(item):
        uid, cfg, rep, arms = item
        try:
            rec = X.run_single_b(units[uid], cfg)
        except Exception as e:  # noqa: BLE001
            rec = {"unit_id": uid, "config": dict(cfg), "error": f"{type(e).__name__}: {e}"}
        rec["rep"] = rep
        rec["arms"] = arms
        rec["cell_key"] = cell_key(uid, cfg, rep)
        rec["truth"] = units[uid]["truth"]["first_print_value"]
        with lock:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            counter["n"] += 1
            if rec.get("error"):
                counter["err"] += 1
            elif "parse_error" in (rec.get("forecast") or {}):
                counter["parse_fail"] += 1
            else:
                counter["ok"] += 1
            if counter["n"] % 50 == 0:
                el = time.time() - start
                rate = counter["n"] / el
                print(f"  [{counter['n']}/{len(todo)}] ok={counter['ok']} "
                      f"parse_fail={counter['parse_fail']} err={counter['err']} "
                      f"{rate:.1f}/s eta={(len(todo)-counter['n'])/rate/60:.1f}min", flush=True)

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))
    fh.close()
    print(f"DONE n={counter['n']} ok={counter['ok']} parse_fail={counter['parse_fail']} "
          f"err={counter['err']} elapsed={(time.time()-start)/60:.1f}min", flush=True)


if __name__ == "__main__":
    main()
