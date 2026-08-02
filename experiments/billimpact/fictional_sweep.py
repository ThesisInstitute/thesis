"""Fictional-identity arm: same units, real history values, identity blocked.

Registered in PREREG-AMENDMENT-3.md (appendix, 2026-07-31) before any run.
ONE builder produces both frames, so the paired contrast never crosses
builders: 'real' carries the true series title, FRED id, and statute
citation; 'fictional' carries a generic type description, no id, the
deconfound arm's statute redaction, an explicit self-contained-hypothetical
instruction, and a post-forecast recognition self-report (a manipulation
check, not a gate). Config mirrors the study's winning cell: fable-5, bill
context, point+80% CI JSON, effort=max. Calendar dates and dollar amounts
are retained — they are mechanism, not identity; residual identifiability
through them is what the self-report measures.
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

MODEL = "claude-fable-5"
EFFORT = "max"
REPS = 3

DESC_REAL = {
    "W826RC1": "US personal current transfer receipts: government social benefits to persons: veterans' benefits (monthly, national)",
    "W823RC1": "US personal current transfer receipts: government social benefits to persons: social security (monthly, national)",
    "W825RC1": "US personal current transfer receipts: government social benefits to persons: unemployment insurance (monthly, national)",
    "W729RC1": "US personal current transfer receipts: government social benefits to persons: Medicaid (monthly, national)",
    "B235RC1Q027SBEA": "US federal customs duties receipts (quarterly, SAAR; observations dated by first month of quarter; national)",
    "B069RC1": "US personal interest payments (monthly, national)",
    "W827RC1": "US personal current transfer receipts: government social benefits to persons: other (monthly, national)",
    "PBHWYCONS": "US Census value of public construction put in place: highway and street (monthly, national)",
}

# Generic type descriptions: program KIND preserved (mechanism needs it),
# every proper noun and official title removed (identity does not survive).
DESC_FICTIONAL = {
    "W826RC1": "monthly aggregate of government benefits paid to former military service members",
    "W823RC1": "monthly aggregate of public old-age and survivors' pension benefits paid to persons",
    "W825RC1": "monthly aggregate of government unemployment-insurance benefits paid to persons",
    "W729RC1": "monthly aggregate of government health-insurance benefit payments made on behalf of low-income persons",
    "B235RC1Q027SBEA": "quarterly aggregate of customs-duty receipts collected by the national government (seasonally adjusted annual rate; observations dated by the first month of each quarter)",
    "B069RC1": "monthly aggregate of interest payments made by households",
    "W827RC1": "monthly aggregate of miscellaneous government social benefits to persons (residual category)",
    "PBHWYCONS": "monthly value of public construction put in place for roads and highways",
}

TASK_REAL = """You are forecasting a US public-program indicator.

TARGET
  Series: {desc}
  FRED series id: {sid}
  Values are in the same units as the history shown below, exactly as published.
  Target month: {target_label}.

WHAT YOU KNOW
  The published history of this series, as it stood at the forecast origin, is
  given below. Nothing after the last row was available at the origin.
  Forecast origin: {origin_label}.

HISTORY (month, value)
{hist}

POLICY CONTEXT (verbatim statutory text, {law}; assume it is in force through the target month):

{operative}

Respond with ONLY JSON:
{{"point": <number>, "low80": <number>, "high80": <number>, "rationale": "<one or two sentences>"}}"""

TASK_FICTIONAL = """Treat everything below as a fully self-contained hypothetical scenario. Do not
attempt to identify any real-world series, statute, or country; reason only
from the mechanism described and the numbers shown.

You are forecasting an economic indicator in this hypothetical jurisdiction.

TARGET
  Series: {desc}
  Values are in the same units as the history shown below.
  Target month: {target_label}.

WHAT YOU KNOW
  The published history of this series, as it stood at the forecast origin, is
  given below. Nothing after the last row was available at the origin.
  Forecast origin: {origin_label}.

HISTORY (month, value)
{hist}

POLICY CONTEXT (verbatim statutory text of a statute of this jurisdiction; assume it is in force through the target month):

{operative}

After forecasting, also report whether you believe you recognized the
underlying real-world series despite the hypothetical frame.

