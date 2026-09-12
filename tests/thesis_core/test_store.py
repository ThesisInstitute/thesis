import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.types.json import Jsonb

from thesis_core.contracts import (
    Attempt,
    EvaluationTask,
    EvidenceBundle,
    Experiment,
    ForecasterVersion,
    ForecastRun,
    PublicationManifest,
    SourceSeries,
    TargetVersion,
)
from thesis_core.store import (
    AcknowledgementPending,
    AttemptBlocked,
    IdentityConflict,
    JobSpec,
    LeaseLost,
    RecordMissing,
)


def source(name="test"):
    return SourceSeries(
        adapter_id="fixture",
        adapter_version="1",
        name=name,
        unit="percent",
        binding={"series": name},
        vintage_policies=("first_print",),
    )


def task_graph(store, *, maximum=3):
    series = source()
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    digest = store.artifacts.put_bytes(b"declared execution configuration")
    target = TargetVersion(
        target_id="test-rate",
        source_series_id=series.id,
        measurement_period="2026-02",
        unit="percent",
        resolution_policy="first_print",
        resolution_rule="official_v1",
        submission_deadline=stamp + timedelta(days=2),
    )
    forecaster = ForecasterVersion(
        provider="local",
        model_request="baseline",
        agent_version="1",
        harness_version="1",
        prompt_template_hash=digest,
        system_prompt_hash=digest,
        tool_policy_hash=digest,
        execution_policy="baseline",
    )
    bundle = EvidenceBundle(
        source_series_id=series.id,
        observation_ids=(),
        artifact_refs=(),
        information_cutoff=stamp,
        mode="replay",
    )
    task = EvaluationTask(
        target_version_id=target.id,
        forecaster_version_id=forecaster.id,
        evidence_bundle_id=bundle.id,
        information_cutoff=stamp,
        submission_deadline=stamp + timedelta(days=2),
        max_attempts=maximum,
        execution_policy="baseline",
        mode="replay",
    )
    with store.transaction() as transaction:
        for record in (series, target, forecaster, bundle, task):
            transaction.put(record)
    return series, target, forecaster, bundle, task


def attempt_factory(store, task):
    digest = store.artifacts.put_bytes(b"prompt and command")
    return lambda sequence, at: Attempt(
        task_id=task.id,
        sequence=sequence,
        started_at=at,
        command_hash=digest,
        prompt_hash=digest,
        code_hash=digest,
        execution_policy="baseline",
    )


def claim_task(store, task, key=None):
    store.enqueue("forecast", task.id, idempotency_key=key or uuid.uuid4().hex)
    store.deliver_outbox()
    return store.claim("worker", ("forecast",), lease_seconds=60)


def expire(store, claim):
    with store.connection() as connection:
        connection.execute(
            "UPDATE jobs SET lease_expires_at=clock_timestamp()-interval '1 "
            "second' WHERE id=%s",
            (claim.job_id,),
        )


def test_migration_identity_immutability_and_pagination(core_store):
    core_store.migrate()
    records = [source(str(index)) for index in range(4)]
    for record in records:
        assert core_store.put(record) == core_store.put(record)
        assert core_store.get(record.id) == record
    page = core_store.list("source_series", limit=2)
    assert len(page.records) == 2 and page.next_cursor
    second = core_store.list("source_series", limit=2, after=page.next_cursor)
    assert len(second.records) == 2 and second.next_cursor is None
    assert {item.id for item in core_store.iter_records("source_series")} == {
        item.id for item in records
    }
    assert len(tuple(core_store.iter_records())) == len(records)
    with pytest.raises(IdentityConflict):
        core_store.put(records[0], expected_id="0" * 64)
    for statement in (
        "UPDATE records SET payload=payload",
        "DELETE FROM records",
        "DELETE FROM record_acceptances",
    ):
        with pytest.raises(psycopg.Error, match="immutable"):
            with core_store.connection() as connection:
                connection.execute(statement)


def test_database_rejects_wrong_identity_wrong_kind_and_missing_links(core_store):
    series, target, forecaster, _, _ = task_graph(core_store)
    payload = target.canonical_payload()
    payload["source_series_id"] = forecaster.id
    from thesis_core.contracts import parse_record

    wrong = parse_record("target_version", payload)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        core_store.put(wrong)
    payload["source_series_id"] = series.id
    payload["target_id"] = "missing-edge"
    missing = parse_record("target_version", payload)
    with pytest.raises(psycopg.Error, match="Missing or mismatched reference"):
        with core_store.connection() as connection:
            connection.execute(
                "INSERT INTO "
                "records(id,kind,schema_version,canonical_payload,payload) VALUES "
                "(%s,%s,1,%s,%s)",
                (
                    missing.id,
                    missing.kind,
                    missing.canonical_bytes(),
                    Jsonb(missing.canonical_payload()),
                ),
            )
    with pytest.raises(psycopg.errors.CheckViolation):
        with core_store.connection() as connection:
            connection.execute(
                "INSERT INTO "
                "records(id,kind,schema_version,canonical_payload,payload) VALUES "
                "(%s,%s,1,%s,%s)",
                (
                    "f" * 64,
                    series.kind,
                    series.canonical_bytes(),
                    Jsonb(series.canonical_payload()),
                ),
            )


