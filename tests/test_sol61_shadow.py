"""Tests for the Sol 6.1 shadow-forecast harness (experiments/sol61_shadow)."""

from __future__ import annotations

import importlib.util
import json
import math
import pathlib
import subprocess
import sys

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sol61_shadow", ROOT / "experiments" / "sol61_shadow" / "shadow.py"
)
shadow = importlib.util.module_from_spec(SPEC)
sys.modules["sol61_shadow"] = shadow
SPEC.loader.exec_module(shadow)


# ------------------------------------------------------------ prompts


@given(
    st.text(min_size=1).filter(lambda s: "----- END PRODUCTION PROMPT -----" not in s)
)
def test_compose_then_extract_round_trips(production: str) -> None:
    for arm in shadow.ARMS:
        composed = shadow.compose_prompt(production, arm)
        assert shadow.extract_production(composed) == production.rstrip("\n")


def test_wrapper_names_only_the_tools_and_mode_each_arm_has() -> None:
    web = shadow.compose_prompt("PROMPT", "web")
    net = shadow.compose_prompt("PROMPT", "net")
    full = shadow.compose_prompt("PROMPT", "full")
    assert "curl" not in web and "curl" not in full
    assert "curl -sS" in net
    assert "prompt mode\nfast)" in web and "prompt mode\nfast)" in net
    assert "prompt mode\nfull)" in full
    for text in (web, net, full):
        assert "thesisinstitute.org" in text
        assert "exactly the one JSON object" in text


def test_committed_prompts_embed_the_runner_prompt_byte_for_byte() -> None:
    targets = shadow.load_targets()
    index = json.loads((shadow.EXP / "prompts" / "index.json").read_text())
    assert set(index) == {f"{arm}/{t['slug']}" for t in targets for arm in shadow.ARMS}
    # One full check per arm keeps the suite fast; the index pins the rest.
    sample = targets[0]
    for arm, spec in shadow.ARMS.items():
        text = shadow.prompt_path(arm, sample["slug"]).read_text()
        assert shadow.sha256_bytes(text.encode()) == index[f"{arm}/{sample['slug']}"]
        expected = shadow.production_prompt(
            sample["target"], network=spec["network"], prompt_mode=spec["promptMode"]
        )
        assert shadow.extract_production(text) == expected.rstrip("\n")


# ------------------------------------------------------------ target selection


def _target(slug: str, start: str | None, *, nested: bool = True) -> dict:
    target = {"series": "s", "period": "p", "catalogSlug": slug, "dataPointId": slug}
    if start is not None:
        window = {"start": start, "end": start}
        if nested:
            target["sourceBinding"] = {"expectedReleaseWindow": window}
        else:
            target["expectedReleaseWindow"] = window
    return target


def test_window_start_prefers_the_authenticated_nested_window() -> None:
    target = _target("a", "2026-11-01")
    target["expectedReleaseWindow"] = {"start": "2026-10-01"}
    target["resolutionDate"] = "2026-09-01"
    assert shadow.window_start(target) == "2026-11-01"
    assert shadow.window_start(_target("b", "2026-12-01", nested=False)) == "2026-12-01"
    assert shadow.window_start({"resolutionDate": "2027-01-02"}) == "2027-01-02"
    assert shadow.window_start({}) == ""


DAYS = st.dates(
    min_value=__import__("datetime").date(2026, 6, 1),
    max_value=__import__("datetime").date(2029, 12, 31),
).map(lambda d: d.isoformat())


@given(
    st.dictionaries(st.text("abcdefgh", min_size=1, max_size=6), DAYS, max_size=20),
    DAYS,
)
def test_select_open_keeps_exactly_the_targets_not_knowable_before_cutoff(
    starts: dict[str, str], cutoff: str
) -> None:
    primaries = {
        slug: {"target": _target(slug, start)} for slug, start in starts.items()
    }
    chosen = shadow.select_open(primaries, cutoff)
    assert {row["key"] for row in chosen} == {
        slug for slug, start in starts.items() if start >= cutoff
    }
    assert all(row["windowStart"] >= cutoff for row in chosen)
    assert [row["windowStart"] for row in chosen] == sorted(
        row["windowStart"] for row in chosen
    )


