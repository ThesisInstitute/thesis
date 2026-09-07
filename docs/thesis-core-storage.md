# Thesis core storage and recovery

The core stores scientific records in PostgreSQL and exact bytes in a local
content-addressed artifact directory. PostgreSQL 14 is the minimum supported
version; CI runs the same database suite on PostgreSQL 14 and 16. This branch
does not migrate public historical records or replace the existing publishers.

Run the real database acceptance tests in a disposable private-socket cluster:

```sh
uv run --frozen --extra core --extra dev python scripts/core_postgres.py -- \
  uv run --frozen --extra core --extra dev --extra custody \
  pytest tests/thesis_core -q
```

The helper uses installed `initdb`, `pg_ctl` and `createdb` binaries, creates an
isolated database, sets `THESIS_CORE_TEST_DSN`, `THESIS_CORE_DSN` and
`THESIS_CORE_REQUIRE_POSTGRES=1` for the child command, then stops and removes
the cluster. It opens no TCP listener. Supply `--pg-bin /path/to/postgres/bin`
when the binaries are not on PATH. PostgreSQL cannot initialize a cluster as
root; run the helper as an ordinary local user.

For an existing database, set `THESIS_CORE_TEST_DSN` to its connection URI and
`THESIS_CORE_REQUIRE_POSTGRES=1` before running the test command. Missing or
unreachable PostgreSQL is a hard test failure with that flag. Without it, the
database tests skip with setup instructions; skipped tests do not establish
database acceptance. Each test creates and removes its own schema.

## Records and artifacts

`LocalArtifactStore(root)` provides `put_bytes(data)`, `read_bytes(sha256)` and
`exists(sha256)`. Writes install complete files atomically without replacing an
existing object. Reads verify SHA-256 and reject symlinks. `exists` checks
presence and file type; callers needing verified bytes must use `read_bytes`.
Media type, response headers and other contextual metadata belong in the
scientific record. Aborted database transactions may leave harmless orphan
artifacts; artifact presence alone never establishes a completed forecast.

`Store(dsn, artifacts, schema=...)` defaults to `THESIS_CORE_SCHEMA` or
`thesis_core`. `migrate()` loads packaged SQL migrations, checks their hashes,
and seeds the strict contracts registry. It is safe to call repeatedly.

Scientific rows include exact canonical bytes, their full SHA-256 identity and
queryable JSON. PostgreSQL verifies byte/hash and JSON agreement. Typed foreign
keys and deferred constraints require the precise dependency links declared by
the model registry; scientific updates and deletes are rejected. An experiment
cannot reuse another experiment's task or repeat a target/forecaster pair.
Attempt rows require an atomically allocated sequence, and forecast/result rows
require the matching terminal execution event.

`put(record)` is idempotent for identical content. Use `transaction()` to commit
several records plus `enqueue(...)` outbox entries together. Outbox delivery and
job creation share one transaction; duplicate delivery creates no extra job,
and reusing an idempotency key for different work raises `IdentityConflict`.

`get`, paginated `list(kind, limit=..., after=..., links=...)`, and
`iter_records(kind, links=...)` read verified typed records. `RecordPage.records`
and its `items` alias contain the page; `next_cursor` is explicit. Scientific
cohort consumers must use complete iteration, not assume one page is complete.
`dependency_closure(id)` returns the full graph in deterministic ID order.

## Availability acknowledgement

Scientific timestamps supplied by collectors cannot establish when a database
write became available. After a scientific transaction successfully commits,
the store starts a separate acknowledgement transaction. A database trigger
assigns `clock_timestamp()` and refuses acknowledgement in the transaction that
created the record. It ignores a caller-supplied acknowledgement timestamp.

`committed_at(record_id)` returns that conservative postcommit upper bound or
`None`. Missing acknowledgements remain unavailable to cutoff-sensitive
consumers, including when the payload contains authenticated publication times.

If the scientific commit succeeds and acknowledgement fails, the store raises
`AcknowledgementPending`, whose `record_ids` identifies the durable records.
**Do not rerun the model or write a compensating failed result.** The records and
job completion already committed. Call `repair_acceptances()` to acknowledge
missing rows at a fresh database time. Repair never backdates the original
capture, and repeated repair is idempotent.

## Attempts and job recovery

`claim(worker_id, kinds, lease_seconds=...)` uses `FOR UPDATE SKIP LOCKED` and
returns a lease token, generation and database expiry. Heartbeats and completion
check all three under a row lock. Worker-local clocks cannot extend a lease.

`start_attempt(claim, task_id, factory)` allocates the next durable per-task
sequence, validates the factory's task/sequence/start time, and commits the
attempt plus dispatch intent before returning. The factory receives
`(sequence, started_at)` and must be pure. **Invoke the model only after this
method returns successfully.** Even a crash immediately before process creation
is conservatively unknown once dispatch intent has committed. An observed
spawn failure can finish as failed while the lease remains valid.

`finish(claim, outcome=..., records=..., followups=...)` commits the run, result,
terminal event and follow-up outbox work together. A stale worker raises
`LeaseLost` and cannot finalize. `recover_expired()` requeues jobs with no
dispatch intent; dispatched jobs receive an immutable unknown result and cannot
be automatically executed again. An unresolved earlier attempt blocks later
attempt creation and selection.

`reconcile_unknown(job_id, actor=..., reason=..., evidence_hashes=...)` is
mechanical and terminal. This release saves successful runs and job completion
atomically, so an unknown job has no separately committed sealed candidate.
Reconciliation therefore records `failed` with `no_sealed_result` for selection,
while retaining the unknown execution history. It does not assert nonexecution.
The caller cannot supply a forecast or choose success. Late orphan artifact
uploads may be recorded as audit evidence but cannot establish a successful
attempt. A second reconciliation refuses. Evaluation separately excludes a
selection that depended on late or ambiguously timed reconciliation.

Publication retries use the same manifest and never rerun its model. The
append-only `log_publication_attempt` audit records verified request/response or
error artifact hashes and database time; `publication_attempts(manifest_id)`
reads the history. These records describe transport attempts, not trusted
timestamp proofs.

`retry_job(job_id, actor=..., reason=...)` explicitly reopens only a failed job
that never committed dispatch intent. This handles a repaired pre-dispatch
problem or a failed publication request. It increments the fencing generation
and appends an immutable operational retry audit. Completed, pending, leased,
unknown and previously dispatched jobs refuse this operation. A failed model
attempt requires a newly scheduled attempt within the original task maximum.

The read API can use `health()`, `jobs(state=...)` and
`attempt_events(attempt_id)` for operational status. Those mutable job
projections are distinct from immutable scientific history.

## Installed distribution verification

```sh
uv build --wheel
python scripts/smoke_packaged_install.py dist/brier-0.2.4-py3-none-any.whl
```

The smoke installs the built wheel into a clean temporary environment and runs
outside the checkout without `PYTHONPATH`. Before adding extras it imports the
shared custody/canonical/parser primitives and verifies bundled public trust
assets without Pydantic, PostgreSQL or HTTP dependencies. It then installs the
core extra and exercises the installed CLI, schema module and migration assets,
alongside the existing Brier CLI setup checks. The dedicated custody CI job
also invokes absolute script paths with `-S -E`, so an editable installation
cannot conceal a broken checkout bootstrap.
