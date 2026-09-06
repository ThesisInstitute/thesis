from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from thesis_core.contracts import (
    AttemptResult,
    NumericCdf,
    PublicationManifest,
    PublicationProof,
    parse_record,
)
from thesis_core.evaluation import (
    Availability,
    VerifiedPublication,
    assess_run,
    available_by,
    build_leaderboard,
    build_normalization,
    established_upper,
    record_available_as_of,
    select_first_valid,
    source_availability_interval,
    validate_experiment,
    validate_normalization,
)
from thesis_core.schema import generate
from thesis_core.scoring import (
    build_interval_distribution,
    score_numeric_cdf_distribution,
)

from .factories import (
    add_resolution,
    add_run,
    at,
    make_forecaster,
    make_graph,
    make_source,
)

ROOT = Path(__file__).resolve().parents[2]


def test_record_identity_and_strict_ingestion():
    original = make_forecaster()
    assert parse_record(original.kind, original.canonical_bytes()).id == original.id
    for changes in (
        {"agent_version": "2"},
        {"model_request": "other"},
        {"briefing_hash": "a" * 64},
        {"inference_settings": {"temperature": 0.2}},
        {"system_prompt_hash": "b" * 64},
    ):
        assert make_forecaster(**changes).id != original.id
    payload = original.canonical_payload()
    with pytest.raises(ValueError):
        parse_record(original.kind, payload | {"schema_version": True})
    with pytest.raises(ValueError):
        parse_record(original.kind, payload | {"surprise": 1})
    with pytest.raises(ValueError, match="duplicate"):
        parse_record(original.kind, '{"kind":"x","kind":"x"}')
    with pytest.raises(ValueError, match="credential-bearing") as error:
        make_forecaster(inference_settings={"api_key": "private-test-value"})
    assert "private-test-value" not in str(error.value)
    assert make_forecaster(inference_settings={"max_tokens": 10})
    source = make_source()
    source.binding["series"] = "changed"
    with pytest.raises(ValueError, match="mutated"):
        source.id
    with pytest.raises(ValueError):
        make_forecaster(inference_settings={"temperature": float("nan")})


def test_native_cdf_strict_and_exact_sealed_roundtrip():
    original = build_interval_distribution(3.3, 3.1, 3.45)
    assert (
        NumericCdf.model_validate_json(original.model_dump_json(by_alias=True))
        == original
    )
    payload = original.model_dump(mode="json", by_alias=True)
    payload["points"][0]["probability"] = -5e-10
    with pytest.raises(ValueError):
        NumericCdf.model_validate_json(json.dumps(payload))
    for count in (200, 202):
        bad = original.model_dump(mode="json", by_alias=True)
        bad["pointCount"] = count
        with pytest.raises(ValueError):
            NumericCdf.model_validate_json(json.dumps(bad))
    assert build_interval_distribution(-0.0, -0.1, 0.1).summary.point_estimate == 0


@pytest.mark.parametrize(
    "points,y,expected,pit",
    [
        ([(0, 0), (1, 1)], 0.5, 1 / 12, 0.5),
        ([(0, 0), (1, 1)], -1, 4 / 3, 0),
        ([(0, 0), (1, 1)], 2, 4 / 3, 1),
        ([(0, 0), (1, 0.25), (3, 1)], 2, 13 / 48, 0.625),
        ([(0, 0), (1 - 1e-6, 0), (1, 1)], 1, 1e-6 / 3, 1),
    ],
)
def test_analytic_and_typescript_crps_parity(points, y, expected, pit):
    distribution = {
        "pointCount": len(points),
        "points": [{"value": x, "probability": p} for x, p in points],
    }
    score = score_numeric_cdf_distribution(distribution, y)
    assert score.crps == pytest.approx(expected, abs=5e-12)
    assert score.pit == pytest.approx(pit)
    if shutil.which("bun"):
        module = ROOT / "site/src/data/prediction-distribution.ts"
        script = (
            f"import {{scoreNumericCdfDistribution}} from {json.dumps(str(module))}; "
            "console.log(JSON.stringify(scoreNumericCdfDistribution("
            f"{json.dumps(distribution)},{y})));"
        )
        assert (
            json.loads(subprocess.check_output(["bun", "-e", script]))
            == score.as_json()
        )


