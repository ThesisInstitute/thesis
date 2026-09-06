"""Real database failures around the worker's externally visible boundaries."""

import pytest

from thesis_core.contracts import Experiment, ForecastRun
from thesis_core.scoring import build_interval_distribution
from thesis_core.worker import work_once

from .test_store import attempt_factory, expire, task_graph


def scheduled(store):
    _, target, forecaster, _, task = task_graph(store)
    experiment = Experiment(
        task_ids=(task.id,),
        target_version_ids=(target.id,),
        forecaster_version_ids=(forecaster.id,),
        baseline_forecaster_id=forecaster.id,
        registration_deadline=task.submission_deadline,
        mode="replay",
    )
    store.put(experiment)
    store.enqueue(
        "forecast",
        task.id,
        {"experiment_id": experiment.id},
        idempotency_key="test-forecast",
    )
    return task


def completed_run(store, claim, task, followups):
    attempt = store.start_attempt(claim, task.id, attempt_factory(store, task))
    digest = store.artifacts.put_bytes(b"observed model response")
    run = ForecastRun(
        attempt_id=attempt.id,
        distribution=build_interval_distribution(12.0, 10.0, 14.0),
        stdout_hash=digest,
        stderr_hash=digest,
        raw_response_hash=digest,
        completed_at=store.health()["database_time"],
        execution_policy="baseline",
        prompt_hash=attempt.prompt_hash,
    )
    store.finish(claim, outcome="succeeded", records=(run,), followups=followups(run))
    return run


def test_finish_ack_failure_preserves_atomic_outbox_without_model_retry(
    core_store, monkeypatch
):
    task = scheduled(core_store)
    invocations = []
    acknowledge = core_store._acknowledge

    def failing_ack(record_ids):
        if any(
            core_store.get(identity).kind == "forecast_run" for identity in record_ids
        ):
            raise ConnectionError("acknowledgement connection unavailable")
        return acknowledge(record_ids)

    def execute(store, claim, *, followups, **kwargs):
        invocations.append(claim.job_id)
        return completed_run(store, claim, task, followups)

    monkeypatch.setattr(core_store, "_acknowledge", failing_ack)
    monkeypatch.setattr("thesis_core.execution.execute_forecast", execute)
    result = work_once(core_store, kinds=("forecast",))
    assert result["status"] == "acknowledgement_pending"
    assert core_store.job(result["job_id"])["state"] == "complete"
    assert len(tuple(core_store.iter_records("forecast_run"))) == 1
    assert len(tuple(core_store.iter_records("attempt_result"))) == 1

    monkeypatch.setattr(core_store, "_acknowledge", acknowledge)
    assert core_store.repair_acceptances() == 2
    assert core_store.deliver_outbox() == 2
    assert core_store.claim("no-repeat", ("forecast",)) is None
    assert core_store.claim("publisher", ("publish_run",)) is not None
    assert core_store.claim("scorer", ("evaluate",)) is not None
    assert len(invocations) == 1


def test_generic_exception_after_dispatch_stays_uncertain(core_store, monkeypatch):
    task = scheduled(core_store)
    claims = []

    def execute(store, claim, **kwargs):
        claims.append(claim)
        store.start_attempt(claim, task.id, attempt_factory(store, task))
        raise ConnectionError("Lost monitoring connection after launch")

    monkeypatch.setattr("thesis_core.execution.execute_forecast", execute)
    result = work_once(core_store, kinds=("forecast",))
    assert result["status"] == "execution_uncertain"
    assert core_store.job(result["job_id"])["state"] == "leased"
    assert tuple(core_store.iter_records("attempt_result")) == ()
    expire(core_store, claims[0])
    assert core_store.recover_expired() == {"requeued": 0, "unknown": 1}
    assert work_once(core_store, kinds=("forecast",)) is None
    (terminal,) = core_store.iter_records("attempt_result")
    assert terminal.outcome == "unknown"


def test_exception_after_durable_completion_cannot_compensate(core_store, monkeypatch):
    task = scheduled(core_store)

    def execute(store, claim, *, followups, **kwargs):
        completed_run(store, claim, task, followups)
        raise RuntimeError("Post-completion observer failed")

    monkeypatch.setattr("thesis_core.execution.execute_forecast", execute)
    result = work_once(core_store, kinds=("forecast",))
    assert result["status"] == "complete"
    (terminal,) = core_store.iter_records("attempt_result")
    assert terminal.outcome == "succeeded"
    assert core_store.deliver_outbox() == 2


def test_predispatch_refusal_is_a_known_job_failure(core_store, monkeypatch):
    scheduled(core_store)

    def refuse(*args, **kwargs):
        raise ValueError("Configuration refused before model invocation")

    monkeypatch.setattr("thesis_core.execution.execute_forecast", refuse)
    result = work_once(core_store, kinds=("forecast",))
    assert result["status"] == "failed"
    assert core_store.job(result["job_id"])["state"] == "failed"
    assert tuple(core_store.iter_records("attempt")) == ()


