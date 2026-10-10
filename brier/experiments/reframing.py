"""Reframing experiment: does the brier framework reduce problem reframing?

Tests whether structured forecasting constrains or preserves an advisor's
ability to challenge the decision framing itself — suggesting different KPIs,
redefining the problem, or surfacing that the "real question" is something else.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from brier.experiments import components
from brier.experiments.llm import call_llm

try:
    import numpy as np
    from scipy import stats

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    np = None  # type: ignore
    stats = None  # type: ignore


@dataclass
class ReframingCase:
    """A decision where a good advisor should reframe the problem."""

    id: str
    name: str
    scenario: str

    # The obvious KPIs implied by the question
    surface_kpis: list[str]

    # The "real" KPIs or reframes a good advisor should surface
    deeper_reframes: list[str]

    # Keywords that indicate reframing (beyond the surface question)
    reframe_indicators: list[str]


REFRAMING_CASES = [
    ReframingCase(
        id="grad_school",
        name="Should I go to grad school?",
        scenario="""I'm a software engineer with 3 years of experience making $130K.
I got into a good MBA program. The tuition is $80K/year for 2 years. Should I go?""",
        surface_kpis=["salary increase", "tuition cost", "ROI", "earnings"],
        deeper_reframes=[
            "What career do you actually want? MBA solves a networking/credential problem, not a skills problem",
            "Are you running toward the MBA or away from your current job?",
            "Have you considered that many tech careers don't value MBAs?",
            "What specific role do you want post-MBA that you can't get now?",
        ],
        reframe_indicators=[
            "wrong question", "real question", "actually want",
            "running away", "running toward", "why do you want",
            "what are you trying to", "underlying goal", "root cause",
            "before we forecast", "step back", "bigger picture",
            "career you want", "not just about", "deeper issue",
            "identity", "what kind of", "who do you want to be",
        ],
    ),
    ReframingCase(
        id="feature_build",
        name="Should we build this feature?",
        scenario="""Our users have been asking for a mobile app. We're a B2B SaaS company
with 200 customers. Our web app works on mobile browsers but isn't optimized.
Building a native app would take 4 months and $200K. Should we build it?""",
        surface_kpis=["development cost", "user retention", "revenue impact", "timeline"],
        deeper_reframes=[
            "Are users actually churning because of mobile, or is this a nice-to-have?",
            "Could you solve this with a responsive web redesign instead?",
            "Is mobile usage high enough in your B2B segment to justify this?",
            "What's the opportunity cost — what else could you build with that $200K?",
        ],
        reframe_indicators=[
            "opportunity cost", "alternative", "responsive",
            "PWA", "progressive web", "actually churning",
            "nice to have", "must have", "what else could",
            "wrong problem", "real problem", "root cause",
            "prioriti", "instead of", "before building",
            "validate", "test first", "prototype",
        ],
    ),
    ReframingCase(
        id="move_cities",
        name="Should I move to SF or stay in Austin?",
        scenario="""I'm a senior engineer. I got an offer in SF for $250K (vs $180K now in Austin).
Cost of living is way higher in SF though. My partner works remotely so they're flexible.
Should I take the SF offer?""",
        surface_kpis=["salary", "cost of living", "savings rate", "career growth"],
        deeper_reframes=[
            "What does your partner actually want? 'Flexible' doesn't mean 'enthusiastic'",
            "Is this about the money or about something else (excitement, status, career stage)?",
            "Could you negotiate remote-first and get a middle ground?",
            "What community and lifestyle factors matter beyond finances?",
        ],
        reframe_indicators=[
            "partner", "relationship", "community", "lifestyle",
            "remote", "negotiate", "hybrid", "what do you value",
            "beyond money", "beyond salary", "not just financial",
            "happiness", "fulfillment", "well-being", "quality of life",
            "social", "friends", "network", "belong",
            "identity", "stage of life", "what matters most",
        ],
    ),
    ReframingCase(
        id="hire_senior",
        name="Should we hire a VP of Engineering?",
        scenario="""We're a 15-person startup that just raised Series A. Engineering is our
bottleneck — we can't ship fast enough. Our CTO is overwhelmed. Should we hire
a VP of Engineering to manage the team so the CTO can focus on architecture?""",
        surface_kpis=["hiring timeline", "salary cost", "shipping velocity", "team productivity"],
        deeper_reframes=[
            "Is the bottleneck actually management, or is it technical debt/process?",
            "Does your CTO actually want to give up management, or will they resist?",
            "At 15 people, do you need a VP or would a strong tech lead suffice?",
            "Could better processes (sprint planning, CI/CD) solve this without a hire?",
        ],
        reframe_indicators=[
            "technical debt", "process", "bottleneck",
            "CTO wants", "CTO willing", "org design",
            "too early", "premature", "team size",
            "tech lead instead", "senior IC", "alternative",
            "root cause", "real problem", "underlying",
            "sprint", "CI/CD", "tooling", "automation",
        ],
    ),
    ReframingCase(
        id="raise_funding",
        name="Should we raise a Series B?",
        scenario="""We're growing 15% month-over-month with $500K MRR. We have 12 months of
