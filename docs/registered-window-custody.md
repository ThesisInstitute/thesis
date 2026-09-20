# Registered-window custody

Some published forecasts are registered with a `sourceBinding` that no
resolver leg can execute. Today that means `adapter == "generic-url"`: the
binding names a page and no executor. What the public record finally says
about those forecasts is a founder ruling, and this page does not make it.

One possible ruling is a reviewed executor assignment. It is only open to a
target that has first-print custody: official bytes, dated by someone other
than Thesis, inside the registered `expectedReleaseWindow`. Custody of that
kind can be made only while the window is open. After the window closes, no
later work can create it.

`scripts/witness_registered_windows.py` and
`.github/workflows/witness-registered-windows.yml` make that custody each day
and decide nothing. They do not resolve, void, re-register, or edit any
target, and they write nothing under `records/**`.

## What runs

Twice a day (19:40 and 22:10 UTC) the workflow:

1. Reads every registration under `records/targets`, and checks each file's
   content hash against its name. A file that fails the check is reported and
   skipped, because its `sourceUrl` is not a registered one.
2. Keeps the targets that meet all three conditions:
   - **No executable plan.** If `resolve_pending.execution_plan_refusal`
     exists (branch `feat/executor-gate`), the witness asks it. Until then the
     rule is `sourceBinding.adapter == "generic-url"`. The report names the
     rule it used. If the resolver module does not import, the witness falls
     back to the adapter rule and says so; it does not stop.
   - **Forecast still pending.** The target's `dataPointId` has a
     `resolutionLinks` row with `status: "pending"` in the Thesis log. If the
     log cannot be read, the pending state is unknown and the witness keeps
     every no-plan target in an open window. An extra capture costs one
     request. A skipped capture cannot be made later.
   - **Window contains today.** The window's `start` and `end` are read as
     UTC calendar days, both inclusive. The Archive's timestamps are UTC too.
3. Asks the Internet Archive to capture each distinct `sourceUrl` once:
   `GET https://web.archive.org/save/<url>`, with the User-Agent
   `thesis-witness/1.0 (+https://app.thesisinstitute.org)`.
4. Reads the Archive's CDX index for the same URL, from the earliest open
   window's start to today, and reports each capture it lists: timestamp,
   HTTP status, content digest, length.
5. Reads the index once more, with no capture request, for windows that
   closed in the last seven days. A window that ended without a capture is
   then known the same week, not when someone looks months later.

The second pass exists because the Archive fails in bursts that outlast one
run's retries. On 2026-09-20 its index answered one client with HTTP 429 and
no `Retry-After` header for more than ten minutes, then recovered. The
second pass leaves alone any URL the index already shows captured since
19:30 UTC that day. A capture from earlier in the day does not count,
because it may predate that day's release.

### Rate

