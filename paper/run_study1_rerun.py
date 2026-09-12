"""Rerun the original Study 1 stability design on one or more models.

This script intentionally freezes the original paper prompt wording so a new
OpenAI rerun can be compared to the original GPT-5.2 corpus without also
changing the prompts.

The live tracks compose their prompts from `brier.experiments.components`.
The `legacy_*` builders below are an archival copy of the Study 1 treatment and
must keep their own literals even when the shared components move on.

Note that only the *emit* side is frozen. This script still imports
`extract_estimate`/`extract_ci` from `stability`, which now resolve to the
shared components — so a change to the parsers does reach this rerun. That is
the pre-existing arrangement, and arguably the right one (a parser fix should
apply to old and new corpora alike), but it means "frozen" covers the prompts
only, not the full pipeline.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brier.experiments.llm import call_llm
from brier.experiments.stability import (
    DEFAULT_PROBE_BATTERY,
    QuantitativeCase,
    StabilityExperiment,
    StabilityResult,
    extract_ci,
    extract_estimate,
    get_all_stability_cases,
    get_stability_case,
)

DEFAULT_MODELS = ["gpt-5.4"]
STUDY1_CONDITIONS = ["naive", "cot", "farness"]

_LEGACY_JSON_INSTRUCTION = """

After your reasoning, output your final answer as a JSON block:
```json
{"estimate": <number>, "ci_low": <number>, "ci_high": <number>}
```
where ci_low and ci_high are the bounds of your 80% confidence interval."""


def _extract_estimate_or_raise(response: str, unit: str, phase: str) -> float:
    estimate = extract_estimate(response, unit)
    if estimate is not None:
        return estimate

    numbers = re.findall(r"\b(\d+\.?\d*)\b", response)
    if numbers:
        return float(numbers[0])

    raise ValueError(f"Could not extract {phase} estimate from response: {response[:200]}")


def legacy_generate_initial_prompt(case: QuantitativeCase, condition: str) -> str:
    if condition == "naive":
        return f"""You are a helpful assistant. Answer directly and concisely.

{case.scenario}

Question: {case.estimate_question} Give a single number and an 80% confidence interval.{_LEGACY_JSON_INSTRUCTION}"""

    if condition == "cot":
        return f"""You are a helpful assistant. Think through this step by step.

{case.scenario}

Question: {case.estimate_question} Think through this carefully step by step, then give a single number and an 80% confidence interval.{_LEGACY_JSON_INSTRUCTION}"""

    if condition == "farness":
        return f"""You are a decision analyst using the "farness" framework. This requires:
1. Cite base rates from research (outside view)
2. Make numeric forecasts with confidence intervals
3. Identify cognitive biases in the framing

{case.scenario}

Question: {case.estimate_question} Give a point estimate and 80% confidence interval.{_LEGACY_JSON_INSTRUCTION}"""

    raise ValueError(f"Unknown condition: {condition}")


def legacy_generate_probe_prompt(
    case: QuantitativeCase,
    initial_estimate: float,
    initial_ci: tuple[float | None, float | None] | None,
    condition: str,
) -> str:
    ci_text = ""
    if initial_ci and initial_ci[0] is not None:
        ci_text = f" (CI: {initial_ci[0]}-{initial_ci[1]})"

    probes_text = "\n\n".join(f"{i + 1}. {probe}" for i, probe in enumerate(case.probes))

    if condition == "naive":
        return f"""You previously estimated {initial_estimate} {case.estimate_unit} for this scenario.

Follow-up information:

{probes_text}

Given this new information, what's your revised estimate ({case.estimate_unit})? Also provide an 80% confidence interval.{_LEGACY_JSON_INSTRUCTION}"""

    if condition == "cot":
        return f"""You previously estimated {initial_estimate} {case.estimate_unit}{ci_text} for this scenario.

Follow-up information:

{probes_text}

Think through this step by step. Given this new information, what's your revised estimate ({case.estimate_unit})? Also provide an 80% confidence interval.{_LEGACY_JSON_INSTRUCTION}"""

    if condition == "farness":
        return f"""You previously estimated {initial_estimate} {case.estimate_unit}{ci_text} for this scenario.

Follow-up information:

{probes_text}

Given this new information, what's your revised estimate and 80% CI?{_LEGACY_JSON_INSTRUCTION}"""

    raise ValueError(f"Unknown condition: {condition}")


def get_study1_cases() -> list[QuantitativeCase]:
    """Return the original 11-case Study 1 battery."""
    return [case for case in get_all_stability_cases() if case.analysis_role != "exploratory"]


def run_single_legacy_test(
    case: QuantitativeCase,
    condition: str,
    model: str,
    verbose: bool = True,
) -> StabilityResult:
    if verbose:
        print(f"  [{condition}] Running initial prompt...")

    initial_prompt = legacy_generate_initial_prompt(case, condition)
    initial_response, _ = call_llm(initial_prompt, model=model, timeout=180.0)
    if initial_response.startswith("ERROR:"):
        raise RuntimeError(f"Initial prompt failed: {initial_response}")

    initial_estimate = _extract_estimate_or_raise(initial_response, case.estimate_unit, "initial")
    initial_ci_low, initial_ci_high = extract_ci(initial_response)

    if verbose:
        ci_str = f" (CI: {initial_ci_low}-{initial_ci_high})" if initial_ci_low is not None else ""
        print(f"    Initial: {initial_estimate}{case.estimate_unit}{ci_str}")

    if verbose:
        print(f"  [{condition}] Running probing prompt...")

    probe_prompt = legacy_generate_probe_prompt(
        case,
        initial_estimate,
        (initial_ci_low, initial_ci_high) if initial_ci_low is not None else None,
        condition,
    )
    final_response, _ = call_llm(probe_prompt, model=model, timeout=180.0)
    if final_response.startswith("ERROR:"):
        raise RuntimeError(f"Probe prompt failed: {final_response}")

    final_estimate = _extract_estimate_or_raise(final_response, case.estimate_unit, "final")
    final_ci_low, final_ci_high = extract_ci(final_response)

    if verbose:
        ci_str = f" (CI: {final_ci_low}-{final_ci_high})" if final_ci_low is not None else ""
        print(f"    Final: {final_estimate}{case.estimate_unit}{ci_str}")
        print(f"    Update: {final_estimate - initial_estimate:+.2f}{case.estimate_unit}")

    return StabilityResult(
        case_id=case.id,
        condition=condition,
        probe_battery=DEFAULT_PROBE_BATTERY,
        model=model,
        initial_estimate=initial_estimate,
        initial_ci_low=initial_ci_low,
        initial_ci_high=initial_ci_high,
        initial_response_text=initial_response,
        final_estimate=final_estimate,
        final_ci_low=final_ci_low,
        final_ci_high=final_ci_high,
        final_response_text=final_response,
    )


