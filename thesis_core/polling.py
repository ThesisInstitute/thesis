"""Bounded durable official-source capture; never dispatches a forecast.

Schedules and events are operational facts, not publication/eligibility proofs.
The database clock and fenced leases control capture, independently of the
scientific job queue. A retry only repeats archived-data processing/publication.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from psycopg.types.json import Jsonb

from .contracts import SourceSeries, TargetVersion
from .store import IdentityConflict, LeaseLost

if TYPE_CHECKING:
    from .store import Store

SAFE_JOB_KINDS = ("resolve", "evaluate", "publish", "publish_run")
MAX_POLLS = 96
MAX_JOB_RETRIES = 3


def _event(connection, target_id, generation, event, error_code=None, exchanges=()):
    connection.execute(
        "INSERT INTO source_poll_events "
        "(target_id,generation,event,error_code,exchange_ids) VALUES (%s,%s,%s,%s,%s)",
        (target_id, generation, event, error_code, Jsonb(list(exchanges))),
    )


def schedule_source(
    store: Store,
    target_id: str,
    *,
    interval_seconds: int = 1800,
    max_polls: int = MAX_POLLS,
    grace_seconds: int = 86400,
) -> dict:
    """Idempotently bind one exact target to its independently parsed window."""
    from .adapters.registry import target_release_availability

    if type(interval_seconds) is not int or not 60 <= interval_seconds <= 86400:
        raise ValueError("interval_seconds must be in 60..86400")
    if type(max_polls) is not int or not 1 <= max_polls <= MAX_POLLS:
        raise ValueError("max_polls must be in 1..96")
    if type(grace_seconds) is not int or not 0 <= grace_seconds <= 172800:
        raise ValueError("grace_seconds must be in 0..172800")
    target = store.get(target_id)
    if not isinstance(target, TargetVersion):
        raise ValueError("Polling requires an exact target version")
    source = store.get(target.source_series_id)
    if not isinstance(source, SourceSeries):
        raise ValueError("Polling requires a registered source")
    boundary = target_release_availability(target, source, store.artifacts)
    if boundary is None or target.resolution_policy == "current_unverified":
        raise ValueError("Polling requires official release evidence and exact vintage")
    if store.committed_at(target.id) is None:
        raise ValueError("Polling requires an acknowledged target")
    values = {
        "target_id": target.id,
        "source_id": source.id,
        "adapter_id": source.adapter_id,
        "measurement_period": target.measurement_period,
        "vintage_date": target.vintage_date,
        "window_start": boundary.lower,
        "window_end": boundary.upper,
        "stop_at": boundary.upper + timedelta(seconds=grace_seconds),
        "interval_seconds": interval_seconds,
        "max_polls": max_polls,
    }
    with store.connection() as connection:
        inserted = connection.execute(
            "INSERT INTO source_poll_schedules "
            "(target_id,source_id,adapter_id,measurement_period,vintage_date,"
            "window_start,window_end,stop_at,interval_seconds,max_polls) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING "
            "RETURNING target_id",
            tuple(values.values()),
        ).fetchone()
        row = connection.execute(
            "SELECT * FROM source_poll_schedules WHERE target_id=%s", (target_id,)
        ).fetchone()
        if any(row[key] != value for key, value in values.items()):
            raise IdentityConflict("Target already has a different polling schedule")
        if inserted:
            connection.execute(
                "INSERT INTO source_poll_state(target_id,next_poll_at) VALUES (%s,%s)",
                (target_id, boundary.lower),
            )
            _event(connection, target_id, 0, "scheduled")
    return values


def _heartbeat(connection):
    connection.execute(
        "INSERT INTO source_poll_worker(singleton) VALUES (true) "
        "ON CONFLICT(singleton) DO UPDATE SET last_poll_at=clock_timestamp()"
    )


def claim_poll(store: Store, *, lease_seconds: int = 300) -> dict | None:
    """Claim at most one due capture, recovering abandoned leases with fencing."""
    if type(lease_seconds) is not int or not 30 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be in 30..3600")
    with store.connection() as connection:
        _heartbeat(connection)
        rows = connection.execute(
            "SELECT p.*,s.stop_at,s.max_polls,s.interval_seconds,s.source_id,"
            "s.adapter_id,s.measurement_period,s.vintage_date "
            "FROM source_poll_state p JOIN source_poll_schedules s USING(target_id) "
            "WHERE p.state='active' AND (p.lease_expires_at IS NULL OR "
            "p.lease_expires_at <= clock_timestamp()) AND "
            "(p.next_poll_at <= clock_timestamp() OR s.stop_at <= clock_timestamp()) "
            "ORDER BY p.next_poll_at,p.target_id FOR UPDATE OF p SKIP LOCKED LIMIT 100"
        ).fetchall()
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        for row in rows:
            identity, generation = row["target_id"], row["generation"]
            if row["lease_token"] is not None:
                _event(
                    connection, identity, generation, "lease_expired", "lease_expired"
                )
                connection.execute(
                    "UPDATE source_poll_state SET lease_token=NULL,"
                    "lease_expires_at=NULL,"
                    "failure_count=failure_count+1,last_error_code='lease_expired' "
                    "WHERE target_id=%s",
                    (identity,),
                )
            if now >= row["stop_at"] or row["poll_count"] >= row["max_polls"]:
                code = (
                    "outcome_overdue"
                    if now >= row["stop_at"]
                    else "poll_budget_exhausted"
                )
                connection.execute(
                    "UPDATE source_poll_state SET state='overdue',next_poll_at=NULL,"
                    "last_error_code=%s WHERE target_id=%s",
                    (code, identity),
                )
                _event(connection, identity, generation, "overdue", code)
                continue
            token = uuid.uuid4().hex
            connection.execute(
                "UPDATE source_poll_state SET lease_token=%s,lease_expires_at=%s,"
                "generation=generation+1,poll_count=poll_count+1,last_started_at=%s "
                "WHERE target_id=%s",
                (token, now + timedelta(seconds=lease_seconds), now, identity),
            )
            _event(connection, identity, generation + 1, "started")
            return {**row, "lease_token": token, "generation": generation + 1}
    return None


def finish_poll(
    store: Store,
    claim: dict,
    *,
    resolved: bool = False,
    error_code: str | None = None,
    exchange_ids=(),
) -> None:
    if error_code not in {
        None,
        "capture_failed",
        "source_unavailable",
        "resolution_invalid",
    }:
        raise ValueError("Unknown public polling error code")
    with store.connection() as connection:
        row = connection.execute(
            "SELECT p.*,s.stop_at,s.max_polls,s.interval_seconds "
            "FROM source_poll_state p JOIN source_poll_schedules s USING(target_id) "
            "WHERE p.target_id=%s AND p.lease_token=%s AND p.generation=%s "
            "AND p.lease_expires_at>clock_timestamp() FOR UPDATE OF p",
            (claim["target_id"], claim["lease_token"], claim["generation"]),
        ).fetchone()
        if row is None:
            raise LeaseLost("Source poll lease expired or was replaced")
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        state = "resolved" if resolved else "active"
        final_error = error_code
        if not resolved and (
            now >= row["stop_at"] or row["poll_count"] >= row["max_polls"]
        ):
            state = "overdue"
            final_error = (
                "outcome_overdue" if now >= row["stop_at"] else "poll_budget_exhausted"
            )
        next_poll = min(
            now + timedelta(seconds=row["interval_seconds"]), row["stop_at"]
        )
        connection.execute(
            "UPDATE source_poll_state SET state=%s,next_poll_at=%s,lease_token=NULL,"
            "lease_expires_at=NULL,last_finished_at=%s,last_success_at=CASE WHEN %s "
            "THEN %s ELSE last_success_at END,failure_count=failure_count+%s,"
            "last_error_code=%s WHERE target_id=%s",
            (
                state,
                next_poll if state == "active" else None,
                now,
                error_code is None,
                now,
                int(error_code is not None),
                final_error,
                claim["target_id"],
            ),
        )
        _event(
            connection,
            claim["target_id"],
            claim["generation"],
            "failed" if error_code else "succeeded",
            error_code,
            exchange_ids,
        )
        if state != "active":
            _event(
                connection, claim["target_id"], claim["generation"], state, final_error
            )


def _verified_resolution(store, target_id):
    from .resolution import validate_resolution

    target = store.get(target_id)
    resolutions = tuple(
        store.iter_records("resolution", links={"target_version": target_id})
    )
    if not resolutions:
        return False
    if len(resolutions) != 1:
        raise ValueError("Conflicting target resolutions")
    resolution = resolutions[0]
    if not validate_resolution(
        store, resolution, target, store.get(resolution.observation_id)
    ):
        raise ValueError("Resolution no longer validates")
    return True


def retry_followups(store: Store) -> int:
    """Atomically retry only allowed nondispatched work, three times total."""
    with store.connection() as connection:
        rows = connection.execute(
            "SELECT j.* FROM jobs j WHERE j.kind=ANY(%s) AND j.state='failed' "
            "AND j.dispatched_attempt_id IS NULL AND "
            "j.updated_at<clock_timestamp()-interval '5 minutes' AND "
            "(SELECT count(*) FROM job_events e WHERE e.job_id=j.id "
            "AND e.actor='source-poller')<%s ORDER BY j.id "
            "FOR UPDATE OF j SKIP LOCKED LIMIT 20",
            (list(SAFE_JOB_KINDS), MAX_JOB_RETRIES),
        ).fetchall()
        for row in rows:
            generation = connection.execute(
                "UPDATE jobs SET state='pending',generation=generation+1,"
                "updated_at=clock_timestamp() WHERE id=%s RETURNING generation",
                (row["id"],),
            ).fetchone()["generation"]
            connection.execute(
                "INSERT INTO job_events(job_id,event,generation,actor,reason) "
                "VALUES (%s,'retry_requested',%s,'source-poller',%s)",
                (row["id"], generation, "Bounded nonforecast follow-up retry"),
            )
    return len(rows)


def drain_followups(store: Store, *, max_jobs: int = 20) -> int:
    from .worker import work_once

    retry_followups(store)
    completed = 0
    for _ in range(max_jobs):
        result = work_once(
            store,
            worker_id="source-poller",
            kinds=SAFE_JOB_KINDS,
            timeout_seconds=30,
            recovery_kinds=SAFE_JOB_KINDS,
        )
        if result is None:
            break
        completed += 1
    return completed


def poll_once(store: Store, *, max_jobs: int = 20, fetch=None) -> dict:
    """A short timer pass: one due official capture plus bounded follow-up work."""
    from .resolution import capture_source

    if type(max_jobs) is not int or not 0 <= max_jobs <= 20:
        raise ValueError("max_jobs must be in 0..20")
    claim = claim_poll(store)
    status = "idle"
    if claim is not None:
        error_code, exchanges, resolved = None, (), False
        try:
            if _verified_resolution(store, claim["target_id"]):
                resolved = True
            else:
                target = store.get(claim["target_id"])
                if (
                    target.source_series_id,
                    target.measurement_period,
                    target.vintage_date,
                ) != (
                    claim["source_id"],
                    claim["measurement_period"],
                    claim["vintage_date"],
                ):
                    raise ValueError("Polling target binding changed")
                result = capture_source(
                    store,
                    claim["adapter_id"],
                    measurement_period=claim["measurement_period"],
                    release_date=(
                        date.fromisoformat(target.vintage_date)
                        if target.vintage_date
                        else None
                    ),
                    mode="live",
                    fetch=fetch,
                )
                exchanges = tuple(exchange.id for exchange in result.exchanges)
                if result.status not in {"captured", "deferred"}:
                    error_code = "source_unavailable"
        except Exception:
            # Original source exchange bytes remain archived by capture_source.
            # Public operations deliberately does not reflect exception strings.
            error_code = "capture_failed"
        if error_code is None and not resolved:
            try:
                from .resolution import resolve_target

                resolve_target(store, claim["target_id"])
                resolved = _verified_resolution(store, claim["target_id"])
            except Exception:
                error_code = "resolution_invalid"
        try:
            finish_poll(
                store,
                claim,
                resolved=resolved,
                error_code=error_code,
                exchange_ids=exchanges,
            )
            status = (
                "resolved" if resolved else ("failed" if error_code else "captured")
            )
        except LeaseLost:
            status = "lease_lost"
    return {
        "status": status,
        "target_id": claim["target_id"] if claim else None,
        "followup_jobs": drain_followups(store, max_jobs=max_jobs),
    }


def _instant(value: datetime | None):
    return (
        value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if value
        else None
    )


def public_status(store: Store) -> dict:
    """Allowlisted operations; missing migration tables raise, never mean empty."""
    with store.connection() as connection:
        rows = connection.execute(
            "SELECT p.*,s.window_start,s.stop_at,s.interval_seconds "
            "FROM source_poll_state p JOIN source_poll_schedules s USING(target_id) "
            "ORDER BY p.target_id"
        ).fetchall()
        heartbeat = connection.execute(
            "SELECT last_poll_at FROM source_poll_worker"
        ).fetchone()
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    keys = (
        "window_start",
        "stop_at",
        "next_poll_at",
        "last_started_at",
        "last_finished_at",
        "last_success_at",
    )
    schedules = [
        {
            "target_id": row["target_id"],
            "state": row["state"],
            "interval_seconds": row["interval_seconds"],
            "failure_count": row["failure_count"],
            "last_error_code": row["last_error_code"],
            **{key: _instant(row[key]) for key in keys},
        }
        for row in rows
    ]
    last = heartbeat["last_poll_at"] if heartbeat else None
    return {
        "schedules": schedules,
        "worker": {
            "last_poll_at": _instant(last),
            "status": "never_seen"
            if last is None
            else ("recent" if now - last <= timedelta(minutes=10) else "stale"),
        },
    }