def test_interval_transform_existing_golden():
    fixture = json.loads(
        (ROOT / "tests/fixtures/interval_anchor_v1_distribution.json").read_text()
    )
    inputs = fixture["inputs"]
    result = build_interval_distribution(
        inputs["pointEstimate"], inputs["ciLow"], inputs["ciHigh"]
    )
    assert [
        {"value": f"{p.value:.10f}", "probability": f"{p.probability:.10f}"}
        for p in result.points
    ] == fixture["points"]


def test_availability_intervals_and_minimum_upper_rule():
    interval = source_availability_interval("2026-09-04", "America/New_York")
    noon = datetime(2026, 9, 4, 16, tzinfo=timezone.utc)
    cutoff = noon + timedelta(hours=1)
    assert interval.lower == datetime(2026, 9, 4, 4, tzinfo=timezone.utc)
    assert interval.upper == datetime(2026, 9, 5, 4, tzinfo=timezone.utc)
    assert established_upper(noon, interval) == noon
    for mode in ("prospective", "replay"):
        assert available_by(cutoff, noon, interval, mode=mode)
        assert not available_by(
            cutoff, cutoff + timedelta(hours=1), interval, mode=mode
        )
        assert not available_by(cutoff, None, interval, mode=mode)
    assert available_by(cutoff, noon, interval, as_of=True)
    assert available_by(cutoff, cutoff, None)
    ambiguous = source_availability_interval("2026-11-01T01:30:00", "America/New_York")
    assert ambiguous.upper - ambiguous.lower == timedelta(hours=1)
    middle = ambiguous.lower + timedelta(minutes=30)
    assert not available_by(middle, ambiguous.upper, ambiguous, mode="replay")
    assert available_by(middle, middle, ambiguous, mode="replay")
    assert (
        source_availability_interval("2026-03-08T02:30:00", "America/New_York") is None
    )
    assert source_availability_interval("2026-09-04", "Unknown/Zone") is None


def test_replay_later_acceptance_and_complete_as_of_closure():
    graph = make_graph()
    observation = next(r for r in graph.records.values() if r.kind == "observation")
    graph.acknowledgements[observation.id] = at(200)
    assert available_by(at(100), at(200), graph.official[observation.id], mode="replay")
    assert not available_by(at(100), at(200), graph.official[observation.id])
    assert not record_available_as_of(observation, at(100), graph.context())
    assert record_available_as_of(observation, at(200), graph.context())
    graph.acknowledgements.pop(observation.source_exchange_ids[0])
    assert not record_available_as_of(observation, at(300), graph.context())


def test_normalization_frozen_recomputed_and_degenerate_floor():
    graph = make_graph()
    normalization = graph.records[graph.experiment.normalization_ids[0]]
    validate_normalization(normalization, graph.target, "replay", graph.context())
    altered = parse_record(
        "normalization", normalization.canonical_payload() | {"scale": 1.0}
    )
    with pytest.raises(ValueError, match="differs"):
        validate_normalization(altered, graph.target, "replay", graph.context())
    observations = [graph.records[oid] for oid in normalization.observation_ids]
    for values in ((10.0, 10.0, 10.0), (10.0, 10.0 + 1e-13, 10.0 + 3e-13)):
        changed = []
        for old, value in zip(observations, values):
            new = graph.add(
                parse_record("observation", old.canonical_payload() | {"value": value})
            )
            graph.official[new.id] = graph.official[old.id]
            changed.append(new)
        result = build_normalization(
            graph.target, changed, at(100), mode="replay", context=graph.context()
        )
        assert result.scale is None
        assert result.unavailable_reason == "dispersion_below_versioned_floor"
    validate_normalization(normalization, graph.target, "replay", graph.context())


