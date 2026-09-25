"""Pin the composed agent prompts against a golden snapshot.

Prompt wording is the experimental treatment. The tracks now compose their
prompts from :mod:`brier.experiments.components` instead of each holding a
forked literal, which means a component edit reaches every track that shares
it — deliberately. This test makes that reach visible: any wording change
fails here, listing exactly which track/condition moved.

If a failure is intended, regenerate from the repo root with::

    python -m tests.test_prompt_components --update

(the ``-m`` form matters: running the file by path puts ``tests/`` on sys.path
instead of the repo root, so ``brier`` resolves to whatever is pip-installed —
in a worktree that is a *different* checkout, and the fixture would be
regenerated from the wrong tree.)

and treat the fixture diff as the record of which conditions changed. Results
collected under the old wording are not comparable to results collected under
the new wording; bump the prompt version rather than silently rescoring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brier.experiments import components, judge, reframing, stability
from brier.experiments import decision_usefulness as du

FIXTURE = Path(__file__).parent / "fixtures" / "prompt_snapshots.json"

STABILITY_CONDITIONS = ["naive", "estimate_only", "format_control", "cot", "farness"]


def current_prompts() -> dict[str, str]:
    """Render every prompt the experiment tracks emit today."""
    out: dict[str, str] = {}

    case = stability.get_all_stability_cases()[0]
    out["stability.case_id"] = case.id
    for cond in STABILITY_CONDITIONS:
        out[f"stability.initial.{cond}"] = stability.generate_initial_prompt(case, cond)
        out[f"stability.probe.{cond}"] = stability.generate_probe_prompt(
            case, 4.0, (2.5, 7.0), cond
        )
    out["stability._JSON_INSTRUCTION"] = stability._JSON_INSTRUCTION

    out["reframing.NAIVE_PROMPT"] = reframing.NAIVE_PROMPT
    out["reframing.COT_PROMPT"] = reframing.COT_PROMPT
    out["reframing.BRIER_PROMPT"] = reframing.BRIER_PROMPT

    for cond, tpl in du.PROMPT_TEMPLATES.items():
        out[f"du.template.{cond}"] = tpl
    du_case = du.get_decision_usefulness_cases()[0]
    out["du.case_id"] = du_case.id
    for cond in du.DECISION_USEFULNESS_CONDITIONS:
        out[f"du.prompt.{cond}"] = du.generate_decision_usefulness_prompt(du_case, cond)
    out["du.PAIRWISE_NEUTRAL_PROMPT"] = du.PAIRWISE_NEUTRAL_PROMPT
    out["du.PAIRWISE_ALIGNED_PROMPT"] = du.PAIRWISE_ALIGNED_PROMPT
    out["du.PAIRWISE_OMISSION_PROMPT"] = du.PAIRWISE_OMISSION_PROMPT
    out["du.PAIRWISE_CRITIQUE_SURVIVAL_PROMPT"] = du.PAIRWISE_CRITIQUE_SURVIVAL_PROMPT

    out["judge.REFRAMING_JUDGE_PROMPT"] = judge.REFRAMING_JUDGE_PROMPT
    out["judge.QUALITY_JUDGE_PROMPT"] = judge.QUALITY_JUDGE_PROMPT

    return out


@pytest.fixture(scope="module")
def snapshot() -> dict[str, str]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_no_prompts_added_or_removed(snapshot):
    assert sorted(current_prompts()) == sorted(snapshot)


@pytest.mark.parametrize("key", sorted(json.loads(FIXTURE.read_text(encoding="utf-8"))))
def test_prompt_matches_snapshot(key, snapshot):
    assert current_prompts()[key] == snapshot[key]


class TestComposition:
    """The composition helpers, independent of any particular track."""

    def test_numbered_starts_at_one(self):
        assert components.numbered(["a", "b"]) == "1. a\n2. b"

    def test_bulleted(self):
        assert components.bulleted(["a", "b"]) == "- a\n- b"

    def test_paragraphs_drops_empty_parts(self):
        assert components.paragraphs("a", "", "b") == "a\n\nb"

    def test_define_kpis_separator(self):
        assert components.define_kpis(qualifier="that resolve") == (
            "Define 1-2 explicit KPIs that resolve."
        )
        assert components.define_kpis(qualifier="including units", sep=", ") == (
            "Define 1-2 explicit KPIs, including units."
        )

    def test_option_expansion_variants(self):
        assert components.option_expansion() == (
            "Expand the option set beyond the user's first framing if needed."
        )
        assert components.option_expansion("initial", "if appropriate") == (
            "Expand the option set beyond the user's initial framing if appropriate."
        )


class TestSharedExtraction:
    """One extraction implementation, reachable from every track."""

    def test_tracks_share_one_estimate_parser(self):
        assert stability.extract_structured is components.structured_estimate
        assert stability.extract_estimate is components.numeric_estimate
        assert stability.extract_ci is components.confidence_interval
        assert du._extract_first_json_object is components.first_json_object

    def test_structured_estimate_round_trips_the_emit_contract(self):
        response = (
            "Some reasoning.\n\n"
            '```json\n{"estimate": 4.0, "ci_low": 2.5, "ci_high": 7.0}\n```'
        )
        assert components.structured_estimate(response) == (4.0, 2.5, 7.0)

    def test_structured_estimate_swaps_reversed_ci(self):
        response = '```json\n{"estimate": 4, "ci_low": 7, "ci_high": 2.5}\n```'
        assert components.structured_estimate(response) == (4.0, 2.5, 7.0)

    def test_first_json_object_raises_on_missing_object(self):
        with pytest.raises(ValueError):
            components.first_json_object("no json here")

    def test_scored_json_is_lenient(self):
        assert components.scored_json("no json here") == ({}, "")

    def test_scored_json_finds_bare_object_via_key_hint(self):
        text = 'prose {"surface_analysis": 4, "reasoning": "ok"} more prose'
        scores, reasoning = components.scored_json(
            text, key_hints=("surface_analysis",)
        )
        assert scores == {"surface_analysis": 4}
        assert reasoning == "ok"


def _update() -> None:
    # newline="\n" so regenerating on Windows does not rewrite every line as
    # CRLF. The fixture's only job is to produce a readable diff when wording
    # changes; a platform-dependent whole-file diff would defeat that.
    FIXTURE.write_text(
        json.dumps(current_prompts(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {FIXTURE}")


if __name__ == "__main__":  # pragma: no cover - maintenance entry point
    import sys

    if "--update" in sys.argv:
        _update()
    else:
        print(__doc__)