def test_frozen_targets_are_all_open_and_unique() -> None:
    document = json.loads((shadow.EXP / "targets.json").read_text())
    targets = document["targets"]
    assert targets, "no targets frozen"
    assert len({t["slug"] for t in targets}) == len(targets)
    assert len({t["dataPointId"] for t in targets}) == len(targets)
    for row in targets:
        assert row["windowStart"] >= document["cutoff"]
        assert shadow.window_start(row["target"]) == row["windowStart"]
        assert row["primary"]["manifestPath"], row["slug"]


def test_published_primaries_skip_failed_runs_and_strategy_suites(tmp_path) -> None:
    batches = tmp_path / "batches"
    (batches / "2026-09-01").mkdir(parents=True)
    ok = {"ok": True, "target": _target("kept", "2026-11-01"), "manifestPath": "m1"}
    failed = {"ok": False, "target": _target("failed", "2026-11-01")}
    (batches / "2026-09-01" / "auto-roll-1-a1.json").write_text(
        json.dumps({"promptMode": "fast", "results": [ok, failed]})
    )
    strategy = {"ok": True, "target": _target("strategy", "2026-11-01")}
    (batches / "2026-09-01" / "strategy-2-a1-ladder.json").write_text(
        json.dumps({"results": [strategy]})
    )
    found = shadow.published_primaries(batches)
    assert set(found) == {"kept"}
    assert found["kept"]["promptMode"] == "fast"


# ------------------------------------------------------------ batch manifests


def test_batch_manifest_isolates_writable_jobs(tmp_path) -> None:
    rows = [{"slug": "alpha"}, {"slug": "beta"}]
    web = shadow.batch_manifest(
        rows, arm="web", rollout=2, ops=tmp_path, tier="hard", label="w"
    )
    net = shadow.batch_manifest(
        rows, arm="net", rollout=1, ops=tmp_path, tier="hard", label="n"
    )
    assert web["defaults"] == {"task": "research", "tier": "hard"}
    assert net["defaults"] == {"task": "build", "tier": "hard"}
    assert {job["workdir"] for job in web["jobs"]} == {str(tmp_path / "workdir")}
    workdirs = [pathlib.Path(job["workdir"]) for job in net["jobs"]]
    assert len(set(workdirs)) == len(rows)
    for workdir in workdirs:
        assert (workdir / ".git").is_dir()
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=workdir, text=True
        ).strip()
        assert branch == shadow.NET_BRANCH and branch not in {"main", "master"}
        assert (
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=workdir, text=True
            )
            == ""
        )
    assert all(job["in_place"] and job["no_preamble"] for job in net["jobs"])
    outs = [job["out"] for job in web["jobs"] + net["jobs"]]
    assert len(set(outs)) == len(outs)
    assert web["jobs"][0]["out"].endswith("out/web/alpha__r2.txt")


def test_load_submissions_keeps_each_job_once(tmp_path) -> None:
    sub = tmp_path / "submissions"
    sub.mkdir()
    row = {"job_id": "j1", "out": "/x/out/web/a__r1.txt"}
    (sub / "a.jsonl").write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    (sub / "b.jsonl").write_text(
        json.dumps({"job_id": None, "outcome": "not-sent"})
        + "\n"
        + json.dumps(row)
        + "\n"
    )
    assert shadow.load_submissions(tmp_path) == [row]


# ------------------------------------------------------------ trace audit


def _event(item: dict) -> str:
    return json.dumps({"type": "item.completed", "item": item})


def test_audit_flags_a_search_that_reaches_a_thesis_surface() -> None:
    lines = [
        _event(
            {
                "type": "web_search",
                "query": "",
                "action": {
                    "type": "open_page",
                    "url": "https://app.thesisinstitute.org/forecasts/jolts",
                },
            }
        ),
    ]
    audit = shadow.audit_trace(lines)
    assert audit["contaminated"]
    assert audit["webSearchCount"] == 1


def test_audit_flags_a_command_that_reads_the_thesis_checkout() -> None:
    lines = [
        _event(
            {
                "type": "command_execution",
                "exit_code": 0,
                "command": "cat /Users/x/ThesisInstitute/thesis/site/src/data/"
                "forecast-cells.ts",
            }
        ),
    ]
    assert shadow.audit_trace(lines)["contaminated"]


