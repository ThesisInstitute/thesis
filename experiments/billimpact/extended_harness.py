"""Amendment-1 harness: Corpus B (4 events / 4 programs), decomposed elicitation,
and the FPUC dollar-perturbation. Design frozen in PREREG-AMENDMENT-1.md.

Reuses the v2 parser and transport from `harness` — no parsing logic is
duplicated here, so the two corpora cannot drift apart.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402

PROVISIONS_B = json.loads((HERE / "provisions_extra.json").read_text())

# Series descriptions. Titles verified against FRED (og:title for the first
# three; search-title + component-sum check for W823RC1). Units are NOT
# asserted — the prompt points at the history's own scale instead.
SERIES_DESC = {
    "W826RC1": "US personal current transfer receipts: government social benefits to persons: veterans' benefits (monthly, national)",
    "W823RC1": "US personal current transfer receipts: government social benefits to persons: social security (monthly, national)",
    "W825RC1": "US personal current transfer receipts: government social benefits to persons: unemployment insurance (monthly, national)",
    "W729RC1": "US personal current transfer receipts: government social benefits to persons: Medicaid (monthly, national)",
}

# FPUC dollar perturbation (amendment arm J). Applies ONLY to the FPUC event's
# operative text. Expected response of a DERIVING model: monotone in the
# supplement — third < actual < tripled — with first-order spread, because the
# supplement mechanically dominates this series in the target months.
FPUC_EVENT = "PL116-260-divN-tII-ch1-s203"
# The operative text is an AMENDMENT that strikes the prior "$600" rate and
# inserts the new one, so a "double to $600" perturbation would produce a
# no-op statute (strike $600, insert $600). $900/$100 keep the amendment
# coherent: only the INSERTED rate moves. Registered expectation for a
# deriving model: monotone response, third($100) < actual($300) < tripled($900).
DOLLAR_SUBSTITUTIONS = {
    "actual": [],
    "tripled": [("$300", "$900")],
    "third": [("$300", "$100")],
}


def apply_dollar_magnitude(text: str, magnitude: str) -> tuple[str, int]:
    subs = DOLLAR_SUBSTITUTIONS[magnitude]
    n = 0
    for old, new in subs:
        text, k = re.subn(re.escape(old), new, text)
        n += k
    return text, n


def build_context_b(policy_event: str, level: str, magnitude: str = "actual") -> tuple[str, dict]:
    ev = PROVISIONS_B[policy_event]
    meta = {"level": level, "magnitude": magnitude, "substitutions": 0, "event": policy_event}
    if level == "none":
        return "", meta
    if level == "summary":
        # context_long_title is the event's own one-line description from the
        # verified extraction; keep it neutral and operational.
        return (
            "POLICY CONTEXT (operational description):\n"
            + ev.get("context_long_title", ev["law"]),
            meta,
        )
    if level == "operative_only":
        parts = []
        total = 0
        for key, text in ev["operative"].items():
            if policy_event == FPUC_EVENT and magnitude != "actual":
                text, n = apply_dollar_magnitude(text, magnitude)
                total += n
            parts.append(text)
        meta["substitutions"] = total
        meta["provisions"] = list(ev["operative"])
        header = f"POLICY CONTEXT (verbatim statutory text, {ev['law']}):"
        return header + "\n\n" + "\n\n".join(parts), meta
    raise ValueError(f"unknown corpus-B policy_context level: {level}")


TASK_B = """You are forecasting a US public-program indicator.

TARGET
  Series: {series_desc}
  FRED series id: {series_id}
  Values are in the same units as the history shown below, exactly as published.
  Target month: {target_label}.

WHAT YOU KNOW
  The published history of this series, as it stood at the forecast origin, is
  given below. Nothing after the last row was available at the origin.
  Forecast origin: {origin_label}.

HISTORY (month, value)
{history_block}
"""

DECOMPOSED_INSTRUCTION = """Decompose the forecast before you state it:
1. BASELINE: what would the target month's value be with NO change in policy —
   pure continuation of the history's trend and seasonality?
2. POLICY DELTA: separately, what is the effect of the policy context supplied
   (zero if none was supplied or if it has no mechanical effect on this series
   by the target month)? State the mechanism in one clause.
