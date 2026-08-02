"""Corpus C — S.3596 (Stronger Start for Working Families Act), tool-access arm.

This arm asks a mechanically-checkable question (by how many dollars does the
bill change a specific household's refundable CTC in TY2026) where PolicyEngine
gives exact ground truth. The ablation of interest is TOOL ACCESS: the same
question with the authoritative calculator available and without it.

The `operative_only_no_conforming` context level is the sharp one. S.3596 does
two things: §2(a) strikes "$3,000" and inserts "$1" in IRC 24(d)(1)(B)(i), and
§2(b) strikes 24(h)(6) — the TCJA override that makes the *operative* current
threshold $2,500 rather than $3,000. Show only §2(a) and a model that has not
internalised 24(h)(6) will baseline against $3,000 and get the delta wrong.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
import tools as T  # noqa: E402

BILL_PATH = HERE / "bills" / "S3596-stronger-start.clean.txt"

OPERATIONAL_SUMMARY_CTC = (
    "A bill before the 119th Congress would change how the refundable portion of "
    "the federal Child Tax Credit phases in with earnings. Under current law for "
    "tax year 2026, the refundable credit phases in at 15 percent of earnings "
    "above a threshold. The bill lowers that earned-income threshold to a nominal "
    "amount, effective for taxable years beginning after 31 December 2025. It "
    "makes no other change to the credit's rate, per-child cap, or phase-out."
)


def load_bill() -> str:
    return BILL_PATH.read_text()


def bill_operative_only() -> str:
    """§2(a) only — the conforming amendment that strikes 24(h)(6) is withheld."""
    text = load_bill()
    start = text.find("SEC. 2.")
    end = text.find("(b) C")
    if start < 0 or end < 0:
        raise RuntimeError("could not slice S.3596 operative subsection")
    return text[start:end].strip()


def build_context(level: str) -> str:
    if level == "none":
        return ""
    if level == "summary":
        return "POLICY CONTEXT (operational description):\n" + OPERATIONAL_SUMMARY_CTC
    if level == "operative_only_no_conforming":
        return (
            "POLICY CONTEXT (excerpt of the bill as introduced):\n\n"
            + bill_operative_only()
        )
    if level == "full_bill":
        return "POLICY CONTEXT (full text of the bill as introduced):\n\n" + load_bill()
    raise ValueError(f"unknown ctc policy_context level: {level}")


TASK = """You are analysing the effect of a proposed federal bill on a specific household.

HOUSEHOLD (tax year 2026)
  Filing status: {filing}
  State: {state}
  Qualifying children: {children}
  Annual employment income: ${earnings:,}

QUESTION
  By how many dollars does the bill change this household's REFUNDABLE Child Tax
  Credit for tax year 2026, relative to current law?

  Report the current-law refundable CTC, the refundable CTC if the bill were
  enacted, and the difference. A difference of zero is a valid answer.
"""

ANSWER_FORMAT = """Respond with ONLY a JSON object, no prose before or after:
{"current_law": <dollars>, "reform": <dollars>, "delta_dollars": <dollars>, "rationale": "<one sentence>"}"""

TOOL_HINT = """You have a PolicyEngine tool available, which computes the federal Child Tax
Credit for a household under either current law or a modified earned-income
phase-in threshold. Use it as you see fit."""

MULTI_AGENT_ROLES = {
    "extractor": """You are the EXTRACTOR. Read the bill excerpt below and state ONLY what it
mechanically changes: which Internal Revenue Code provision, from what value to
what value, and effective when. Quote the operative words verbatim. If the
excerpt is incomplete such that the resulting operative value is ambiguous, say
so explicitly and say what is missing. Do not estimate any dollar amounts for
any household.

{context}""",
    "analyst": """You are the ANALYST. Below is a household, an extraction of what a bill
changes, and your task.

{task}

=== EXTRACTION ===
{extraction}

{tool_hint}

Compute the household's refundable Child Tax Credit under current law and under
the bill. Show your reasoning briefly.""",
    "critic": """You are the CRITIC. Below is a household question, an extraction, and an
analyst's answer.

{task}

=== EXTRACTION ===
{extraction}

=== ANALYST ===
{analysis}

Attack the analyst's answer. Check specifically:
- Is the CURRENT-LAW baseline right? The operative threshold under current law
  for 2026 may be set by a provision the excerpt does not show.
- Does the household actually benefit, or are its earnings too low to phase in
  at all, or already high enough to reach the per-child refundable cap? A
  difference of zero is a common correct answer and is easy to get wrong.
- Is the arithmetic right given the phase-in rate?
Be concrete and brief.""",
    "judge": """You are the JUDGE. Below is a household question, an extraction, an analyst's
answer, and a critic's attack.

{task}

=== EXTRACTION ===
{extraction}

=== ANALYST ===
{analysis}

=== CRITIC ===
{critique}

{tool_hint}

