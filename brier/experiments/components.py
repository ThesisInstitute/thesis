"""Reusable prompt components shared by the experiment tracks.

Three tracks generate agent prompts — stability-under-probing
(:mod:`brier.experiments.stability`), reframing
(:mod:`brier.experiments.reframing`), and decision-usefulness
(:mod:`brier.experiments.decision_usefulness`) — plus the LLM judges
(:mod:`brier.experiments.judge`). Each one had forked its own copy of the same
instruction blocks, so a wording fix in one track silently failed to reach the
others and the tracks drifted apart.

This module owns those blocks. Prompt wording is the experimental treatment, so
every component here is a *verbatim* record of text that is already in use; the
tracks compose from it instead of restating it. Changing a string in this file
changes the treatment for every track that shares it — which is the point, and
also the reason `tests/test_prompt_components.py` pins the composed output of
every track against a golden fixture.

Four component families, matching the four things a track can ask an agent to
do beyond answering:

``EXTRACTION``
    Make the answer machine-readable, and read it back. Both halves of the
    contract live together so the emit format and the parser cannot drift.

``GOAL IMPUTATION``
    Make the agent state the objective and the live alternatives, rather than
    inheriting the framing implied by the question.

``EFFECT SURFACING``
    Make latent consequences and counter-evidence explicit — base rates,
    biases in the framing, disconfirming evidence, failure modes, mechanism.
    Also the *suppression* clauses, which are how the control conditions
    withhold exactly these considerations.

``METRIC CANDIDACY``
    Propose the KPIs the decision resolves against, and the forecasts attached
    to them.

A short ``SHARED CLOSERS`` section holds the recommendation/review blocks,
which are shared across tracks but do not belong to any of the four families.

`paper/run_study1_rerun.py` deliberately keeps a frozen fork of the Study 1
wording and is *not* wired to this module: its whole job is to reproduce the
original prompts even after this text moves on.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Composition helpers
# ---------------------------------------------------------------------------


def numbered(steps: Iterable[str]) -> str:
    """Render steps as a ``1.``-prefixed list."""
    return "\n".join(f"{i}. {step}" for i, step in enumerate(steps, start=1))


def bulleted(items: Iterable[str]) -> str:
    """Render items as a ``-``-prefixed list."""
    return "\n".join(f"- {item}" for item in items)


def paragraphs(*parts: str) -> str:
    """Join non-empty parts with a blank line between them."""
    return "\n\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# EXTRACTION — emit side
# ---------------------------------------------------------------------------

#: Appended to every prompt in the stability track. Leading blank lines are
#: part of the contract: it is concatenated directly onto the prompt tail.
JSON_ESTIMATE_CONTRACT = """

After your reasoning, output your final answer as a JSON block:
```json
{"estimate": <number>, "ci_low": <number>, "ci_high": <number>}
```
where ci_low and ci_high are the bounds of your 80% confidence interval.
Use the same units and scale as the question. If the question asks for a percentage or probability, return 0-100 rather than 0-1."""


def json_only_contract(schema: str) -> str:
    """Demand a bare JSON object matching ``schema`` (decision-usefulness judges).

    ``schema`` is a ``str.format``-ready literal, so its braces are doubled.
    """
    return f"Return JSON only:\n{schema}"


def fenced_json_contract(schema: str, label: str = "Output your scores as JSON") -> str:
    """Demand a fenced JSON block matching ``schema`` (reframing/quality judges)."""
    return f"{label}:\n```json\n{schema}\n```"


# ---------------------------------------------------------------------------
# EXTRACTION — parse side
# ---------------------------------------------------------------------------


def structured_estimate(
    text: str,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Extract estimate, CI low, and CI high from structured JSON output.

    Expects the response to contain a JSON block like:
    {"estimate": 4.0, "ci_low": 2.5, "ci_high": 7.0}

    Returns: (estimate, ci_low, ci_high) — any may be None if not found.
    """
    json_patterns = [
        r"```json\s*(\{[^}]+\})\s*```",  # ```json {...} ```
        r"```\s*(\{[^}]+\})\s*```",  # ``` {...} ```
        r'(\{"estimate"[^}]+\})',  # {"estimate": ...}
    ]

    for pattern in json_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                estimate = data.get("estimate")
                ci_low = data.get("ci_low")
                ci_high = data.get("ci_high")
                if estimate is not None:
                    estimate = float(estimate)
                if ci_low is not None:
                    ci_low = float(ci_low)
                if ci_high is not None:
                    ci_high = float(ci_high)
                # Swap CI if reversed
                if ci_low is not None and ci_high is not None and ci_low > ci_high:
                    ci_low, ci_high = ci_high, ci_low
                return estimate, ci_low, ci_high
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

    return None, None, None