def test_atomic_record_outbox_and_duplicate_delivery(core_store):
    record = source()
    with pytest.raises(RuntimeError, match="rollback"):
        with core_store.transaction() as transaction:
            transaction.put(record)
            transaction.enqueue("capture", record.id, idempotency_key="capture-once")
            raise RuntimeError("rollback")
    with pytest.raises(RecordMissing):
        core_store.get(record.id)
    with core_store.transaction() as transaction:
        transaction.put(record)
        transaction.enqueue(
            "capture", record.id, {"mode": "live"}, idempotency_key="capture-once"
        )
    core_store.enqueue(
        "capture", record.id, {"mode": "live"}, idempotency_key="capture-once"
    )
    with pytest.raises(IdentityConflict):
        core_store.enqueue(
            "capture", record.id, {"mode": "replay"}, idempotency_key="capture-once"
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: core_store.deliver_outbox(), range(2))) == 1
    assert core_store.deliver_outbox() == 0
    assert len(core_store.jobs()) == 1


def test_competing_claims_and_stale_token_fencing(core_store):
    record = source()
    core_store.put(record)
    core_store.enqueue("capture", record.id, idempotency_key="claim")
    core_store.deliver_outbox()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda worker: core_store.claim(worker), ("a", "b")))
    claim = next(value for value in claims if value is not None)
    assert sum(value is not None for value in claims) == 1
    expire(core_store, claim)
    with pytest.raises(LeaseLost):
        core_store.heartbeat(claim)
    assert core_store.recover_expired() == {"requeued": 1, "unknown": 0}
    replacement = core_store.claim("new")
    assert replacement.generation == claim.generation + 1
    assert replacement.lease_token != claim.lease_token
    with pytest.raises(LeaseLost):
        core_store.finish(claim, outcome="succeeded")
    core_store.finish(replacement, outcome="succeeded")


def test_worker_clock_skew_cannot_change_lease_time(core_store, monkeypatch):
    import thesis_core.store as store_module

    class FarFuture:
        @staticmethod
        def now(*args, **kwargs):
            return datetime(2100, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(store_module, "datetime", FarFuture)
    record = source()
    core_store.put(record)
    core_store.enqueue("capture", record.id, idempotency_key="clock")
    core_store.deliver_outbox()
    claim = core_store.claim("clock-skew", lease_seconds=30)
    now = core_store.health()["database_time"]
    assert timedelta(seconds=20) < claim.lease_expires_at - now < timedelta(seconds=31)
    core_store.finish(claim, outcome="succeeded")


def test_explicit_retry_only_reopens_never_dispatched_failed_work(core_store):
    record = source()
    core_store.put(record)
    core_store.enqueue("publication", record.id, idempotency_key="retry-publication")
    core_store.deliver_outbox()
    original = core_store.claim("publisher")
    core_store.finish(original, outcome="failed")
    retried = core_store.retry_job(
        original.job_id, actor="test", reason="TSA recovered"
    )
    assert retried["state"] == "pending"
    assert retried["generation"] > original.generation
    (audit,) = core_store.job_events(original.job_id)
    assert audit["event"] == "retry_requested" and audit["actor"] == "test"
    with pytest.raises(AttemptBlocked):
        core_store.retry_job(original.job_id)
    replacement = core_store.claim("publisher")
    with pytest.raises(LeaseLost):
        core_store.finish(original, outcome="succeeded")
    core_store.finish(replacement, outcome="succeeded")

    *_, task = task_graph(core_store)
    forecast = claim_task(core_store, task)
    core_store.start_attempt(forecast, task.id, attempt_factory(core_store, task))
    core_store.finish(forecast, outcome="failed")
    with pytest.raises(AttemptBlocked):
        core_store.retry_job(forecast.job_id)
    with pytest.raises(psycopg.Error, match="immutable"):
        with core_store.connection() as connection:
            connection.execute("DELETE FROM job_events")


def test_atomic_sequences_unknown_blocks_and_reconciliation_is_terminal(core_store):
    *_, task = task_graph(core_store)
    claim = claim_task(core_store, task)
    attempt = core_store.start_attempt(
        claim, task.id, attempt_factory(core_store, task)
    )
    assert attempt.sequence == 1
    assert core_store.attempt_events(attempt.id)[0]["event"] == "started"
    expire(core_store, claim)
    assert core_store.recover_expired() == {"requeued": 0, "unknown": 1}
    assert core_store.claim("second") is None
    second_claim = claim_task(core_store, task)
    with pytest.raises(AttemptBlocked, match="unresolved"):
        core_store.start_attempt(
            second_claim, task.id, attempt_factory(core_store, task)
        )
    orphan = core_store.artifacts.put_bytes(
        b"late alleged forecast; never committed under a fence"
    )
    result = core_store.reconcile_unknown(
        claim.job_id,
        actor="test-operator",
        reason="No sealed database result",
        evidence_hashes=(orphan,),
    )
    assert result.outcome == "failed" and result.run_id is None
    assert result.reconciliation_method == "no_sealed_result"
    assert [event["event"] for event in core_store.attempt_events(attempt.id)] == [
        "started",
        "unknown",
        "reconciled",
    ]
    with pytest.raises(AttemptBlocked):
        core_store.reconcile_unknown(claim.job_id, actor="test", reason="Repeated")
    with pytest.raises(LeaseLost):
        core_store.finish(claim, outcome="failed")
    second_attempt = core_store.start_attempt(
        second_claim, task.id, attempt_factory(core_store, task)
    )
    assert second_attempt.sequence == 2
    core_store.finish(second_claim, outcome="failed")


def test_concurrent_attempt_creation_allocates_only_one_sequence(core_store):
    *_, task = task_graph(core_store)
    claims = [claim_task(core_store, task) for _ in range(2)]

    def start(claim):
        try:
            return core_store.start_attempt(
                claim, task.id, attempt_factory(core_store, task)
            )
        except AttemptBlocked:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(start, claims))
    assert [value.sequence for value in attempts if value is not None] == [1]


