# Running the Thesis core locally

The core runs alongside the existing publisher. These commands use a separate
PostgreSQL schema and content-addressed artifact directory. They do not migrate
or rewrite `records/`, replace scheduled publishers, or deploy the site.

## Install and initialize

From the repository checkout:

```sh
uv sync --locked --extra core --extra custody --extra dev
source .venv/bin/activate
export THESIS_CORE_DSN='postgresql://thesis_core@localhost/thesis_core'
export THESIS_CORE_SCHEMA='thesis_core'
export THESIS_CORE_ARTIFACTS="$PWD/.thesis-core/artifacts"
uv run --frozen --extra core thesis-core init
uv run --frozen --extra core thesis-core health
```

Use an existing authorized PostgreSQL 14+ database and its actual connection
configuration. The example DSN assumes a local database/user already exists;
`init` applies migrations inside the schema. `--dsn`, `--schema` and
`--artifacts` override those variables and go before the subcommand. Keep the
same CAS directory when reopening a schema: database records reference its
immutable bytes. Do not put credentials in recorded model arguments. Registration
refuses credential-shaped flags in either `--api-key=value` or separate
`--api-key value` form; use the authenticated transport's existing credential
mechanism instead.

The package is included in the existing `brier` distribution. `uv build --wheel`
builds its wheel, including migrations, generated schemas and trust assets.
Install that wheel with the `core` extra to use the `thesis-core` command outside
a checkout. The generic core does not import legacy scripts; only the explicit
legacy import command below needs a separately trusted checkout.

To run acceptance tests against a temporary real database:

```sh
uv run --frozen --extra core --extra dev python scripts/core_postgres.py -- \
  uv run --frozen --extra core --extra custody --extra dev pytest tests/thesis_core -q
```

This helper needs installed PostgreSQL binaries; `--pg-bin /path/to/bin` selects
them explicitly. It creates an isolated private Unix socket and removes the
temporary cluster after the test command exits.

## Capture official observations

```sh
thesis-core sources
thesis-core capture abs-labour-unemployment
thesis-core capture statcan-cpi-yoy
thesis-core capture bea-fixed-investment \
  --measurement-period 2026-Q2 --release-date 2026-07-30
```

`sources` prints each exact binding and content ID. A capture reports its status,
exchange IDs, observation IDs and any refusal. Successful response bytes are
archived before parsing, and the capture service commits exchanges even when
parsing or a later request fails. Each invocation handles one source.

ABS captures currently provide values without authenticated publication timing.
They remain `current_unverified`; HTTP Date is never substituted. StatCan CPI
uses the current and prior-year index and their publication fields. BEA binds
the exact table, row, units, quarter and revision date to the advance release.
The live iTable advances to later revisions, so fetching an old advance vintage
afterward correctly refuses; the archived July 30 fixture supports replay of
that vintage. The `--release-date` option alone is not publication evidence.

## Register future targets and other records

The BEA official release calendar supports future target registration:

```sh
thesis-core release-evidence bea-fixed-investment 2026-Q3
thesis-core register --kind target_version target.json
```

`release-evidence` archives the official ICS response and returns its exchange
ID and `release_evidence` JSON. The versioned parser matches the exact quarter's
GDP advance title and UTC `DTSTART`, not file-generation `DTSTAMP`. Use the
returned evidence in a target with the registered source ID, `YYYY-QN`
measurement period, `usd_billions` unit, explicit `fixed_vintage` policy and
`vintage_date`, and an aware submission deadline strictly before release.
Unsupported or missing calendar formats refuse rather than infer a cadence.

`register --kind KIND FILE` validates the strict scientific record and commits
its exact canonical ID; `--expected-id HASH` additionally pins the expected
identity. Schema definitions are in `thesis_core/schemas/records.json` and
`thesis-core serve` exposes OpenAPI at `/docs`. `thesis-core artifact FILE`
archives bytes and prints the hash for prompt/policy artifacts. Native records
use full content IDs for their references; display labels are not identities.

## Run an explicitly retrospective experiment

This prepares a real StatCan capture, uses its latest available period as the
target, freezes at least three eligible earlier observations, and registers a
persistence baseline with a fixed comparison set and normalization:

```sh
thesis-core prepare-replay
```

Copy the returned IDs into the commands below:

```sh
thesis-core schedule EXPERIMENT_ID
thesis-core work --kind forecast --max-jobs 2
thesis-core work --kind resolve --kind evaluate --max-jobs 20
```

The selected historical values alone become model input. Custody bodies may
also contain later observations and are not model evidence. The pilot's
historical cutoff is before the target's authenticated release boundary, but
the actual bundle freeze occurs afterward and is displayed separately. This
remains replay regardless of how convincing its forecasts appear. ABS's unknown
historical timing and BEA's single-quarter fixture cannot satisfy this helper's
history requirements.

