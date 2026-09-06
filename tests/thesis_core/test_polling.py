"""Real PostgreSQL leases, bounded retries and independent resolution capture."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from thesis_core.adapters import release_evidence_from_bytes
from thesis_core.adapters.registry import get_source
from thesis_core.adapters.timing import BEA_CALENDAR_URL
from thesis_core.contracts import TargetVersion
from thesis_core.polling import (
    claim_poll,
    finish_poll,
    poll_once,
    public_status,
    retry_followups,
    schedule_source,
)
from thesis_core.store import IdentityConflict, LeaseLost


def polling_target(
    store, *, seconds_until_release=-2, grace_seconds=86400, max_polls=96
):
    source = get_source("bea-fixed-investment")
    now = store.health()["database_time"]
    release = (now + timedelta(seconds=seconds_until_release)).replace(microsecond=0)
    raw = (
        Path(__file__).parents[1]
        / "fixtures/thesis_core/bea-release-schedule-2026-09-04.ics"
    ).read_bytes()
    raw = raw.replace(
        b"DTSTART:20261029T123000Z", release.strftime("DTSTART:%Y%m%dT%H%M%SZ").encode()
    )
    evidence = release_evidence_from_bytes(
        source, "2026-Q3", raw, BEA_CALENDAR_URL, store.artifacts
    )
    target = TargetVersion(
        target_id="polling-lease-test",
        source_series_id=source.id,
        measurement_period="2026-Q3",
        unit=source.unit,
        resolution_policy="fixed_vintage",
        vintage_date=release.date().isoformat(),
        resolution_rule="Exact registered BEA table and vintage",
        submission_deadline=release - timedelta(minutes=5),
        release_evidence=evidence,
    )
    with store.transaction() as transaction:
        transaction.put(source)
        transaction.put(target)
    schedule_source(store, target.id, max_polls=max_polls, grace_seconds=grace_seconds)
    return target


def test_schedule_exact_binding_and_idempotency(core_store):
    target = polling_target(core_store)
    schedule = schedule_source(core_store, target.id)
    assert schedule["source_id"] == target.source_series_id
    assert schedule["measurement_period"] == target.measurement_period
    assert schedule["vintage_date"] == target.vintage_date
    with pytest.raises(IdentityConflict):
        schedule_source(core_store, target.id, max_polls=2)
    with core_store.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM source_poll_events"
            ).fetchone()["n"]
            == 1
        )
    with pytest.raises(psycopg.Error, match="immutable"):
        with core_store.connection() as connection:
            connection.execute("UPDATE source_poll_schedules SET max_polls=2")


def test_concurrent_claims_only_one_winner(core_store):
    polling_target(core_store)
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: claim_poll(core_store), range(2)))
    assert sum(claim is not None for claim in claims) == 1


def test_crash_recovery_fences_old_owner_and_counts_budget(core_store):
    target = polling_target(core_store, max_polls=2)
    first = claim_poll(core_store)
    with core_store.connection() as connection:
        connection.execute(
            "UPDATE source_poll_state SET lease_expires_at="
            "clock_timestamp()-interval '1 second' WHERE target_id=%s",
            (target.id,),
        )
    second = claim_poll(core_store)
    assert second["generation"] == first["generation"] + 1
    with pytest.raises(LeaseLost):
        finish_poll(core_store, first)
    finish_poll(core_store, second)
    status = public_status(core_store)["schedules"][0]
    assert status["state"] == "overdue"
    assert status["last_error_code"] == "poll_budget_exhausted"
    assert status["failure_count"] == 1
    assert claim_poll(core_store) is None


def test_outer_deadline_is_overdue_without_network(core_store, monkeypatch):
    polling_target(core_store, seconds_until_release=-10, grace_seconds=0)
    monkeypatch.setattr(
        "thesis_core.resolution.capture_source",
        lambda *a, **k: pytest.fail("overdue poll fetched source"),
    )
    assert poll_once(core_store, max_jobs=0)["status"] == "idle"
    status = public_status(core_store)["schedules"][0]
    assert status["state"] == "overdue"
    assert status["last_error_code"] == "outcome_overdue"


def test_future_release_does_not_capture_early(core_store, monkeypatch):
    polling_target(core_store, seconds_until_release=172800)
    monkeypatch.setattr(
        "thesis_core.resolution.capture_source",
        lambda *a, **k: pytest.fail("future poll fetched source"),
    )
    assert poll_once(core_store, max_jobs=0)["status"] == "idle"
    assert public_status(core_store)["schedules"][0]["state"] == "active"


def test_transient_failure_archives_exchange_and_retries_later(core_store):
    from thesis_core.adapters import HttpResponse

    target = polling_target(core_store)
    result = poll_once(
        core_store,
        max_jobs=0,
        fetch=lambda request: HttpResponse(b"upstream unavailable", request.url, 503),
    )
    assert result["status"] == "failed"
    status = public_status(core_store)["schedules"][0]
    assert status["state"] == "active"
    assert status["failure_count"] == 1
    assert status["last_error_code"] == "source_unavailable"
    assert len(tuple(core_store.iter_records("source_exchange"))) == 1
    assert claim_poll(core_store) is None  # wait until next scheduled poll
    with core_store.connection() as connection:
        connection.execute(
            "UPDATE source_poll_state SET next_poll_at="
            "clock_timestamp()-interval '1 second' WHERE target_id=%s",
            (target.id,),
        )
    assert claim_poll(core_store) is not None


def test_resolved_stop_keeps_forecast_job_untouched(core_store, monkeypatch):
    target = polling_target(core_store)
    core_store.enqueue("forecast", target.id, idempotency_key="do-not-dispatch")
    core_store.deliver_outbox()
    monkeypatch.setattr("thesis_core.polling._verified_resolution", lambda *a: True)
    monkeypatch.setattr(
        "thesis_core.resolution.capture_source",
        lambda *a, **k: pytest.fail("resolved target fetched source"),
    )
    assert poll_once(core_store)["status"] == "resolved"
    assert core_store.jobs()[0]["state"] == "pending"
    assert claim_poll(core_store) is None
    assert public_status(core_store)["schedules"][0]["state"] == "resolved"


def test_retries_bounded_and_never_retry_failed_forecast(core_store):
    target = polling_target(core_store, seconds_until_release=172800)
    for kind in ("forecast", "publish"):
        core_store.enqueue(kind, target.id, idempotency_key=f"failure:{kind}")
    core_store.deliver_outbox()
    for kind in ("forecast", "publish"):
        claim = core_store.claim("test", (kind,))
        core_store.finish(claim, outcome="failed")
    for index in range(4):
        with core_store.connection() as connection:
            connection.execute(
                "UPDATE jobs SET updated_at=clock_timestamp()-interval '6 minutes'"
            )
        assert retry_followups(core_store) == (1 if index < 3 else 0)
        forecast = next(job for job in core_store.jobs() if job["kind"] == "forecast")
        assert forecast["state"] == "failed"
        assert core_store.job_events(forecast["id"]) == ()
        if index < 3:
            claim = core_store.claim("test", ("publish",))
            core_store.finish(claim, outcome="failed")
    publication = next(job for job in core_store.jobs() if job["kind"] == "publish")
    assert len(core_store.job_events(publication["id"])) == 3


def test_public_status_allowlist_and_missing_migration(core_store):
    status = public_status(core_store)
    assert status == {
        "schedules": [],
        "worker": {"last_poll_at": None, "status": "never_seen"},
    }
    target = polling_target(core_store)
    claim_poll(core_store)
    status = public_status(core_store)
    assert status["worker"]["status"] == "recent"
    assert status["schedules"][0]["target_id"] == target.id
    forbidden = (
        "lease_token",
        "source_id",
        "schema",
        "postgres_version",
        "dsn",
        "worker_id",
    )
    assert all(key not in str(status) for key in forbidden)
    with core_store.connection() as connection:
        connection.execute("DROP TABLE source_poll_worker")
    with pytest.raises(psycopg.errors.UndefinedTable):
        public_status(core_store)


def test_poll_pass_does_not_recover_an_expired_forecast_lease(core_store):
    target = polling_target(core_store, seconds_until_release=172800)
    for kind in ("forecast", "resolve"):
        core_store.enqueue(kind, target.id, idempotency_key=f"expired:{kind}")
    core_store.deliver_outbox()
    claims = [
        core_store.claim("other-worker", (kind,)) for kind in ("forecast", "resolve")
    ]
    with core_store.connection() as connection:
        connection.execute(
            "UPDATE jobs SET lease_expires_at=clock_timestamp()-interval '1 second'"
        )
    before = core_store.job(claims[0].job_id)
    poll_once(core_store, max_jobs=1)
    assert core_store.job(claims[0].job_id) == before
    assert not tuple(core_store.iter_records("attempt_result"))
    assert core_store.job(claims[1].job_id)["state"] == "failed"


def force_due(store):
    # Fixture-only accelerated polling; real schedules begin at the official lower.
    with store.connection() as connection:
        connection.execute(
            "UPDATE source_poll_state SET next_poll_at="
            "clock_timestamp()-interval '1 second'"
        )


def test_96_scoped_polls_preserve_history_and_bounded_api_latency(core_store):
    from time import perf_counter

    from fastapi.testclient import TestClient

    from thesis_core.api import create_app
    from thesis_core.pilot import prepare_live_pilot

    from .live_fixtures import future_fetch, future_period

    experiment = prepare_live_pilot(core_store, future_period(), fetch=future_fetch)
    target = core_store.get(experiment.target_version_ids[0])
    before = {record.id for record in core_store.iter_records("observation")}
    original_exchanges = len(tuple(core_store.iter_records("source_exchange")))
    schedule_source(core_store, target.id)
    for _ in range(96):
        force_due(core_store)
        assert (
            poll_once(core_store, max_jobs=0, fetch=future_fetch)["status"]
            == "captured"
        )
    assert {record.id for record in core_store.iter_records("observation")} == before
    assert (
        len(tuple(core_store.iter_records("source_exchange")))
        == original_exchanges + 96
    )
    assert public_status(core_store)["schedules"][0]["state"] == "overdue"
    assert not tuple(core_store.iter_records("attempt"))
    client = TestClient(create_app(core_store))
    started = perf_counter()
    response = client.get("/lab/forecasts")
    elapsed = perf_counter() - started
    assert response.status_code == 200, response.text
    assert elapsed < 5, f"Lab request took {elapsed:.3f}s after the full poll budget"
    print(f"Lab list after 96 scoped polls: {elapsed:.3f}s")


def test_exact_vintage_resolution_stops_real_capture_idempotently(core_store):
    import json

    from thesis_core.adapters import HttpResponse
    from thesis_core.pilot import prepare_live_pilot

    from .live_fixtures import future_fetch, future_outcome, future_period

    experiment = prepare_live_pilot(core_store, future_period(), fetch=future_fetch)
    target = core_store.get(experiment.target_version_ids[0])
    schedule_source(core_store, target.id)

    def wrong_vintage(request):
        response = future_outcome(request)
        payload = json.loads(response.body)
        payload[0]["object"]["vectorDataPoint"][-1]["releaseTime"] = (
            target.vintage_date[:-2] + "15T08:30"
        )
        return HttpResponse(json.dumps(payload).encode(), request.url)

    force_due(core_store)
    assert (
        poll_once(core_store, max_jobs=0, fetch=wrong_vintage)["status"] == "captured"
    )
    assert not tuple(core_store.iter_records("resolution"))
    force_due(core_store)
    assert (
        poll_once(core_store, max_jobs=0, fetch=future_outcome)["status"] == "resolved"
    )
    resolutions = tuple(core_store.iter_records("resolution"))
    assert len(resolutions) == 1
    assert (
        core_store.get(resolutions[0].observation_id).publication_evidence.raw_value[
            :10
        ]
        == target.vintage_date
    )
    assert public_status(core_store)["schedules"][0]["state"] == "resolved"
    assert (
        poll_once(
            core_store, max_jobs=0, fetch=lambda request: pytest.fail("extra capture")
        )["status"]
        == "idle"
    )
    assert tuple(core_store.iter_records("resolution")) == resolutions
