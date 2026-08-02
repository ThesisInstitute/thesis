"""Knowledge probe: recall questions with no forecasting frame.

Registered in PREREG-AMENDMENT-3.md (appendix, 2026-07-31) before any run.
For each accuracy-corpus unit, ask the model what the value WAS, as first
published — the anchored variant shows the last 12 history rows for
orientation; the bare variant shows nothing. The probe measures RECALL;
the payoff analysis stratifies EXISTING forecast results by probe-classified
KNOWN/UNKNOWN, so no new forecast runs are implicated.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
from probe_fix import generic_last_json, to_float  # noqa: E402  (H._last_json_object requires "point")

# Series descriptions, verbatim from extended_harness.SERIES_DESC (first 4)
# and booking_sweep.SERIES_DESC (last 4); titles were FRED-verified when
# those modules were written.
DESC = {
    "W826RC1": "US personal current transfer receipts: government social benefits to persons: veterans' benefits (monthly, national)",
    "W823RC1": "US personal current transfer receipts: government social benefits to persons: social security (monthly, national)",
    "W825RC1": "US personal current transfer receipts: government social benefits to persons: unemployment insurance (monthly, national)",
    "W729RC1": "US personal current transfer receipts: government social benefits to persons: Medicaid (monthly, national)",
    "B235RC1Q027SBEA": "US federal customs duties receipts (quarterly, SAAR; observations dated by first month of quarter; national)",
    "B069RC1": "US personal interest payments (monthly, national)",
    "W827RC1": "US personal current transfer receipts: government social benefits to persons: other (monthly, national)",
    "PBHWYCONS": "US Census value of public construction put in place: highway and street (monthly, national)",
}

Q_ANCHORED = """Answer from memory. As FIRST PUBLISHED (the initial vintage, before any later revision), what was the value of this series?
  Series: {desc}
  FRED series id: {sid}
  Month: {label}
Recent published history, for orientation only (it ends before the month asked about):
{hist}
Respond with ONLY JSON:
{{"value": <number in the same units as the history>, "basis": "known" | "estimate" | "guess"}}"""

Q_BARE = """Answer from memory. As FIRST PUBLISHED (the initial vintage, before any later revision), what was the value of this series?
  Series: {desc}
  FRED series id: {sid}
  Month: {label}
Respond with ONLY JSON:
{{"value": <number>, "basis": "known" | "estimate" | "guess"}}"""


def load_units() -> dict:
    units: dict = {}
    for f in ("ground_truth_B_all.json", "ground_truth_crosstype.json", "ground_truth_wave2.json"):
        for u in json.loads((HERE / f).read_text()):
            if u.get("truth", {}).get("first_print_value") is not None:
                units[u["unit_id"]] = u
    return units


def fmt_hist(history: list[dict]) -> str:
    return "\n".join(f"  {r['month'][:7]}  {r['value']:,.1f}" for r in history[-12:])


def main() -> None:
    units = load_units()
    assert len(units) == 36, f"expected 36 accuracy units, got {len(units)}"
    out_path = HERE / "runs_probe.jsonl"
    done: set = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            try:
                done.add(json.loads(line)["cell_key"])
            except Exception:  # noqa: BLE001
                continue
    plan = [
        (uid, model, variant, rep)
        for uid in sorted(units)
        for model in ("claude-opus-5", "claude-fable-5")
        for variant in ("anchored", "bare")
        for rep in (1, 2, 3)
    ]
    plan = [p for p in plan if f"KP|{p[0]}|{p[1]}|{p[2]}|{p[3]}" not in done]
    print(f"probe todo={len(plan)}", flush=True)
    out = out_path.open("a")
    lock = threading.Lock()
    n = [0]
    t0 = time.time()

    def work(item):
        uid, model, variant, rep = item
        u = units[uid]
        tmpl = Q_ANCHORED if variant == "anchored" else Q_BARE
        prompt = tmpl.format(
            desc=DESC[u["series_id"]],
            sid=u["series_id"],
            label=H.month_label(u["target_month"]),
            hist=fmt_hist(u["history"]) if variant == "anchored" else "",
        )
        # 2000, not 400: opus burned a 400 cap on deliberation and returned
        # empty content on 98/432 first-pass calls (worst on anchored).
        res = H.call_model(prompt, model, max_tokens=2000)
        rec = {
            "cell_key": f"KP|{uid}|{model}|{variant}|{rep}",
            "unit_id": uid, "model": model, "variant": variant, "rep": rep,
            "series_id": u["series_id"], "target_month": u["target_month"],
            "truth": u["truth"]["first_print_value"],
            "transport": os.environ.get("BILLIMPACT_TRANSPORT", "anthropic"),
        }
        if res.ok:
            obj = generic_last_json(res.text) or {}
            rec["recall"] = to_float(obj.get("value"))
            if rec["recall"] is None:
                m = re.search(r'"value"\s*:\s*"?\$?([-\d.,]+)', res.text)
                rec["recall"] = H._to_float(m.group(1)) if m else None
            rec["basis"] = obj.get("basis")
            rec["text"] = res.text[:600]
        else:
            rec["error"] = res.error
        with lock:
            out.write(json.dumps(rec) + "\n")
            out.flush()
            n[0] += 1
            if n[0] % 50 == 0:
                print(f"[{n[0]}/{len(plan)}] {(time.time() - t0) / 60:.1f}min", flush=True)

    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(work, plan))
    out.close()
    print(f"PROBE DONE n={n[0]} elapsed={(time.time() - t0) / 60:.1f}min", flush=True)


if __name__ == "__main__":
    main()
