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
are the two `releaseLagDays` values. For all 27 weekly claims weeks in the
Chronicle ledger, the first ALFRED vintage that holds the week is that
Thursday; `test_derived_release_day_is_alfreds_first_vintage` pins the 27
dates.

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

- An explicit `expectedReleaseWindow` still wins. An explicit `expectedReleaseDate` for these two series wins only when it is DOL's scheduled day or a listed exception; any other day is refused at registration.
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

Status as of 2026-10-12, with the row appended on 2026-10-18. "First print"
is the first ALFRED vintage that holds the week, found by bisecting ALFRED
itself.

| Target | Registered window | First print | Window holds it | `resolutionDate` | Ledger row | Matches first print |
| --- | --- | --- | --- | --- | --- | --- |
| initial, weeks 2026-07-11 to 2026-08-08 | centered | Thursday | yes | Thursday, then 08-15 | advance values | yes |
| initial, week 2026-08-15 | 08-20 to 08-24 | 206.0 on 08-20 | yes, off center | 08-24 | 206.0 from vintage 08-24 | yes |
| initial, week 2026-08-22 | 08-29 to 09-02 | 203.0 on 08-27 | **no** | 09-02 | 203.0 from vintage 09-02 | yes |
| initial, week 2026-08-29 | 09-07 to 09-11 | 206.0 on 09-03 | **no** | 09-11 | **207.0** from vintage 09-11 | **no, revised** |
| initial, week 2026-09-05 | 09-16 to 09-20 | 206.0 on 09-10 | **no** | 09-20 | 206.0 from vintage 09-20 | value yes, vintage late |
| initial, week 2026-09-12 | 09-25 to 09-29 | 196.0 on 09-17 | **no** | 09-29 | **198.0** from vintage 09-29 | **no, revised** |
| initial, week 2026-09-19 | 10-04 to 10-08 | 197.0 on 09-24 | **no** | 10-08 | **198.0** from vintage 10-08 | **no, revised** |
| initial, week 2026-09-26 | 10-13 to 10-17 | 10-01 | **no** | none | expired unforecast (#303) | n/a |
| continued, weeks 2026-07-11 to 2026-08-22 | centered | Thursday | yes | Thursday | advance values | yes |
| continued, week 2026-08-29 | 09-08 to 09-12 | 1.774 on 09-10 | yes | 09-12 | 1.774 from vintage 09-12 | yes |
| continued, week 2026-09-05 | 09-17 to 09-21 | 1.730 on 09-17 | yes, off center | 09-21 | 1.730 from vintage 09-21 | yes |
| continued, week 2026-09-12 | 09-26 to 09-30 | 1.719 on 09-24 | **no** | 09-30 | 1.719 from vintage 09-30 | yes |
| continued, week 2026-09-19 | 10-05 to 10-09 | 1.701 on 10-01 | **no** | 10-09 | **1.699** from vintage 10-09 | **no, revised** |
| continued, week 2026-09-26 | 10-14 to 10-18 | 1.716 on 10-08 | **no** | 10-18 | **1.714** from vintage 10-18, appended 2026-10-18 | **no, revised** |
| continued, week 2026-10-03 | 10-23 to 10-27 | 10-15 | **no** | none | expired unforecast (`94609afb`) | n/a |

Twelve registrations are off schedule; they are the waiver members. Five
ledger rows record DOL's revised figure under the advance label. On
2026-10-12 one forecast was still pending: continued claims, week ending
2026-09-26. DOL printed it on 2026-10-08 (1.716) and revised it on
2026-10-15 (1.714). The guard had not merged when its `resolutionDate`
came, so the scheduled resolver run of 2026-10-18 (Actions run 39147142911,
on `main` at `992b15b2`) read ALFRED's 2026-10-18 vintage and appended 1.714
as Chronicle line 239 (`86da0233`).

The per-row audit, with the vintage bisection script, is kept at
`~/reviews/thesis-weekly-claims-2026-10/` (`first_vintage_audit.py`,
`first_vintage_audit.json`).

## The ledger so far

`ledger/official_observations.jsonl` on `codex/thesis-ledger-facts` held 27
weekly initial and continued claims observations on 2026-10-12. Twenty-three
equal ALFRED's first print. The four above do not. No `resolve-and-rebuild`
run has finished successfully since 2026-08-31, but a run's resolve step
appends what it resolved through a reviewed proposal before later steps
(refused rows, pin advance, site rebuild) fail it or it is cancelled. Those
appends read the late vintages. A run that fails while fetching, before
the proposal merges, appends nothing; a failure after the merge (its
verification or the proposal-ref cleanup) still leaves the rows appended. Each of the four rows carries an `assertionVersion` id and
`supersedes: null`; no superseding row exists in the ledger yet.

On 2026-10-18 a 28th was appended, the fifth that does not equal the first
print: continued claims week 2026-09-26, 1.714 from vintage 2026-10-18
(Chronicle `86da0233`, line 239,
`av2:b1c9579624a6cf93d0a0f5343c4c861a03a0637048bf689012538c05c75ed2e9`).

## Other code that reads the window or the late date

- `scripts/ingest_challenge_submissions.py` accepts a submission when
  `generatedAtUtc` is before `expectedReleaseWindow.start`, after refusing
  any expired-unforecast registration. Initial claims week 2026-09-26 is
  expired, so it is refused. Continued claims week 2026-09-26 is not: DOL
  printed it on 2026-10-08 and its window starts 2026-10-14, so a forecast
  made up to six days after the print would be admitted.
  `challenge/inbox` held no claims submission on 2026-10-12.
- `scripts/strategy_targets.py` treats a target as open until its published
  `resolutionDate`. A strategy-docket dispatch between the print and that
  date would run web-search agents on a published number. None has: on
  2026-10-12 the public log held 43 claims forecasts (23 analyst, 20
  time-series prior) and their 43 runs, and none was generated at or after
  the scheduled print.
- `scripts/generation_tickets.py` clamps ticket expiry to the earliest
  window start. The claims series run in the scheduled lane, not the
  ticketed lane.

## Decision

Max ruled on 2026-09-27 (d352): land the guard and this fix now, then
resolve the drifted weeks at the first ALFRED vintage, with a note on each
resolution. The rows above were appended after that ruling and before the
guard merged. Carrying out the ruling now means two things:

1. Every weekly claims cell resolves from its first print: ALFRED's vintage
   of DOL's scheduled release day (`weekly_claims_release_day`, exceptions
   included), confirmed by four reads. The day before must lack the week on
   two byte-identical reads; the release day must hold it; the day after
   must print the same value. The day comes from DOL's schedule, so no single
   ALFRED response can move it; a faulty response makes the cell defer. A
   release DOL makes off schedule (early or late) defers until its day is
   listed in `WEEKLY_CLAIMS_RELEASE_EXCEPTIONS`, provided ALFRED answers
   honestly on the scheduled day and the day before it. If an unlisted
   off-schedule release and a faulty ALFRED answer on one of those days
   coincide, the cell can resolve on the scheduled day: the right value,
   the wrong date. The three reads are archived with the run as
   `firstPrintEvidence`, and `verify_custody` replays them by the same
   parser the resolver uses.

   ALFRED's header names the vintage a response is, and it is not always
   the requested date. On 2026-10-18 its ICSA responses for seven of 291
   daily vintage dates in 2026, all Fridays or weekend days from
   2026-09-25, named the day before and held that day's rows; the
   2026-09-25 response is byte-identical to the 2026-09-24 one. The same
   query with its parameters reordered returned a header naming the
   requested date. A response is read as the vintage its header
   names, which must not be later than the requested date. The day before
   and the release day must each be the vintage of that very day; the day
   after may be the release day's vintage (`CLAIMS_LABEL_LAG` in
   `scripts/verify_custody.py`). A read answered with an earlier day's
   vintage than its role allows defers the week. The survey and the
   body comparison are kept at
   `~/reviews/thesis-weekly-claims-2026-10/header_survey/`.
2. The six rows read from a later release (the five above, and initial
   claims week 2026-09-05, whose value was unchanged) are corrected by
   appending first-print rows whose `assertionVersion.supersedes` names the
   replaced row's id (`CLAIMS_FIRST_PRINT_CORRECTIONS`). Chronicle's append
   gate (`receipt.append_gate.check_rows`) accepts a second row for a
   `source_record_id` only when it supersedes that id's active version, and
   its current view (`effective_current_rows`) drops the replaced row. The
   site scores the earliest `observedAt` per `dataPointId`, which is the
   correction, dated at the release day.

The guard in #344 holds a cell rather than record a revised figure until
this resolution lands.

Two smaller items stay open. Challenge intake admits a submission until
`expectedReleaseWindow.start`, which for the drifted registrations is after
DOL prints the number. And the docket roll proposes only the successor of
the latest published week, so it skips the two expired weeks on every run:
neither weekly series has registered a new week since 2026-09-28.

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