def test_experiment_rejects_mixed_cutoffs_duplicate_pairs_and_task_reuse():
    graph = make_graph()
    validate_experiment(graph.experiment, graph.context())
    shifted = graph.add(
        parse_record(
            "evaluation_task",
            graph.task.canonical_payload()
            | {"information_cutoff": at(101).isoformat()},
        )
    )
    bad = parse_record(
        "experiment",
        graph.experiment.canonical_payload()
        | {"task_ids": [shifted.id, graph.baseline_task.id]},
    )
    with pytest.raises(ValueError, match="share one"):
        validate_experiment(bad, graph.context())
    duplicate = graph.add(
        parse_record(
            "evaluation_task", graph.task.canonical_payload() | {"max_attempts": 2}
        )
    )
    bad = parse_record(
        "experiment",
        graph.experiment.canonical_payload()
        | {"task_ids": [graph.task.id, duplicate.id, graph.baseline_task.id]},
    )
    with pytest.raises(ValueError, match="exactly one"):
        validate_experiment(bad, graph.context())
    duplicate_cohort = graph.add(
        parse_record(
            "experiment",
            graph.experiment.canonical_payload()
            | {"registration_deadline": at(99).isoformat()},
        )
    )
    with pytest.raises(ValueError, match="another experiment"):
        validate_experiment(duplicate_cohort, graph.context())


def test_attempt_sequence_not_completion_order_and_unknown_blocks():
    graph = make_graph()
    first, run1, result1 = add_run(graph, sequence=1)
    second, run2, result2 = add_run(graph, sequence=2)
    assert select_first_valid(graph.task, graph.context()).run_id == run1.id
    graph.records.pop(result1.id)
    unknown = graph.add(
        AttemptResult(attempt_id=first.id, outcome="unknown", recorded_at=at(250))
    )
    assert (
        select_first_valid(graph.task, graph.context()).reason == "unresolved_attempt"
    )
    repaired = graph.add(
        AttemptResult(
            attempt_id=first.id,
            outcome="failed",
            recorded_at=at(300),
            reconciles_result_id=unknown.id,
            reconciliation_method="no_sealed_result",
            reconciled_by="operator",
            reconciliation_reason="no lease-fenced sealed result",
        ),
        at(300),
    )
    assert (
        select_first_valid(graph.task, graph.context()).reason == "unresolved_attempt"
    )
    selection = select_first_valid(
        graph.task, graph.context(reconciliation_valid=lambda x: x.id == repaired.id)
    )
    assert selection.run_id == run2.id
    assert selection.reconciliation_times == (at(300),)


def test_replay_raw_diagnostics_idempotence_and_no_rank():
    graph = make_graph()
    _, run, _ = add_run(graph)
    _, resolution = add_resolution(graph)
    first = assess_run(run, resolution, graph.experiment, graph.context())
    second = assess_run(run, resolution, graph.experiment, graph.context())
    assert first.eligibility == "replay"
    assert first.score.crps is not None and first.score.normalized_crps is not None
    assert first.score.reward is None
    assert first.score.id == second.score.id
    graph.add(first.score, at(550))
    assert not record_available_as_of(first.score, at(549), graph.context())
    assert record_available_as_of(first.score, at(550), graph.context())
    assert all(
        row["rank"] is None
        for row in build_leaderboard(graph.experiment, [first.score], graph.context())
    )


def test_schema_generation_deterministic(tmp_path):
    generate(output_dir=tmp_path)
    generate(check=True, output_dir=tmp_path)
    (tmp_path / "records.json").write_text("changed")
    with pytest.raises(ValueError, match="drift"):
        generate(check=True, output_dir=tmp_path)