def test_audit_passes_official_sources_and_counts_curls_and_usage() -> None:
    lines = [
        "not json",
        _event(
            {
                "type": "web_search",
                "query": "BLS JOLTS schedule 2026",
                "action": {"type": "search", "queries": ["site:bls.gov jolts"]},
            }
        ),
        _event(
            {
                "type": "command_execution",
                "exit_code": 0,
                "command": "curl -sS https://api.bls.gov/publicAPI/v2/timeseries/data/X",
            }
        ),
        _event(
            {
                "type": "command_execution",
                "exit_code": 6,
                "command": "bash -lc 'curl -sS https://x'",
            }
        ),
        _event({"type": "command_execution", "exit_code": 0, "command": "date -u"}),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 3,
                    "cached_input_tokens": 4,
                },
            }
        ),
        json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 1}}
        ),
    ]
    audit = shadow.audit_trace(lines)
    assert not audit["contaminated"]
    assert audit["curlCount"] == 2 and audit["curlSucceeded"] == 1
    assert audit["commandCount"] == 3
    assert audit["usage"] == {
        "input_tokens": 15,
        "cached_input_tokens": 4,
        "output_tokens": 4,
    }


# ------------------------------------------------------------ chronology


def test_chronology_requires_finishing_before_the_window_day() -> None:
    assert shadow.chronology_ok("2026-10-12T23:59:59Z", "2026-10-13")
    assert not shadow.chronology_ok("2026-10-13T00:00:00Z", "2026-10-13")
    assert not shadow.chronology_ok(None, "2026-10-13")
    assert not shadow.chronology_ok("2026-10-01T00:00:00Z", "")


@given(DAYS, DAYS)
def test_chronology_is_strictly_day_ordered(finished_day: str, start_day: str) -> None:
    assert shadow.chronology_ok(f"{finished_day}T12:00:00Z", start_day) == (
        finished_day < start_day
    )


# ------------------------------------------------------------ CRPS


def _cdf(values: list[float], probabilities: list[float]) -> list[dict]:
    return [{"value": v, "probability": p} for v, p in zip(values, probabilities)]


@st.composite
def numeric_cdfs(draw):
    count = draw(st.integers(min_value=2, max_value=12))
    start = draw(st.floats(min_value=-1e3, max_value=1e3))
    gaps = draw(
        st.lists(
            st.floats(min_value=1e-3, max_value=50),
            min_size=count - 1,
            max_size=count - 1,
        )
    )
    values = [start]
    for gap in gaps:
        values.append(values[-1] + gap)
    raw = sorted(
        draw(
            st.lists(
                st.floats(min_value=0, max_value=1),
                min_size=count - 2,
                max_size=count - 2,
            )
        )
    )
    return _cdf(values, [0.0, *raw, 1.0])


def _numeric_crps(points: list[dict], observed: float, steps: int = 20000) -> float:
    lower = min(points[0]["value"], observed)
    upper = max(points[-1]["value"], observed)
    width = (upper - lower) / steps
    total = 0.0
    for index in range(steps):
        x = lower + (index + 0.5) * width
        total += (
            shadow.cdf_probability(points, x) - (1.0 if x >= observed else 0.0)
        ) ** 2
    return total * width


@settings(max_examples=60, deadline=None)
@given(numeric_cdfs(), st.floats(min_value=-1.2e3, max_value=2e3))
def test_crps_matches_numeric_integration(points: list[dict], observed: float) -> None:
    exact = shadow.crps_numeric_cdf(points, observed)
    approx = _numeric_crps(points, observed)
    span = max(points[-1]["value"], observed) - min(points[0]["value"], observed)
    assert exact >= 0
    assert math.isclose(exact, approx, rel_tol=1e-3, abs_tol=1e-6 * max(span, 1.0))


@given(
    numeric_cdfs(),
    st.floats(min_value=-1e3, max_value=1e3),
    st.floats(min_value=-1e3, max_value=1e3),
)
def test_crps_is_translation_invariant(
    points: list[dict], observed: float, shift: float
) -> None:
    moved = [
        {"value": p["value"] + shift, "probability": p["probability"]} for p in points
    ]
    assume(all(b["value"] > a["value"] for a, b in zip(moved, moved[1:])))
    original = shadow.crps_numeric_cdf(points, observed)
    shifted = shadow.crps_numeric_cdf(moved, observed + shift)
    assert math.isclose(original, shifted, rel_tol=1e-6, abs_tol=1e-6)