Produce the final answer. {answer_format}""",
}


def parse_ctc(text: str) -> dict:
    # The harness object-scanner keys on "point", which this schema does not
    # carry, so parse the CTC blob directly. (Was a dead call to
    # H._first_json_object whose result was never read; removed when that helper
    # was renamed _last_json_object.)
    import re

    blobs = re.findall(r"\{[^{}]*\}", text, re.S)
    for blob in reversed(blobs):
        try:
            o = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and "delta_dollars" in o:
            d = H._to_float(o.get("delta_dollars"))
            if d is None:
                continue
            return {
                "delta_dollars": d,
                "current_law": H._to_float(o.get("current_law")),
                "reform": H._to_float(o.get("reform")),
                "parse_mode": "json",
            }
    nums = [H._to_float(m.group(0)) for m in re.finditer(r"[-+]?\$?\d[\d,]*(?:\.\d+)?", text)]
    nums = [n for n in nums if n is not None]
    if nums:
        return {"parse_error": "no_delta_key", "candidates": nums[:5], "parse_mode": "failed"}
    return {"parse_error": "no_numbers", "parse_mode": "failed"}


def run_ctc_single(case: dict, config: dict) -> dict:
    ctx = build_context(config["policy_context"])
    task = TASK.format(
        filing="married filing jointly" if case.get("married") else "single / head of household",
        state=case.get("state", "TX"),
        children=case["children"],
        earnings=int(case["earnings"]),
    )
    use_tools = config["tools"] == "policyengine"
    parts = [task]
    if ctx:
        parts.append(ctx)
    if use_tools:
        parts.append(TOOL_HINT)
    parts.append(ANSWER_FORMAT)
    prompt = "\n\n".join(parts)

    rec: dict = {
        "case_id": case["case_id"],
        "config": dict(config),
        "prompt_chars": len(prompt),
        "truth_delta": case["truth"]["delta"],
        "truth_current_law": case["truth"]["refundable_ctc_current_law"],
        "truth_reform": case["truth"]["refundable_ctc_reform"],
    }

    if config["pipeline"] == "single_pass":
        if use_tools:
            out = T.call_with_tools(prompt, config["model"], [T.POLICYENGINE_TOOL], {}, max_tokens=5000)
            if not out.get("ok"):
                rec["error"] = out.get("error")
                return rec
            rec["tool_calls"] = out.get("tool_calls", 0)
            rec["tool_log"] = out.get("tool_log", [])
            rec["final_text"] = out.get("final_text", "")
        else:
            res = H.call_model(prompt, config["model"], max_tokens=6000)
            if not res.ok:
                rec["error"] = res.error
                return rec
            rec["tool_calls"] = 0
            rec["final_text"] = res.text
        rec["answer"] = parse_ctc(rec["final_text"])
        return rec

    # multi-agent: extractor -> analyst -> critic -> judge
    tool_hint = TOOL_HINT if use_tools else ""
    steps: list[dict] = []

    def step(name: str, prompt_text: str, allow_tools: bool, max_tokens: int = 5000) -> str | None:
        if allow_tools and use_tools:
            out = T.call_with_tools(prompt_text, config["model"], [T.POLICYENGINE_TOOL], {}, max_tokens=5000)
            if not out.get("ok"):
                rec["error"] = f"{name}: {out.get('error')}"
                return None
            steps.append({"role": name, "tool_calls": out.get("tool_calls", 0)})
            rec.setdefault("tool_log", []).extend(out.get("tool_log", []))
            return out.get("final_text", "")
        res = H.call_model(prompt_text, config["model"], max_tokens=max_tokens)
        if not res.ok:
            rec["error"] = f"{name}: {res.error}"
            return None
        steps.append({"role": name, "tool_calls": 0})
        return res.text

    extraction = step(
        "extractor",
        MULTI_AGENT_ROLES["extractor"].format(context=ctx or "(no bill text supplied)"),
        allow_tools=False,
    )
    if extraction is None:
        return rec
    analysis = step(
        "analyst",
        MULTI_AGENT_ROLES["analyst"].format(task=task, extraction=extraction, tool_hint=tool_hint),
        allow_tools=True,
    )
    if analysis is None:
        return rec
    critique = step(
        "critic",
        MULTI_AGENT_ROLES["critic"].format(task=task, extraction=extraction, analysis=analysis),
        allow_tools=False,
    )
    if critique is None:
        return rec
    final = step(
        "judge",
        MULTI_AGENT_ROLES["judge"].format(
            task=task, extraction=extraction, analysis=analysis,
            critique=critique, tool_hint=tool_hint, answer_format=ANSWER_FORMAT,
        ),
        allow_tools=True,
    )
    if final is None:
        return rec

    rec["steps"] = steps
    rec["tool_calls"] = sum(s.get("tool_calls", 0) for s in steps)
    rec["extraction_text"] = extraction
    rec["critic_text"] = critique
    rec["final_text"] = final
    rec["answer"] = parse_ctc(final)
    return rec