def _proof(graph, verified, *, instant, run=None, cohort=None, accuracy=0):
    """Trusted callback fixture; cryptographic verification is tested separately."""
    manifest = graph.add(
        PublicationManifest(
            manifest_type="run" if run else "cohort",
            experiment_id=graph.experiment.id,
            run_id=run.id if run else None,
            artifacts=tuple(sorted(graph.artifacts)),
            code_hash=graph.blob("code"),
            recorded_at=at(instant - 1),
            cohort_proof_id=cohort.id if cohort else None,
            cohort_token_hash=cohort.token_hash if cohort else None,
            attempt_result_ids=select_first_valid(
                graph.records[graph.records[run.attempt_id].task_id], graph.context()
            ).result_ids
            if run
            else (),
            declared_information_cutoff=at(100),
            effective_information_boundary=at(80),
        ),
        at(instant - 1),
    )
    proof = graph.add(
        PublicationProof(
            manifest_id=manifest.id,
            request_hash=graph.blob(f"request {manifest.id}"),
            token_hash=graph.blob(f"token {manifest.id}"),
            subject_hash=graph.blob(f"subject {manifest.id}"),
            trust_bundle_path="test-only",
            trust_bundle_hash=graph.blob("test trust"),
            trust_anchor_id="test-only",
            gen_time=at(instant),
            accuracy_micros=accuracy,
            signer_identity="test-only",
            policy_oid="test-only",
            verification_version="test-only",
            verified_at=at(instant),
        ),
        at(instant),
    )
    verified[proof.id] = VerifiedPublication(
        proof.id,
        manifest.id,
        proof.token_hash,
        Availability(
            at(instant) - timedelta(microseconds=accuracy),
            at(instant) + timedelta(microseconds=accuracy),
        ),
    )
    return proof


def _prospective(*, cohort_at=90, run_at=250, accuracy=0, normalization=True):
    graph = make_graph(mode="prospective")
    if not normalization:
        old = graph.experiment
        graph.records.pop(old.id)
        graph.experiment = graph.add(
            parse_record(
                "experiment", old.canonical_payload() | {"normalization_ids": []}
            )
        )
    verified = {}
    cohort = _proof(graph, verified, instant=cohort_at)
    _, run, _ = add_run(
        graph, cohort_proof_id=cohort.id, cohort_token_hash=cohort.token_hash
    )
    _proof(graph, verified, instant=run_at, run=run, cohort=cohort, accuracy=accuracy)
    _, baseline, _ = add_run(
        graph,
        task=graph.baseline_task,
        cohort_proof_id=cohort.id,
        cohort_token_hash=cohort.token_hash,
    )
    _proof(graph, verified, instant=run_at, run=baseline, cohort=cohort)
    _, resolution = add_resolution(graph)
    context = graph.context(publication=lambda proof: verified.get(proof.id))
    return graph, run, baseline, resolution, context, verified


def test_prospective_complete_coverage_and_missing_normalization():
    graph, run, baseline, resolution, context, _ = _prospective()
    scores = [
        assess_run(r, resolution, graph.experiment, context).score
        for r in (run, baseline)
    ]
    assert [s.eligibility for s in scores] == ["eligible", "eligible"]
    assert all(s.reward is not None for s in scores)
    rows = build_leaderboard(graph.experiment, scores, context)
    assert {row["rank"] for row in rows} == {1, 2}
    graph, run, baseline, resolution, context, _ = _prospective(normalization=False)
    scores = [
        assess_run(r, resolution, graph.experiment, context).score
        for r in (run, baseline)
    ]
    assert all(s.crps is not None and s.normalized_crps is None for s in scores)
    assert all(
        row["rank"] is None
        for row in build_leaderboard(graph.experiment, scores, context)
    )


@pytest.mark.parametrize("cohort_at", [100, 501])
def test_cohort_witness_strictly_precedes_cutoff_and_outcomes(cohort_at):
    graph, run, _, resolution, context, _ = _prospective(cohort_at=cohort_at)
    assert (
        assess_run(run, resolution, graph.experiment, context).eligibility
        == "late_cohort"
    )


def test_witness_accuracy_overlap_and_unverified_metadata_excluded():
    graph, run, _, resolution, context, verified = _prospective(
        run_at=499, accuracy=1_000_000
    )
    assert (
        assess_run(run, resolution, graph.experiment, context).eligibility
        == "late_publication"
    )
    verified.clear()
    assert (
        assess_run(run, resolution, graph.experiment, context).eligibility
        == "invalid_cohort"
    )