runway. VCs are interested and we could probably raise $20M at a $200M valuation.
Should we raise now or wait until we're bigger for a better valuation?""",
        surface_kpis=["valuation", "dilution", "runway", "growth rate"],
        deeper_reframes=[
            "Do you actually need the money, or are you raising because you can?",
            "What would you do with $20M that you can't do with your current runway?",
            "Is 15% MoM sustainable, or are you about to hit a growth ceiling?",
            "Have you considered profitability as an alternative to fundraising?",
        ],
        reframe_indicators=[
            "need the money", "use of funds", "what would you do with",
            "profitable", "profitability", "bootstrap", "self-fund",
            "growth ceiling", "sustainable", "plateau",
            "default alive", "burn rate", "unit economics",
            "why raise", "don't need to", "optionality",
        ],
    ),
    ReframingCase(
        id="quit_job",
        name="Should I quit to start a startup?",
        scenario="""I'm a product manager at Google making $350K. I have a startup idea
I'm passionate about — a developer tools company. I have $200K saved. My spouse
works and we have a 2-year-old. Should I quit to go full-time on this?""",
        surface_kpis=["financial runway", "startup success probability", "income loss", "market size"],
        deeper_reframes=[
            "Can you validate the idea before quitting? Nights/weekends MVP?",
            "What does your spouse actually think? Have you had the real conversation?",
            "Is this about the startup or about being unhappy at Google?",
            "What would make you regret NOT doing this in 10 years?",
        ],
        reframe_indicators=[
            "spouse", "family", "partner", "validate first",
            "side project", "nights and weekends", "before quitting",
            "regret", "unhappy", "fulfillment", "calling",
            "risk tolerance", "worst case", "reversible",
            "identity", "founder identity", "who you want to be",
            "why now", "timing", "could you wait",
        ],
    ),
]


NAIVE_PROMPT = """You are a helpful advisor. Help me think through this decision:

{scenario}

What should I do? Give me your honest recommendation with reasoning."""

COT_PROMPT = """You are a helpful advisor. Think through this step by step.

{scenario}

Think through this carefully step by step, then give me your honest recommendation with reasoning."""

BRIER_PROMPT = (
    'You are a decision analyst using the "Brier" framework. Apply this process:\n\n'
    + components.numbered(
        [
            components.DEFINE_MEASURABLE_KPIS,
            components.OPTIONS_INCLUDING_UNMENTIONED,
            components.FORECAST_OPTION_BY_KPI,
            components.BASE_RATES_RELEVANT,
            components.COGNITIVE_BIASES_IN_FRAMING,
            components.RECOMMENDATION_FROM_EV,
        ]
    )
    + "\n\nDecision:\n{scenario}"
)


@dataclass
class ReframingResult:
    """Result from a single reframing trial."""

    case_id: str
    condition: str  # "naive", "cot", or "farness"
    run_number: int
    response_text: str
    timestamp: str
    duration_seconds: float
    model: str = "claude-opus-4-6"

    # Computed
    reframe_count: int = 0
    reframe_matches: list[str] = field(default_factory=list)
    introduced_new_kpis: bool = False
    challenged_framing: bool = False

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "condition": self.condition,
            "model": self.model,
            "run_number": self.run_number,
            "reframe_count": self.reframe_count,
            "reframe_matches": self.reframe_matches,
            "introduced_new_kpis": self.introduced_new_kpis,
            "challenged_framing": self.challenged_framing,
            "response_text": self.response_text,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
        }


def score_reframing(response: str, case: ReframingCase) -> tuple[int, list[str], bool, bool]:
    """Score a response for reframing indicators.

    Returns: (reframe_count, matched_indicators, introduced_new_kpis, challenged_framing)
    """
    text_lower = response.lower()
    matched = []

    for indicator in case.reframe_indicators:
        if indicator.lower() in text_lower:
            matched.append(indicator)

    # Check if response introduced KPIs beyond the surface ones
    surface_kpi_words = set()
    for kpi in case.surface_kpis:
        surface_kpi_words.update(kpi.lower().split())

    # Look for novel KPI-like language
    kpi_patterns = [
        r"(?:KPI|metric|measure|optimize for|success means|define success as)\s*[:\-]?\s*(.+)",
        r"what (?:really |actually )?matters (?:here )?is\s+(.+)",
    ]
    new_kpi = False
    for pattern in kpi_patterns:
        match = re.search(pattern, text_lower)
        if match:
            kpi_text = match.group(1)
            # Check if it's about something NOT in surface KPIs
            if not any(word in kpi_text for word in surface_kpi_words if len(word) > 3):
                new_kpi = True
                break

    # Check if response explicitly challenges the framing
    challenge_patterns = [
        r"(?:the )?(?:real|actual|underlying|deeper) (?:question|issue|problem)",
        r"(?:before|first).{0,30}(?:consider|ask|think about)",
        r"step back",
        r"wrong (?:question|frame|way to think)",
        r"reframe",
        r"(?:might|should) (?:instead|also) (?:ask|consider|think)",
        r"not (?:really|actually|just) about",
    ]
    challenged = any(
        re.search(p, text_lower) for p in challenge_patterns
    )

    return len(matched), matched, new_kpi, challenged


