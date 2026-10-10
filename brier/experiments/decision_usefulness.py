"""LLM-judge evaluation for decision-usefulness artifacts.

This experiment asks a different question than stability-under-probing:
do held-out judges prefer the decision artifacts produced by a prompt?

It compares four prompt conditions:
- naive
- format_control
- forecast_only
- brier

Each generated analysis is evaluated in three representations:
- decision_memo: a neutral fixed-envelope summary for recommendation quality
- raw: the original response, blinded to condition
- normalized: a canonical representation for framework-aligned diagnostics
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from brier.experiments import components
from brier.experiments.llm import call_llm, _is_openai_model, model_short_name


DECISION_USEFULNESS_CONDITIONS = [
    "naive",
    "format_control",
    "forecast_only",
    "farness",
]

PRIMARY_PAIRWISE_COMPARISONS = [
    ("farness", "naive"),
    ("farness", "forecast_only"),
    ("forecast_only", "naive"),
    ("format_control", "naive"),
]

PRIMARY_REPRESENTATION = "decision_memo"
REPRESENTATIONS = ["decision_memo", "raw", "normalized"]
JUDGE_TASKS = ["utility", "omission", "critique_survival"]


@dataclass(frozen=True)
class DecisionUsefulnessCase:
    """A realistic decision prompt for artifact-quality evaluation."""

    id: str
    name: str
    domain: str
    scenario: str


SEED_DECISION_USEFULNESS_CASES = [
    DecisionUsefulnessCase(
        id="auth_rewrite",
        name="Auth layer rewrite",
        domain="engineering",
        scenario=(
            "We have repeated incidents around our authentication layer. The current system is messy but "
            "understood. A rewrite could improve long-run reliability, but it would pull senior engineers "
            "off roadmap work for at least a quarter. Should we rewrite now, patch incrementally, or take "
            "some other path?"
        ),
    ),
    DecisionUsefulnessCase(
        id="interactive_feature_prioritization",
        name="Interactive feature prioritization",
        domain="product",
        scenario=(
            "We are launching a new public-facing interactive and want the largest possible reach in the "
            "first month. We have time for only two more major features before launch. Should we prioritize "
            "shareability, customization, distribution partnerships, faster load time, or something else?"
        ),
    ),
    DecisionUsefulnessCase(
        id="microdata_model_parameters",
        name="Microdata model parameters",
        domain="policy",
        scenario=(
            "We need to choose model parameters for a tax-benefit microsimulation. Our main goal is improving "
            "microdata accuracy, but more complex settings will increase runtime and maintenance burden. Which "
            "parameter strategy should we use?"
        ),
    ),
    DecisionUsefulnessCase(
        id="policy_research_centralization",
        name="Policy research centralization",
        domain="operations",
        scenario=(
            "Our team needs to encode a new set of policies as quickly and accurately as possible. Should "
            "research stay embedded with each implementer, move to a centralized research function, or use "
            "a hybrid setup?"
        ),
    ),
    DecisionUsefulnessCase(
        id="wealth_tax_outreach",
        name="Wealth tax outreach strategy",
        domain="policy",
        scenario=(
            "We built an interactive model for a California wealth tax proposal and want the strongest launch "
            "strategy. Options include a broad social launch, a journalist-briefing-first strategy, a "
            "validator-first strategy, or an adversarial debate-first strategy. Which should we choose?"
        ),
    ),
    DecisionUsefulnessCase(
        id="hire_vp_eng",
        name="Hire VP Engineering",
        domain="hiring",
        scenario=(
            "We are a 15-person startup with engineering bottlenecks and an overwhelmed CTO. Should we hire "
            "a VP of Engineering now, promote a senior engineer, improve process first, or do something else?"
        ),
    ),
    DecisionUsefulnessCase(
        id="mobile_app",
        name="Build a mobile app",
        domain="product",
        scenario=(
            "Customers keep asking for a mobile app. Our current web product mostly works on phones but is not "
            "well optimized. Building a native app would take months and delay other roadmap items. Should we "
            "build the app now, improve the mobile web experience, or wait?"
        ),
    ),
    DecisionUsefulnessCase(
        id="series_b_timing",
        name="Series B timing",
        domain="finance",
        scenario=(
            "We have strong growth and enough runway for about 12 months. Investors are interested now, but "
            "waiting could improve the valuation if growth holds. Should we raise a Series B now, wait, or "
            "pursue a different financing strategy?"
        ),
    ),
    DecisionUsefulnessCase(
        id="office_location",
        name="Office location",
        domain="operations",
        scenario=(
            "We need to decide where to place a new office. The leading options are San Francisco, Sacramento, "
            "and staying fully remote. We care about hiring, operating cost, collaboration, and long-run "
            "execution. What should we do?"
        ),
    ),
    DecisionUsefulnessCase(
        id="grant_strategy",
        name="Grant application strategy",
        domain="strategy",
        scenario=(
            "We can spend the next two months either pursuing one large grant, several smaller grants, or a "
            "mixed strategy. Staff time is limited and fundraising uncertainty is high. Which path should we take?"
        ),
    ),
    DecisionUsefulnessCase(
        id="analytics_migration",
        name="Analytics stack migration",
        domain="engineering",
        scenario=(
            "Our analytics stack is unreliable and expensive, but migrating it would consume substantial "
            "engineering time and risk reporting disruption. Should we migrate now, patch the current stack, "
            "or phase in a replacement gradually?"
        ),
    ),
    DecisionUsefulnessCase(
        id="pricing_rework",
        name="Pricing model rework",
        domain="product",
        scenario=(
            "We think our current pricing is leaving money on the table, but changing it could hurt conversion "
            "or create customer confusion. Should we rework pricing now, run a limited experiment, or defer?"
        ),
    ),
]


PROMPT_TEMPLATES = {
    "naive": components.decision_task(
        "You are a helpful assistant.",
        "Give your recommendation and reasoning. Be concise but complete.",
    ),
    "format_control": components.decision_task(
        "You are a decision analyst.",
        components.paragraphs(
            "Respond using exactly these headings:\n"
            + components.bulleted(
                [
                    components.GOAL_HEADING,
                    components.OPTIONS_HEADING,
                    components.KEY_CONSIDERATIONS,
                    components.RECOMMENDATION_HEADING,
                ]
            ),
            components.NO_NUMERIC_FORECASTS,
        ),
    ),
    "forecast_only": components.decision_task(
        "You are a decision analyst.",
        components.paragraphs(
            "Do the following:\n"
            + components.numbered(
                [
                    components.define_kpis(
                        qualifier="that would determine whether the decision succeeded"
                    ),
                    components.option_expansion(),
                    components.FORECAST_PER_OPTION_KPI,
                    components.RECOMMENDATION_FROM_FORECASTS,
                    components.FORECAST_ASSUMPTIONS,
                ]
            ),
            components.NO_FRAMEWORK_FURNITURE,
        ),
    ),
    "farness": components.decision_task(
        "You are a decision analyst using the brier framework.",
        components.paragraphs(
            "Use this workflow:\n"
            + components.numbered(
                [
                    components.define_kpis(
                        qualifier="including units and how they would resolve later",
                        sep=", ",
                    ),
                    components.option_expansion(
                        framing="initial", hedge="if appropriate"
                    ),
                    components.FORECAST_PER_OPTION_KPI,
                    components.OUTSIDE_VIEW_BEFORE_INSIDE,
                    components.DISCONFIRMING_EVIDENCE,
                    components.FORECAST_MECHANISM,
                    components.RECOMMEND_OPTION_FROM_FORECASTS,
                    components.REVIEW_DATE,
                ]
            ),
            components.NO_QUALITATIVE_VIBES,
        ),
    ),
}


PAIRWISE_NEUTRAL_PROMPT = components.paragraphs(
    "You are evaluating two decision writeups for usefulness to a careful human decision-maker.",
    components.JUDGE_NOT_PROVENANCE,
    components.NO_REWARD_FOR_STRUCTURE
    + "\nPrefer the writeup that gives clearer action guidance, more discriminative"
    " reasoning between live alternatives, more useful caveat/uncertainty handling,"
    " and stronger quantitative support when that support meaningfully helps the"
    " recommendation.",
    components.pairwise_exhibits("Writeup"),
    "Score each analysis from 1-5 on:\n"
    + components.numbered(
        [
            "Action guidance",
            "Comparative reasoning",
            "Uncertainty handling",
            "Quantitative support",
            "Overall decision usefulness",
        ]
    ),
    "Then choose the overall winner.",
    components.json_only_contract(
        """{{
  "scores_a": {{
    "action_guidance": <1-5>,
    "comparative_reasoning": <1-5>,
    "uncertainty_handling": <1-5>,
    "quantitative_support": <1-5>,
    "overall_usefulness": <1-5>
  }},
  "scores_b": {{
    "action_guidance": <1-5>,
    "comparative_reasoning": <1-5>,
    "uncertainty_handling": <1-5>,
    "quantitative_support": <1-5>,
    "overall_usefulness": <1-5>
  }},
  "overall_winner": "A" | "B" | "tie",
  "confidence": <0-100>,
  "rationale": "<<=120 words>"
}}"""
    ),
)


PAIRWISE_ALIGNED_PROMPT = components.paragraphs(
    "You are evaluating two decision analyses for usefulness to a careful human decision-maker.",
    components.JUDGE_NOT_PROVENANCE,
    components.NO_REWARD_FOR_FORMATTING,
    components.pairwise_exhibits("Analysis"),
    "Score each analysis from 1-5 on:\n"
    + components.numbered(
        [
            "KPI clarity and resolvability",
            "Option-set completeness",
            "Forecast specificity and comparability",
            "Outside-view grounding",
            "Disconfirming evidence / failure-mode coverage",
            "Recommendation traceability",
        ]
    ),
    "Then choose the overall winner.",
    components.json_only_contract(
        """{{
  "scores_a": {{
    "kpi_clarity": <1-5>,
    "option_completeness": <1-5>,
    "forecast_specificity": <1-5>,
    "outside_view": <1-5>,
    "disconfirming_evidence": <1-5>,
    "recommendation_traceability": <1-5>
  }},
  "scores_b": {{
    "kpi_clarity": <1-5>,
    "option_completeness": <1-5>,
    "forecast_specificity": <1-5>,
    "outside_view": <1-5>,
    "disconfirming_evidence": <1-5>,
    "recommendation_traceability": <1-5>
  }},
  "overall_winner": "A" | "B" | "tie",
  "confidence": <0-100>,
  "rationale": "<<=120 words>"
}}"""
    ),
)


PAIRWISE_OMISSION_PROMPT = components.paragraphs(
    "You are evaluating two decision analyses for the most important thing each one failed to consider.",
    components.pairwise_exhibits("Analysis"),
    components.json_only_contract(
        """{{
  "largest_missing_consideration_a": "<one concise omission or 'none'>",
  "largest_missing_consideration_b": "<one concise omission or 'none'>",
  "which_analysis_has_more_serious_omission": "A" | "B" | "tie",
  "confidence": <0-100>,
  "rationale": "<<=100 words>"
}}"""
    ),
)


#: Held-out critique lenses, deliberately not tied to any framework the
#: generator conditions were prompted with.
CRITIQUE_LENSES = [
    "implementation fragility",
    "incentive or stakeholder response",
    "opportunity cost",
    "reversibility and switching cost",
    "hidden dependencies",
    "tail risk or timing risk",
]


PAIRWISE_CRITIQUE_SURVIVAL_PROMPT = components.paragraphs(
    "You are stress-testing two decision writeups using held-out critique lenses.",
    "Your job is to decide which recommendation is less undermined after applying"
    " critiques that are NOT tied to any particular decision framework.",
    "Use these critique lenses:\n" + components.bulleted(CRITIQUE_LENSES),
    components.NO_REWARD_FOR_PROCESS
    + "\nPrefer the writeup whose recommendation would require less revision after"
    " these critiques.",
    components.pairwise_exhibits("Writeup"),
    components.json_only_contract(
        """{{
  "most_damaging_critique_a": "<=35 words>",
  "most_damaging_critique_b": "<=35 words>",
  "less_undermined_analysis": "A" | "B" | "tie",
  "confidence": <0-100>,
  "rationale": "<<=120 words>"
}}"""
    ),
)


SECTION_ALIASES = {
    "kpis": (
        "kpis",
        "kpi",
        "metrics",
        "metric",
        "goal",
        "goals",
        "success criteria",
        "success metric",
        "success metrics",
    ),
    "options": ("options", "option", "alternatives", "paths"),
    "forecast_summary": (
        "forecast summary",
        "forecast",
        "forecasts",
        "forecasts by option",
        "predictions",
        "estimates",
    ),
    "outside_view": (
        "outside view",
        "base rates",
        "base rate",
        "reference class",
        "reference classes",
        "historical base rates",
    ),
    "disconfirming_evidence": (
        "disconfirming evidence",
        "failure modes",
        "failure mode",
        "risks",
        "downsides",
        "counterarguments",
        "arguments against",
        "what could go wrong",
    ),
    "recommendation": ("recommendation", "recommended option", "decision"),
    "review_plan": ("review plan", "review date", "follow-up", "review"),
}


@dataclass
class DecisionUsefulnessArtifact:
    """Generated analysis artifact for a case/condition/model/run."""

    case_id: str
    condition: str
    model: str
    run_number: int
    prompt: str
    response_text: str
    timestamp: str
    duration_seconds: float
    normalized_sections: dict[str, str] = field(default_factory=dict)
    normalized_representation: str = ""
    decision_memo_representation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "condition": self.condition,
            "model": self.model,
            "run_number": self.run_number,
            "prompt": self.prompt,
            "response_text": self.response_text,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "normalized_sections": self.normalized_sections,
            "normalized_representation": self.normalized_representation,
            "decision_memo_representation": self.decision_memo_representation,
        }


@dataclass
class PairwiseUtilityJudgeResult:
    """Pairwise utility judgment for a comparison."""

    case_id: str
    source_model: str
    judge_model: str
    run_number: int
    comparison: str
    representation: str
    condition_a: str
    condition_b: str
    left_condition: str
    right_condition: str
    winner_condition: str
    confidence: int
    rationale: str
    scores_a: dict[str, int] = field(default_factory=dict)
    scores_b: dict[str, int] = field(default_factory=dict)
    raw_judge_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "source_model": self.source_model,
            "judge_model": self.judge_model,
            "run_number": self.run_number,
            "comparison": self.comparison,
            "representation": self.representation,
            "condition_a": self.condition_a,
            "condition_b": self.condition_b,
            "left_condition": self.left_condition,
            "right_condition": self.right_condition,
            "winner_condition": self.winner_condition,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "scores_a": self.scores_a,
            "scores_b": self.scores_b,
            "raw_judge_response": self.raw_judge_response,
        }


@dataclass
class PairwiseOmissionJudgeResult:
    """Pairwise omission judgment for a comparison."""

    case_id: str
    source_model: str
    judge_model: str
    run_number: int
    comparison: str
    representation: str
    condition_a: str
    condition_b: str
    left_condition: str
    right_condition: str
    more_serious_omission_condition: str
    confidence: int
    rationale: str
    largest_missing_consideration_a: str
    largest_missing_consideration_b: str
    raw_judge_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "source_model": self.source_model,
            "judge_model": self.judge_model,
            "run_number": self.run_number,
            "comparison": self.comparison,
            "representation": self.representation,
            "condition_a": self.condition_a,
            "condition_b": self.condition_b,
            "left_condition": self.left_condition,
            "right_condition": self.right_condition,
            "more_serious_omission_condition": self.more_serious_omission_condition,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "largest_missing_consideration_a": self.largest_missing_consideration_a,
            "largest_missing_consideration_b": self.largest_missing_consideration_b,
            "raw_judge_response": self.raw_judge_response,
        }


@dataclass
class PairwiseCritiqueSurvivalJudgeResult:
    """Pairwise held-out critique-survival judgment for a comparison."""

    case_id: str
    source_model: str
    judge_model: str
    run_number: int
    comparison: str
    representation: str
    condition_a: str
    condition_b: str
    left_condition: str
    right_condition: str
    less_undermined_condition: str
    confidence: int
    rationale: str
    most_damaging_critique_a: str
    most_damaging_critique_b: str
    raw_judge_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "source_model": self.source_model,
            "judge_model": self.judge_model,
            "run_number": self.run_number,
            "comparison": self.comparison,
            "representation": self.representation,
            "condition_a": self.condition_a,
            "condition_b": self.condition_b,
            "left_condition": self.left_condition,
            "right_condition": self.right_condition,
            "less_undermined_condition": self.less_undermined_condition,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "most_damaging_critique_a": self.most_damaging_critique_a,
            "most_damaging_critique_b": self.most_damaging_critique_b,
            "raw_judge_response": self.raw_judge_response,
        }


def get_decision_usefulness_cases() -> list[DecisionUsefulnessCase]:
    """Return the seed decision-usefulness case set."""
    return list(SEED_DECISION_USEFULNESS_CASES)


def get_decision_usefulness_case(case_id: str) -> Optional[DecisionUsefulnessCase]:
    """Return a specific decision-usefulness case."""
    for case in SEED_DECISION_USEFULNESS_CASES:
        if case.id == case_id:
            return case
    return None


def generate_decision_usefulness_prompt(
    case: DecisionUsefulnessCase,
    condition: str,
) -> str:
    """Generate the prompt for a decision-usefulness condition."""
    try:
        template = PROMPT_TEMPLATES[condition]
    except KeyError as exc:
        raise ValueError(f"Unsupported condition: {condition}") from exc
    return template.format(scenario=case.scenario.strip())


def _normalize_heading(line: str) -> Optional[str]:
    """Map a markdown-ish heading line to a canonical section key."""
    candidate = line.strip()
    if not candidate:
        return None

    candidate = re.sub(r"^[#*\-\d.\)\s]+", "", candidate)
    candidate = candidate.strip().rstrip(":").lower()
    if not candidate:
        return None

    for canonical, aliases in SECTION_ALIASES.items():
        if candidate in aliases:
            return canonical
    return None


def _clean_section_text(lines: list[str]) -> str:
    """Normalize captured section text."""
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        cleaned.append(stripped)
    return "\n".join(cleaned).strip()


def _find_inline_content(text: str, patterns: tuple[str, ...]) -> str:
    """Extract inline content from the first sentence matching one of the patterns."""
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return ""


def _extract_numeric_lines(text: str) -> str:
    """Extract lines that look like forecasts or explicit estimates."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"\b\d+(\.\d+)?\b", stripped) and (
            "%" in stripped
            or "$" in stripped
            or "week" in stripped.lower()
            or "month" in stripped.lower()
            or re.search(r"\bCI\b|\bconfidence interval\b", stripped, re.IGNORECASE)
            or re.search(r"\b\d+(\.\d+)?\s*[-–]\s*\d+(\.\d+)?\b", stripped)
        ):
            lines.append(stripped)
    return "\n".join(lines[:8]).strip()


