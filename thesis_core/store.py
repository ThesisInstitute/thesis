"""PostgreSQL scientific records, transactional work, and fenced execution.

Scientific writes commit before their availability acknowledgements. A failed
acknowledgement raises AcknowledgementPending: it never means a model invocation
or its scientific transaction should be retried.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from importlib.resources import files
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .artifacts import ArtifactStore


class StoreError(Exception):
    pass


class RecordMissing(StoreError, KeyError):  # noqa: N818
    pass


class IdentityConflict(StoreError):  # noqa: N818
    pass


class LeaseLost(StoreError):  # noqa: N818
    pass


class AttemptBlocked(StoreError):  # noqa: N818
    pass


class AcknowledgementPending(StoreError):  # noqa: N818
    """The scientific transaction committed; only availability ack is missing."""

    def __init__(self, record_ids: Sequence[str]):
        self.record_ids = tuple(sorted(set(record_ids)))
        super().__init__(
            "Scientific transaction committed; repair_acceptances is required for "
            + ", ".join(self.record_ids)
        )


@dataclass(frozen=True)
class JobSpec:
    kind: str
    subject_id: str
    idempotency_key: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Claim:
    job_id: int
    kind: str
    subject_id: str
    payload: Mapping[str, Any]
    worker_id: str
    lease_token: str
    generation: int
    lease_expires_at: datetime


@dataclass(frozen=True)
class RecordPage:
    records: tuple[Any, ...]
    next_cursor: str | None

    @property
    def items(self) -> tuple[Any, ...]:
        return self.records


def _contracts():
    # Keep the database module out of pure contracts/canonical import paths.
    from . import contracts

    return contracts


def _claim(row: Mapping[str, Any]) -> Claim:
    return Claim(
        job_id=row["id"],
        kind=row["kind"],
        subject_id=row["subject_id"],
        payload=row["payload"],
        worker_id=row["worker_id"],
        lease_token=row["lease_token"],
        generation=row["generation"],
        lease_expires_at=row["lease_expires_at"],
    )


class Transaction:
    def __init__(self, store: Store, connection: psycopg.Connection):
        self.store = store
        self.connection = connection
        self.record_ids: set[str] = set()

    def put(self, record: Any, *, expected_id: str | None = None) -> str:
        contracts = _contracts()
        canonical = record.canonical_bytes()
        validated = contracts.parse_record(record.kind, canonical)
        digest = hashlib.sha256(canonical).hexdigest()
        if digest != record.id or (expected_id is not None and digest != expected_id):
            raise IdentityConflict("Scientific ID does not match canonical payload")
        if validated.canonical_bytes() != canonical:
            raise IdentityConflict("Scientific payload is not in its canonical form")
        if self.store.artifacts.put_bytes(canonical) != digest:
            raise IdentityConflict("Artifact store returned a conflicting identity")
        inserted = self.connection.execute(
            "INSERT INTO records(id,kind,schema_version,canonical_payload,payload) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING id",
            (
                digest,
                validated.kind,
                validated.schema_version,
                canonical,
                Jsonb(validated.canonical_payload()),
            ),
        ).fetchone()
        if inserted:
            for link in contracts.record_links(validated):
                self.connection.execute(
                    "INSERT INTO record_links "
                    "(source_id,source_kind,field_path,relation,target_id,target_kind) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        digest,
                        validated.kind,
                        link.field_path,
                        link.relation,
                        link.target_id,
                        link.target_kind,
                    ),
                )
            self._validate_relations(validated)
        else:
            previous = self.connection.execute(
                "SELECT canonical_payload FROM records WHERE id=%s",
                (digest,),
            ).fetchone()
            if previous is None or bytes(previous["canonical_payload"]) != canonical:
                raise IdentityConflict(f"Conflicting stored content for {digest}")
        self.record_ids.add(digest)
        return digest

    def _validate_relations(self, record: Any) -> None:
        # Experiments are inserted after their tasks; their paired population is
        # fixed at registration. The deferred SQL trigger repeats this invariant.
        if record.kind != "experiment":
            return
        tasks = self.connection.execute(
            "SELECT r.payload FROM record_links l JOIN records r ON r.id=l.target_id "
            "WHERE l.source_id=%s AND l.target_kind='evaluation_task'",
            (record.id,),
        ).fetchall()
        pairs = [
            (
                row["payload"].get("target_version_id"),
                row["payload"].get("forecaster_version_id"),
            )
            for row in tasks
        ]
        if len(set(pairs)) != len(pairs):
            raise IdentityConflict(
                "An experiment cannot repeat a target/forecaster pair"
            )

    def enqueue(
        self,
        kind: str,
        subject_id: str,
        payload: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str,
    ) -> int:
        if not kind or not idempotency_key:
            raise ValueError("Job kind and idempotency key are required")
        payload = dict(payload or {})
        row = self.connection.execute(
            "INSERT INTO outbox(kind,subject_id,payload,idempotency_key) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT(idempotency_key) DO NOTHING RETURNING id",
            (kind, subject_id, Jsonb(payload), idempotency_key),
        ).fetchone()
        if row is None:
            row = self.connection.execute(
                "SELECT * FROM outbox WHERE idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if (row["kind"], row["subject_id"], row["payload"]) != (
                kind,
                subject_id,
                payload,
            ):
                raise IdentityConflict(
                    "Job idempotency key already names different work"
                )
        self.connection.execute(
            "INSERT INTO outbox_delivery(outbox_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (row["id"],),
        )
        return row["id"]


class Store:
    def __init__(
        self, dsn: str, artifacts: ArtifactStore, *, schema: str | None = None
    ):
        self.dsn = dsn
        self.artifacts = artifacts
        self.schema = schema or os.environ.get("THESIS_CORE_SCHEMA", "thesis_core")
        if re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.schema) is None:
            raise ValueError("Schema must be a simple lowercase PostgreSQL identifier")

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(
            self.dsn,
            row_factory=dict_row,
            options=f"-csearch_path={self.schema}",
        ) as connection:
            yield connection

    def migrate(self) -> None:
        with self.connection() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"thesis-core:{self.schema}",),
            )
            connection.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(self.schema)
                )
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz "
                "NOT NULL DEFAULT clock_timestamp())"
            )
            migration_root = files("thesis_core.migrations")
            for resource in sorted(
                migration_root.iterdir(), key=lambda item: item.name
            ):
                if not resource.name.endswith(".sql"):
                    continue
                body = resource.read_bytes()
                digest = hashlib.sha256(body).hexdigest()
                previous = connection.execute(
                    "SELECT sha256 FROM schema_migrations WHERE name=%s",
                    (resource.name,),
                ).fetchone()
                if previous is not None:
                    if previous["sha256"] != digest:
                        raise IdentityConflict(
                            f"Applied migration changed: {resource.name}"
                        )
                    continue
                connection.execute(body.decode("utf-8"), prepare=False)
                connection.execute(
                    "INSERT INTO schema_migrations(name,sha256) VALUES (%s,%s)",
                    (resource.name, digest),
                )
            contracts = _contracts()
            for kind in contracts.LINK_SPECS:
                connection.execute(
                    "INSERT INTO record_kinds(kind) VALUES (%s) ON CONFLICT DO NOTHING",
                    (kind,),
                )
            for kind, specs in contracts.LINK_SPECS.items():
                for spec in specs:
                    expected = (
                        kind,
                        spec.field,
                        spec.relation,
                        spec.target_kind,
                        spec.many,
                        spec.required,
                    )
                    connection.execute(
                        "INSERT INTO "
                        "link_specs(kind,field,relation,target_kind,many,required) "
                        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        expected,
                    )
                    actual = connection.execute(
                        "SELECT kind,field,relation,target_kind,many,required FROM "
                        "link_specs "
                        "WHERE kind=%s AND field=%s",
                        (kind, spec.field),
                    ).fetchone()
                    if tuple(actual.values()) != expected:
                        raise IdentityConflict(
                            "Scientific link registry drift requires a migration"
                        )

    def health(self) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT current_setting('server_version') AS postgres_version, "
                "clock_timestamp() AS database_time"
            ).fetchone()
            counts = connection.execute(
                "SELECT state,count(*) AS count FROM jobs GROUP BY state"
            ).fetchall()
        return {
            "ok": True,
            "schema": self.schema,
            **row,
            "jobs": {item["state"]: item["count"] for item in counts},
        }

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        with self.connection() as connection:
            transaction = Transaction(self, connection)
            yield transaction
            connection.commit()
        if transaction.record_ids:
            try:
                self._acknowledge(transaction.record_ids)
            except Exception as exc:
                raise AcknowledgementPending(tuple(transaction.record_ids)) from exc

    def _acknowledge(self, record_ids: Sequence[str] | set[str]) -> int:
        count = 0
        with self.connection() as connection:
            for record_id in sorted(record_ids):
                row = connection.execute(
                    "INSERT INTO record_acceptances(record_id) VALUES (%s) "
                    "ON CONFLICT DO NOTHING RETURNING record_id",
                    (record_id,),
                ).fetchone()
                count += row is not None
        return count

    def repair_acceptances(self, *, limit: int = 1000) -> int:
        if limit < 1 or limit > 100000:
            raise ValueError("Repair limit must be in 1..100000")
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT r.id FROM records r LEFT JOIN record_acceptances a ON "
                "a.record_id=r.id "
                "WHERE a.record_id IS NULL ORDER BY r.id LIMIT %s",
                (limit,),
            ).fetchall()
        return self._acknowledge([row["id"] for row in rows])

    def committed_at(self, record_id: str) -> datetime | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT committed_at FROM record_acceptances WHERE record_id=%s",
                (record_id,),
            ).fetchone()
        return None if row is None else row["committed_at"]

    def put(self, record: Any, *, expected_id: str | None = None) -> str:
        with self.transaction() as transaction:
            record_id = transaction.put(record, expected_id=expected_id)
        return record_id

    def _read_record(self, row: Mapping[str, Any]) -> Any:
        canonical = bytes(row["canonical_payload"])
        if hashlib.sha256(canonical).hexdigest() != row["id"]:
            raise IdentityConflict("Stored canonical bytes do not match their ID")
        if self.artifacts.read_bytes(row["id"]) != canonical:
            raise IdentityConflict("Database and artifact canonical bytes disagree")
        record = _contracts().parse_record(row["kind"], canonical)
        if record.id != row["id"]:
            raise IdentityConflict("Parsed scientific identity changed")
        return record

    def get(self, record_id: str) -> Any:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM records WHERE id=%s", (record_id,)
            ).fetchone()
        if row is None:
            raise RecordMissing(record_id)
        return self._read_record(row)

    def list(
        self,
        kind: str | None = None,
        *,
        limit: int = 100,
        after: str | None = None,
        links: Mapping[str, str] | None = None,
    ) -> RecordPage:
        if not 1 <= limit <= 10000:
            raise ValueError("Record page limit must be in 1..10000")
        conditions = ["TRUE"]
        parameters: list[Any] = []
        if kind is not None:
            conditions.append("r.kind=%s")
            parameters.append(kind)
        if after is not None:
            conditions.append("r.id>%s")
            parameters.append(after)
        for relation, target_id in sorted((links or {}).items()):
            conditions.append(
                "EXISTS (SELECT 1 FROM record_links l WHERE l.source_id=r.id "
                "AND l.relation=%s AND l.target_id=%s)"
            )
            parameters.extend((relation, target_id))
        parameters.append(limit + 1)
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT r.* FROM records r WHERE "
                + " AND ".join(conditions)
                + " ORDER BY r.id LIMIT %s",
                parameters,
            ).fetchall()
        next_cursor = rows[limit - 1]["id"] if len(rows) > limit else None
        return RecordPage(
            tuple(self._read_record(row) for row in rows[:limit]), next_cursor
        )

    def iter_records(
        self, kind: str | None = None, *, links: Mapping[str, str] | None = None
    ) -> Iterator[Any]:
        after = None
        while True:
            page = self.list(kind, limit=1000, after=after, links=links)
            yield from page.records
            if page.next_cursor is None:
                return
            after = page.next_cursor

    def dependency_closure(
        self, record_id: str, *, include_self: bool = True
    ) -> tuple[Any, ...]:
        visited: dict[str, Any] = {}
        visiting: set[str] = set()

        def visit(identity: str) -> None:
            if identity in visiting:
                raise IdentityConflict("Scientific dependency cycle")
            if identity in visited:
                return
            visiting.add(identity)
            record = self.get(identity)
            for link in _contracts().record_links(record):
                visit(link.target_id)
            visiting.remove(identity)
            visited[identity] = record

        visit(record_id)
        return tuple(
            visited[key] for key in sorted(visited) if include_self or key != record_id
        )

    def enqueue(
        self,
        kind: str,
        subject_id: str,
        payload: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str,
    ) -> int:
        with self.transaction() as transaction:
            outbox_id = transaction.enqueue(
                kind, subject_id, payload, idempotency_key=idempotency_key
            )
        return outbox_id

    def deliver_outbox(self, *, limit: int = 100) -> int:
        if not 1 <= limit <= 10000:
            raise ValueError("Outbox delivery limit must be in 1..10000")
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT o.* FROM outbox_delivery d JOIN outbox o ON o.id=d.outbox_id "
                "WHERE d.delivered_at IS NULL ORDER BY o.id FOR UPDATE OF d SKIP "
                "LOCKED LIMIT %s",
                (limit,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "INSERT INTO "
                    "jobs(outbox_id,idempotency_key,kind,subject_id,payload) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(outbox_id) DO NOTHING",
                    (
                        row["id"],
                        row["idempotency_key"],
                        row["kind"],
                        row["subject_id"],
                        Jsonb(row["payload"]),
                    ),
                )
                connection.execute(
                    "UPDATE outbox_delivery SET delivered_at=clock_timestamp() "
                    "WHERE outbox_id=%s",
                    (row["id"],),
                )
        return len(rows)

    @staticmethod
    def _seconds(seconds: float) -> float:
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not 0 < seconds <= 86400
        ):
            raise ValueError("Lease seconds must be positive and at most one day")
        return float(seconds)

    def claim(
        self,
        worker_id: str,
        kinds: Sequence[str] | None = None,
        *,
        lease_seconds: float = 60,
    ) -> Claim | None:
        lease_seconds = self._seconds(lease_seconds)
        if not worker_id:
            raise ValueError("Worker identity is required")
        if kinds is not None and not kinds:
            return None
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE state='pending' "
                + ("AND kind=ANY(%s) " if kinds is not None else "")
                + "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1",
                (list(kinds),) if kinds is not None else (),
            ).fetchone()
            if row is None:
                return None
            row = connection.execute(
                "UPDATE jobs SET "
                "state='leased',worker_id=%s,lease_token=%s,generation=generation+1,"
                "lease_expires_at=clock_timestamp()+(%s * interval '1 "
                "second'),updated_at=clock_timestamp() "
                "WHERE id=%s RETURNING *",
                (worker_id, uuid.uuid4().hex, lease_seconds, row["id"]),
            ).fetchone()
        return _claim(row)

    @staticmethod
    def _fence(connection: psycopg.Connection, claim: Claim) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM jobs WHERE id=%s FOR UPDATE", (claim.job_id,)
        ).fetchone()
        valid = row is not None and (
            row["state"] == "leased"
            and row["worker_id"] == claim.worker_id
            and row["lease_token"] == claim.lease_token
            and row["generation"] == claim.generation
        )
        if valid:
            valid = connection.execute(
                "SELECT lease_expires_at>clock_timestamp() AS valid FROM jobs "
                "WHERE id=%s",
                (claim.job_id,),
            ).fetchone()["valid"]
        if not valid:
            raise LeaseLost(f"Job {claim.job_id} no longer belongs to this live lease")
        return row

    def heartbeat(self, claim: Claim, *, lease_seconds: float = 60) -> Claim:
        lease_seconds = self._seconds(lease_seconds)
        with self.connection() as connection:
            self._fence(connection, claim)
            row = connection.execute(
                "UPDATE jobs SET lease_expires_at=clock_timestamp()+(%s * interval "
                "'1 second'),"
                "updated_at=clock_timestamp() WHERE id=%s RETURNING *",
                (lease_seconds, claim.job_id),
            ).fetchone()
        return _claim(row)

    def start_attempt(
        self, claim: Claim, task_id: str, factory: Callable[[int, datetime], Any]
    ) -> Any:
        """Commit dispatch intent before returning; only then may a model run.

        The callback is pure and must preserve the allocated task/sequence/time.
        A crash after this method, even before process creation, is conservatively
        unknown. Observable spawn errors may finish as failed under a valid lease.
        """
        with self.transaction() as transaction:
            connection = transaction.connection
            job = self._fence(connection, claim)
            if task_id != job["subject_id"] or job["dispatched_attempt_id"] is not None:
                raise AttemptBlocked("Claim does not name an unstarted task")
            task_row = connection.execute(
                "SELECT payload FROM records WHERE id=%s AND kind='evaluation_task'",
                (task_id,),
            ).fetchone()
            if task_row is None:
                raise RecordMissing(task_id)
            connection.execute(
                "INSERT INTO task_attempt_counters(task_id,next_sequence) VALUES "
                "(%s,1) ON CONFLICT DO NOTHING",
                (task_id,),
            )
            counter = connection.execute(
                "SELECT next_sequence FROM task_attempt_counters WHERE task_id=%s "
                "FOR UPDATE",
                (task_id,),
            ).fetchone()
            unresolved = connection.execute(
                "SELECT 1 FROM attempt_allocations a JOIN jobs j ON j.id=a.job_id "
                "WHERE a.task_id=%s AND j.state IN ('leased','unknown') LIMIT 1",
                (task_id,),
            ).fetchone()
            if unresolved:
                raise AttemptBlocked("An earlier task attempt is unresolved")
            sequence = counter["next_sequence"]
            maximum = task_row["payload"].get("max_attempts", 1)
            if sequence > maximum:
                raise AttemptBlocked(
                    "The registered maximum number of attempts is exhausted"
                )
            now = connection.execute("SELECT clock_timestamp() AS now").fetchone()[
                "now"
            ]
            attempt = factory(sequence, now)
            if (
                attempt.kind,
                attempt.task_id,
                attempt.sequence,
                attempt.started_at,
            ) != (
                "attempt",
                task_id,
                sequence,
                now,
            ):
                raise IdentityConflict(
                    "Attempt factory changed its allocated identity or timestamp"
                )
            transaction.put(attempt)
            connection.execute(
                "INSERT INTO "
                "attempt_allocations(attempt_id,task_id,sequence,job_id) VALUES "
                "(%s,%s,%s,%s)",
                (attempt.id, task_id, sequence, claim.job_id),
            )
            connection.execute(
                "UPDATE task_attempt_counters SET next_sequence=next_sequence+1 "
                "WHERE task_id=%s",
                (task_id,),
            )
            self._fence(connection, claim)
            connection.execute(
                "UPDATE jobs SET "
                "dispatched_attempt_id=%s,updated_at=clock_timestamp() WHERE id=%s",
                (attempt.id, claim.job_id),
            )
            connection.execute(
                "INSERT INTO attempt_events(attempt_id,event) VALUES (%s,'started')",
                (attempt.id,),
            )
        return attempt

    def finish(
        self,
        claim: Claim,
        *,
        outcome: str,
        records: Sequence[Any] = (),
        followups: Sequence[JobSpec] = (),
    ) -> None:
        if outcome not in {"succeeded", "failed"}:
            raise ValueError("Live completion outcome must be succeeded or failed")
        with self.transaction() as transaction:
            connection = transaction.connection
            job = self._fence(connection, claim)
            attempt_id = job["dispatched_attempt_id"]
            result = None
            run = None
            for record in records:
                if record.kind in {"attempt_result", "forecast_run"}:
                    if attempt_id is None or record.attempt_id != attempt_id:
                        raise IdentityConflict("Completion references another attempt")
                    if record.kind == "attempt_result":
                        if result is not None or record.outcome != outcome:
                            raise IdentityConflict(
                                "Completion has conflicting attempt results"
                            )
                        result = record
                    else:
                        if run is not None:
                            raise IdentityConflict("Completion has multiple forecasts")
                        run = record
            if outcome == "failed" and run is not None:
                raise IdentityConflict("A failed attempt cannot publish a forecast")
            if attempt_id and result is None:
                now = connection.execute("SELECT clock_timestamp() AS now").fetchone()[
                    "now"
                ]
                result = _contracts().AttemptResult(
                    attempt_id=attempt_id,
                    outcome=outcome,
                    recorded_at=now,
                    completed_at=now,
                    run_id=run.id if run else None,
                )
            for record in records:
                transaction.put(record)
            if result is not None:
                transaction.put(result)
            for followup in followups:
                transaction.enqueue(
                    followup.kind,
                    followup.subject_id,
                    followup.payload,
                    idempotency_key=followup.idempotency_key,
                )
            self._fence(connection, claim)
            if attempt_id is not None:
                connection.execute(
                    "INSERT INTO attempt_events(attempt_id,event,result_id) VALUES "
                    "(%s,%s,%s)",
                    (attempt_id, outcome, result.id),
                )
            connection.execute(
                "UPDATE jobs SET "
                "state=%s,worker_id=NULL,lease_token=NULL,lease_expires_at=NULL,"
                "updated_at=clock_timestamp() WHERE id=%s",
                ("complete" if outcome == "succeeded" else "failed", claim.job_id),
            )

    def recover_expired(self) -> dict[str, int]:
        counts = {"requeued": 0, "unknown": 0}
        with self.transaction() as transaction:
            connection = transaction.connection
            rows = connection.execute(
                "SELECT * FROM jobs WHERE state='leased' AND "
                "lease_expires_at<=clock_timestamp() "
                "ORDER BY id FOR UPDATE SKIP LOCKED",
            ).fetchall()
            for row in rows:
                attempt_id = row["dispatched_attempt_id"]
                state = "pending"
                if attempt_id:
                    state = "unknown"
                    now = connection.execute(
                        "SELECT clock_timestamp() AS now"
                    ).fetchone()["now"]
                    result = _contracts().AttemptResult(
                        attempt_id=attempt_id,
                        outcome="unknown",
                        recorded_at=now,
                    )
                    transaction.put(result)
                    connection.execute(
                        "INSERT INTO attempt_events(attempt_id,event,result_id) "
                        "VALUES (%s,'unknown',%s)",
                        (attempt_id, result.id),
                    )
                connection.execute(
                    "UPDATE jobs SET "
                    "state=%s,worker_id=NULL,lease_token=NULL,lease_expires_at=NULL,"
                    "updated_at=clock_timestamp() WHERE id=%s",
                    (state, row["id"]),
                )
                counts["unknown" if attempt_id else "requeued"] += 1
        return counts

    def reconcile_unknown(
        self,
        job_id: int,
        *,
        actor: str,
        reason: str,
        evidence_hashes: Sequence[str] = (),
    ) -> Any:
        """Accept one evidenced terminal reconciliation, never an implicit retry.

        This release atomically saves successful runs and finishes their jobs, so
        an unknown attempt has no previously fenced sealed candidate. Consequently
        artifact-only success reconciliation is deliberately unavailable here.
        Reconciliation records failure for selection, retaining the unknown
        execution history. This does not claim that the model never executed.
        Caller-supplied/orphaned artifacts cannot introduce a replacement result.
        """
        with self.transaction() as transaction:
            connection = transaction.connection
            job = connection.execute(
                "SELECT * FROM jobs WHERE id=%s FOR UPDATE", (job_id,)
            ).fetchone()
            if job is None or job["state"] != "unknown":
                raise AttemptBlocked("Only an unresolved unknown job can be reconciled")
            previous = connection.execute(
                "SELECT result_id FROM attempt_events WHERE attempt_id=%s AND "
                "event='unknown'",
                (job["dispatched_attempt_id"],),
            ).fetchone()
            if not actor.strip() or not reason.strip():
                raise ValueError("Reconciliation requires an actor and reason")
            for digest in evidence_hashes:
                self.artifacts.read_bytes(digest)
            now = connection.execute("SELECT clock_timestamp() AS now").fetchone()[
                "now"
            ]
            result = _contracts().AttemptResult(
                attempt_id=job["dispatched_attempt_id"],
                outcome="failed",
                recorded_at=now,
                reconciles_result_id=previous["result_id"],
                reconciliation_method="no_sealed_result",
                reconciled_by=actor,
                reconciliation_reason=reason,
                reconciliation_evidence_hashes=tuple(evidence_hashes),
            )
            transaction.put(result)
            connection.execute(
                "INSERT INTO attempt_events(attempt_id,event,result_id) VALUES "
                "(%s,'reconciled',%s)",
                (result.attempt_id, result.id),
            )
            connection.execute(
                "UPDATE jobs SET state='failed',updated_at=clock_timestamp() WHERE "
                "id=%s",
                (job_id,),
            )
        return result

    def jobs(self, *, state: str | None = None) -> tuple[dict[str, Any], ...]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs "
                + ("WHERE state=%s " if state is not None else "")
                + "ORDER BY id",
                (state,) if state is not None else (),
            ).fetchall()
        return tuple(rows)

    def job(self, job_id: int) -> dict[str, Any] | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE id=%s", (job_id,)
            ).fetchone()

    def retry_job(
        self, job_id: int, *, actor: str = "operator", reason: str = "Explicit retry"
    ) -> dict[str, Any]:
        """Retry only failed work that never committed model dispatch intent."""
        if not actor.strip() or not reason.strip():
            raise ValueError("Retry requires an actor and reason")
        with self.connection() as connection:
            job = connection.execute(
                "SELECT * FROM jobs WHERE id=%s FOR UPDATE", (job_id,)
            ).fetchone()
            if (
                job is None
                or job["state"] != "failed"
                or job["dispatched_attempt_id"] is not None
            ):
                raise AttemptBlocked("Only a failed job without dispatch can retry")
            row = connection.execute(
                "UPDATE jobs SET state='pending',generation=generation+1,"
                "updated_at=clock_timestamp() WHERE id=%s RETURNING *",
                (job_id,),
            ).fetchone()
            connection.execute(
                "INSERT INTO job_events(job_id,event,generation,actor,reason) "
                "VALUES (%s,'retry_requested',%s,%s,%s)",
                (job_id, row["generation"], actor, reason),
            )
        return row

    def job_events(self, job_id: int) -> tuple[dict[str, Any], ...]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM job_events WHERE job_id=%s ORDER BY id", (job_id,)
            ).fetchall()
        return tuple(rows)

    def attempt_events(self, attempt_id: str) -> tuple[dict[str, Any], ...]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM attempt_events WHERE attempt_id=%s ORDER BY id",
                (attempt_id,),
            ).fetchall()
        return tuple(rows)

    def log_publication_attempt(
        self,
        manifest_id: str,
        request_hash: str | None = None,
        response_hash: str | None = None,
        error_hash: str | None = None,
    ) -> int:
        if response_hash is None and error_hash is None:
            raise ValueError("Publication attempt needs a response or archived error")
        for digest in (request_hash, response_hash, error_hash):
            if digest is not None:
                self.artifacts.read_bytes(digest)
        with self.connection() as connection:
            row = connection.execute(
                "INSERT INTO publication_attempts "
                "(manifest_id,request_hash,response_hash,error_hash) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (manifest_id, request_hash, response_hash, error_hash),
            ).fetchone()
        return row["id"]

    def publication_attempts(self, manifest_id: str) -> tuple[dict[str, Any], ...]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM publication_attempts WHERE manifest_id=%s ORDER BY id",
                (manifest_id,),
            ).fetchall()
        return tuple(rows)
