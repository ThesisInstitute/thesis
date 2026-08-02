"""Run the Corpus C (S.3596 / tool-access) ablation.

Headline dimension is TOOL ACCESS. Tool-using runs are much slower than
single-shot ones (a tool loop is several sequential API round-trips), so the
cross-product is deliberately narrower here than in the SNAP arm; the reps
stay at 5 because a config difference without its repeat variance is
uninterpretable.
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

import ctc_harness as C  # noqa: E402
import tools as T  # noqa: E402

SONNET = "claude-sonnet-5"
OPUS = "claude-opus-5"
FABLE = "claude-fable-5"
HAIKU = "claude-haiku-4-5-20251001"

CONTEXTS = ["summary", "operative_only_no_conforming", "full_bill"]
TOOLS = ["none", "policyengine"]
REPS = 5


def cell_key(case_id: str, cfg: dict, rep: int) -> str:
    return "|".join([case_id, cfg["policy_context"], cfg["tools"], cfg["pipeline"],
                     cfg["model"], str(rep)])


def build_plan(case_ids: list[str]) -> list[tuple]:
    plan: dict[str, tuple] = {}

    def add(cid, cfg, rep, arm):
        k = cell_key(cid, cfg, rep)
        if k in plan:
            if arm not in plan[k][3]:
                plan[k][3].append(arm)
            return
        plan[k] = (cid, cfg, rep, [arm])

    for cid in case_ids:
        for rep in range(1, REPS + 1):
            # Arm E — tool access x policy context, two model tiers
            for model in (SONNET, OPUS):
                for ctx in CONTEXTS:
                    for tool in TOOLS:
                        add(cid, {"policy_context": ctx, "tools": tool,
                                  "pipeline": "single_pass", "model": model}, rep, "E")
            # Arm F — multi-agent pipeline, held at the full bill
            for model in (SONNET, OPUS):
                for tool in TOOLS:
                    add(cid, {"policy_context": "full_bill", "tools": tool,
                              "pipeline": "multi_agent", "model": model}, rep, "F")
            # Arm G — cross-model breadth at one reference config
            for model in (FABLE, HAIKU):
                for tool in TOOLS:
                    add(cid, {"policy_context": "full_bill", "tools": tool,
                              "pipeline": "single_pass", "model": model}, rep, "G")
    return list(plan.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "runs_ctc.jsonl")
    ap.add_argument("--corpus", type=Path, default=HERE / "corpus_ctc.json")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--pe-workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = json.loads(args.corpus.read_text())
    case_list = raw["cases"] if isinstance(raw, dict) and "cases" in raw else raw
    cases = {c["case_id"]: c for c in case_list}
    plan = build_plan(sorted(cases))
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
    print(f"cases={len(cases)} planned={len(plan)} done={len(done)} todo={len(todo)}", flush=True)
    if args.dry_run:
        from collections import Counter
        print(Counter((p[1]["pipeline"], p[1]["tools"]) for p in plan))
        return

    T.pool(args.pe_workers)._ensure()
    print("policyengine pool warm", flush=True)

    lock = threading.Lock()
    counter = {"n": 0, "ok": 0, "parse_fail": 0, "err": 0, "tool_calls": 0}
    start = time.time()
    fh = args.out.open("a")

    def work(item):
        cid, cfg, rep, arms = item
        try:
            rec = C.run_ctc_single(cases[cid], cfg)
        except Exception as e:  # noqa: BLE001
            rec = {"case_id": cid, "config": dict(cfg), "error": f"{type(e).__name__}: {e}"}
        rec["rep"] = rep
        rec["arms"] = arms
        rec["cell_key"] = cell_key(cid, cfg, rep)
        with lock:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            counter["n"] += 1
            counter["tool_calls"] += rec.get("tool_calls", 0) or 0
            if rec.get("error"):
                counter["err"] += 1
            elif "parse_error" in (rec.get("answer") or {}):
                counter["parse_fail"] += 1
            else:
                counter["ok"] += 1
            if counter["n"] % 25 == 0:
                el = time.time() - start
                rate = counter["n"] / el
                print(f"  [{counter['n']}/{len(todo)}] ok={counter['ok']} "
                      f"parse_fail={counter['parse_fail']} err={counter['err']} "
                      f"tools={counter['tool_calls']} {rate:.2f}/s "
                      f"eta={(len(todo)-counter['n'])/rate/60:.1f}min", flush=True)

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))
    fh.close()
    print(f"DONE n={counter['n']} ok={counter['ok']} parse_fail={counter['parse_fail']} "
          f"err={counter['err']} tool_calls={counter['tool_calls']} "
          f"elapsed={(time.time()-start)/60:.1f}min", flush=True)


if __name__ == "__main__":
    main()