def test_attempt_factory_cannot_change_allocation_or_exceed_maximum(core_store):
    *_, task = task_graph(core_store, maximum=1)
    claim = claim_task(core_store, task)
    good = attempt_factory(core_store, task)
    with pytest.raises(IdentityConflict):
        core_store.start_attempt(
            claim, task.id, lambda sequence, at: good(sequence + 1, at)
        )
    attempt = core_store.start_attempt(claim, task.id, good)
    assert attempt.sequence == 1
    core_store.finish(claim, outcome="failed")
    second = claim_task(core_store, task)
    with pytest.raises(AttemptBlocked, match="maximum"):
        core_store.start_attempt(second, task.id, good)
    forged = good(99, datetime.now(timezone.utc))
    with pytest.raises(psycopg.Error, match="atomically allocated"):
        core_store.put(forged)


def test_postcommit_ack_cannot_be_backdated_or_created_in_same_transaction(core_store):
    record = source()
    with pytest.raises(psycopg.Error, match="previously committed"):
        with core_store.transaction() as transaction:
            transaction.put(record)
            transaction.connection.execute(
                "INSERT INTO record_acceptances(record_id,committed_at) VALUES "
                "(%s,'2000-01-01Z')",
                (record.id,),
            )
    original = core_store._acknowledge
    core_store._acknowledge = lambda ids: None
    core_store.put(record)
    core_store._acknowledge = original
    with core_store.connection() as connection:
        cutoff = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        connection.execute(
            "INSERT INTO record_acceptances(record_id,committed_at) VALUES "
            "(%s,'2000-01-01Z')",
            (record.id,),
        )
    assert core_store.committed_at(record.id) >= cutoff


def test_ack_crash_preserves_completed_job_and_repair_gets_later_time(
    core_store, monkeypatch
):
    *_, task = task_graph(core_store)
    claim = claim_task(core_store, task)
    attempt = core_store.start_attempt(
        claim, task.id, attempt_factory(core_store, task)
    )
    original = core_store._acknowledge

    def crash(ids):
        raise RuntimeError("Crash after scientific COMMIT")

    monkeypatch.setattr(core_store, "_acknowledge", crash)
    with pytest.raises(AcknowledgementPending) as pending:
        core_store.finish(claim, outcome="failed")
    (result_id,) = pending.value.record_ids
    assert core_store.get(result_id).attempt_id == attempt.id
    assert core_store.jobs()[0]["state"] == "failed"
    assert core_store.committed_at(result_id) is None
    assert core_store.claim("retry") is None
    cutoff = core_store.health()["database_time"]
    monkeypatch.setattr(core_store, "_acknowledge", original)
    assert core_store.repair_acceptances() == 1
    assert core_store.committed_at(result_id) > cutoff
    assert core_store.repair_acceptances() == 0


