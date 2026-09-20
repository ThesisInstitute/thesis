# Weekly claims release-window drift

Found 2026-09-20 on `origin/main` at `619cbb22`. This page records the
mechanism, the evidence, what the fix changes, every affected registration,
and the decision that is still open.

## What happened

Both weekly series, `us.dol.initial_claims.sa` and
`dol.eta.continued_claims.sa`, registered an `expectedReleaseWindow` that
moved 2 days later each week relative to the reference week. By the
2026-09-20 registration the initial-claims window for the week ending
2026-09-26 was 2026-10-13 to 2026-10-17. DOL prints that week on 2026-10-01.

The cause is two facts that are each harmless alone.

1. `scripts/roll_docket.py` copies the latest published forecast's
   `resolutionDate` into `previousTarget` for every roll.
2. `expected_release_window` in `scripts/register_targets.py` tested
   `previous.resolutionDate` before it tested `SERIES_BINDINGS`. For a
   `week_` period it set the center to `previous.resolutionDate + 7 days` and
   the window to the center plus or minus 2 days. The branch that derives
   the window from the reference week and `releaseLagDays` ran only when
   there was no previous target, which is true only for a series' first
   registration.

That chain holds its position only while each published forecast carries
the true release Thursday. The analyst chooses the published
`resolutionDate`; nothing requires the Thursday. Through the week ending
2026-08-01 the published date was the Thursday. From the initial-claims cell
for the week ending 2026-08-08 (published 2026-08-07) the published date has
equalled the registered window end. Continued claims made the same switch
at the week ending 2026-08-29. From then on each roll gives
`new end = old end + 9 days` while DOL's release moves 7 days.

`tests/test_weekly_claims_release_window.py` feeds the two live inputs to
the unmodified function and gets the two live registrations back:
2026-10-13 to 2026-10-17 for initial claims, week ending 2026-09-26, and
2026-10-05 to 2026-10-09 for continued claims, week ending 2026-09-19.

## Evidence for the release day

`AGENTS.md` forbids inferring a release date from cadence. The lag now rests
on DOL's own stated schedule. The Office of Unemployment Insurance archive
page, <https://oui.doleta.gov/unemploy/claims_arch.asp>, read 2026-09-20,
says the UI Weekly Claims news release is published each Thursday at 8:30am
Eastern, that exceptions occur when a Thursday is a federal holiday, and it
lists each off-Thursday date. It listed one: Wednesday 2026-11-25.

A reference week ends on a Saturday. The release carries the advance
initial-claims figure for the week that ended 5 days earlier and the
insured-unemployment figure for the week that ended 12 days earlier. Those
are the two `releaseLagDays` values. All 19 claims observations in the
Chronicle ledger match ALFRED's vintage on that Thursday, and none has a
value one day earlier.

The OMB schedule of principal federal economic indicators for 2026 does not
list the weekly claims release, so it is not evidence here.

## What the fix changes

- `weekly_claims_release_day(series, period)` derives the release day from
  the reference week only. A previous target is never an input.
- The `SERIES_BINDINGS` branch now runs before the previous-target branch.
- `WEEKLY_CLAIMS_RELEASE_EXCEPTIONS` holds the off-Thursday dates DOL lists.
  A Thursday that is a federal holiday and is not in the table fails
  registration closed, with a message naming the DOL page. DOL has not
  published 2027 exceptions; Veterans Day 2027 is the first Thursday that
  will need one.
- A reference week that does not end on a Saturday fails closed.
- `waivers.json` gains `weekly_claims_windows_off_schedule`, the frozen list
  of registrations whose window is not the scheduled day plus or minus 2
  days. CI fails if a registration joins it.

What the fix does not change:

- An explicit `expectedReleaseWindow` or `expectedReleaseDate` still wins.
  `rebuild_registered_target` replays a snapshot's stored window, so a retry
  of a drifted registration reproduces it byte for byte. No registration or
  record is modified.
- The corrected rule cannot rewrite a drifted registration. `roll_docket.py`
  skips a `dataPointId` that already has a registration, and
  `_may_supersede` needs a committed docket binding template, which these
  two series do not have. The unpublished week 2026-09-26 registration
  therefore keeps its 2026-10-13 window.
- `register()` is untouched. The local executor-gate commit `7f4e57c2`
  merges with this change without conflict.
- The resolver is untouched here. See the companion pull request.
- The monthly and quarterly branches of the same function still step the
  previous forecast's date forward. See the last section.

## Every registered weekly target

Scheduled release is the reference week plus the lag. The resolver's claims
leg reads the forecast's published `resolutionDate`, waits for that day,
then reads the ALFRED vintage dated that day
(`pending_claims_refs` and `fred_advance_value` in
`scripts/resolve_pending.py`). It never reads the window. DOL revises each
week's figure in the next release, 7 days later.

