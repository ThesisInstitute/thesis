# Thesis lab verification — September 5, 2026

This additive preview is stacked on the experiment core. It does not migrate
legacy records, change the Chronicle pin, or cut over a production publisher.
The operating instructions and remaining release milestones are in
[the lab runbook](thesis-lab.md).

## Automated checks

The final implementation passed 616 core tests with required, real PostgreSQL,
219 legacy analyst/environment tests, and all 1,161 site tests. The production
Next.js build completed with 1,760 static pages. After moving the generated lab
JSON schema inside the site build root, all 75 focused lab tests and the
production build passed again. The runtime installer’s three tests passed
after its asynchronous launchd unload correction.

An additional independent review found that the agent catalog counted existing
task records instead of declared cohort pairs when a pair was missing. The
projection now counts declared target memberships, while attempts still count
actual executions. All 29 lab API tests passed after this correction, including
list/detail coverage for the absent-pair fixture.

PostgreSQL 16 CI exposed an order-dependent corruption fixture: choosing the
first observation by content hash sometimes deleted the captured, unreferenced
target outcome instead of declared historical evidence. Independent checks
confirmed each referenced observation refuses all four projections with 409,
while the unrelated outcome correctly leaves this unresolved cohort readable.
The test now chooses exact declared dependencies and separately checks that
unreferenced-outcome case. The complete 616-test suite passed after this change;
no production integrity behavior was weakened or changed.

An independently installed wheel passed a smoke covering all 49 packaged core
files, seven migrations, 13 populated lab routes, strict errors, polling CLI,
the Codex entry point and exact binary artifacts. No model was run by this smoke.
Generated-site size budgets also passed.

Focused regression coverage includes missing transitive records and artifacts,
cross-attempt run ownership, exact-vintage and date-only overdue status,
timeout sealing, pre-spawn deadline refusal, immutable source schedules,
fenced capture leases, bounded retries, and protection of expired forecast
leases from the nonforecast poller. A 96-capture budget test verifies that
repeated period-scoped captures do not re-ingest historical observations.
The lab list took 0.143 seconds in that local maximum-budget fixture.

Both generated contract checks and scoped Ruff checks passed. The approved
core plan, all three original source identities, and the existing ledger
availability and pin artifacts were checked for byte preservation.

## Actual pilot

The isolated local PostgreSQL/CAS runtime contains one fresh, non-fixture
experiment for Canada CPI all-items year-on-year, August 2026:

- Experiment: `c14f2f2525148043af75feb72b9359890b5d70c10ef155cdd51a755b7013c598`
- Target: `596bce04ec92db9bafffb6081e6ec6566e2e148241cb67c34e9d15a5685b8f9c`
- Baseline run: `1ee042d02fe0432740781368ff5098963ac3a06b50cf89de8ac7382b737ad2e2`
- Codex run: `1fd16ed777258e028b8a45503eb0ee3d7c63bdf6629db7082958b95cce731d75`

Both methods succeeded with native 201-point CDFs. The baseline median is
3.00%, with a derived 80% interval of 2.543–3.457%; the actual Codex transport
produced a 2.95% median and 2.489–3.411% interval. Recorded elapsed times are
1.268 and 101.712 seconds. These are pipeline observations, not evidence of
forecast skill. Cost and observed model identity remain unreported.

Full traces and two verified publication proofs are retained in the local CAS.
The proofs do not establish strict temporal ordering. The experiment uses
`live_pilot` / `unranked_live_pilot_v1`; rewards and ranks remain null permanently.
No model retry was performed. A separate fixture schema was used to rehearse
the actual CLI transport before preparation of this live experiment.