Registration, captures and sealed results queue resolution/evaluation work
automatically. The worker resolves only a source-verified candidate matching
the exact target, then scores the affected experiment. Repeated deliveries
preserve one resolution per target. `resolve TARGET_ID` and `evaluate
EXPERIMENT_ID` remain available for explicit inspection; they are not required
between normal capture and worker commands. `repair` reconstructs missed
follow-ups for previously stored records without rerunning a forecaster.

To add one actual Codex model alongside the baseline, use the included
`examples/thesis_core_codex.py` stdin/JSON transport. Substitute absolute paths
to the core-installed Python, example script and authenticated Codex executable:

```sh
thesis-core prepare-replay --argv-json \
  '["/absolute/checkout/.venv/bin/python","/absolute/checkout/examples/thesis_core_codex.py","--codex","/absolute/path/to/codex"]'
```

The Codex CLI must already be authenticated. This executes the real CLI and can
consume the operator's model allowance. The model supplies all 201 CDF points;
the transport does not construct a distribution from a reported interval. The
exact argv, prompt artifacts, protocol and execution policy are frozen in the
forecaster record. The operator subprocess's access limitation is declared;
this path does not establish isolation from outside information. An optional
`--model` argument to the example pins the requested model; returned model
identity remains unknown unless actual provider metadata establishes it.

For a prospective experiment, independently witness the complete frozen cohort
before its shared information cutoff and before dispatch, then supply that
proof to `schedule --cohort-proof-id PROOF_ID`. Every attempt commits the exact
receipt hash. The run witness must also precede its submission deadline and the
earliest official first print, including when resolution uses a later revision.
The replay helper does not manufacture those prerequisites.

## Publish, verify and recover

The forecast worker queues `publish_run` work for the already sealed result:

```sh
thesis-core work --kind publish_run --max-jobs 2
```

Alternatively, inspect and publish a concrete manifest explicitly:

```sh
thesis-core manifest EXPERIMENT_ID --run-id RUN_ID
thesis-core publish MANIFEST_ID
thesis-core verify-proof PROOF_ID
```

Publishing calls a registered RFC 3161 timestamp authority. Trust anchors,
signer identity, policy, imprint and signed time are verified using the shared
custody implementation. A valid receipt without signed accuracy has unknown
ordering bounds; `verify-proof` can report `valid: true, ordered: false`. That
receipt does not establish the strict ordering needed for a prospective rank.
Replay stays unranked even when its later receipt verifies.

```sh
thesis-core jobs
thesis-core repair
thesis-core retry-job JOB_ID --actor operator --reason 'Timestamp service recovered'
thesis-core work --kind publish_run --max-jobs 1
```

`repair` restores missing post-commit acknowledgements using fresh database
time, recovers expired leases, and repairs publication, resolution and evaluation
follow-ups. It does not
backdate acceptance or rerun a model. `retry-job` accepts failed jobs that never
dispatched a model attempt, such as failed publication. It records the operator
and reason and reuses the sealed forecast/manifest. Attempt jobs require their
preregistered retry policy; unknown attempts need explicit `reconcile JOB_ID
--actor ACTOR --reason REASON --evidence-hash HASH`. Reconciliation cannot select
a newly uploaded replacement result.

## Inspect and export

```sh
thesis-core export --experiment-id EXPERIMENT_ID --as-of 2026-09-04T20:00:00Z
thesis-core serve --host 127.0.0.1 --port 8100
```

`export` includes only rewards whose entire transitive record dependency set
has a durable acknowledgement and established availability at or before the
explicit cutoff. The example timestamp is illustrative; choose the actual
as-of boundary for the analysis. A late freeze cannot enter an earlier export
merely because the outcome's publication date is historical.

The API provides read-only `/experiments`, `/tasks`, `/runs`, `/proofs`,
`/observations`, `/resolutions`, `/pending`, `/rewards`, `/leaderboard` and exact
`/records/HASH` reads. Collection queries use `limit` (1–100) and `after` cursors.
Configure the site's server-only `THESIS_CORE_API_URL=http://127.0.0.1:8100` and
open `/core`. The Next.js proxy has a closed read allowlist and forwards no
browser credentials; the site builds and shows an unconfigured state without
that variable. Expose the API only through the deployment's intended access
boundary; this local service has no mutation HTTP routes.

## Import a sealed legacy run

```sh
thesis-core import-legacy \
  /absolute/trusted-checkout/records/thesis-analyst/DATE/RUN \
  --trusted-checkout /absolute/trusted-checkout
```

The explicitly trusted checkout supplies the existing read-only custody
verifier. Import preserves verifier revision/code hashes, the verified root and
manifest, and every exact authenticated artifact, including the materialized
CDF. Copied bytes are checked again against the verifier-authenticated hash and
size commitments, so a file changed after verification cannot enter the import.
The result is `legacy_custody_verified`, never a new prospective claim. Source
records are not modified. The Python `import_legacy_registration` boundary also
imports exact registered-contract bytes and preserves their original semantic
content hash.