def drain_scientific_jobs(store):
    outcomes = []
    for _ in range(30):
        result = work_once(store, kinds=("forecast", "resolve", "evaluate"))
        if result is None:
            return outcomes
        assert result.get("status") != "failed", result
        outcomes.append(result)
    raise AssertionError("Scientific work did not quiesce")


def test_capture_and_drain_resolves_and_scores_without_manual_commands(core_store):
    from thesis_core.pilot import prepare_replay
    from thesis_core.resolution import capture_source
    from thesis_core.worker import schedule_experiment

    from .test_pilot import statcan_fixture

    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    schedule_experiment(core_store, experiment.id)
    captured = capture_source(
        core_store, "statcan-cpi-yoy", fetch=statcan_fixture, mode="replay"
    )
    assert captured.status == "captured"
    outcomes = drain_scientific_jobs(core_store)
    assert {item["kind"] for item in outcomes} >= {"forecast", "resolve", "evaluate"}
    (resolution,) = core_store.iter_records("resolution")
    (score,) = core_store.iter_records("score")
    assert resolution.target_version_id == experiment.target_version_ids[0]
    assert score.crps is not None and score.eligibility == "replay"
    assert score.resolution_id == resolution.id
    assert len(tuple(core_store.iter_records("attempt"))) == 1
    assert drain_scientific_jobs(core_store) == []


def test_scientific_repair_backfills_registration_once(core_store):
    from thesis_core.pilot import prepare_replay
    from thesis_core.resolution import repair_scientific_followups

    from .test_pilot import statcan_fixture

    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    assert core_store.jobs() == ()
    assert repair_scientific_followups(core_store) > 0
    core_store.deliver_outbox()
    identities = {job["id"] for job in core_store.jobs()}
    repair_scientific_followups(core_store)
    core_store.deliver_outbox()
    assert {job["id"] for job in core_store.jobs()} == identities
    drain_scientific_jobs(core_store)
    (resolution,) = core_store.iter_records("resolution")
    assert resolution.target_version_id == experiment.target_version_ids[0]


