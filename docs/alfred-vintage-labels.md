# ALFRED vintage labels

ALFRED's graph CSV, `alfredgraph.csv?id=S&vintage_date=D`, answers with the
header `observation_date,S_<YYYYMMDD>`. This page calls that date the
response's label. The label is not always D, and the rows are those of the
label's vintage. This page records what was observed, which readers depend
on the label, and the rule each one applies. The code is
`scripts/alfred_vintage.py`, and the tests are
`tests/test_alfred_vintage_labels.py`.

## What ALFRED did

These were observed on 2026-10-18, between 18:59 and 19:13 UTC. The responses
are kept as test fixtures, and
`tests/fixtures/alfred_vintage_labels/captures.json` gives each request, its
time, header and SHA-256.

| Request | Label | Same bytes as |
|---|---|---|
| `id=ICSA&vintage_date=2026-09-25` | 2026-09-24 | the 2026-09-24 response |
| `vintage_date=2026-09-25&id=ICSA` | 2026-09-25 | |
| `id=PAYEMS&vintage_date=2026-09-29` | 2026-09-28 | |
| `id=PAYEMS&vintage_date=2026-10-01` | 2026-09-29 | |
| `vintage_date=2026-10-01&id=PAYEMS` | 2026-10-01 | |
| `id=PAYEMS&vintage_date=2026-10-02` | 2026-10-02 | the reordered request |
| `id=PAYEMS&vintage_date=2026-10-18` | 2026-10-17 | |
| `id=PAYEMS&vintage_date=2026-11-06&thesis_lag_probe=fixture` | 2026-10-18 | |

- **Lagged answers.** A lagged answer is one labeled earlier than the date
  asked for. The claims leg's survey that day (#345,
  `tests/fixtures/alfred_claims_vintages_2026.json`) found 7 of 291 daily ICSA
  dates in 2026 answered a day early. PAYEMS answered one and two days early.
- **The reordered spelling.** The same query with its parameters reordered
  answered with the date asked for each time it was tried.
- **Future dates.** A request for a date after the current one was answered
  with the current date's vintage, under that date's label.

On 2026-11-18 at 17:56 UTC, the canonical requests for ICSA 2026-09-25 and
PAYEMS 2026-09-29, 2026-10-01 and 2026-10-18 came back labeled with the date
asked for. These are the time, query, header, length in bytes and SHA-256
prefix of each response:

```text
2026-11-18T17:56:34Z id=ICSA&vintage_date=2026-09-25   observation_date,ICSA_20260925   56139 39b7cbb171bb7095
2026-11-18T17:56:38Z id=PAYEMS&vintage_date=2026-09-29 observation_date,PAYEMS_20260929 18396 727ac971dc221970
2026-11-18T17:56:43Z id=PAYEMS&vintage_date=2026-10-01 observation_date,PAYEMS_20261001 18396 edfb8e9337ce7f73
2026-11-18T17:56:46Z id=PAYEMS&vintage_date=2026-10-18 observation_date,PAYEMS_20261018 18414 964906a2412c3659
```

Each was byte-identical to a response seen labeled that date in October:

- ICSA 2026-09-25 matched the reordered 2026-09-25 request.
- PAYEMS 2026-09-29 matched what the 2026-10-01 request had returned.
- PAYEMS 2026-10-01 matched the reordered 2026-10-01 request.
- PAYEMS 2026-10-18 matched the probe's answer.

So a lagged answer was ALFRED's file for its label's day, not a corrupted
file, and the lag on those requests did not last a month.

**What is not known:**

- why the canonical spelling lagged;
- where ALFRED's day turns over;
- how long a lagged answer persists for one URL.

An overnight probe meant to measure the last two stopped without output. No
claim here depends on any of them.

## Readers

Inventory of `origin/main` at `06ffc9fe` (2026-11-17). Every request to
`alfred.stlouisfed.org` in the repository, excluding `records/`, is one of
these.