def test_experiment_task_ownership_and_duplicate_pair_refuse_atomically(core_store):
    _, target, forecaster, _, task = task_graph(core_store)

    def experiment(tasks, day):
        return Experiment(
            task_ids=tuple(item.id for item in tasks),
            target_version_ids=(target.id,),
            forecaster_version_ids=(forecaster.id,),
            baseline_forecaster_id=forecaster.id,
            registration_deadline=datetime(2026, 1, day, tzinfo=timezone.utc),
            mode="replay",
        )

    first = experiment((task,), 1)
    core_store.put(first)
    second = experiment((task,), 2)
    with pytest.raises(psycopg.errors.UniqueViolation):
        core_store.put(second)
    with pytest.raises(RecordMissing):
        core_store.get(second.id)
    from thesis_core.contracts import parse_record

    task_payload = task.canonical_payload()
    task_payload["max_attempts"] = 4
    alternative = parse_record("evaluation_task", task_payload)
    task_payload["max_attempts"] = 5
    third = parse_record("evaluation_task", task_payload)
    core_store.put(alternative)
    core_store.put(third)
    duplicate = experiment((alternative, third), 3)
    with pytest.raises(IdentityConflict, match="repeat"):
        core_store.put(duplicate)
    assert {record.id for record in core_store.dependency_closure(first.id)} >= {
        first.id,
        task.id,
        target.id,
        forecaster.id,
    }


def test_successful_finish_is_atomic_and_publication_failure_preserves_run(core_store):
    from thesis_core.scoring import build_interval_distribution

    *_, task = task_graph(core_store)
    claim = claim_task(core_store, task)
    attempt = core_store.start_attempt(
        claim, task.id, attempt_factory(core_store, task)
    )
    digest = core_store.artifacts.put_bytes(b"complete model response")
    run = ForecastRun(
        attempt_id=attempt.id,
        distribution=build_interval_distribution(12.0, 10.0, 14.0),
        stdout_hash=digest,
        stderr_hash=digest,
        raw_response_hash=digest,
        completed_at=core_store.health()["database_time"],
        execution_policy="baseline",
        prompt_hash=attempt.prompt_hash,
    )
    # A CAS upload and generic record insert cannot bypass finalization.
    with pytest.raises(psycopg.Error, match="fenced successful"):
        core_store.put(run)
    core_store.finish(
        claim,
        outcome="succeeded",
        records=(run,),
        followups=(JobSpec("publication", run.id, "publish-once"),),
    )
    assert core_store.get(run.id) == run
    assert core_store.committed_at(run.id) is not None
    results = tuple(core_store.iter_records("attempt_result"))
    assert len(results) == 1 and results[0].run_id == run.id
    with pytest.raises(LeaseLost):
        core_store.finish(claim, outcome="succeeded", records=(run,))
    core_store.deliver_outbox()
    publication = core_store.claim("publisher", ("publication",))
    core_store.finish(publication, outcome="failed")
    assert core_store.get(run.id) == run
    assert len(tuple(core_store.iter_records("attempt"))) == 1


def test_publication_transport_audit_is_immutable(core_store):
    _, target, forecaster, _, task = task_graph(core_store)
    experiment = Experiment(
        task_ids=(task.id,),
        target_version_ids=(target.id,),
        forecaster_version_ids=(forecaster.id,),
        baseline_forecaster_id=forecaster.id,
        registration_deadline=task.submission_deadline,
        mode="replay",
    )
    core_store.put(experiment)
    request = core_store.artifacts.put_bytes(b"timestamp request")
    error = core_store.artifacts.put_bytes(b"sanitized connection error")
    response = core_store.artifacts.put_bytes(b"invalid timestamp token")
    manifest = PublicationManifest(
        manifest_type="cohort",
        experiment_id=experiment.id,
        artifacts=(request,),
        code_hash=request,
        recorded_at=core_store.health()["database_time"],
        declared_information_cutoff=task.information_cutoff,
        effective_information_boundary=core_store.committed_at(task.id),
    )
    core_store.put(manifest)
    core_store.log_publication_attempt(manifest.id, request, error_hash=error)
    core_store.log_publication_attempt(manifest.id, request, response, error)
    core_store.log_publication_attempt(manifest.id, error_hash=error)
    events = core_store.publication_attempts(manifest.id)
    assert len(events) == 3
    assert events[0]["response_hash"] is None
    assert events[1]["response_hash"] == response
    assert events[2]["request_hash"] is None
    assert events[0]["recorded_at"] <= events[1]["recorded_at"]
    with pytest.raises(psycopg.Error, match="immutable"):
        with core_store.connection() as connection:
            connection.execute("DELETE FROM publication_attempts")
