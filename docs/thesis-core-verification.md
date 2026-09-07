# Thesis core verification

The first implementation runs locally on branch `thesis-core-20260904`, based
on `origin/main` commit `51d9fa6bbd3275d12a1988be6befdd77116b720f`.
It adds the experiment backend alongside the existing publishers. It has not
been deployed or cut over to production, and no files in `records/` were changed.

## Design review

Fable reviewed the written implementation plan through Subfleet before the
build began. The completed gate is `20260904-183206-plan-34cfc839`; its final
verdict approved SHA-256
`3b566fa29473c1fc7119ec85380717fa7c0e53a1c0d6999c9692eba5d5954519`
with no actionable plan findings. The [recorded verdict](thesis-core-plan-verdict.json)
and [review responses](thesis-core-plan-review-response.md) preserve that review.
This is plan approval, not a claim that Fable audited the resulting code.

Independent implementation reviews covered domain/publication and the
storage/worker/application boundaries. They identified missing receipt bytes in
the actual model prompt, missing automatic resolution/evaluation follow-ups,
concurrent resolution selection, malformed candidate handling and ambiguous
vintage selection. The implementation includes fixes and regressions for those
cases. A later conflicting capture automatically queues a new evaluation and
invalidates the current result while preserving the original resolution bytes.

## Acceptance checks

Local verification uses PostgreSQL 14.22 with required database tests, Python
3.14, Bun 1.3.12 and OpenSSL 3.6.3. The dedicated CI workflow also specifies
PostgreSQL 14 and 16. Both remote jobs passed on PR #228's original reviewed
head, along with the full Python CI, site, packaging and legacy compatibility
jobs. The [PR review response](thesis-core-pr-review-response.md) records the
subsequent Fable findings and fixes; the checks below describe the initial
implementation unless a later revision is stated explicitly.

- Core contracts, actual PostgreSQL concurrency/recovery, subprocess execution,
  source parsing, timestamp verification and API integration: **302 passed**.
- Relevant legacy parser, credential-hygiene and producer-signing suite:
  **193 passed**; analyst runner: **211 passed**; trust transitions and SBA
  witness compatibility: **46 passed**.
- Full site Vitest: **1,086 passed** across 35 files. The TypeScript build,
  production Next.js build and existing output-size budgets also pass.
- Generated Python/TypeScript contract drift and scoped Ruff checks pass.
- A built wheel installs and runs outside the checkout with migrations, schemas
  and trust assets. Legacy entry points also work without the core extra.
- The actual legacy record-chain verification passes: **145 snapshots and 144
  available witnesses**. Existing FreeTSA and DigiCert receipts also replay
  offline through the extracted verifier without a `records/` directory.
- A broader legacy integrity sweep exceeded its external worker runtime and
  was terminated; it is not counted as passed. The completed checks above
  separately establish the actual chain, extracted verifier and shared-entry
  compatibility results.
- The `/core` browser view was exercised against the actual API and live pilot
  database, including replay labels, distinct timing fields and unranked rows.

Reproduce the database tests with the private-cluster helper in the
[runbook](thesis-core-runbook.md); it sets the required-database flag so a
missing database cannot count as a passing acceptance run.

## PR review regression checks, September 5

At fix commit `7d90098e1846cdc4f4778a04cdb2bd32519d947b`, after applying the
confirmed Fable code-review findings:

- Complete core suite with required PostgreSQL 14.22: **371 passed** in 78.05 s.
- Security/execution plus the complete legacy environment-hygiene and analyst
  runner suites: **381 passed** in 55.68 s. This overlaps the core count.
- The custody/publication subset, including actual prospective dispatch through
  locally signed accuracy-bearing receipts: **69 passed** in 33.86 s.
- Scoped Ruff, generated-contract drift, lockfile consistency and diff checks pass.
- The wheel rebuilt and passed the installed-package smoke test outside the
  checkout, including packaged trust assets.

These regression checks used synthetic credentials, offline official fixtures
and local test authorities. They did not invoke an external model or timestamp
service. The site source was unchanged in this revision.