3. Your point forecast = baseline + delta. Give an 80% central credible
   interval around it.

Respond with ONLY a JSON object, no prose before or after:
{"baseline_no_policy": <number>, "policy_delta": <number>, "point": <number>, "ci_low": <number>, "ci_high": <number>, "rationale": "<one sentence>"}"""


def format_history_b(history: list[dict], max_rows: int = 60) -> str:
    rows = history[-max_rows:]
    return "\n".join(f"  {r['month'][:7]}  {r['value']:,.1f}" for r in rows)


def build_prompt_b(unit: dict, config: dict) -> tuple[str, dict]:
    ctx, meta = build_context_b(
        unit["policy_event"], config["policy_context"], config.get("magnitude", "actual")
    )
    base = TASK_B.format(
        series_desc=SERIES_DESC[unit["series_id"]],
        series_id=unit["series_id"],
        target_label=H.month_label(unit["target_month"]),
        origin_label=H.month_label(unit["origin_vintage"]),
        history_block=format_history_b(unit["history"]),
    )
    parts = [base]
    if ctx:
        parts.append(ctx)
    if config["elicitation"] == "decomposed_json":
        parts.append(DECOMPOSED_INSTRUCTION)
    else:
        parts.append(H.ELICITATION_INSTRUCTIONS[config["elicitation"]])
    return "\n\n".join(parts), meta


def parse_decomposed(text: str, anchor: Optional[float]) -> dict:
    """Parse the decomposed schema; falls back to the shared v2 parser."""
    obj = H._last_json_object(text)
    if obj is not None and "point" in obj:
        p = H._to_float(obj.get("point"))
        lo = H._to_float(obj.get("ci_low"))
        hi = H._to_float(obj.get("ci_high"))
        if p is not None and lo is not None and hi is not None:
            if lo > hi:
                lo, hi = hi, lo
            out = {"point": p, "ci_low": lo, "ci_high": hi, "parse_mode": "decomposed_json"}
            b = H._to_float(obj.get("baseline_no_policy"))
            d = H._to_float(obj.get("policy_delta"))
            if b is not None:
                out["baseline_no_policy"] = b
            if d is not None:
                out["policy_delta"] = d
            return out
    return H.parse_forecast(text, "point_ci_json", anchor)


def run_single_b(unit: dict, config: dict) -> dict:
    """Single-pass run for a Corpus B unit (or SNAP unit with decomposed elic)."""
    corpus = config.get("corpus", "B")
    if corpus == "A":
        # SNAP unit through the original context builder, decomposed elicitation.
        provisions = json.loads((HERE / "provisions.json").read_text())
        ctx, meta = H.build_policy_context(
            provisions, config["policy_context"], config.get("magnitude", "actual")
        )
        base = H.BASE_TASK.format(
            state=unit["state"],
            state_name=H.STATE_NAMES[unit["state"]],
            target_month_label=H.month_label(unit["target_month"]),
            origin_label=H.month_label(unit["origin_vintage"]),
            history_block=H.format_history(unit["history"]),
        )
        parts = [base] + ([ctx] if ctx else []) + [DECOMPOSED_INSTRUCTION]
        prompt = "\n\n".join(parts)
    else:
        prompt, meta = build_prompt_b(unit, config)

    rec: dict = {
        "unit_id": unit["unit_id"],
        "config": dict(config),
        "context_meta": meta,
        "prompt_chars": len(prompt),
        "parser_version": H.PARSER_VERSION,
    }
    res = H.call_model(prompt, config["model"], max_tokens=6000,
                       effort=config.get("effort"))
    rec["calls"] = [{
        "role": "draft", "ok": res.ok, "duration_s": round(res.duration_s, 2),
        "prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens,
        "error": res.error,
    }]
    if not res.ok:
        rec["error"] = res.error
        return rec
    rec["final_text"] = res.text
    anchor = H.history_anchor(unit)
    if config["elicitation"] == "decomposed_json":
        rec["forecast"] = parse_decomposed(res.text, anchor)
    else:
        rec["forecast"] = H.parse_forecast(res.text, config["elicitation"], anchor)
    return rec