Respond with ONLY JSON:
{{"point": <number>, "low80": <number>, "high80": <number>, "rationale": "<one or two sentences>", "recognized": "none" | "suspected" | "identified", "series_guess": <string or null>}}"""


def load_units() -> dict:
    units: dict = {}
    for f in ("ground_truth_B_all.json", "ground_truth_crosstype.json", "ground_truth_wave2.json"):
        for u in json.loads((HERE / f).read_text()):
            if u.get("truth", {}).get("first_print_value") is not None:
                units[u["unit_id"]] = u
    return units


def load_provisions() -> dict:
    merged: dict = {}
    for f in ("provisions_extra.json", "provisions_crosstype.json", "provisions_wave2.json"):
        merged.update(json.loads((HERE / f).read_text()))
    return merged


def fmt_hist(history: list[dict]) -> str:
    return "\n".join(f"  {r['month'][:7]}  {r['value']:,.1f}" for r in history[-60:])


def redact(text: str, law: str) -> str:
    # Deconfound treatment (Pub. L. citation -> "the statute") plus this
    # statute's own short title, which some operative texts repeat inline —
    # the selfcheck caught medicaid.us.2023-06 doing exactly that.
    text = re.sub(r"Pub\. L\. [0-9–—-]+", "the statute", text)
    short_title = law.split(",")[0].strip()
    if short_title:
        text = re.sub(re.escape(short_title), "the statute", text, flags=re.I)
    return text


def build_prompt(u: dict, ev: dict, frame: str) -> str:
    sid = u["series_id"]
    # operative is section-keyed; join values in registered (insertion) order,
    # exactly as extended_harness.build_context_b does.
    operative_text = "\n\n".join(ev["operative"].values())
    common = dict(
        target_label=H.month_label(u["target_month"]),
        origin_label=H.month_label(u["origin_vintage"]),
        hist=fmt_hist(u["history"]),
    )
    if frame == "real":
        return TASK_REAL.format(desc=DESC_REAL[sid], sid=sid, law=ev["law"],
                                operative=operative_text, **common)
    return TASK_FICTIONAL.format(desc=DESC_FICTIONAL[sid],
                                 operative=redact(operative_text, ev["law"]), **common)


def selfcheck(units: dict, provisions: dict) -> None:
    """Assert the redaction actually fired before any API call (negative-tested
    both directions: real keeps the citation, fictional loses it)."""
    for uid, u in units.items():
        ev = provisions[u["policy_event"]]
        real_p = build_prompt(u, ev, "real")
        fic_p = build_prompt(u, ev, "fictional")
        law = ev["law"]
        assert law.split(",")[0] in real_p, f"{uid}: law title missing from real frame"
        if "Pub. L." in law:
            assert "Pub. L." in real_p, f"{uid}: citation missing from real frame"
        assert "Pub. L." not in fic_p, f"{uid}: citation survived redaction"
        assert law.split(",")[0] not in fic_p, f"{uid}: law title leaked into fictional frame"
        assert "FRED" not in fic_p, f"{uid}: series id leaked into fictional frame"
    print(f"selfcheck OK on {len(units)} units x 2 frames", flush=True)


def main() -> None:
    units = load_units()
    assert len(units) == 36, f"expected 36 accuracy units, got {len(units)}"
    provisions = load_provisions()
    missing = {u["policy_event"] for u in units.values()} - set(provisions)
    assert not missing, f"events missing from provisions: {missing}"
    selfcheck(units, provisions)

    out_path = HERE / "runs_fictional.jsonl"
    done: set = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            try:
                done.add(json.loads(line)["cell_key"])
            except Exception:  # noqa: BLE001
                continue
    plan = [(uid, frame, rep) for uid in sorted(units)
            for frame in ("real", "fictional") for rep in range(1, REPS + 1)]
    plan = [p for p in plan if f"FIC|{p[0]}|{p[1]}|{p[2]}" not in done]
    print(f"fictional todo={len(plan)}", flush=True)
    out = out_path.open("a")
    lock = threading.Lock()
    n = [0]
    t0 = time.time()

    def work(item):
        uid, frame, rep = item
        u = units[uid]
        ev = provisions[u["policy_event"]]
        prompt = build_prompt(u, ev, frame)
        res = H.call_model(prompt, MODEL, max_tokens=6000, timeout=420.0, effort=EFFORT)
        rec = {
            "cell_key": f"FIC|{uid}|{frame}|{rep}",
            "unit_id": uid, "frame": frame, "rep": rep, "model": MODEL,
            "effort": EFFORT, "series_id": u["series_id"],
            "target_month": u["target_month"],
            "truth": u["truth"]["first_print_value"],
            "transport": os.environ.get("BILLIMPACT_TRANSPORT", "anthropic"),
        }
        if res.ok:
            obj = H._last_json_object(res.text) or {}
            rec["point"] = H._to_float(obj.get("point"))
            rec["low80"] = H._to_float(obj.get("low80"))
            rec["high80"] = H._to_float(obj.get("high80"))
            rec["recognized"] = obj.get("recognized")
            rec["series_guess"] = obj.get("series_guess")
            rec["rationale"] = str(obj.get("rationale", ""))[:400]
            if rec["point"] is None:
                rec["text"] = res.text[:500]
        else:
            rec["error"] = res.error
        with lock:
            out.write(json.dumps(rec) + "\n")
            out.flush()
            n[0] += 1
            if n[0] % 10 == 0:
                print(f"[{n[0]}/{len(plan)}] {(time.time() - t0) / 60:.1f}min", flush=True)

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(work, plan))
    out.close()
    print(f"FICTIONAL DONE n={n[0]} elapsed={(time.time() - t0) / 60:.1f}min", flush=True)


if __name__ == "__main__":
    main()