| Target | Registered window | Scheduled release | Window holds it | Published `resolutionDate` | What the resolver does |
| --- | --- | --- | --- | --- | --- |
| initial, week 2026-07-11 to 2026-08-08 (5 weeks) | centered | Thursday | yes | Thursday, then 2026-08-15 | Resolved. Advance print. |
| initial, week 2026-08-15 | 08-20 to 08-24 | 08-20 | yes, off center | 08-24 | Resolved 206.0. Advance print. |
| initial, week 2026-08-22 | 08-29 to 09-02 | 08-27 | **no** | 09-02 | In the ledger: 203.0, advance. One day before the 09-03 revision to 204.0. |
| initial, week 2026-08-29 | 09-07 to 09-11 | 09-03 | **no** | 09-11 | Due now. Reads vintage 09-11 and records **207.0, the revised figure**. The advance print was 206.0. |
| initial, week 2026-09-05 | 09-16 to 09-20 | 09-10 | **no** | 09-20 | Due now. Reads the revised vintage. The value is 206.0 in both vintages. |
| initial, week 2026-09-12 | 09-25 to 09-29 | 09-17 | **no** | 09-29 | Waits 12 days, then reads a vintage after the 09-24 revision. Advance print was 196.0. |
| initial, week 2026-09-19 | 10-04 to 10-08 | 09-24 | **no** | 10-08 | Waits 14 days, then reads a vintage after the 10-01 revision. |
| initial, week 2026-09-26 | 10-13 to 10-17 | 10-01 | **no** | not yet published | If the forecast carries the window end, waits 16 days and reads a vintage after two later releases. |
| continued, week 2026-07-11 to 2026-08-29 (8 weeks) | centered | Thursday | yes | Thursday, then 2026-09-12 | Resolved or due. Advance print. |
| continued, week 2026-09-05 | 09-17 to 09-21 | 09-17 | yes, off center | 09-21 | Reads vintage 09-21. Advance print, 1.730. |
| continued, week 2026-09-12 | 09-26 to 09-30 | 09-24 | **no** | 09-30 | Reads vintage 09-30. Advance print, one day before the 10-01 revision. |
| continued, week 2026-09-19 | 10-05 to 10-09 | 10-01 | **no** | 10-09 | Reads a vintage after the 10-08 revision. **Revised figure.** |

Eight registrations exclude the scheduled release day: six initial and two
continued. Two more hold it off center. Those ten are the waiver members.
Six of them resolve to a revised figure if nothing changes: initial weeks
2026-08-29 through 2026-09-26, and continued week 2026-09-19.

Values are from `alfred.stlouisfed.org/graph/alfredgraph.csv`, fetched
2026-09-20.

## The ledger so far

`ledger/official_observations.jsonl` on `codex/thesis-ledger-facts` holds 19
weekly claims observations. Each equals ALFRED's value on the scheduled
release Thursday. Each was revised the following Thursday, by 1 to 3
thousand for initial claims and 0.002 to 0.007 million for continued claims.
No revised figure has been recorded. The ledger was not changed.

No scheduled `resolve-and-rebuild` run has succeeded since 2026-08-31; every
run from 2026-09-01 through 2026-09-20 failed or was cancelled. That outage
is the only reason no revised figure has been recorded yet. Pull requests
#255 and #258, which address it, merged at 2026-09-20 19:44 UTC, so the next
scheduled run may append. Initial-claims weeks 2026-08-29 and 2026-09-05 are past
their published `resolutionDate` and would be recorded from revised
vintages on that run.

## Other code that reads the window or the late date

- `scripts/ingest_challenge_submissions.py` accepts a submission when
  `generatedAtUtc` is before `expectedReleaseWindow.start`. For the week
  ending 2026-09-26 that admits a forecast made up to 12 days after DOL
  prints the number. `challenge/inbox` holds no claims submission today.
- `scripts/strategy_targets.py` treats a target as open until its published
  `resolutionDate`. A strategy-docket dispatch between the print and that
  date would run web-search agents on a published number. None has: of 32
  claims forecast and run rows in the public log, none was generated at or
  after the scheduled print.
- `scripts/generation_tickets.py` clamps ticket expiry to the earliest
  window start. The claims series run in the scheduled lane, not the
  ticketed lane.

## Options for the registered drifted weeks

The registrations are immutable, and their content hash covers the window.
The registered `releasePolicy` is `advance_vintage`. The window and the
published `resolutionDate` disagree with that policy for six targets.

1. **Hold.** The claims leg refuses a vintage that already held the week 7
   days earlier, prints the reason, and leaves the forecast pending. Nothing
   wrong is recorded, and every other option stays open. The companion pull
   request implements this. It needs a ruling later, or the six forecasts
   stay pending.
2. **Resolve at the first vintage.** Read `advance_vintage` as the contract
   and resolve each week from the first ALFRED vintage that holds it. This
   scores the forecast against what it said it was forecasting. The
   observation's `observed_at` would precede the published
   `resolutionDate`, and splits use `resolutionDate`, so the six rows sit up
   to 16 days late in the split order. It needs resolver work and a note on
   each resolution.
3. **Resolve as registered.** Let the resolver record what the late vintage
   returns. No code. The ledger then labels revised figures as advance
   prints, in a signed append-only file, and six forecasts score against a
   number they did not forecast. Not recommended.
4. **Void.** Mark the six terminal and unscored, and re-register nothing for
   those weeks. Clean, but it discards six forecasts whose only defect is a
   date.

Recommended: option 1 now, because a recorded observation cannot be
withdrawn, then option 2. Options 2 and 4 both need the hold first.

Two smaller decisions ride along. Challenge intake could refuse claims
submissions after the scheduled print rather than the registered start. The
bind step could refuse a weekly claims contract whose window is off
schedule; that would also stop a retry of the unpublished week 2026-09-26
registration, which is a way to carry out option 4 for that week.

## The same ratchet on monthly series

The monthly and quarterly branches of `expected_release_window` still set
the center to the previous forecast's `resolutionDate` plus one month or
one quarter. Where published forecasts carry the window end, the window
moves 4 days later each month. `fns.snap.total_persons` windows start
2026-09-26, 2026-10-26, 2026-11-29, 2027-01-03, 2027-02-07.
`fns.wic.total_participation`, `treasury.mts.monthly_deficit`,
`ssa.ssi.total_recipients`, the two Statbel series and the two Eurostat
unemployment series show the same pattern. Calendar-gated adapters are not
affected, because they require an official date.

This change leaves those branches alone. There is no reviewed lag for those
series, and replacing one cadence guess with another would not satisfy
`AGENTS.md`. Most of those targets are `generic-url` registrations, which
are already waiting on a ruling.