def _extract_option_candidates(options_text: str) -> list[str]:
    """Extract option-like entries from an options block."""
    if not options_text or options_text == "Not provided":
        return []

    candidates = []
    for raw_line in options_text.splitlines():
        line = re.sub(r"^[\-\*\d\.\)\s]+", "", raw_line.strip()).strip()
        if line:
            candidates.append(line)
    return candidates


def _first_meaningful_line(text: str) -> str:
    """Return the first non-empty line from a block of text."""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line:
            return line
    return "Not clearly stated."


def _extract_sentences(text: str) -> list[str]:
    """Split text into reasonably clean sentences."""
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return []
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", compact) if sentence.strip()]


def _clean_freeform_for_memo(text: str) -> str:
    """Remove obvious heading lines before extracting a memo rationale."""
    kept_lines = []
    for raw_line in _redact_framework_names(text).splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if _normalize_heading(stripped) is not None:
            continue
        kept_lines.append(stripped)
    return " ".join(kept_lines).strip()


def _redact_framework_names(text: str) -> str:
    """Remove explicit framework references from judged text."""
    redacted = re.sub(r"\bbrier\b", "[framework]", text, flags=re.IGNORECASE)
    redacted = re.sub(r"\bforecasting as a harness\b", "[framework]", redacted, flags=re.IGNORECASE)
    return redacted


