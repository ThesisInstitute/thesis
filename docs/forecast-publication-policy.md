# Forecast publication policy

The public catalog publishes forecasts only when the server can verify a
successful archived model execution and bind the displayed result to its output.
The raw catalog and `records/**` remain an audit archive. Their presence in the
repository does not make a forecast eligible for publication or scoring.

## Publication gate

`site/src/lib/forecast-publication.ts` checks each candidate run before exposing
it on forecast pages, catalog cards, metrics, comparison pages, logs, model and
calibration pages, or public scoring exports. A candidate needs:

- An analyst archive with matching artifact byte counts and SHA-256 commitments,
  including a committed manifest or a custody root binding that manifest.
- A successful manifest and validation report for the forecast target.
- A successful, non-mock Codex command and execution receipt, with model identity
  matching the displayed metadata.
- A completed model event whose final message matches the archived raw response.
- Matching target, unit, estimate, interval, confidence, analysis, drivers,
  historical context, distribution, run time, and supported attribution metadata
  across the displayed projection and archived outputs. Documented deterministic
  distribution transforms may be reconstructed from the model output.

Paths are confined to the analyst archive; symlinks, missing artifacts, unknown
hash modes, inconsistent commitments, and unsupported execution formats fail
closed. A label such as `activity_backed`, a model name, or an artifact list alone
is insufficient.

If the original primary run fails, the most recent eligible comparison becomes
the displayed forecast. Its original run variant identity is preserved, as is
the target's original normalization cutoff. Other ineligible comparisons are
omitted. A target with no eligible run retains its URL with “No forecast
available”; its estimates, charts, and analysis are not sent to the browser.

## Withdrawn material

Hand-authored prototype reports, legacy runs without sufficient execution
receipts, failed API runs, formula fallbacks, unsupported external submissions,
and derived ensembles without constituent verification are excluded. A failed
check means the available evidence is insufficient; it does not establish that
the original work was fabricated.

Forecast API failures now emit an error and `done: { ok: false }`, without an
estimate or replacement explanation. The unimplemented current-law CTC endpoint
fails explicitly. API snapshots remain audit records, including successful
snapshots: the snapshot format does not carry the complete execution receipts
required by this gate. No records are deleted or rewritten by the withdrawal.

## Scoring and training exports

The scoring evaluator independently refuses unverified runs. Brier exports
apply publication filtering even when a caller supplies the raw catalog, so
withdrawn reports cannot survive as unresolved training examples. The existing
resolution-contract, chronology, witness, and normalization checks still apply.

A deterministic persistence baseline is a separately identified comparison, not
an agent forecast. It is eligible only when its primary forecast verifies and
the entire baseline matches a fresh reconstruction from the supplied ledger.
Changing its agent label cannot bypass these checks.

## Limits

This gate establishes internal artifact consistency and recorded successful
execution. It does not independently prove provider authorship, the accuracy of
source data, or that every tool-use claim in the model's written report actually
occurred. Report code blocks are therefore labeled “Reported tool use”; the
underlying activity artifacts are the execution record. Workflow attestations,
external timestamp witnesses, source validation, and resolution contracts serve
separate purposes and remain necessary.

The publication projection is cached for a site build or server process; the
archive is treated as immutable during that lifetime. Changes to archived
records require rebuilding or restarting the site. Verification tests exercise
missing, altered, unsuccessful, mismatched, and mock artifacts without changing
committed records.