The run is sequential. It waits 20 seconds between capture requests and 5
seconds between index reads, avoids asking for one host twice in a row when
another host is waiting, makes at most 3 attempts per request with backoff
(30, 90, 180 seconds, or the server's `Retry-After` capped at 300), and stops
asking after 90 minutes. The daily cap is 20 URLs. The pending population on
2026-09-20 was 48 targets on 25 URLs and 12 hosts; its busiest day is
2026-09-30 with 15 URLs on 10 hosts, so the cap does not bind. If it ever
does, the windows that close soonest are kept and every dropped URL is
named in the report. `tests/test_witness_registered_windows.py` fails if the
committed registrations ever exceed the cap.

### The invariant

No capture is requested outside a registered window. The selection filters
on the run's UTC date, and the last step before each request re-checks the
UTC date at that moment. A run that crosses midnight therefore refuses a
target whose window ended the day before. Closed windows are read from the
index and never saved. `--date` plans another day and is accepted only with
`--dry-run`.

## Where the evidence lives

In the Internet Archive's index, and nowhere in this repository.

- The value of this custody is that a third party holds the bytes and the
  date. A manifest committed by Thesis would restate the Archive's index. It
  would add our claim about the evidence, and no evidence.
- The record is re-derivable from the registration alone. The `sourceUrl`
  and the window give the index query. `--audit` runs that query for every
  no-plan target whose window has started, open or closed, and requests no
  capture. So nothing is lost when workflow logs and the 90-day report
  artifact expire.
- `records/**` belongs to the allowlisted attesting workflows
  (AGENTS.md, "Records provenance"). A committed manifest would need a new
  daily writer with `contents: write` and `id-token: write` on that
  allowlist. That widens who can push records and buys no proof. The
  workflow instead holds `contents: read`, and
  `tests/test_witness_registered_windows_workflow.py` fails if it gains a
  write permission, a git write, or a place on the allowlist. The script
  refuses a `--report` or `--summary` path under `records/`.

One risk this choice does not cover: the Archive can later withdraw a
capture. A committed list of timestamps would not cover it either, because
it would hold no bytes. Holding the bytes ourselves is a different design
(fetch the bytes, hash them, and publish them through an attesting workflow
whose commits the recorder then witnesses, as `witness-sba-pdf.yml` does).
Those bytes would be fetched by Thesis, not by a third party, and third-party
custody is the property the executor-assignment option asks for. It is not
built here and is not needed to keep the option open.

## What this custody can and cannot prove

A capture proves one thing: on the capture date, the Archive's crawler
requested that exact URL and the server returned those bytes with that
status.

It does not prove any of the following.

- **That a figure on the page is the registered statistic.** The witness
  never reads a capture. Whether some executor's reading of those bytes is
  the number the contract registered (same statistic, unit, transform,
  period and vintage) is the question a reviewed assignment would have to
  answer, per contract, with the outcome already public.
- **That the release had been published when the capture was made.** A
  window spans several days and the release lands on one of them. A
  capture from before that day shows the previous period. A change of
  digest between two captures shows that the page changed between them, and
  nothing more exact than that.
- **That the capture is the first print.** It bounds the first print from
  above: the page showed this no later than the capture time. A revision
  between publication and capture is invisible.
- **That the page's figures are in the capture at all.** A capture stores
  the response to one request. Where a page loads its figures by script,
  the stored response may hold the frame and not the figures.
- **That the URL is the right source.** The witness captures the registered
  `sourceUrl` as written. If the registration names a landing page, or the
  wrong month's release, the capture is faithful to that mistake.

## Known limits

The run reports these beside each URL they apply to. It never uses them to
skip a URL.

- **ssa.gov.** Save Page Now failed with HTTP 520 "Job failed" on every
  attempt on 2026-08-23 (`docs/anchor-verifications.md`, "SSA official
  pages"). Expect `SAVE_FAILED` for an ssa.gov URL. The Archive's own crawl
  does sometimes reach the host (one SSA page has a 2026-07-11 capture), so
  the index read still matters. A window on its last two days with no
  capture turns the run red and opens an issue; for ssa.gov that alert may
  have no remedy, and that is then a fact for the ruling.
- **bls.gov.** The host answers non-browser clients with HTTP 403, but the
  Archive's crawler does get the page: the index lists HTTP 200 captures of
  `https://www.bls.gov/web/empsit/cpseea19.htm` at 20260710110509,
  20260819191418 and 20260904170006 (read 2026-09-20). Only an HTTP 200
  capture counts. A capture with another status is listed as
  `CAPTURED_NOT_AS_PAGE` and is not custody.
- **Status other than 200.** An index row counts toward custody only when
  its status field is exactly `200`. A row with any other value, numeric or
  not, stays in the JSON report and is not counted. The counts can therefore
  understate what the Archive holds. They cannot overstate it.
- **API URLs.** Several registrations bind an API query (Statistics Canada
  WDS, the ABS Data API, Eurostat SDMX). A capture of one holds a single
  response to that exact query string at one instant. It is a payload, not
  a release, and it carries no release date of its own.
- **Redirects.** A page that redirects is stored under the URL it
  redirected to, and the registered URL's index row is a 3xx. When the save
  response names a different archived URL, the witness reads that URL's
  index too and reports `CAPTURED_UNDER_REDIRECT_TARGET`. Whether that URL
  is the registered source is not the witness's call, so it does not count
  the capture toward the registered URL.
- **Index lag.** A new capture can take time to appear in the index. The
  verdict `SAVE_NOT_YET_INDEXED` says the save request returned and what
  capture time it named; the next run re-reads the whole window. A window
  on its last two days in that state is listed as awaiting the index, and
  does not raise the alert.
- **One capture a day.** A page that changes twice in a day is seen once
  by this job, late in the UTC day.

## Reading the output

Per URL, one verdict about the run's day:

| Verdict | Meaning |
|---|---|
| `CAPTURED` | The index lists an HTTP 200 capture dated today. The text says what the save request did; the capture may be the Archive's own. |
| `CAPTURED_UNDER_REDIRECT_TARGET` | No HTTP 200 capture of the registered URL today; one of the URL it redirected to. |
| `CAPTURED_NOT_AS_PAGE` | The index lists today's capture only with a status other than 200. |
| `SAVE_NOT_YET_INDEXED` | The save request returned; the index does not list the capture yet. |
| `SAVE_FAILED` | Every attempt failed (the text carries the status, such as HTTP 520 or 429) and the index lists nothing today. |
| `INDEX_UNREAD` | The index could not be read. This is a failure to look, not a finding of absence, and it never counts as a custody gap. |
| `NO_CAPTURE_TODAY` | No save was requested (audit, or a window that closed during the run) and the index lists nothing today. |

Per target, the report gives the count of HTTP 200 captures inside its own
window so far, the first and last of them, and the number of distinct
digests. `custodyGaps` lists windows on their last two days with no capture
(`closingWithoutCapture`, which turns the run red), the same but awaiting
the index (`closingAwaitingIndex`), and windows that closed in the lookback
with none (`closedWithoutCapture`).

The script exits 0 whatever the per-URL outcomes are, because they are
findings. It exits 1 only when it could not read the registrations at all.

## Running it by hand

```bash
# What would be captured today. Sends nothing to the Archive.
uv run --locked python scripts/witness_registered_windows.py --dry-run

# The plan for another day.
uv run --locked python scripts/witness_registered_windows.py --dry-run --date 2026-09-30

# Read the index for every no-plan target whose window has started. No capture requests.
uv run --locked python scripts/witness_registered_windows.py --audit --report /tmp/custody-audit.json

# A real run.
uv run --locked python scripts/witness_registered_windows.py
```

`--log-dir` reads a Thesis log downloaded with
`scripts/thesis_log_client.py --output-dir` instead of the live one. From
GitHub: `gh workflow run witness-registered-windows.yml --ref main -f mode=dry-run`.

To check one registration without this script, query the index directly:

```bash
curl -s 'https://web.archive.org/cdx/search/cdx?url=<sourceUrl, percent-encoded>&from=<start>000000&to=<end>235959&output=json&fl=timestamp,original,statuscode,digest'
```