def test_no_cohort_receipt_dependency_and_late_reconciliation():
    graph = make_graph(mode="prospective")
    _, run, _ = add_run(graph)
    _, resolution = add_resolution(graph)
    assert (
        assess_run(run, resolution, graph.experiment, graph.context()).eligibility
        == "missing_cohort_proof"
    )
    graph, first_run, _, resolution, context, verified = _prospective()
    first = graph.records[first_run.attempt_id]
    old = next(
        r
        for r in graph.records.values()
        if isinstance(r, AttemptResult) and r.run_id == first_run.id
    )
    graph.records.pop(old.id)
    unknown = graph.add(
        AttemptResult(attempt_id=first.id, outcome="unknown", recorded_at=at(300)),
        at(300),
    )
    repaired = graph.add(
        AttemptResult(
            attempt_id=first.id,
            outcome="failed",
            recorded_at=at(500),
            reconciles_result_id=unknown.id,
            reconciliation_method="no_sealed_result",
            reconciled_by="operator",
            reconciliation_reason="no lease-fenced result",
        ),
        at(500),
    )
    _, second, _ = add_run(
        graph,
        sequence=2,
        cohort_proof_id=first.cohort_proof_id,
        cohort_token_hash=first.cohort_token_hash,
    )
    cohort = graph.records[first.cohort_proof_id]
    _proof(graph, verified, instant=250, run=second, cohort=cohort)
    context = graph.context(
        publication=lambda p: verified.get(p.id),
        reconciliation_valid=lambda r: r.id == repaired.id,
    )
    assert (
        assess_run(second, resolution, graph.experiment, context).eligibility
        == "late_attempt_reconciliation"
    )


def test_as_of_export_refuses_corrupted_artifact_closure():
    from thesis_core.artifacts import ArtifactCorrupt

    graph = make_graph()
    assert record_available_as_of(graph.forecaster, at(100), graph.context())
    graph.artifacts.pop(graph.forecaster.system_prompt_hash)
    assert not record_available_as_of(graph.forecaster, at(100), graph.context())

    def corrupt(_):
        raise ArtifactCorrupt("changed archived bytes")

    assert not record_available_as_of(
        graph.forecaster, at(100), graph.context(artifact_exists=corrupt)
    )


def test_score_overflow_is_a_bounded_validation_error():
    with pytest.raises(ValueError, match="finite numeric range"):
        score_numeric_cdf_distribution(
            {
                "pointCount": 2,
                "points": [
                    {"value": -1e308, "probability": 0},
                    {"value": 1e308, "probability": 1},
                ],
            },
            1e308,
        )


def test_request_local_context_reuses_work_but_reverifies_next_request(monkeypatch):
    from thesis_core import publication, resolution
    from thesis_core.adapters import registry
    from thesis_core.service import context_for_store

    graph, run, _, resolved, _, verified = _prospective()
    counts = Counter()

    def count(name, value):
        counts[name] += 1
        return value

    monkeypatch.setattr(registry, "validate_source", lambda _: count("source", None))
    monkeypatch.setattr(
        registry,
        "observation_availability",
        lambda observation, *_: count(
            "observation", graph.official.get(observation.id)
        ),
    )
    monkeypatch.setattr(
        registry, "target_release_availability", lambda *_: count("target", None)
    )
    monkeypatch.setattr(
        publication, "verify_proof", lambda _, proof: count("proof", verified[proof.id])
    )
    monkeypatch.setattr(
        resolution, "validate_resolution", lambda *_: count("resolution", True)
    )
    store = SimpleNamespace(
        iter_records=lambda kind: (r for r in graph.records.values() if r.kind == kind),
        committed_at=lambda identity: count(
            "ack", graph.acknowledgements.get(identity)
        ),
        artifacts=SimpleNamespace(
            read_bytes=lambda digest: count("artifact", graph.artifacts[digest])
        ),
    )
    observation = graph.records[resolved.observation_id]
    proof = next(r for r in graph.records.values() if r.kind == "publication_proof")

    def read_twice(context):
        for _ in range(2):
            assert context.committed_at(run.id)
            context.availability(observation)
            context.target_availability(graph.target)
            assert context.artifact_exists(run.prompt_hash)
            assert context.publication(proof)
            assert context.resolution_valid(resolved, graph.target, observation)

    read_twice(context_for_store(store))
    assert counts == Counter(
        {
            key: 1
            for key in (
                "source",
                "observation",
                "target",
                "proof",
                "resolution",
                "ack",
                "artifact",
            )
        }
    )
    read_twice(context_for_store(store))
    assert set(counts.values()) == {2}