def run_single_trial(
    case: ReframingCase,
    condition: str,
    run_number: int,
    model: str = "claude-opus-4-6",
    timeout: int = 120,
) -> ReframingResult:
    """Run a single reframing trial using the LLM API."""
    if condition == "naive":
        template = NAIVE_PROMPT
    elif condition == "cot":
        template = COT_PROMPT
    else:
        template = BRIER_PROMPT
    prompt = template.format(scenario=case.scenario.strip())

    timestamp = datetime.now().isoformat()
    response, duration = call_llm(prompt, model=model, timeout=float(timeout))

    reframe_count, reframe_matches, new_kpis, challenged = score_reframing(response, case)

    return ReframingResult(
        case_id=case.id,
        condition=condition,
        run_number=run_number,
        response_text=response,
        timestamp=timestamp,
        duration_seconds=duration,
        model=model,
        reframe_count=reframe_count,
        reframe_matches=reframe_matches,
        introduced_new_kpis=new_kpis,
        challenged_framing=challenged,
    )


def run_reframing_experiment(
    cases: list[ReframingCase] | None = None,
    runs_per_condition: int = 3,
    output_dir: Path | None = None,
    verbose: bool = True,
    start_run: int = 1,
    model: str = "claude-opus-4-6",
    conditions: list[str] | None = None,
) -> list[ReframingResult]:
    """Run the full reframing experiment."""
    if cases is None:
        cases = REFRAMING_CASES
    if conditions is None:
        conditions = ["naive", "farness"]

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    total = len(cases) * len(conditions) * runs_per_condition
    i = 0

    for case in cases:
        for condition in conditions:
            for run_num in range(start_run, start_run + runs_per_condition):
                i += 1
                if verbose:
                    print(f"[{i}/{total}] {case.id} - {condition} - run {run_num}")

                result = run_single_trial(case, condition, run_num, model=model)
                results.append(result)

                if verbose:
                    print(f"  reframe_count={result.reframe_count} challenged={result.challenged_framing} ({result.duration_seconds:.1f}s)")

                if output_dir:
                    result_file = output_dir / f"reframe_{case.id}_{condition}_{run_num}.json"
                    with open(result_file, "w") as f:
                        json.dump(result.to_dict(), f, indent=2)

    return results