def run_study1_rerun(
    *,
    model: str,
    cases: list[QuantitativeCase],
    runs_per_condition: int,
    output_dir: Path,
    seed: int | None,
    start_run: int,
    verbose: bool = True,
) -> StabilityExperiment:
    import random

    if seed is None:
        seed = int(datetime.now().timestamp() * 1000) % (2**31)
    random.seed(seed)

    output_dir.mkdir(parents=True, exist_ok=True)
    experiment = StabilityExperiment(cases=cases)

    metadata = {
        "study": "study1_rerun",
        "prompt_version": "legacy_study1",
        "random_seed": seed,
        "runs_per_condition": runs_per_condition,
        "n_cases": len(cases),
        "case_ids": [case.id for case in cases],
        "conditions": STUDY1_CONDITIONS,
        "probe_batteries": [DEFAULT_PROBE_BATTERY],
        "model": model,
        "started_at": datetime.now().isoformat(),
        "condition_orders": {},
    }

    total_tests = len(cases) * len(STUDY1_CONDITIONS) * runs_per_condition
    test_num = 0

    for case in cases:
        if verbose:
            print(f"\n{'=' * 60}")
            print(f"Case: {case.name}")
            print(f"{'=' * 60}")

        for run_offset in range(runs_per_condition):
            run_num = start_run + run_offset
            run_conditions = STUDY1_CONDITIONS.copy()
            random.shuffle(run_conditions)
            metadata["condition_orders"][f"{case.id}_run{run_num}"] = run_conditions.copy()

            for condition in run_conditions:
                test_num += 1
                if verbose:
                    print(f"\n[{test_num}/{total_tests}] {case.id} - {condition} - run {run_num}")

                try:
                    result = run_single_legacy_test(
                        case=case,
                        condition=condition,
                        model=model,
                        verbose=verbose,
                    )
                    experiment.results.append(result)
                    result_file = output_dir / f"{case.id}_{condition}_run{run_num}.json"
                    with open(result_file, "w") as fh:
                        json.dump(result.to_dict(), fh, indent=2)
                except Exception as exc:
                    print(f"    ERROR: {exc}")
                    continue

    metadata["completed_at"] = datetime.now().isoformat()
    metadata["n_results"] = len(experiment.results)

    with open(output_dir / "experiment_metadata.json", "w") as fh:
        json.dump(metadata, fh, indent=2)

    analysis = experiment.analyze()
    analysis["metadata"] = metadata
    with open(output_dir / "summary.json", "w") as fh:
        json.dump(analysis, fh, indent=2)

    with open(output_dir / "results_table.md", "w") as fh:
        fh.write("# Study 1 Rerun Results\n\n")
        fh.write(f"**Model**: {model}\n\n")
        fh.write(f"**Prompt version**: legacy_study1\n\n")
        fh.write(experiment.summary_table())

    return experiment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rerun the original Study 1 stability design."
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=DEFAULT_MODELS,
        help="Models to run (default: gpt-5.4)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=6,
        help="Runs per condition (default: 6)",
    )
    parser.add_argument(
        "--start-run",
        type=int,
        default=1,
        help="Starting run number for appending to an existing rerun",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--case",
        type=str,
        default=None,
        help="Optional single case to run instead of the full Study 1 battery",
    )
    parser.add_argument(
        "--output-base",
        type=Path,
        default=Path("experiments/stability_results"),
        help="Base output directory (default: experiments/stability_results)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.case:
        case = get_stability_case(args.case)
        if case is None:
            raise SystemExit(f"Unknown case: {args.case}")
        if case.analysis_role == "exploratory":
            raise SystemExit(f"Case {args.case} is not part of the original Study 1 design")
        cases = [case]
    else:
        cases = get_study1_cases()

    results_per_model = len(cases) * len(STUDY1_CONDITIONS) * args.runs
    api_calls_per_model = results_per_model * 2

    print("Study 1 rerun")
    print(f"  Cases: {len(cases)}")
    print(f"  Conditions: {', '.join(STUDY1_CONDITIONS)}")
    print(f"  Runs per condition: {args.runs}")
    print(f"  Result files per model: {results_per_model}")
    print(f"  API calls per model: {api_calls_per_model}")

    for model in args.models:
        output_dir = args.output_base / model
        print(f"\nRunning Study 1 rerun for {model}")
        print(f"  Output: {output_dir}")
        run_study1_rerun(
            model=model,
            cases=cases,
            runs_per_condition=args.runs,
            output_dir=output_dir,
            seed=args.seed,
            start_run=args.start_run,
            verbose=True,
        )


if __name__ == "__main__":
    main()