Freshly captured [official StatCan release evidence](https://www.statcan.gc.ca/en/subjects-start/prices_and_price_indexes/consumer_price_indexes)
announced the August CPI release for September 14. The archived portal SHA-256
is `6da63c97fb952cfc2ae861f3eda73d924681e5d8b1391fc4bd6f71f64d1159f0`.
The date-only America/Toronto notice yields a conservative UTC interval from
September 14 at 04:00 to September 15 at 04:00. The target binds the September 14
vintage and remains unresolved. Source capture is scheduled every 30 minutes
from the lower bound, with a 96-capture maximum and September 16 at 04:00 UTC
outer stop. Budget exhaustion or a missed window remains visibly overdue.

## Runtime and browser checks

An actual stop/restart of the per-user PostgreSQL, API, site and polling jobs
preserved the rehearsal data. PostgreSQL reports `fsync=on` and accepts only
private-socket connections. The API and site listen on loopback. The timer
reports recent successful heartbeats; it makes no source request before the
scheduled release boundary.

The localhost app was inspected in the in-app browser on desktop and at a
390-pixel viewport. The empty forecast list, operations state, fresh target,
selected-cohort original-CDF comparison and detailed run evidence were checked.
The agent catalog/detail and experiment matrix links retained the correct
cohort. Temporarily unloading the loopback API produced the explicit records
unavailable state without stale results; restoring it restored the data. The
actual same-origin official-release artifact download retained its exact hash,
38,855 bytes, attachment disposition, hash ETag and `nosniff` header.

The Mac must remain logged in and awake for scheduled work. Two actual future
release cycles, qualified prospective timing, production hosting, backups and
production cutover remain separate acceptance work. No completed future
resolution is claimed by this verification.

## CDF/PDF display follow-up

The comparison now defaults to the original CDF and offers an approximate PDF
in 40 bins on one shared density axis. Each bin averages five native intervals
while preserving their probability mass. Raw adjacent slopes amplified rounded
quantile coordinates into alternating spikes in the actual CPI chart; broader
bins, a thinner outline and a light fill make its shape easier to inspect.
Seven added regressions cover integrated and per-bin probability, unequal widths and plateaus,
densities above one, numeric overflow/underflow, toggling without CDF mutation,
outcome markers, keyboard emphasis, and baseline styling. All 1,168 site tests
and the production build passed after the addition.

The rebuilt localhost preview was checked with the actual two-method CPI cohort
on desktop and at 390 pixels: both density paths contained 40 bins and
finite SVG coordinates, and switching back restored the CDF. Mobile retained
the existing horizontally scrollable chart. This display change did not run a
model, alter stored forecast artifacts, or change resolution or scoring.

## Round axis ticks

CDF and PDF axes now use outward-rounded bounds and 1, 2, 2.5, 5 tick intervals
times powers of ten. Nine regressions cover both chart views, the observed
outcome outside forecast support, negative and very small/large ranges,
floating-point noise at round bounds, and distinct labels for narrow ranges
around a large offset. All 1,177 site tests and the production build passed.

The rebuilt CPI comparison was checked on desktop and at 390 pixels. Its x ticks
are 0–5 in units of one, its PDF ticks are 0–1.25 in units of 0.25, and its CDF
ticks are 0–100% in units of 20 percentage points. Both curves retain finite SVG
coordinates. The underlying CDF points, density bins and outcome values remain
unchanged.

## Chart inspection

Chart tooltips compare all loaded methods at a shared x value. CDF readouts use
piecewise linear interpolation of the original points; PDF readouts preserve
each method's own displayed bin bounds and probability mass. Six regressions
cover interpolation and tails, bin boundaries, scaled plot coordinates,
mouse dismissal, touch persistence, keyboard changes and resets, method-specific
support, and precision for narrow ranges at large offsets. Independent review
prompted adaptive labels and exclusion of the transient close button from the
Tab order; keyboard users dismiss with Escape.

All 1,183 site tests and the production build passed. The actual CPI comparison
was inspected with mouse and native range keyboard events, including Home, End,
Escape and Tab onward to the method controls. At 390 pixels the tooltip stayed
inside the viewport while the SVG retained horizontal scrolling. Touch retention
and cancellation have automated coverage; physical touch hardware and audible
screen-reader announcements were not exercised.