The subsequent execution-review follow-up preserves ordinary mixed diagnostic
logs while refusing unsafe credential fragments. It adds atomic argument,
duplicate-key and serialized-JSON regressions. The complete core suite passes
**412 tests** in 80.04 s with PostgreSQL required. Scoped Ruff, generated-contract
drift and diff checks also pass. The rebuilt wheel passes the isolated
installed-package smoke. The science,
timestamp and API implementation approved or examined at `7d90098e` is unchanged
by this follow-up.

## Recorded-output compatibility and failure handling

The final corrective revision adds pair-aware duplicate-member redaction,
explicit scalar boundaries, supported container-literal validation and safe
exception diagnostics. The complete core suite passes **546 tests** in 96.19 s
with PostgreSQL 14.22 required. The complete legacy analyst, credential-hygiene
and channel-refusal suites pass **227 tests** in 35.29 s. Scoped Ruff, formatting,
generated-contract drift and diff checks pass. The rebuilt wheel passes the
isolated installed-package smoke test.

A read-only audit processed all **2,053 recorded stdout/stderr streams**
(**374,657,368 bytes**) in 103.31 s: no refusals, **2,026 byte-identical** outputs
and no non-idempotent results. The other 27 streams were safely redacted under
the existing credential policy; the archive itself was not rewritten.

These checks cover known failures without raw-output fallback, partial
credential expressions, safe JSONL preservation and legacy channel custody.
They use synthetic credentials and local test authorities. The approved plan,
scientific formulas, prospective admission and trust-verification code remain
unchanged; the publication exception path now records bounded safe diagnostics.

## Real source and model smoke

The local pilot captured **36 official Statistics Canada CPI observations**,
registered an explicit historical experiment, and executed a persistence
baseline and the real Codex CLI transport. Each produced its original native
201-point CDF. The core archived the exact prompt, output, execution records and
code bytes, resolved the target, calculated CRPS, and obtained actual FreeTSA
receipts for both sealed runs. Reverification reads the archived receipt bytes
and committed manifest closure.

The experiment ID is
`a487b150c2a79bb0089bd6dda62231e711e5bb3cf080c6757956df7ba5898094`.
Its historical information cutoff is `2026-08-17T12:28:00Z`; the actual evidence
freeze is `2026-09-04T23:25:48.305531Z`. Those different times remain visible.

| Transport | Run ID | Raw CRPS | Observed execution latency |
| --- | --- | ---: | ---: |
| Persistence baseline | `21ffcd759ccd8d31c1fd142ecb9c9cd22371300ba762bddbc79844df1276bc96` | 0.130772308924 | 0.017444 s |
| Actual Codex CLI | `83c7e29a5eb059bbafb550b3bd092dc71980ad131cfd2335dd1b2bbcb2c672cf` | 0.132577504713 | 105.982477 s |

These numbers establish an exercised path, not forecasting skill. Both rows
have eligibility `replay`, null training reward and no prospective rank. The
CLI's provider-returned model identity and monetary cost were unavailable and
are not inferred.

Verified publication proof IDs:

- `b8106fede256420526f017eb30e28ee57d728f292fe1b725502c19eda7b3de1b`,
  signed time `2026-09-04T23:32:39Z`.
- `cf56577e2776ee00fcc6d84d1125ea7cd288ce9aa71dc518376c6260fab65ee6`,
  signed time `2026-09-04T23:32:36Z`.

Both receipts verify cryptographically but omit a signed accuracy bound.
Verification therefore returns valid but unordered. The current pinned
authorities cannot establish the strict timing interval required for a
prospective rank with these receipts. A trustworthy accuracy bound is still
needed for live prospective qualification; zero uncertainty is never assumed.

The ABS live adapter also captured 30 observations. The BEA official calendar
path retrieved future release evidence; its current table correctly refused an
old requested advance vintage that no longer matched. The three source-family
fixtures cover deterministic offline replay and refusal behavior.

## Local inspection

The pilot API is at `http://127.0.0.1:18100`, and the local production site build
is at `http://127.0.0.1:18101/core` while those processes remain running.
Its schema is `core_live_pilot`. Local artifacts and the smoke report are under
the ignored `.thesis-core/` directory. These runtime files are not part of the
commit or the production record tree.

Production provisioning, access controls, historical migration and switching
scheduled publishers remain the later release work defined in the approved
plan. The operator-subprocess transport records its access policy; it does not
prove that the subprocess was isolated from all outside information.
