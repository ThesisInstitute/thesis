# Thesis lab preview

The lab uses the immutable experiment core to compare forecasts, inspect the
complete execution history, and follow official outcome capture. It opens at
`/lab/forecasts`; `/lab/experiments` and `/lab/agents` retain the registered
comparison cohort. `/lab/operations` shows source polling and job status.
Marketing routes and legacy records remain available during this preview.
Production publisher and host cutover require a separate release decision.

## Scientific and operational state

Forecast execution, target resolution and eligibility are separate fields. An
attempt can finish successfully while its target awaits an official release.
An unknown attempt remains visible and blocks implicit selection of a later
attempt. Missing cost and observed model identity remain unknown. CDF charts use
the original 201 points. The CDF/PDF toggle also offers an approximate density
in 40 bins. Each bin averages five adjacent CDF intervals using its endpoint
probability difference divided by its width, preserving the probability in that
bin. Wider bins reduce the noise amplified by rounded quantile coordinates;
they do not alter the stored distribution. All methods share a density scale; for
percent-valued outcomes its unit is probability per percentage point. A density
that cannot be represented at the input's numeric scale is explicitly unavailable.
Display quantiles use the named inverse-CDF method in the API. Browser code does
not calculate scientific scores.

Both chart axes use round bounds and tick intervals from the 1, 2, 2.5, 5
sequence times powers of ten, following the preferred spacing of
[Recharts `niceTicks`](https://github.com/recharts/recharts/pull/7009).
The lab renders its charts directly in SVG. Domains enclose all loaded curves
and any observed outcome; tick rounding does not round the underlying data.

Hover or tap the plot to compare every loaded method at one horizontal value.
The CDF tooltip interpolates between original points. The PDF tooltip reports
each method's own displayed bin, its density and its probability mass, with
zero outside support distinguished from an unavailable density. Tab to the chart
and use arrow keys, Home or End to inspect; Escape or the close control dismisses
the readout. Touch readouts remain after lifting the finger. Changing view,
selected runs or domain, scrolling the plot, or resizing clears inspection.

Bill analyses and conditional comparisons remain in the legacy `/bills` and
`/compare/[slug]` views. The new core does not yet register bill/provision links
or condition identities and resolutions. Numeric outcome polling does not
resolve legal conditions. Legacy scoring gates continue to exclude unregistered,
open or failed conditions. Bringing this workflow into the lab requires explicit
condition evidence and branch-gated scoring, including nonexhaustive conditions
for which neither registered branch occurs.

An experiment matrix includes the complete declared target-by-method population,
including missing, queued, failed and unknown cells. Invalid scientific evidence
stays visible with closed exclusion reasons. Missing referenced records and
structural corruption refuse the request. Scores and rankings are grouped by
experiment, with the paired denominator visible; there is no pooled agent rank.
The API does not invent an experiment hypothesis when none was registered.

`live_pilot` is a permanently unranked protocol with local timing checks. It
requires `unranked_live_pilot_v1`, full preregistration acknowledgement before
its deadline, frozen evidence, and dispatch before the information cutoff and
official outcome boundary. The sealed execution budget must fit the remaining
interval. Later publication receipts cannot promote its reward or rank. This
supports exercising the real pipeline while qualified prospective timing is
unavailable; it does not demonstrate forecasting skill.

## Prepare a live pilot

Install the locked core and development dependencies, migrate an isolated
PostgreSQL schema, and select a durable artifact directory as described in
[the core runbook](thesis-core-runbook.md). Keep these separate from legacy
publishers and fixture stores. The StatCan CPI portal parser accepts an explicit
future announcement for the requested month and validates its scoped date and
year. It does not infer a release date from cadence or an intraday clock from
convention. A date-only Toronto notice uses local midnight as its earliest
possible outcome boundary.

The packaged `thesis-core-codex` transport invokes the actual authenticated Codex
CLI and asks it for a native 201-point CDF. Use a portable launcher on PATH:

```python
#!/usr/bin/env python3
from thesis_core.codex_transport import main
raise SystemExit(main())
```

Make the launcher executable and put its directory before the installed console
entrypoint on PATH. The pilot pins both launcher and transport module bytes in
the artifact store and checks them before dispatch. Recorded argv uses a command
name, never a machine-local absolute path. Rehearse the actual transport under
`agent_subprocess_env` in a separate fixture schema before the one-shot live run.
Do not revise implementation files during an actual invocation.

```sh
thesis-core prepare-live-pilot 2026-08 \
  --argv-json '["thesis-core-codex"]'
thesis-core schedule EXPERIMENT_ID
thesis-core work --kind forecast --max-jobs 2 --timeout 120
thesis-core schedule-source TARGET_VERSION_ID
thesis-core poll-status
```

Use the period currently supported by the fetched official announcement; the
example month is not continuing authority. Preparation archives fresh history
and release evidence, rejects an already captured outcome, and fixes the cutoff
five minutes after capture. Dispatch immediately after successful preparation.
Preparation does not execute a model. The initial live pilot permits one attempt
per method and no automatic model retry. Failure remains a scientific record.

## Durable source capture

Migration 007 separates immutable schedule definitions and append-only poll
events from mutable operational lease state. A schedule binds an exact target,
source, period, vintage, official window, outer stop time, interval and budget.
Defaults are a 30-minute interval, 24-hour grace after the official window, and
at most 96 captures, including abandoned captures. Grace is operator-selected
operational metadata, not an official release claim. Schedules cannot be silently
redefined or extended after their budget expires. An operator can explicitly use
`thesis-core capture ADAPTER_ID --measurement-period PERIOD` and `thesis-core resolve` for a
later audit; the old polling deadline remains part of the operational history. Budget exhaustion or a missed stop time is overdue, never resolved.

Each timer invocation checks the database clock, claims one due capture with a
fenced lease, and captures only the bound measurement period. Repeated polls do
not re-ingest the whole observation history. A capture can retain official bytes
without a matching observation. A verified exact-vintage resolution stops routine
polling. A later explicit source audit can still invalidate ambiguous or corrected
evidence under the existing scientific rules.

The poller processes only `resolve`, `evaluate`, `publish` and `publish_run` jobs.
It never claims, enqueues or retries forecast jobs. Failed nonforecast jobs can
receive at most three automatic retries, spaced by at least five minutes and
recorded durably. Publication retries reuse the sealed run. Database leases and
the job filter make this independent of an interactive worker process.

For a persistent Linux host, adapt `deploy/thesis-lab/runtime.env.example` and
install `thesis-source-poll.service` plus its timer. Provision the `thesis` Unix
user, matching PostgreSQL peer-auth role/database, immutable application release
under `/opt/thesis`, and durable writable `/var/lib/thesis`. The timer checks once
per minute; the schedule determines when an actual source capture is due. Enable
regular database and CAS backups on that host. No production deployment is
performed by adding these templates.

For an isolated macOS preview, build the site, then run:

```sh
python scripts/thesis_lab_runtime.py install \
  --root ~/.local/share/thesis-lab-20260905
python scripts/thesis_lab_runtime.py status \
  --root ~/.local/share/thesis-lab-20260905
```

The installer starts per-user launchd jobs for a private peer-auth PostgreSQL
socket, loopback API, loopback site and one-minute poll timer. PostgreSQL retains
normal fsync durability. CAS and database files live outside the checkout. The
runtime configuration is owner-readable and contains no password. Installation
refuses existing runtime/database paths. `stop` disables and unloads only these named jobs, including across future
logins, and preserves all data. `restart` enables and starts them again. A staged
installation that stopped during service bootstrap can resume with `restart`. Preserve the checkout and its virtual
environment while the pilot depends on them.

This local installation depends on the Mac being logged in and awake. On wake,
the next timer pass catches up using the database clock. A missed outer window
remains visibly overdue. It is not an always-on production deployment. Two actual
future release cycles remain acceptance milestones after this preview; synthetic
fixture resolution tests cannot satisfy those milestones.

## API and verification

The additive read-only API uses `thesis_lab_v1` and generated Python/TypeScript
DTO schemas. Collections use bounded, validated content-ID pagination. A single
request uses one authoritative evaluation context, with score persistence disabled.
The public operations projection allowlists fields and distinguishes missing
polling infrastructure from zero schedules. Poll-worker freshness does not prove
that a forecast worker is alive.

The same-origin artifact proxy verifies an exact hash path, refuses redirects,
and returns original bytes as an attachment with `nosniff` and a hash ETag.
Downloads are atomic and capped at 32 MiB. Oversized artifacts remain archived
and report an explicit 413 rather than being truncated; they require a separate
operator retrieval path. JSON routes retain their independent 2 MiB limit.

```sh
python -m thesis_core.schema --check
python -m thesis_core.lab_schema --check
python scripts/core_postgres.py -- .venv/bin/python -m pytest tests/thesis_core -q
cd site
bun run test
bun run build
```

Real PostgreSQL is required for database acceptance. Check the actual localhost
list, comparison, matrix, attempt evidence and operations pages in the in-app
browser, including narrow screens and unavailable/empty/error states. Preserve
the approved core plan, all original source identities and all `records/**` bytes.