| Reader | What it requested | Before this change | Rule now |
|---|---|---|---|
| Generic ALFRED leg: `resolve_pending.fred_vintage_series`, for every `ALFRED_ADAPTERS` cell | The canonical spelling, at the cell's `resolutionDate` | It looked up the column `S_<D>`. A lagged answer has no such column, so the cell deferred as "not yet published", with no wrong value and no retry. | Label must equal the date asked for (`verify_custody.ALFRED_VINTAGE_LABEL_LAG = 0`). After an earlier label, it retries once in the reordered spelling, then defers as `ALFRED VINTAGE LAGGED`. A later label, or bytes that are not this series' vintage CSV, defer as `ALFRED READ FAILED`. A date after `alfred_today()` is never requested and defers as `ALFRED VINTAGE NOT REACHED`. |
| Weekly claims leg: `resolve_pending.fetch_claims_vintage` (#345) | The canonical spelling, on four days around DOL's release day | It already read the label: `read_alfred_claims_vintage` with `CLAIMS_LABEL_LAG` | Unchanged: lag 0 for the day before and the release day, lag 1 for the day after. Its header parse now calls the shared `alfred_vintage_label`. |
| `resolve_pending.fred_advance_value` | Had no callers after #345 | Dead code | Deleted |
| `ALFRED_HISTORY_MIRRORS` | Never fetched at run time | Test data | Not a reader |

Other ALFRED URLs in the tree are metadata: binding `sourceUrl`s in
`scripts/docket_series.json` and `register_targets.py`, and `claims_fact`'s
source URL. Resolver provenance (`source_binding_projection`) and the site
(`site/src/data/thesis-log.ts`) compare only a fact URL's host with the
binding's `allowedHosts`. A fact read from the reordered spelling therefore
binds as the canonical one does, and names the request that was answered.

Custody (`verify_custody._verify_resolver_alfred_labels`) replays the rule on
every resolver fact whose own archived response has an ALFRED header. The
label must equal the fact's `sourceVintage`, for the series the archive is
named after.

## Why lag 0 for the generic leg

A generic cell resolves to the period as ALFRED printed it on the cell's
`resolutionDate`. An earlier day's vintage either lacks the period or prints
it before any revision made on that day. PAYEMS shows both: its 2026-09-29
vintage, returned for 2026-10-01, has no September 2026 row. It also prints
August as 159,075 thousand, against 159,015 in the 2026-10-02 vintage, so
mixing the two vintages would give -31 instead of +29 for September.

## Survey of the cells that read ALFRED

The survey scripts, their output and the custody replay live in the review
folder for this work (`~/reviews/thesis-alfred-header-lag-2026-10/survey/`).

- **2026-11-18, generic leg.** The live log has 62 cells (36 linked, 26
  pending). Their 58 past release-day reads were each labeled with the date
  asked for, on both spellings. Four reads, 2026-12-01 to 2026-12-10, are in
  the future and were not requested. ECIWAG (2026-10-30) and PRS85006112
  (2026-11-05), both future on 2026-10-18, resolved with archives labeled
  their day.
- **2026-10-18, generic leg.** 59 cells. All 54 past reads were labeled with
  the date asked for, and no cell's resolution date was among the lagged
  dates above.
- **Custody replay, 2026-11-18.** It covered every resolver run on `main`:
  65 ALFRED fact archives in 28 runs, 36 series, each labeled with its
  `sourceVintage`. `tests/test_alfred_vintage_labels.py` repeats this on the
  checked-out `records/`.

No recorded fact came from a lagged response.

## The clock

`alfred_today()` is the date on US Central standard time (UTC-6). That date is
never later than the date in US Central or Eastern time, on standard or
daylight time, nor than the UTC date. The resolver does not request a vintage
date later than it. This is a conservative choice, not a measured boundary:
before 06:00 UTC it holds back the UTC day's vintage. The resolve workflow
runs at 13:40 UTC, when the two dates agree.

## Follow-ups not taken here

- The claims leg asks only the canonical spelling. A lagged release-day read
  there waits rather than retrying the reordered spelling.
- The claims leg dates its reads by the runner's `dt.date.today()`, which runs
  ahead of `alfred_today()` between 00:00 and 06:00 UTC. Its label rule
  already covers what such a read returns: a release-day read labeled the
  day before is refused, and a day-after read labeled the release day is the
  lag-1 case it accepts.