def test_concurrent_resolution_calls_preserve_one_identity(core_store):
    from concurrent.futures import ThreadPoolExecutor

    from thesis_core.pilot import prepare_replay
    from thesis_core.resolution import resolve_target

    from .test_pilot import statcan_fixture

    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    target_id = experiment.target_version_ids[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        resolutions = list(
            pool.map(lambda _: resolve_target(core_store, target_id), range(2))
        )
    assert resolutions[0].id == resolutions[1].id
    assert len(tuple(core_store.iter_records("resolution"))) == 1


def test_no_resolution_job_before_a_verifiable_candidate(core_store):
    from thesis_core.contracts import parse_record
    from thesis_core.pilot import prepare_replay
    from thesis_core.resolution import scientific_followups

    from .test_pilot import statcan_fixture

    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    original = core_store.get(experiment.target_version_ids[0])
    target = parse_record(
        "target_version",
        original.canonical_payload()
        | {
            "target_id": "future-not-released",
            "measurement_period": "2050-01",
        },
    )
    core_store.put(target)
    assert scientific_followups(core_store, target) == ()


def test_malformed_peer_cannot_block_a_valid_resolution_and_score(core_store):
    from thesis_core.contracts import parse_record
    from thesis_core.pilot import prepare_replay
    from thesis_core.resolution import resolve_target
    from thesis_core.worker import schedule_experiment

    from .test_pilot import statcan_fixture

    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    target = core_store.get(experiment.target_version_ids[0])
    genuine = next(
        observation
        for observation in core_store.iter_records("observation")
        if observation.measurement_period == target.measurement_period
    )
    malformed = parse_record(
        "observation", genuine.canonical_payload() | {"value": genuine.value + 1.0}
    )
    core_store.put(malformed)
    # An explicit request for malformed evidence still refuses; automatic
    # candidate discovery must continue to independently valid captures.
    with pytest.raises(ValueError, match="differs from registered raw parse"):
        resolve_target(core_store, target.id, malformed.id)
    schedule_experiment(core_store, experiment.id)
    drain_scientific_jobs(core_store)
    (resolution,) = core_store.iter_records("resolution")
    (score,) = core_store.iter_records("score")
    assert resolution.observation_id == genuine.id
    assert score.resolution_id == resolution.id
    assert score.crps is not None and score.eligibility == "replay"
    assert drain_scientific_jobs(core_store) == []


def capture_conflicting_statcan_vintage(store, *, enqueue=True):
    import json
    from dataclasses import replace

    from thesis_core.resolution import capture_source

    from .test_pilot import statcan_fixture

    def corrected_capture(request):
        response = statcan_fixture(request)
        payload = json.loads(response.body)
        # Same official publication field and vintage date, different genuine
        # parsed index/YoY value. Neither capture is a forged observation claim.
        payload[0]["object"]["vectorDataPoint"][-1]["value"] = 169.7
        return replace(response, body=json.dumps(payload).encode())

    if enqueue:
        return capture_source(
            store, "statcan-cpi-yoy", fetch=corrected_capture, mode="replay"
        )
    from thesis_core.adapters import capture

    result = capture(
        "statcan-cpi-yoy", store.artifacts, fetch=corrected_capture, mode="replay"
    )
    # Simulate a durable import whose followup edge was missed.
    with store.transaction() as transaction:
        for record in (result.source, *result.exchanges, *result.observations):
            transaction.put(record)
    return result


@pytest.mark.parametrize("path", ["automatic", "explicit", "native_register"])
def test_every_resolution_entry_point_refuses_conflicting_valid_vintages(
    core_store, tmp_path, path
):
    from datetime import datetime, timezone

    from thesis_core import cli
    from thesis_core.contracts import Resolution
    from thesis_core.pilot import prepare_replay
    from thesis_core.resolution import VALIDATION_VERSION, resolve_target

    from .test_pilot import statcan_fixture

    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    target = core_store.get(experiment.target_version_ids[0])
    captured = capture_conflicting_statcan_vintage(core_store)
    observation = next(
        o
        for o in captured.observations
        if o.measurement_period == target.measurement_period
    )
    assert observation.value == 3.3
    with pytest.raises(ValueError, match="conflicting values"):
        if path == "automatic":
            resolve_target(core_store, target.id)
        elif path == "explicit":
            resolve_target(core_store, target.id, observation.id)
        else:
            record = Resolution(
                target_version_id=target.id,
                observation_id=observation.id,
                resolution_policy=target.resolution_policy,
                validation_version=VALIDATION_VERSION,
                recorded_at=datetime.now(timezone.utc),
            )
            document = tmp_path / "ambiguous-resolution.json"
            document.write_bytes(record.canonical_bytes())
            cli._dispatch(
                cli.parser().parse_args(
                    ["register", str(document), "--kind", "resolution"]
                ),
                core_store,
            )
    assert tuple(core_store.iter_records("resolution")) == ()


@pytest.mark.parametrize("trigger", ["capture", "repair"])
def test_later_ambiguity_invalidates_current_score_without_rewriting_resolution(
    core_store, trigger
):
    from thesis_core.pilot import prepare_replay
    from thesis_core.resolution import (
        repair_scientific_followups,
        resolve_target,
        scientific_followups,
    )
    from thesis_core.service import reward_rows
    from thesis_core.worker import schedule_experiment

    from .test_pilot import statcan_fixture

    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    target_id = experiment.target_version_ids[0]
    schedule_experiment(core_store, experiment.id)
    assert work_once(core_store, kinds=("forecast",))["run_id"]
    original = resolve_target(core_store, target_id)
    drain_scientific_jobs(core_store)
    # Exhaust pre-existing backfill edges before testing that the new capture
    # independently schedules work and subsequent repairs are idempotent.
    repair_scientific_followups(core_store)
    drain_scientific_jobs(core_store)
    (before,) = core_store.iter_records("score")
    assert before.eligibility == "replay" and before.crps is not None
    old_jobs = {job["id"] for job in core_store.jobs()}
    captured = capture_conflicting_statcan_vintage(
        core_store, enqueue=trigger == "capture"
    )
    observation = next(
        o
        for o in captured.observations
        if o.measurement_period == core_store.get(target_id).measurement_period
    )
    # The native registration path uses this same immutable observation trigger.
    (followup,) = scientific_followups(core_store, observation)
    assert followup.kind == "evaluate" and followup.subject_id == experiment.id
    if trigger == "repair":
        repair_scientific_followups(core_store)
    core_store.deliver_outbox()
    assert any(
        job["id"] not in old_jobs and job["kind"] == "evaluate"
        for job in core_store.jobs()
    )
    drain_scientific_jobs(core_store)
    (after,) = (
        score for score in core_store.iter_records("score") if score.id != before.id
    )
    assert after.eligibility == "invalid_resolution"
    assert after.reward is None
    # The current export re-evaluates instead of serving the old favorable row.
    (exported,) = reward_rows(core_store, experiment.id)
    assert exported["id"] == after.id
    assert exported["eligibility"] == "invalid_resolution"
    assert tuple(core_store.iter_records("resolution")) == (original,)
    with pytest.raises(ValueError, match="conflicting values"):
        resolve_target(core_store, target_id)
    completed_jobs = {job["id"] for job in core_store.jobs()}
    repair_scientific_followups(core_store)
    core_store.deliver_outbox()
    assert {job["id"] for job in core_store.jobs()} == completed_jobs
    assert drain_scientific_jobs(core_store) == []