def normalize_decision_analysis(
    response_text: str,
    scenario: str,
) -> tuple[dict[str, str], str]:
    """Build a canonical representation of a generated decision analysis."""
    sections: dict[str, list[str]] = {key: [] for key in SECTION_ALIASES}
    current_section: Optional[str] = None
    redacted_text = _redact_framework_names(response_text)

    for raw_line in redacted_text.splitlines():
        heading = _normalize_heading(raw_line)
        if heading is not None:
            current_section = heading
            continue
        if current_section is not None:
            sections[current_section].append(raw_line)

    extracted = {key: _clean_section_text(value) for key, value in sections.items()}

    if not extracted["recommendation"]:
        extracted["recommendation"] = _find_inline_content(
            redacted_text,
            (
                r"(?:^|\n)\s*Recommendation\s*:\s*(.+)",
                r"(?:^|\n)\s*I recommend\s+(.+)",
                r"(?:^|\n)\s*Recommended option\s*:\s*(.+)",
            ),
        )

    if not extracted["outside_view"] and re.search(
        r"base rate|outside view|reference class|historical",
        redacted_text,
        re.IGNORECASE,
    ):
        extracted["outside_view"] = "\n".join(
            line.strip()
            for line in redacted_text.splitlines()
            if re.search(r"base rate|outside view|reference class|historical", line, re.IGNORECASE)
        ).strip()

    if not extracted["disconfirming_evidence"] and re.search(
        r"disconfirm|failure mode|what could go wrong|downside|risk",
        redacted_text,
        re.IGNORECASE,
    ):
        extracted["disconfirming_evidence"] = "\n".join(
            line.strip()
            for line in redacted_text.splitlines()
            if re.search(r"disconfirm|failure mode|what could go wrong|downside|risk", line, re.IGNORECASE)
        ).strip()

    if not extracted["review_plan"]:
        extracted["review_plan"] = _find_inline_content(
            redacted_text,
            (
                r"(?:^|\n)\s*Review date\s*:\s*(.+)",
                r"(?:^|\n)\s*Review plan\s*:\s*(.+)",
                r"(?:^|\n)\s*Follow-up\s*:\s*(.+)",
            ),
        )

    if not extracted["forecast_summary"]:
        extracted["forecast_summary"] = _extract_numeric_lines(redacted_text)

    if not extracted["kpis"] and re.search(
        r"\bKPI\b|metric|success criteria|success means",
        redacted_text,
        re.IGNORECASE,
    ):
        extracted["kpis"] = "\n".join(
            line.strip()
            for line in redacted_text.splitlines()
            if re.search(r"\bKPI\b|metric|success criteria|success means", line, re.IGNORECASE)
        ).strip()

    normalized_sections = {
        key: value if value else "Not provided"
        for key, value in extracted.items()
    }

    normalized_representation = "\n".join(
        [
            "Decision question:",
            scenario.strip(),
            "",
            "KPIs:",
            normalized_sections["kpis"],
            "",
            "Options considered:",
            normalized_sections["options"],
            "",
            "Forecast summary:",
            normalized_sections["forecast_summary"],
            "",
            "Outside-view evidence:",
            normalized_sections["outside_view"],
            "",
            "Disconfirming evidence:",
            normalized_sections["disconfirming_evidence"],
            "",
            "Recommendation:",
            normalized_sections["recommendation"],
            "",
            "Review plan:",
            normalized_sections["review_plan"],
        ]
    ).strip()

    return normalized_sections, normalized_representation