def analyze_reframing(results: list[ReframingResult]) -> dict:
    """Analyze reframing experiment results.

    Supports 2 or 3 conditions with pairwise comparisons and Holm-Bonferroni correction.
    """
    from brier.experiments.stability import holm_bonferroni

    valid = [r for r in results if not r.response_text.startswith("ERROR")]
    conditions = sorted(set(r.condition for r in valid))
    by_condition = {c: [r for r in valid if r.condition == c] for c in conditions}

    def stats_for(group: list[ReframingResult]) -> dict:
        if not group:
            return {}
        n = len(group)
        return {
            "n": n,
            "mean_reframe_count": sum(r.reframe_count for r in group) / n,
            "challenged_framing_rate": sum(r.challenged_framing for r in group) / n,
            "introduced_new_kpis_rate": sum(r.introduced_new_kpis for r in group) / n,
        }

    analysis = {c: stats_for(by_condition[c]) for c in conditions}
    analysis["conditions"] = conditions

    # Pairwise comparisons
    comparison = {}
    raw_p_values = []
    pair_keys = []

    if HAS_SCIPY:
        for i, c1 in enumerate(conditions):
            for c2 in conditions[i+1:]:
                g1, g2 = by_condition[c1], by_condition[c2]
                if len(g1) >= 2 and len(g2) >= 2:
                    pair_key = f"{c1}_vs_{c2}"
                    pair_keys.append(pair_key)
                    counts1 = [r.reframe_count for r in g1]
                    counts2 = [r.reframe_count for r in g2]

                    # Mann-Whitney U (two-sided)
                    u_stat, p_value = stats.mannwhitneyu(counts1, counts2, alternative='two-sided')
                    n1, n2 = len(counts1), len(counts2)
                    r_rb = 1 - (2 * u_stat) / (n1 * n2)

                    # New KPI rates: Fisher's exact (two-sided)
                    kpi1 = sum(r.introduced_new_kpis for r in g1)
                    kpi2 = sum(r.introduced_new_kpis for r in g2)
                    kpi_table = [[kpi1, len(g1) - kpi1], [kpi2, len(g2) - kpi2]]
                    _, p_kpis = stats.fisher_exact(kpi_table, alternative='two-sided')

                    comparison[pair_key] = {
                        "reframe_count": {
                            "mann_whitney_u": float(u_stat),
                            "p_value_raw": float(p_value),
                            "effect_size_r": float(r_rb),
                        },
                        "introduced_new_kpis": {
                            "fisher_exact_p_raw": float(p_kpis),
                            f"{c1}_count": int(kpi1),
                            f"{c2}_count": int(kpi2),
                        },
                    }
                    raw_p_values.extend([p_value, p_kpis])

        # Holm-Bonferroni correction across all p-values
        if raw_p_values:
            corrected = holm_bonferroni(raw_p_values)
            idx = 0
            for key in pair_keys:
                comparison[key]["reframe_count"]["p_value_corrected"] = float(corrected[idx])
                comparison[key]["introduced_new_kpis"]["fisher_exact_p_corrected"] = float(corrected[idx + 1])
                idx += 2

    analysis["statistical_comparison"] = comparison

    # Per-case breakdown
    case_ids = sorted(set(r.case_id for r in valid))
    by_case = {}
    for cid in case_ids:
        by_case[cid] = {c: stats_for([r for r in by_condition.get(c, []) if r.case_id == cid]) for c in conditions}
    analysis["by_case"] = by_case

    return analysis


def summary_table(results: list[ReframingResult]) -> str:
    """Generate markdown summary table."""
    analysis = analyze_reframing(results)
    conditions = analysis.get("conditions", ["naive", "farness"])

    sizes = ", ".join(f"n_{c} = {analysis.get(c, {}).get('n', 0)}" for c in conditions)
    lines = [
        "## Reframing experiment results",
        "",
        f"**Sample sizes**: {sizes}",
        "",
        "### Reframing metrics",
        "",
    ]

    # Dynamic header
    header = "| Metric |" + " | ".join(c.capitalize() for c in conditions) + " |"
    sep = "|--------|" + " | ".join("-------" for _ in conditions) + " |"
    lines.extend([header, sep])

    def fmt(v):
        if v is None:
            return "N/A"
        if isinstance(v, float):
            if 0 <= v <= 1:
                return f"{v:.0%}"
            return f"{v:.2f}"
        return str(v)

    def fmt_p(p):
        if p is None:
            return "—"
        if p < 0.001:
            return "<0.001"
        if p < 0.01:
            return f"{p:.3f}"
        return f"{p:.2f}"

    for metric in ["mean_reframe_count", "challenged_framing_rate", "introduced_new_kpis_rate"]:
        label = metric.replace("_", " ").replace("mean ", "").capitalize()
        vals = " | ".join(fmt(analysis.get(c, {}).get(metric)) for c in conditions)
        lines.append(f"| {label} | {vals} |")

    # Pairwise comparisons
    comparison = analysis.get("statistical_comparison", {})
    if comparison:
        lines.extend(["", "### Pairwise comparisons", ""])
        for pair_key, data in comparison.items():
            c1, c2 = pair_key.split("_vs_")
            lines.append(f"**{c1} vs {c2}**:")
            rc = data.get("reframe_count", {})
            if rc:
                lines.append(f"- Reframe count: U={rc.get('mann_whitney_u', 'N/A'):.1f}, "
                             f"p(raw)={fmt_p(rc.get('p_value_raw'))}, "
                             f"p(corrected)={fmt_p(rc.get('p_value_corrected'))}, "
                             f"r={rc.get('effect_size_r', 0):.2f}")
            nk = data.get("introduced_new_kpis", {})
            if nk:
                lines.append(f"- New KPIs: Fisher p(raw)={fmt_p(nk.get('fisher_exact_p_raw'))}, "
                             f"p(corrected)={fmt_p(nk.get('fisher_exact_p_corrected'))}")
            lines.append("")

    # Per-case
    lines.extend(["### Per-case breakdown", ""])
    for cid, data in analysis.get("by_case", {}).items():
        parts = []
        for c in conditions:
            val = data.get(c, {}).get("mean_reframe_count", 0) or 0
            parts.append(f"{c}={val:.1f}")
        lines.append(f"- **{cid}**: {' vs '.join(parts)}")

    return "\n".join(lines)
