"""Prospective dispatch over real PostgreSQL and locally signed RFC 3161 bytes.

The future calendar is explicitly synthetic and is replayed by the real admitted
BEA parser. Historical input is an archived official BEA fixture. No source,
publication-verification, scheduling or execution result is mocked.
"""

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from thesis_core import publication, tsa
from thesis_core.adapters import release_evidence_from_bytes
from thesis_core.adapters.timing import BEA_CALENDAR_URL
from thesis_core.contracts import EvaluationTask, Experiment, TargetVersion
from thesis_core.evidence import build_evidence_bundle
from thesis_core.execution import PERSISTENCE_BASELINE_VERSION
from thesis_core.worker import schedule_experiment, work_once

from .factories import make_forecaster
from .test_adapters_evidence import captured
from .test_tsa import authorities, pinned_tsa  # noqa: F401


def prospective_cohort(
    store, *, short_cutoff=False, past_registration=False, deadline_after_release=False
):
    capture = captured(store.artifacts, "bea-fixed-investment")
    assert capture.status == "captured", capture.errors
    with store.transaction() as transaction:
        transaction.put(capture.source)
        for record in (*capture.exchanges, *capture.observations):
            transaction.put(record)
    now = publication.database_now(store)
    release = datetime(now.year + 1, 10, 29, 12, 30, tzinfo=timezone.utc)
    cutoff = now + (timedelta(seconds=2) if short_cutoff else timedelta(hours=1))
    deadline = (
        release + timedelta(days=1)
        if deadline_after_release
        else (cutoff + timedelta(hours=1))
    )
    # This is a local test calendar, never an archived or published official claim.
    calendar = (
        "BEGIN:VCALENDAR\nPRODID://BEA-Release-Calendar-Subscription//\n"
        "BEGIN:VEVENT\n"
        f"SUMMARY:GDP (Advance Estimate), 3rd Quarter {release.year}\n"
        f"DTSTART:{release:%Y%m%dT%H%M%SZ}\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    ).encode()
    target = TargetVersion(
        target_id=f"synthetic-prospective-bea:{now.isoformat()}",
        source_series_id=capture.source.id,
        measurement_period=f"{release.year}-Q3",
        unit=capture.source.unit,
        resolution_policy="fixed_vintage",
        vintage_date=release.date().isoformat(),
        resolution_rule="registered-source-vintage-v1",
        submission_deadline=deadline,
        release_evidence=release_evidence_from_bytes(
            capture.source,
            f"{release.year}-Q3",
            calendar,
            BEA_CALENDAR_URL,
            store.artifacts,
        ),
    )
    bundle = build_evidence_bundle(
        capture.source,
        capture.observations,
        {exchange.id: exchange for exchange in capture.exchanges},
        store.artifacts,
        information_cutoff=cutoff,
        mode="prospective",
        committed_at=store.committed_at,
    )
    assert len(bundle.observation_ids) == 1
    prompt = store.artifacts.put_bytes(b"Use only supplied prospective evidence.")
    forecaster = make_forecaster(
        baseline=True,
        agent_version=PERSISTENCE_BASELINE_VERSION,
        prompt_template_hash=prompt,
        system_prompt_hash=prompt,
        tool_policy_hash=prompt,
    )
    task = EvaluationTask(
        target_version_id=target.id,
        forecaster_version_id=forecaster.id,
        evidence_bundle_id=bundle.id,
        information_cutoff=cutoff,
        submission_deadline=deadline,
        mode="prospective",
        execution_policy="baseline",
    )
    experiment = Experiment(
        task_ids=(task.id,),
        target_version_ids=(target.id,),
        forecaster_version_ids=(forecaster.id,),
        baseline_forecaster_id=forecaster.id,
        registration_deadline=now - timedelta(days=1) if past_registration else cutoff,
        mode="prospective",
    )
    with store.transaction() as transaction:
        for record in (target, bundle, forecaster, task, experiment):
            transaction.put(record)
    manifest = publication.create_manifest(store, experiment.id)
    return SimpleNamespace(
        experiment=experiment,
        task=task,
        bundle=bundle,
        manifest=manifest,
        release=release,
    )


def sign_cohort(store, graph, authority, monkeypatch, *, accuracy="millisecs:1"):
    # Signed precision is one millisecond; establish a real gap after DB freeze.
    time.sleep(0.01)
    monkeypatch.setattr(
        tsa,
        "post_timestamp_query",
        authority.transport(accuracy=accuracy, clock_precision_digits=6),
    )
    proof = publication.publish_manifest(
        store, graph.manifest.id, anchor_id=authority.anchor_id
    )
    verified = publication.verify_proof(store, proof)
    assert verified is not None
    return proof, verified


def test_real_receipt_gates_schedule_worker_and_actual_prompt(
    core_store,
    pinned_tsa,  # noqa: F811
    monkeypatch,
):
    graph = prospective_cohort(core_store)
    proof, verified = sign_cohort(core_store, graph, pinned_tsa, monkeypatch)
    assert verified.interval is not None
    assert core_store.committed_at(graph.bundle.id) < verified.interval.lower
    assert (
        publication.verify_cohort_for_dispatch(
            core_store, graph.task, graph.experiment.id, proof.id
        )
        == proof
    )
    assert (
        schedule_experiment(core_store, graph.experiment.id, cohort_proof_id=proof.id)
        == 1
    )
    result = work_once(core_store, kinds=("forecast",))
    assert result["run_id"], result
    run = core_store.get(result["run_id"])
    attempt = core_store.get(run.attempt_id)
    assert attempt.cohort_proof_id == proof.id
    assert attempt.cohort_token_hash == proof.token_hash
    prompt = core_store.artifacts.read_bytes(run.prompt_hash)
    assert b"prompt section: cohort_receipt" in prompt
    assert proof.id.encode() in prompt and proof.token_hash.encode() in prompt
    assert run.prompt_hash == attempt.prompt_hash

    # A cryptographically valid run witness is not a cohort witness.
    manifest = publication.create_manifest(
        core_store, graph.experiment.id, run_id=run.id
    )
    run_proof = publication.publish_manifest(
        core_store, manifest.id, anchor_id=pinned_tsa.anchor_id
    )
    assert publication.verify_proof(core_store, run_proof) is not None
    with pytest.raises(ValueError, match="independently ordered receipt"):
        publication.verify_cohort_for_dispatch(
            core_store, graph.task, graph.experiment.id, run_proof.id
        )


def test_unknown_accuracy_blocks_schedule_and_worker_before_attempt(
    core_store,
    pinned_tsa,  # noqa: F811
    monkeypatch,
):
    graph = prospective_cohort(core_store)
    proof, verified = sign_cohort(
        core_store, graph, pinned_tsa, monkeypatch, accuracy=None
    )
    assert verified.interval is None
    with pytest.raises(ValueError, match="independently ordered receipt"):
        schedule_experiment(core_store, graph.experiment.id, cohort_proof_id=proof.id)
    # Queue bypass does not bypass the worker's independent pre-dispatch replay.
    core_store.enqueue(
        "forecast",
        graph.task.id,
        {"experiment_id": graph.experiment.id, "cohort_proof_id": proof.id},
        idempotency_key="test-unordered-cohort",
    )
    result = work_once(core_store, kinds=("forecast",))
    assert result["status"] == "failed", result
    assert "independently ordered receipt" in result["error"]
    assert not tuple(core_store.iter_records("attempt"))


def test_real_cohort_receipt_cannot_authorize_another_task_or_experiment(
    core_store,
    pinned_tsa,  # noqa: F811
    monkeypatch,
):
    graph = prospective_cohort(core_store)
    proof, _ = sign_cohort(core_store, graph, pinned_tsa, monkeypatch)
    outsider = EvaluationTask.model_validate(
        graph.task.model_dump() | {"max_attempts": 2}
    )
    core_store.put(outsider)
    with pytest.raises(ValueError, match="outside dispatch cohort"):
        publication.verify_cohort_for_dispatch(
            core_store, outsider, graph.experiment.id, proof.id
        )
    other = prospective_cohort(core_store)
    with pytest.raises(ValueError, match="independently ordered receipt"):
        publication.verify_cohort_for_dispatch(
            core_store, other.task, other.experiment.id, proof.id
        )


def test_signed_accuracy_overlap_with_freeze_refuses_dispatch(
    core_store,
    pinned_tsa,  # noqa: F811
    monkeypatch,
):
    graph = prospective_cohort(core_store)
    proof, verified = sign_cohort(
        core_store, graph, pinned_tsa, monkeypatch, accuracy="secs:60"
    )
    interval = verified.interval
    assert interval.lower < core_store.committed_at(graph.bundle.id) < interval.upper
    # Move only operational dispatch time past the upper bound. The signed
    # interval and the real recorded freeze remain unchanged, isolating overlap.
    monkeypatch.setattr(
        publication, "database_now", lambda _: interval.upper + timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="not strictly ordered"):
        publication.verify_cohort_for_dispatch(
            core_store, graph.task, graph.experiment.id, proof.id
        )


@pytest.mark.parametrize("boundary", ["registration", "cutoff"])
def test_witness_after_registered_boundary_refuses_scheduling(
    core_store,
    pinned_tsa,  # noqa: F811
    monkeypatch,
    boundary,
):
    graph = prospective_cohort(
        core_store,
        short_cutoff=boundary == "cutoff",
        past_registration=boundary == "registration",
    )
    if boundary == "cutoff":
        remaining = graph.task.information_cutoff - datetime.now(timezone.utc)
        time.sleep(max(0, remaining.total_seconds()) + 0.02)
    proof, verified = sign_cohort(core_store, graph, pinned_tsa, monkeypatch)
    limit = (
        graph.experiment.registration_deadline
        if boundary == "registration"
        else (graph.task.information_cutoff)
    )
    assert verified.interval.lower > limit
    with pytest.raises(ValueError, match="not strictly ordered"):
        schedule_experiment(core_store, graph.experiment.id, cohort_proof_id=proof.id)
    assert not tuple(core_store.iter_records("attempt"))


@pytest.mark.parametrize("boundary", ["receipt_upper", "submission", "outcome"])
def test_dispatch_requires_prior_witness_and_unexpired_target(
    core_store,
    pinned_tsa,  # noqa: F811
    monkeypatch,
    boundary,
):
    graph = prospective_cohort(core_store, deadline_after_release=boundary == "outcome")
    proof, verified = sign_cohort(core_store, graph, pinned_tsa, monkeypatch)
    now = {
        "receipt_upper": verified.interval.upper,
        "submission": graph.task.submission_deadline,
        "outcome": graph.release,
    }[boundary]
    monkeypatch.setattr(publication, "database_now", lambda _: now)
    message = "not strictly ordered" if boundary == "receipt_upper" else "too late"
    with pytest.raises(ValueError, match=message):
        publication.verify_cohort_for_dispatch(
            core_store, graph.task, graph.experiment.id, proof.id
        )