def build_decision_memo(
    response_text: str,
    normalized_sections: dict[str, str],
) -> str:
    """Build a neutral fixed-envelope memo for judge comparisons."""
    recommendation = _first_meaningful_line(normalized_sections.get("recommendation", ""))

    option_candidates = _extract_option_candidates(normalized_sections.get("options", ""))
    recommendation_lower = recommendation.lower()
    alternative = next(
        (
            option
            for option in option_candidates
            if option.lower() not in recommendation_lower and recommendation_lower not in option.lower()
        ),
        option_candidates[0] if option_candidates else "Not clearly stated.",
    )

    cleaned_text = _clean_freeform_for_memo(response_text)
    rationale_sentences = []
    for sentence in _extract_sentences(cleaned_text):
        sentence_lower = sentence.lower()
        if recommendation != "Not clearly stated." and recommendation_lower in sentence_lower:
            continue
        if any(
            marker in sentence_lower
            for marker in ("review date", "review plan", "follow-up", "revisit trigger", "recommended option:")
        ):
            continue
        rationale_sentences.append(sentence)
    rationale = " ".join(rationale_sentences[:3]).strip() or "Not clearly stated."

    caveat_text = normalized_sections.get("disconfirming_evidence", "Not provided")
    caveat = (
        _first_meaningful_line(caveat_text)
        if caveat_text != "Not provided"
        else "Not clearly stated."
    )

    review_text = normalized_sections.get("review_plan", "Not provided")
    revisit_trigger = (
        _first_meaningful_line(review_text)
        if review_text != "Not provided"
        else "Not clearly stated."
    )

    quantitative_text = normalized_sections.get("forecast_summary", "Not provided")
    if quantitative_text != "Not provided":
        quantitative_lines = [line.strip() for line in quantitative_text.splitlines() if line.strip()][:2]
        quantitative_support = "\n".join(quantitative_lines).strip() or "Not clearly stated."
    else:
        quantitative_support = "Not clearly stated."

    return "\n".join(
        [
            "Recommended option:",
            recommendation,
            "",
            "Main alternative:",
            alternative,
            "",
            "Decisive rationale:",
            rationale,
            "",
            "Key caveat:",
            caveat,
            "",
            "Revisit trigger:",
            revisit_trigger,
            "",
            "Quantitative support:",
            quantitative_support,
        ]
    ).strip()