def numeric_estimate(text: str, unit: str) -> Optional[float]:
    """Extract numeric estimate from response text.

    First tries structured JSON, then falls back to regex patterns.
    """
    estimate, _, _ = structured_estimate(text)
    if estimate is not None:
        return estimate

    # Fallback to regex
    patterns = [
        rf"(?:point estimate|estimate|prediction|forecast)[:\s]+\**(\d+\.?\d*)\**\s*{re.escape(unit)}",
        rf"\*\*(\d+\.?\d*)\s*{re.escape(unit)}\*\*",  # **4 weeks**
        rf"(\d+\.?\d*)\s*{re.escape(unit)}",  # "4 weeks"
        r"(?:point estimate)[:\s]+\**(\d+\.?\d*)\**",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return float(match.group(1))

    return None


def confidence_interval(text: str) -> tuple[Optional[float], Optional[float]]:
    """Extract confidence interval from response text.

    First tries structured JSON, then falls back to context-aware regex.
    """
    _, ci_low, ci_high = structured_estimate(text)
    if ci_low is not None and ci_high is not None:
        return ci_low, ci_high

    # Fallback: context-aware regex — only match CIs near CI-related keywords
    ci_patterns = [
        r"(?:confidence interval|CI|80%\s*CI)[:\s]*\[?\s*(\d+\.?\d*)%?\s*[-–—,]\s*(\d+\.?\d*)%?\s*\]?",
        r"(?:confidence interval|CI|80%\s*CI)[:\s]*\[?\s*(\d+\.?\d*)%?\s+to\s+(\d+\.?\d*)%?\s*\]?",
        r"(?:range|interval)[:\s]*\[?\s*(\d+\.?\d*)%?\s*[-–—,]\s*(\d+\.?\d*)%?\s*\]?",
        r"(?:range|interval)[:\s]*\[?\s*(\d+\.?\d*)%?\s+to\s+(\d+\.?\d*)%?\s*\]?",
        r"\[(\d+\.?\d*)%?\s*,\s*(\d+\.?\d*)%?\]",  # [2.5, 7]
    ]

    for pattern in ci_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            low, high = float(match.group(1)), float(match.group(2))
            if low > high:
                low, high = high, low
            return low, high

    return None, None


def first_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response.

    Raises ``ValueError`` when the response contains no object, so a judge that
    ignored its output contract fails loudly rather than scoring as empty.
    """
    fenced_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        return json.loads(fenced_match.group(1))

    fenced_match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if fenced_match:
        return json.loads(fenced_match.group(1))

    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj

    raise ValueError(f"No JSON object found in judge response: {text[:200]}")


def scored_json(text: str, key_hints: Iterable[str] = ()) -> tuple[dict, str]:
    """Extract integer scores plus a free-text ``reasoning`` field.

    Unlike :func:`first_json_object` this is lenient — an unparseable judge
    response yields ``({}, "")`` and is dropped downstream rather than aborting
    a batch. ``key_hints`` are score keys used to find a bare (unfenced) object.
    """
    json_patterns = [
        r"```json\s*(\{[^}]+\})\s*```",
        r"```\s*(\{[^}]+\})\s*```",
    ]
    json_patterns += [rf'(\{{[^}}]*"{hint}"[^}}]*\}})' for hint in key_hints]

    for pattern in json_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                reasoning = data.pop("reasoning", "")
                # Convert all values to int
                scores = {
                    k: int(v) for k, v in data.items() if isinstance(v, (int, float))
                }
                return scores, reasoning
            except (json.JSONDecodeError, ValueError):
                continue

    return {}, ""


# ---------------------------------------------------------------------------
# GOAL IMPUTATION
# ---------------------------------------------------------------------------

#: Headings that ask for the objective and the live alternatives.
GOAL_HEADING = "Goal"
OPTIONS_HEADING = "Options"

#: Restate the situation before analysing it (format-control conditions).
SITUATION_SUMMARY = "Situation summary"

#: Name alternatives the user did not (reframing track).
OPTIONS_INCLUDING_UNMENTIONED = "Identify the options (including ones not mentioned)"


def option_expansion(framing: str = "first", hedge: str = "if needed") -> str:
    """Ask the agent to widen the option set past the framing it was handed."""
    return f"Expand the option set beyond the user's {framing} framing {hedge}."


# ---------------------------------------------------------------------------
# EFFECT SURFACING
# ---------------------------------------------------------------------------

#: Outside view. The reference class before the inside-view story.
BASE_RATES_FROM_RESEARCH = "Cite base rates from research (outside view)"
BASE_RATES_RELEVANT = "Cite relevant base rates (outside view)"
OUTSIDE_VIEW_BEFORE_INSIDE = (
    "Cite outside-view base rates or reference classes before relying on "
    "inside-view adjustments."
)

#: Biases in how the question was posed.
COGNITIVE_BIASES_IN_FRAMING = "Identify cognitive biases in the framing"

#: What would go wrong, and why the forecast moves.
DISCONFIRMING_EVIDENCE = (
    "Surface the strongest disconfirming evidence and failure modes."
)
FORECAST_MECHANISM = "Explain the main mechanism behind the forecast differences."
FORECAST_ASSUMPTIONS = "Briefly state the main assumptions behind the forecast."

#: Qualitative headings used by the format-control conditions.
KEY_CONSIDERATIONS = "Key considerations"
KEY_OPERATIONAL_CONSIDERATIONS = "Key operational considerations"
UNCERTAINTY_SOURCES = "Main sources of uncertainty"

#: Suppression clauses. The controls exist only because these hold the
#: framework-specific considerations out, so they are treated as first-class
#: components rather than prompt boilerplate.
NO_NAMED_FRAMEWORK = (
    "Do not use any named decision framework. Do not add special instructions "
    "about base rates or cognitive biases unless they arise directly from the "
    "scenario."
)
NO_NAMED_FRAMEWORK_INLINE = (
    "Do not use any named decision framework or special instructions about base "
    "rates or cognitive biases unless they arise directly from the scenario."
)
NO_NUMERIC_FORECASTS = (
    "You may be qualitative. Do not introduce numeric forecasts unless they are "
    "obviously necessary for the scenario."
)
NO_FRAMEWORK_FURNITURE = (
    "Do not explicitly cite cognitive biases, base rates, disconfirming "
    "evidence, or review dates unless they are strictly necessary to support "
    "the forecast."
)
NO_QUALITATIVE_VIBES = (
    "Do not stop at qualitative vibes; make explicit numeric forecasts."
)

#: Judge-side instruction: score the analysis, not its formatting.
NO_REWARD_FOR_STRUCTURE = (
    "Do not reward verbosity, polish, headings, or visible process steps by "
    "themselves."
)
NO_REWARD_FOR_FORMATTING = (
    "Do not reward verbosity, polish, or formatting alone. Prefer analyses that "
    "make the decision easier to audit, compare, and revisit later."
)
NO_REWARD_FOR_PROCESS = (
    "Do not reward visible process, headings, checklist completeness, or "
    "verbosity by themselves."
)


# ---------------------------------------------------------------------------
# METRIC CANDIDACY
# ---------------------------------------------------------------------------


def define_kpis(count: str = "1-2", qualifier: str = "", sep: str = " ") -> str:
    """Ask for the KPIs the decision will resolve against.

    ``qualifier`` carries the track-specific tail — resolvability, units, or
    the success condition — and is appended before the period. ``sep`` is the
    join: a restrictive clause reads ``KPIs that ...``, a non-restrictive one
    reads ``KPIs, including ...``.
    """
    stem = f"Define {count} explicit KPIs"
    if qualifier:
        return f"{stem}{sep}{qualifier}."
    return f"{stem}."


#: Reframing track phrases this as a bare step (no trailing period).
DEFINE_MEASURABLE_KPIS = "Define 2-3 explicit, measurable KPIs for this decision"

#: Forecasts attached to the candidate metrics.
FORECAST_PER_OPTION_KPI = (
    "For each option, give numeric point estimates and 80% confidence intervals "
    "for each KPI."
)
FORECAST_OPTION_BY_KPI = (
    "For each option x KPI, give a point estimate and 80% confidence interval"
)
FORECAST_NUMERIC_WITH_CIS = "Make numeric forecasts with confidence intervals"
POINT_ESTIMATE_AND_CI = "Point estimate and 80% confidence interval"
REVISED_ESTIMATE_AND_CI = "Revised estimate and 80% confidence interval"


# ---------------------------------------------------------------------------
# SHARED CLOSERS
# ---------------------------------------------------------------------------

RECOMMENDATION_HEADING = "Recommendation"
RECOMMENDATION_FROM_FORECASTS = "State the recommendation implied by those forecasts."
RECOMMEND_OPTION_FROM_FORECASTS = "Recommend the option implied by the forecasts."
RECOMMENDATION_FROM_EV = "Give a recommendation based on expected value"
REVIEW_DATE = "Give a review date and what would be checked later."


# ---------------------------------------------------------------------------
# Track-level scaffolding
# ---------------------------------------------------------------------------


def estimate_task(preamble: str, scenario: str, question: str, tail: str = "") -> str:
    """Stability-track envelope: preamble, scenario, question, JSON contract."""
    suffix = f" {tail}" if tail else ""
    return f"{preamble}\n\n{scenario}\n\nQuestion: {question}{suffix}{JSON_ESTIMATE_CONTRACT}"


def probe_task(
    estimate: float,
    unit: str,
    ci_text: str,
    probes_text: str,
    instruction: str,
) -> str:
    """Stability-track follow-up envelope, after new information arrives."""
    return (
        f"You previously estimated {estimate} {unit}{ci_text} for this scenario.\n\n"
        f"Follow-up information:\n\n"
        f"{probes_text}\n\n"
        f"{instruction}{JSON_ESTIMATE_CONTRACT}"
    )


def decision_task(role: str, body: str) -> str:
    """Decision-usefulness envelope. Leaves ``{scenario}`` for later formatting."""
    return (
        f'{role}\n\nA user needs help with this decision:\n\n"{{scenario}}"\n\n{body}'
    )


def pairwise_exhibits(label: str) -> str:
    """Judge-side envelope presenting the scenario and the two blinded artifacts."""
    return (
        "## Decision scenario\n{scenario}\n\n"
        f"## {label} A\n{{analysis_a}}\n\n"
        f"## {label} B\n{{analysis_b}}"
    )


#: Shared framing for every pairwise judge: rank usefulness, not provenance.
JUDGE_NOT_PROVENANCE = (
    "Your job is not to guess which one came from a better prompt. Your job is "
    "to decide which analysis would better help a user make the decision."
)