@pytest.mark.parametrize("y", [0.0, 0.25, 0.5, 0.9, 1.0])
def test_crps_of_uniform_matches_closed_form(y: float) -> None:
    uniform = _cdf([0.0, 1.0], [0.0, 1.0])
    assert math.isclose(
        shadow.crps_numeric_cdf(uniform, y), (y**3 + (1 - y) ** 3) / 3, rel_tol=1e-12
    )


def test_crps_outside_support_adds_the_distance() -> None:
    uniform = _cdf([0.0, 1.0], [0.0, 1.0])
    assert math.isclose(shadow.crps_numeric_cdf(uniform, 3.0), 1 / 3 + 2.0)
    assert math.isclose(shadow.crps_numeric_cdf(uniform, -2.0), 1 / 3 + 2.0)


def test_crps_of_a_narrow_distribution_approaches_absolute_error() -> None:
    narrow = _cdf([4.999, 5.001], [0.0, 1.0])
    assert math.isclose(shadow.crps_numeric_cdf(narrow, 7.0), 2.0, abs_tol=1e-3)


def test_crps_refuses_degenerate_input() -> None:
    with pytest.raises(ValueError):
        shadow.crps_numeric_cdf(_cdf([1.0], [1.0]), 0.0)
    with pytest.raises(ValueError):
        shadow.crps_numeric_cdf(_cdf([0.0, 1.0], [0.0, 1.0]), float("nan"))


@given(numeric_cdfs(), st.floats(min_value=0.01, max_value=0.99))
def test_score_distribution_reports_coverage_consistent_with_quantiles(
    points, q
) -> None:
    observed = shadow._quantile(points, q)
    scored = shadow.score_distribution({"points": points}, observed)
    assert scored["crps"] >= 0
    assert 0.0 <= scored["pit"] <= 1.0
    if 0.1 + 1e-9 < q < 0.9 - 1e-9:
        p10, p90 = shadow._quantile(points, 0.1), shadow._quantile(points, 0.9)
        assert scored["covered80"] == (p10 <= observed <= p90)


# ------------------------------------------------------------ launch facts


def test_launch_facts_reads_the_codex_argv_subfleet_ran() -> None:
    argv = [
        "/opt/codex/bin/codex", "exec", "--json", "-m", "gpt-6.1-sol",
        "-c", "model_reasoning_effort=ultra", "--sandbox", "workspace-write",
        "-c", "sandbox_workspace_write.network_access=true",
        "-c", "features.unified_exec=false", "--output-last-message", "/x/last.md",
    ]  # fmt: skip
    assert shadow.launch_facts(argv) == {
        "binary": "codex",
        "model": "gpt-6.1-sol",
        "reasoningEffort": "ultra",
        "sandbox": "workspace-write",
        "networkAccess": True,
    }
    read_only = [
        "codex",
        "exec",
        "--json",
        "-m",
        "gpt-6-luna",
        "--sandbox",
        "read-only",
    ]
    facts = shadow.launch_facts(read_only)
    assert facts["model"] == "gpt-6-luna" and facts["model"] != shadow.EXPECTED_MODEL
    assert facts["networkAccess"] is False and facts["reasoningEffort"] is None
    assert shadow.launch_facts([])["model"] is None


def test_resolve_by_bound_targets_are_not_validatable() -> None:
    assert shadow.validatable({"resolutionDateBasis": "release-calendar"})
    assert shadow.validatable({})
    assert not shadow.validatable({"resolutionDateBasis": "resolve-by-bound"})
    frozen = shadow.load_targets()
    bound = {row["slug"] for row in frozen if not shadow.validatable(row["target"])}
    assert bound == {
        "spm-child-poverty-rate-cy2027-current-law",
        "spm-child-poverty-rate-cy2027-threshold-one-dollar",
        "us-crp-enrolled-acres-september-2027-ceiling-27-million-source-recovered-2026-08-13",
        "us-crp-enrolled-acres-september-2027-no-fy2027-31-ceiling-source-recovered-2026-08-13",
    }
