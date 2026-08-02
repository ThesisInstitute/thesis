"""Wave-2 cross-type accuracy arms: 4 units (2018 Section 301 tariffs ->
quarterly customs duties; FRA-2023 s271 student-loan restart -> monthly
personal interest payments) x claude-opus-5 x {none, operative_only} x
point_ci_json x 5 reps, plus operative_only x decomposed_json x 5 reps.

Reuses extended_harness.run_single_b unchanged. Wave-2 series descriptions and
provisions are injected into the imported module's dicts AT RUNTIME (a local
extension, per the wave-2 brief) — extended_harness.py itself is not modified.
Records mirror runs_bakeoff.jsonl: config dict (corpus "B2"), rep, cell_key
(prefix "W2"), truth = first print.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import extended_harness as X  # noqa: E402

MODEL = "claude-opus-5"
REPS = 5

# Local SERIES_DESC extension. Titles verified 2026-07-31 by retrieved search
# results carrying the canonical FRED/ALFRED page titles against the exact
# /series/<ID> URLs (see WAVE2_NOTES.md section 0), plus event-signature checks
# in the data. The quarterly-dating convention for the BEA quarterly series is
# stated so the month-labelled prompt is not misleading.
WAVE2_SERIES_DESC = {
    "B235RC1Q027SBEA": (
        "US federal government current tax receipts: taxes on production and "
        "imports: customs duties (quarterly, at seasonally adjusted annual rate; "
        "observations are dated by the first month of their quarter, so the "
        "target month names a quarter — e.g. 'October 2018' is 2018Q4; national)"
    ),
    "B069RC1": "US personal interest payments (monthly, national)",
}

PROVISIONS_W2 = json.loads((HERE / "provisions_wave2.json").read_text())


def inject() -> None:
    X.SERIES_DESC.update(WAVE2_SERIES_DESC)
    X.PROVISIONS_B.update(PROVISIONS_W2)


def main() -> None:
    inject()
    units = {
        u["unit_id"]: u
        for u in json.loads((HERE / "ground_truth_wave2.json").read_text())
        if u.get("truth", {}).get("first_print_value") is not None
    }
    plan = []
    for uid in sorted(units):
        for rep in range(1, REPS + 1):
            for ctx in ("none", "operative_only"):
                plan.append((uid, {"corpus": "B2", "policy_context": ctx,
                                   "elicitation": "point_ci_json", "model": MODEL,
                                   "magnitude": "actual"}, rep))
            plan.append((uid, {"corpus": "B2", "policy_context": "operative_only",
                               "elicitation": "decomposed_json", "model": MODEL,
                               "magnitude": "actual"}, rep))

    out_path = HERE / "runs_wave2.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                    # Errored records (e.g. the 2026-07-31 workspace-quota
                    # exhaustion) do NOT count as done: a rerun retries them.
                    if rec.get("error") is None and not any(
                        c.get("error") for c in rec.get("calls", [])
                    ):
                        done.add(rec["cell_key"])
                except Exception:  # noqa: BLE001
                    pass

    def key(uid: str, cfg: dict, rep: int) -> str:
        return "|".join(["W2", uid, cfg["policy_context"], cfg["elicitation"],
                         cfg["model"], str(rep)])

    todo = [(u, c, r) for u, c, r in plan if key(u, c, r) not in done]
    print(f"units={len(units)} planned={len(plan)} todo={len(todo)}", flush=True)

    out = out_path.open("a")
    lock = threading.Lock()
    n = [0]
    t0 = time.time()

    def work(item):
        uid, cfg, rep = item
        try:
            rec = X.run_single_b(units[uid], cfg)
        except Exception as e:  # noqa: BLE001
            rec = {"unit_id": uid, "config": dict(cfg), "error": f"{type(e).__name__}: {e}"}
        rec["rep"] = rep
        rec["cell_key"] = key(uid, cfg, rep)
        rec["truth"] = units[uid]["truth"]["first_print_value"]
        with lock:
            out.write(json.dumps(rec) + "\n")
            out.flush()
            n[0] += 1
            if n[0] % 10 == 0:
                r = n[0] / (time.time() - t0)
                print(f"[{n[0]}/{len(todo)}] {r:.2f}/s eta={(len(todo) - n[0]) / r / 60:.1f}min",
                      flush=True)

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(work, todo))
    out.close()
    print(f"DONE {n[0]} in {(time.time() - t0) / 60:.1f}min", flush=True)


if __name__ == "__main__":
    main()
