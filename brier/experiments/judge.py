"""LLM-as-judge evaluation for reframing quality and stability quality.

Cross-model judging: Claude judges GPT responses and vice versa.
Judge is blinded to condition.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from brier.experiments import components
from brier.experiments.llm import call_llm, _is_openai_model


REFRAMING_JUDGE_PROMPT = """You are an expert evaluator of decision advice quality. You will evaluate a response
to a decision scenario. You do NOT know what method or prompt was used to generate this response.

## Scenario
{scenario}

## Response to evaluate
{response}

## Scoring criteria

Rate each dimension on a 1-5 scale:

1. **Surface analysis** (1-5): Does the response address the obvious/surface-level aspects of the decision?
   1 = ignores the question, 5 = thorough surface analysis

2. **New KPIs** (1-5): Does the response introduce metrics or success criteria beyond those implied by the question?
   1 = only addresses obvious metrics, 5 = introduces multiple novel, relevant KPIs

3. **Framing challenge** (1-5): Does the response challenge the assumptions or framing of the question itself?
   1 = accepts framing at face value, 5 = fundamentally reframes the problem

4. **Alternatives** (1-5): Does the response surface options or paths not mentioned in the original question?
   1 = only discusses stated options, 5 = introduces multiple creative alternatives

""" + components.fenced_json_contract(
    '{{"surface_analysis": <1-5>, "new_kpis": <1-5>, "framing_challenge": <1-5>, "alternatives": <1-5>, "reasoning": "<brief explanation>"}}'
) + "\n"

QUALITY_JUDGE_PROMPT = """You are an expert evaluator of decision analysis quality. You will evaluate a pair of
responses (initial analysis and revised analysis after receiving new information) for a decision scenario.
You do NOT know what method or prompt was used.

## Scenario
{scenario}

## Initial response
{initial_response}

## New information provided
{probes}

## Revised response
{final_response}

## Scoring criteria

Rate each dimension on a 1-5 scale:

1. **Reasoning depth** (1-5): How thorough and well-structured is the reasoning?
   1 = superficial, 5 = deeply analytical with clear logical chain

2. **Appropriate updating** (1-5): Did the revision appropriately incorporate the new information?
   1 = ignored evidence or over-reacted, 5 = calibrated Bayesian-like updating

3. **Bias recognition** (1-5): Does the response identify and account for cognitive biases?
   1 = no awareness of biases, 5 = explicitly identifies and mitigates relevant biases

4. **Uncertainty quantification** (1-5): How well does the response handle uncertainty?
   1 = false precision, 5 = well-calibrated confidence intervals with appropriate hedging