def test_leaderboard_attempt_counts_preserve_unknown_history_and_observed_latency(
    monkeypatch,
):
    from thesis_core import service

    graph = make_graph()
    add_run(graph)
    unknown_attempt, orphaned_run, original_result = add_run(graph, sequence=2)
    graph.records.pop(orphaned_run.id)
    graph.records.pop(original_result.id)
    unknown = graph.add(
        AttemptResult(
            attempt_id=unknown_attempt.id, outcome="unknown", recorded_at=at(220)
        )
    )
    reconciliation = graph.add(
        AttemptResult(
            attempt_id=unknown_attempt.id,
            outcome="failed",
            recorded_at=at(900),
            completed_at=at(900),
            reconciles_result_id=unknown.id,
            reconciliation_method="no_sealed_result",
            reconciled_by="fixture-operator",
            reconciliation_reason="No result was committed under a valid fence",
        )
    )
    _, pending_run, pending_result = add_run(graph, sequence=3)
    graph.records.pop(pending_run.id)
    graph.records.pop(pending_result.id)
    add_resolution(graph)
    context = graph.context(
        reconciliation_valid=lambda result: result.id == reconciliation.id
    )
    monkeypatch.setattr(service, "context_for_store", lambda _: context)
    store = SimpleNamespace(
        get=graph.records.__getitem__,
        iter_records=lambda kind: (r for r in graph.records.values() if r.kind == kind),
    )
    row = next(
        r
        for r in service.leaderboard_rows(store)
        if r["forecaster_id"] == graph.forecaster.id
    )
    assert row["attempt_counts"] == {
        "total": 3,
        "succeeded": 1,
        "failed": 1,
        "unknown": 0,
        "pending": 1,
        "reconciled": 1,
        "unknown_history": 1,
    }
    assert row["mean_latency_seconds"] == 90.0
    assert row["rank"] is None  # Descriptive attempts do not grant replay rank.
    graph.records.pop(reconciliation.id)
    row = next(
        r
        for r in service.leaderboard_rows(store)
        if r["forecaster_id"] == graph.forecaster.id
    )
    assert row["attempt_counts"]["unknown"] == 1
    assert row["attempt_counts"]["failed"] == 0
    assert row["attempt_counts"]["unknown_history"] == 1
    assert row["mean_latency_seconds"] == 90.0


@pytest.mark.parametrize("run_at", [201, 202, 203])
def test_run_witness_must_strictly_follow_completion_and_result_acknowledgements(
    run_at,
):
    graph, run, _, resolution, context, _ = _prospective(run_at=run_at)
    assert (
        assess_run(run, resolution, graph.experiment, context).eligibility
        == "invalid_publication"
    )


@pytest.mark.parametrize("changed_field", ["attempt_result_ids", "code_hash"])
def test_publication_binds_selected_results_and_dispatch_code(changed_field):
    graph, run, _, resolution, context, verified = _prospective()
    proof = next(
        record
        for record in graph.records.values()
        if isinstance(record, PublicationProof)
        and graph.records[record.manifest_id].run_id == run.id
    )
    manifest = graph.records[proof.manifest_id]
    replacement = graph.add(
        parse_record(
            "publication_manifest",
            manifest.canonical_payload()
            | {
                changed_field: []
                if changed_field == "attempt_result_ids"
                else graph.blob("different code")
            },
        )
    )
    altered = graph.add(
        parse_record(
            "publication_proof",
            proof.canonical_payload() | {"manifest_id": replacement.id},
        )
    )
    interval = verified.pop(proof.id).interval
    graph.records.pop(proof.id)
    verified[altered.id] = VerifiedPublication(
        altered.id, replacement.id, altered.token_hash, interval
    )
    assert (
        assess_run(run, resolution, graph.experiment, context).eligibility
        == "invalid_publication"
    )