def run_decision_usefulness_trial(
    case: DecisionUsefulnessCase,
    condition: str,
    run_number: int,
    model: str,
    temperature: float = 1.0,
    max_tokens: int = 4096,
) -> DecisionUsefulnessArtifact:
    """Generate one decision-analysis artifact."""
    prompt = generate_decision_usefulness_prompt(case, condition)
    timestamp = datetime.now().isoformat()
    response_text, duration = call_llm(
        prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    normalized_sections, normalized_representation = normalize_decision_analysis(
        response_text=response_text,
        scenario=case.scenario,
    )
    decision_memo_representation = build_decision_memo(
        response_text=response_text,
        normalized_sections=normalized_sections,
    )

    return DecisionUsefulnessArtifact(
        case_id=case.id,
        condition=condition,
        model=model,
        run_number=run_number,
        prompt=prompt,
        response_text=response_text,
        timestamp=timestamp,
        duration_seconds=duration,
        normalized_sections=normalized_sections,
        normalized_representation=normalized_representation,
        decision_memo_representation=decision_memo_representation,
    )


def run_decision_usefulness_experiment(
    cases: Optional[list[DecisionUsefulnessCase]] = None,
    conditions: Optional[list[str]] = None,
    runs_per_condition: int = 3,
    model: str = "claude-opus-4-6",
    start_run: int = 1,
    output_dir: Optional[Path] = None,
    verbose: bool = True,
) -> list[DecisionUsefulnessArtifact]:
    """Generate decision artifacts across cases and conditions."""
    if cases is None:
        cases = get_decision_usefulness_cases()
    if conditions is None:
        conditions = list(DECISION_USEFULNESS_CONDITIONS)

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    results: list[DecisionUsefulnessArtifact] = []
    total = len(cases) * len(conditions) * runs_per_condition
    completed = 0

    for case in cases:
        for condition in conditions:
            for offset in range(runs_per_condition):
                run_number = start_run + offset
                completed += 1
                if verbose:
                    print(
                        f"[{completed}/{total}] generate {case.id}/{condition}/run{run_number} ({model})"
                    )
                artifact = run_decision_usefulness_trial(
                    case=case,
                    condition=condition,
                    run_number=run_number,
                    model=model,
                )
                results.append(artifact)
                if output_dir is not None:
                    output_path = output_dir / f"{case.id}_{condition}_run{run_number}.json"
                    with open(output_path, "w") as fh:
                        json.dump(artifact.to_dict(), fh, indent=2)

    if output_dir is not None:
        metadata = {
            "experiment_type": "decision_usefulness",
            "model": model,
            "conditions": conditions,
            "runs_per_condition": runs_per_condition,
            "start_run": start_run,
            "cases": [case.id for case in cases],
            "generated_at": datetime.now().isoformat(),
        }
        with open(output_dir / "experiment_metadata.json", "w") as fh:
            json.dump(metadata, fh, indent=2)

    return results


def _pick_judge_model(source_model: str, explicit_judge: Optional[str] = None) -> str:
    """Choose a held-out judge model for a generated artifact."""
    if explicit_judge:
        return explicit_judge
    if _is_openai_model(source_model):
        return "claude-opus-4-6"
    return "gpt-5.4"


_extract_first_json_object = components.first_json_object


def _deterministic_ordering(
    case_id: str,
    run_number: int,
    comparison: str,
    representation: str,
    judge_model: str,
) -> bool:
    """Return True if the first condition should appear as A/left."""
    token = f"{case_id}|{run_number}|{comparison}|{representation}|{judge_model}"
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return digest[0] % 2 == 0


def _prepare_pairwise_text(
    artifact_a: DecisionUsefulnessArtifact,
    artifact_b: DecisionUsefulnessArtifact,
    representation: str,
) -> tuple[str, str]:
    """Return the representation text for a pairwise comparison."""
    if representation == "decision_memo":
        return artifact_a.decision_memo_representation, artifact_b.decision_memo_representation
    if representation == "raw":
        return _redact_framework_names(artifact_a.response_text), _redact_framework_names(artifact_b.response_text)
    if representation == "normalized":
        return artifact_a.normalized_representation, artifact_b.normalized_representation
    raise ValueError(f"Unsupported representation: {representation}")


def judge_pairwise_decision_usefulness(
    case: DecisionUsefulnessCase,
    artifact_a: DecisionUsefulnessArtifact,
    artifact_b: DecisionUsefulnessArtifact,
    judge_model: Optional[str] = None,
    representation: str = "normalized",
) -> PairwiseUtilityJudgeResult:
    """Judge which of two artifacts is more decision-useful."""
    jm = _pick_judge_model(artifact_a.model, judge_model)
    comparison = f"{artifact_a.condition}_vs_{artifact_b.condition}"
    use_original_order = _deterministic_ordering(
        case_id=case.id,
        run_number=artifact_a.run_number,
        comparison=comparison,
        representation=representation,
        judge_model=jm,
    )

    if use_original_order:
        left_artifact, right_artifact = artifact_a, artifact_b
    else:
        left_artifact, right_artifact = artifact_b, artifact_a

    analysis_a, analysis_b = _prepare_pairwise_text(left_artifact, right_artifact, representation)
    prompt_template = PAIRWISE_ALIGNED_PROMPT if representation == "normalized" else PAIRWISE_NEUTRAL_PROMPT
    prompt = prompt_template.format(
        scenario=case.scenario,
        analysis_a=analysis_a,
        analysis_b=analysis_b,
    )
    raw_judge_response, _ = call_llm(
        prompt,
        model=jm,
        temperature=0.0,
        max_tokens=1400,
    )
    payload = _extract_first_json_object(raw_judge_response)
    winner_raw = str(payload.get("overall_winner", "tie")).strip().upper()
    if winner_raw == "A":
        winner_condition = left_artifact.condition
    elif winner_raw == "B":
        winner_condition = right_artifact.condition
    else:
        winner_condition = "tie"

    return PairwiseUtilityJudgeResult(
        case_id=case.id,
        source_model=artifact_a.model,
        judge_model=jm,
        run_number=artifact_a.run_number,
        comparison=comparison,
        representation=representation,
        condition_a=artifact_a.condition,
        condition_b=artifact_b.condition,
        left_condition=left_artifact.condition,
        right_condition=right_artifact.condition,
        winner_condition=winner_condition,
        confidence=int(payload.get("confidence", 0) or 0),
        rationale=str(payload.get("rationale", "")),
        scores_a={
            k: int(v)
            for k, v in dict(payload.get("scores_a", {})).items()
            if isinstance(v, (int, float))
        },
        scores_b={
            k: int(v)
            for k, v in dict(payload.get("scores_b", {})).items()
            if isinstance(v, (int, float))
        },
        raw_judge_response=raw_judge_response,
    )


def judge_pairwise_omissions(
    case: DecisionUsefulnessCase,
    artifact_a: DecisionUsefulnessArtifact,
    artifact_b: DecisionUsefulnessArtifact,
    judge_model: Optional[str] = None,
    representation: str = "normalized",
) -> PairwiseOmissionJudgeResult:
    """Judge which artifact has the more serious omission."""
    jm = _pick_judge_model(artifact_a.model, judge_model)
    comparison = f"{artifact_a.condition}_vs_{artifact_b.condition}"
    use_original_order = _deterministic_ordering(
        case_id=case.id,
        run_number=artifact_a.run_number,
        comparison=f"{comparison}|omission",
        representation=representation,
        judge_model=jm,
    )

    if use_original_order:
        left_artifact, right_artifact = artifact_a, artifact_b
    else:
        left_artifact, right_artifact = artifact_b, artifact_a

    analysis_a, analysis_b = _prepare_pairwise_text(left_artifact, right_artifact, representation)
    prompt = PAIRWISE_OMISSION_PROMPT.format(
        scenario=case.scenario,
        analysis_a=analysis_a,
        analysis_b=analysis_b,
    )
    raw_judge_response, _ = call_llm(
        prompt,
        model=jm,
        temperature=0.0,
        max_tokens=1000,
    )
    payload = _extract_first_json_object(raw_judge_response)
    omission_raw = str(payload.get("which_analysis_has_more_serious_omission", "tie")).strip().upper()
    if omission_raw == "A":
        more_serious_omission_condition = left_artifact.condition
    elif omission_raw == "B":
        more_serious_omission_condition = right_artifact.condition
    else:
        more_serious_omission_condition = "tie"

    return PairwiseOmissionJudgeResult(
        case_id=case.id,
        source_model=artifact_a.model,
        judge_model=jm,
        run_number=artifact_a.run_number,
        comparison=comparison,
        representation=representation,
        condition_a=artifact_a.condition,
        condition_b=artifact_b.condition,
        left_condition=left_artifact.condition,
        right_condition=right_artifact.condition,
        more_serious_omission_condition=more_serious_omission_condition,
        confidence=int(payload.get("confidence", 0) or 0),
        rationale=str(payload.get("rationale", "")),
        largest_missing_consideration_a=str(payload.get("largest_missing_consideration_a", "")),
        largest_missing_consideration_b=str(payload.get("largest_missing_consideration_b", "")),
        raw_judge_response=raw_judge_response,
    )


def judge_pairwise_critique_survival(
    case: DecisionUsefulnessCase,
    artifact_a: DecisionUsefulnessArtifact,
    artifact_b: DecisionUsefulnessArtifact,
    judge_model: Optional[str] = None,
    representation: str = "decision_memo",
) -> PairwiseCritiqueSurvivalJudgeResult:
    """Judge which recommendation is less undermined by held-out critiques."""
    jm = _pick_judge_model(artifact_a.model, judge_model)
    comparison = f"{artifact_a.condition}_vs_{artifact_b.condition}"
    use_original_order = _deterministic_ordering(
        case_id=case.id,
        run_number=artifact_a.run_number,
        comparison=f"{comparison}|critique_survival",
        representation=representation,
        judge_model=jm,
    )

    if use_original_order:
        left_artifact, right_artifact = artifact_a, artifact_b
    else:
        left_artifact, right_artifact = artifact_b, artifact_a

    analysis_a, analysis_b = _prepare_pairwise_text(left_artifact, right_artifact, representation)
    prompt = PAIRWISE_CRITIQUE_SURVIVAL_PROMPT.format(
        scenario=case.scenario,
        analysis_a=analysis_a,
        analysis_b=analysis_b,
    )
    raw_judge_response, _ = call_llm(
        prompt,
        model=jm,
        temperature=0.0,
        max_tokens=1200,
    )
    payload = _extract_first_json_object(raw_judge_response)
    less_undermined_raw = str(payload.get("less_undermined_analysis", "tie")).strip().upper()
    if less_undermined_raw == "A":
        less_undermined_condition = left_artifact.condition
    elif less_undermined_raw == "B":
        less_undermined_condition = right_artifact.condition
    else:
        less_undermined_condition = "tie"

    return PairwiseCritiqueSurvivalJudgeResult(
        case_id=case.id,
        source_model=artifact_a.model,
        judge_model=jm,
        run_number=artifact_a.run_number,
        comparison=comparison,
        representation=representation,
        condition_a=artifact_a.condition,
        condition_b=artifact_b.condition,
        left_condition=left_artifact.condition,
        right_condition=right_artifact.condition,
        less_undermined_condition=less_undermined_condition,
        confidence=int(payload.get("confidence", 0) or 0),
        rationale=str(payload.get("rationale", "")),
        most_damaging_critique_a=str(payload.get("most_damaging_critique_a", "")),
        most_damaging_critique_b=str(payload.get("most_damaging_critique_b", "")),
        raw_judge_response=raw_judge_response,
    )


def _load_artifact(path: Path) -> DecisionUsefulnessArtifact:
    """Load a generated artifact from disk."""
    with open(path) as fh:
        data = json.load(fh)
    return DecisionUsefulnessArtifact(
        case_id=data["case_id"],
        condition=data["condition"],
        model=data["model"],
        run_number=data["run_number"],
        prompt=data["prompt"],
        response_text=data["response_text"],
        timestamp=data["timestamp"],
        duration_seconds=data.get("duration_seconds", 0.0),
        normalized_sections=data.get("normalized_sections", {}),
        normalized_representation=data.get("normalized_representation", ""),
        decision_memo_representation=data.get("decision_memo_representation", ""),
    )


def _ensure_artifact_representations(
    artifact: DecisionUsefulnessArtifact,
    scenario: str,
) -> DecisionUsefulnessArtifact:
    """Backfill newer judge representations for older saved artifacts."""
    normalized_sections = artifact.normalized_sections
    normalized_representation = artifact.normalized_representation

    if not normalized_sections or not normalized_representation:
        normalized_sections, normalized_representation = normalize_decision_analysis(
            response_text=artifact.response_text,
            scenario=scenario,
        )

    decision_memo_representation = artifact.decision_memo_representation or build_decision_memo(
        response_text=artifact.response_text,
        normalized_sections=normalized_sections,
    )

    return DecisionUsefulnessArtifact(
        case_id=artifact.case_id,
        condition=artifact.condition,
        model=artifact.model,
        run_number=artifact.run_number,
        prompt=artifact.prompt,
        response_text=artifact.response_text,
        timestamp=artifact.timestamp,
        duration_seconds=artifact.duration_seconds,
        normalized_sections=normalized_sections,
        normalized_representation=normalized_representation,
        decision_memo_representation=decision_memo_representation,
    )


def load_decision_usefulness_artifacts(output_dir: Path) -> list[DecisionUsefulnessArtifact]:
    """Load generated artifacts from an output directory."""
    results = []
    for path in sorted(Path(output_dir).glob("*_run*.json")):
        if path.name.startswith("judge_"):
            continue
        results.append(_load_artifact(path))
    return results


def run_decision_usefulness_judging(
    output_dir: Path,
    cases: Optional[list[DecisionUsefulnessCase]] = None,
    comparisons: Optional[list[tuple[str, str]]] = None,
    representations: Optional[list[str]] = None,
    judge_tasks: Optional[list[str]] = None,
    judge_model: Optional[str] = None,
    verbose: bool = True,
) -> tuple[
    list[PairwiseUtilityJudgeResult],
    list[PairwiseOmissionJudgeResult],
    list[PairwiseCritiqueSurvivalJudgeResult],
]:
    """Run pairwise judging over saved artifacts."""
    output_dir = Path(output_dir)
    if cases is None:
        cases = get_decision_usefulness_cases()
    if comparisons is None:
        comparisons = PRIMARY_PAIRWISE_COMPARISONS
    if representations is None:
        representations = REPRESENTATIONS
    if judge_tasks is None:
        judge_tasks = JUDGE_TASKS
    unsupported_tasks = sorted(set(judge_tasks) - set(JUDGE_TASKS))
    if unsupported_tasks:
        raise ValueError(f"Unsupported judge task(s): {unsupported_tasks}")

    case_lookup = {case.id: case for case in cases}
    artifacts = [
        _ensure_artifact_representations(artifact, case_lookup[artifact.case_id].scenario)
        for artifact in load_decision_usefulness_artifacts(output_dir)
        if artifact.case_id in case_lookup
    ]

    grouped: dict[tuple[str, str, int], DecisionUsefulnessArtifact] = {}
    for artifact in artifacts:
        grouped[(artifact.case_id, artifact.condition, artifact.run_number)] = artifact

    utility_results: list[PairwiseUtilityJudgeResult] = []
    omission_results: list[PairwiseOmissionJudgeResult] = []
    critique_results: list[PairwiseCritiqueSurvivalJudgeResult] = []

    for case in cases:
        run_numbers = sorted(
            {
                artifact.run_number
                for artifact in artifacts
                if artifact.case_id == case.id
            }
        )
        for run_number in run_numbers:
            for left_condition, right_condition in comparisons:
                left_artifact = grouped.get((case.id, left_condition, run_number))
                right_artifact = grouped.get((case.id, right_condition, run_number))
                if left_artifact is None or right_artifact is None:
                    continue
                for representation in representations:
                    if verbose:
                        print(
                            f"judge {case.id}/run{run_number} {left_condition} vs {right_condition} ({representation})"
                        )
                    if "utility" in judge_tasks:
                        utility_result = judge_pairwise_decision_usefulness(
                            case=case_lookup[case.id],
                            artifact_a=left_artifact,
                            artifact_b=right_artifact,
                            judge_model=judge_model,
                            representation=representation,
                        )
                        utility_results.append(utility_result)

                        utility_path = output_dir / (
                            "judge_utility_"
                            f"{case.id}_{left_condition}_vs_{right_condition}_run{run_number}_{representation}.json"
                        )
                        with open(utility_path, "w") as fh:
                            json.dump(utility_result.to_dict(), fh, indent=2)

                    if "omission" in judge_tasks:
                        omission_result = judge_pairwise_omissions(
                            case=case_lookup[case.id],
                            artifact_a=left_artifact,
                            artifact_b=right_artifact,
                            judge_model=judge_model,
                            representation=representation,
                        )
                        omission_results.append(omission_result)

                        omission_path = output_dir / (
                            "judge_omission_"
                            f"{case.id}_{left_condition}_vs_{right_condition}_run{run_number}_{representation}.json"
                        )
                        with open(omission_path, "w") as fh:
                            json.dump(omission_result.to_dict(), fh, indent=2)

                    if "critique_survival" in judge_tasks:
                        critique_result = judge_pairwise_critique_survival(
                            case=case_lookup[case.id],
                            artifact_a=left_artifact,
                            artifact_b=right_artifact,
                            judge_model=judge_model,
                            representation=representation,
                        )
                        critique_results.append(critique_result)

                        critique_path = output_dir / (
                            "judge_critique_"
                            f"{case.id}_{left_condition}_vs_{right_condition}_run{run_number}_{representation}.json"
                        )
                        with open(critique_path, "w") as fh:
                            json.dump(critique_result.to_dict(), fh, indent=2)

    summary = summarize_decision_usefulness_judging(
        utility_results,
        omission_results,
        critique_results,
    )
    with open(output_dir / "judge_summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)

    return utility_results, omission_results, critique_results


def summarize_decision_usefulness_judging(
    utility_results: list[PairwiseUtilityJudgeResult],
    omission_results: list[PairwiseOmissionJudgeResult],
    critique_results: Optional[list[PairwiseCritiqueSurvivalJudgeResult]] = None,
) -> dict[str, Any]:
    """Summarize pairwise judging results."""
    if critique_results is None:
        critique_results = []

    summary: dict[str, Any] = {
        "utility": {},
        "omission": {},
        "critique_survival": {},
    }

    for representation in REPRESENTATIONS:
        rep_utility = [result for result in utility_results if result.representation == representation]
        rep_omission = [result for result in omission_results if result.representation == representation]
        rep_critique = [result for result in critique_results if result.representation == representation]
        summary["utility"][representation] = {}
        summary["omission"][representation] = {}
        summary["critique_survival"][representation] = {}

        comparisons = sorted({result.comparison for result in rep_utility})
        for comparison in comparisons:
            comp_utility = [result for result in rep_utility if result.comparison == comparison]
            winners: dict[str, int] = {}
            for result in comp_utility:
                winners[result.winner_condition] = winners.get(result.winner_condition, 0) + 1
            total_non_tie = sum(count for cond, count in winners.items() if cond != "tie")
            summary["utility"][representation][comparison] = {
                "n": len(comp_utility),
                "wins": winners,
                "non_tie_n": total_non_tie,
                "mean_confidence": round(
                    sum(result.confidence for result in comp_utility) / len(comp_utility),
                    2,
                )
                if comp_utility
                else None,
            }

        omission_comparisons = sorted({result.comparison for result in rep_omission})
        for comparison in omission_comparisons:
            comp_omission = [result for result in rep_omission if result.comparison == comparison]
            flagged: dict[str, int] = {}
            for result in comp_omission:
                flagged[result.more_serious_omission_condition] = (
                    flagged.get(result.more_serious_omission_condition, 0) + 1
                )
            summary["omission"][representation][comparison] = {
                "n": len(comp_omission),
                "flagged_more_serious": flagged,
                "mean_confidence": round(
                    sum(result.confidence for result in comp_omission) / len(comp_omission),
                    2,
                )
                if comp_omission
                else None,
            }

        critique_comparisons = sorted({result.comparison for result in rep_critique})
        for comparison in critique_comparisons:
            comp_critique = [result for result in rep_critique if result.comparison == comparison]
            less_undermined: dict[str, int] = {}
            for result in comp_critique:
                less_undermined[result.less_undermined_condition] = (
                    less_undermined.get(result.less_undermined_condition, 0) + 1
                )
            summary["critique_survival"][representation][comparison] = {
                "n": len(comp_critique),
                "less_undermined": less_undermined,
                "mean_confidence": round(
                    sum(result.confidence for result in comp_critique) / len(comp_critique),
                    2,
                )
                if comp_critique
                else None,
            }

    return summary


def print_decision_usefulness_summary(
    utility_results: list[PairwiseUtilityJudgeResult],
    omission_results: list[PairwiseOmissionJudgeResult],
    critique_results: Optional[list[PairwiseCritiqueSurvivalJudgeResult]] = None,
) -> None:
    """Print a concise summary for CLI use."""
    summary = summarize_decision_usefulness_judging(
        utility_results,
        omission_results,
        critique_results,
    )
    print("\n============================================================")
    print("DECISION-USEFULNESS JUDGING SUMMARY")
    print("============================================================")
    for representation in REPRESENTATIONS:
        if summary["utility"][representation]:
            print(f"\n[{representation}] utility")
            for comparison, data in summary["utility"][representation].items():
                wins = ", ".join(f"{cond}={count}" for cond, count in sorted(data["wins"].items()))
                print(
                    f"  {comparison}: n={data['n']} mean_conf={data['mean_confidence']} wins({wins})"
                )
        if summary["omission"][representation]:
            print(f"\n[{representation}] omission")
            for comparison, data in summary["omission"][representation].items():
                flagged = ", ".join(
                    f"{cond}={count}" for cond, count in sorted(data["flagged_more_serious"].items())
                )
                print(
                    f"  {comparison}: n={data['n']} mean_conf={data['mean_confidence']} flagged({flagged})"
                )
        if summary["critique_survival"][representation]:
            print(f"\n[{representation}] critique survival")
            for comparison, data in summary["critique_survival"][representation].items():
                less_undermined = ", ".join(
                    f"{cond}={count}" for cond, count in sorted(data["less_undermined"].items())
                )
                print(
                    f"  {comparison}: n={data['n']} mean_conf={data['mean_confidence']} "
                    f"less_undermined({less_undermined})"
                )


def default_output_dir_for_model(model: str) -> Path:
    """Return the default output directory for a generator model."""
    return Path(f"experiments/decision_usefulness/{model_short_name(model)}")