""" + components.fenced_json_contract(
    '{{"reasoning_depth": <1-5>, "appropriate_updating": <1-5>, "bias_recognition": <1-5>, "uncertainty_quantification": <1-5>, "reasoning": "<brief explanation>"}}'
) + "\n"


@dataclass
class JudgeScore:
    """Score from LLM-as-judge evaluation."""

    source_model: str  # Model that generated the response
    judge_model: str  # Model acting as judge
    case_id: str
    condition: str
    scores: dict[str, int] = field(default_factory=dict)
    reasoning: str = ""
    judge_type: str = ""  # "reframing" or "quality"

    def to_dict(self) -> dict:
        return {
            "source_model": self.source_model,
            "judge_model": self.judge_model,
            "case_id": self.case_id,
            "condition": self.condition,
            "scores": self.scores,
            "reasoning": self.reasoning,
            "judge_type": self.judge_type,
        }


def _extract_judge_scores(response: str) -> tuple[dict, str]:
    """Extract JSON scores from judge response."""
    return components.scored_json(
        response, key_hints=("surface_analysis", "reasoning_depth")
    )


def _pick_judge_model(source_model: str, explicit_judge: Optional[str] = None) -> str:
    """Pick a judge model for cross-model evaluation."""
    if explicit_judge:
        return explicit_judge
    # Cross-model: if source is OpenAI, judge with Anthropic and vice versa
    if _is_openai_model(source_model):
        return "claude-opus-4-6"
    return "gpt-5.2"


def judge_reframing(
    response: str,
    scenario: str,
    case_id: str,
    condition: str,
    source_model: str,
    judge_model: Optional[str] = None,
) -> JudgeScore:
    """Judge a reframing response for quality dimensions."""
    jm = _pick_judge_model(source_model, judge_model)

    prompt = REFRAMING_JUDGE_PROMPT.format(
        scenario=scenario,
        response=response,
    )

    judge_response, _ = call_llm(prompt, model=jm, temperature=0.0, max_tokens=1024)
    scores, reasoning = _extract_judge_scores(judge_response)

    return JudgeScore(
        source_model=source_model,
        judge_model=jm,
        case_id=case_id,
        condition=condition,
        scores=scores,
        reasoning=reasoning,
        judge_type="reframing",
    )


def judge_quality(
    initial_response: str,
    final_response: str,
    scenario: str,
    probes: str,
    case_id: str,
    condition: str,
    source_model: str,
    judge_model: Optional[str] = None,
) -> JudgeScore:
    """Judge stability response quality (stability != rigidity)."""
    jm = _pick_judge_model(source_model, judge_model)

    prompt = QUALITY_JUDGE_PROMPT.format(
        scenario=scenario,
        initial_response=initial_response,
        probes=probes,
        final_response=final_response,
    )

    judge_response, _ = call_llm(prompt, model=jm, temperature=0.0, max_tokens=1024)
    scores, reasoning = _extract_judge_scores(judge_response)

    return JudgeScore(
        source_model=source_model,
        judge_model=jm,
        case_id=case_id,
        condition=condition,
        scores=scores,
        reasoning=reasoning,
        judge_type="quality",
    )


def run_judge_evaluation(
    reframing_dir: Path,
    stability_dir: Path,
    judge_model: Optional[str] = None,
    verbose: bool = True,
) -> None:
    """Run LLM-as-judge evaluation on existing results."""
    from brier.experiments.reframing import REFRAMING_CASES
    from brier.experiments.stability import STABILITY_CASES

    reframing_dir = Path(reframing_dir)
    stability_dir = Path(stability_dir)

    # Build case lookup
    reframing_lookup = {c.id: c for c in REFRAMING_CASES}
    stability_lookup = {c.id: c for c in STABILITY_CASES}

    all_scores = []

    # Judge reframing results
    for model_dir in _iter_model_dirs(reframing_dir):
        model_name = model_dir.name
        for f in sorted(model_dir.glob("reframe_*.json")):
            if f.name in ("summary.json", "scores.json"):
                continue
            with open(f) as fh:
                data = json.load(fh)

            case_id = data["case_id"]
            case = reframing_lookup.get(case_id)
            if not case:
                continue

            source_model = data.get("model", model_name)

            if verbose:
                print(f"Judging reframing: {case_id}/{data['condition']} ({source_model})")

            score = judge_reframing(
                response=data.get("response_text", ""),
                scenario=case.scenario,
                case_id=case_id,
                condition=data["condition"],
                source_model=source_model,
                judge_model=judge_model,
            )
            all_scores.append(score)

            # Save incrementally
            score_file = model_dir / f"judge_{f.stem}.json"
            with open(score_file, "w") as fh:
                json.dump(score.to_dict(), fh, indent=2)

    # Judge stability results (quality evaluation)
    for model_dir in _iter_model_dirs(stability_dir):
        model_name = model_dir.name
        for f in sorted(model_dir.glob("*_run*.json")):
            if f.name in ("summary.json", "experiment_metadata.json") or f.name.startswith("judge_"):
                continue
            with open(f) as fh:
                data = json.load(fh)

            case_id = data["case_id"]
            case = stability_lookup.get(case_id)
            if not case:
                continue

            source_model = data.get("model", model_name)
            initial_text = data.get("initial_response_text", "")
            final_text = data.get("final_response_text", "")

            # Skip if no response texts saved
            if not initial_text or not final_text:
                continue

            probes_text = "\n".join(f"- {p}" for p in case.probes)

            if verbose:
                print(f"Judging quality: {case_id}/{data['condition']} ({source_model})")

            score = judge_quality(
                initial_response=initial_text,
                final_response=final_text,
                scenario=case.scenario,
                probes=probes_text,
                case_id=case_id,
                condition=data["condition"],
                source_model=source_model,
                judge_model=judge_model,
            )
            all_scores.append(score)

            score_file = model_dir / f"judge_{f.stem}.json"
            with open(score_file, "w") as fh:
                json.dump(score.to_dict(), fh, indent=2)

    # Summary
    if verbose and all_scores:
        _print_judge_summary(all_scores)


def _iter_model_dirs(base: Path) -> list[Path]:
    """Find model subdirectories, or use base as single dir."""
    if not base.exists():
        return []
    subdirs = [d for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if subdirs:
        return sorted(subdirs)
    return [base]


def _print_judge_summary(scores: list[JudgeScore]) -> None:
    """Print summary of judge scores by condition."""
    print(f"\n{'='*60}")
    print("LLM-AS-JUDGE RESULTS")
    print(f"{'='*60}")

    for judge_type in ["reframing", "quality"]:
        type_scores = [s for s in scores if s.judge_type == judge_type]
        if not type_scores:
            continue

        print(f"\n--- {judge_type.upper()} ---")
        conditions = sorted(set(s.condition for s in type_scores))
        dimensions = sorted(set(k for s in type_scores for k in s.scores.keys()))

        header = f"{'Dimension':<25}" + "".join(f"{c:>12}" for c in conditions)
        print(header)
        print("-" * len(header))

        for dim in dimensions:
            vals = {}
            for cond in conditions:
                cond_scores = [s.scores.get(dim, 0) for s in type_scores if s.condition == cond and dim in s.scores]
                if cond_scores:
                    vals[cond] = sum(cond_scores) / len(cond_scores)
                else:
                    vals[cond] = None

            row = f"{dim:<25}" + "".join(
                f"{vals[c]:>12.2f}" if vals[c] is not None else f"{'N/A':>12}"
                for c in conditions
            )
            print(row)
