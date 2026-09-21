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
   archived URL, HTTP status, content digest, length. A row counts only if
   its archived URL is the registered one (see "What counts as a capture").
5. Reads the index once more, with no capture request, for windows that
   closed in the last seven days. A window that ended without a capture is
   then known the same week, not when someone looks months later.

The second pass exists because the Archive fails in bursts that outlast one
run's retries. On 2026-09-20 it answered one client with HTTP 429 and no
`Retry-After` header for more than ten minutes, on both the index and the
save endpoint, and later the same evening answered every save request with
HTTP 500. The second pass leaves alone any URL the index already shows
captured since 19:30 UTC that day. A capture from earlier in the day does
not count, because it may predate that day's release. If the index does not
yet list the first pass's capture, the second pass asks again, so a URL can
be captured twice in a day.

### Rate

The run is sequential. Between two capture requests it waits 20 seconds, and
between two index reads 5 seconds. It never skips a wait to save time: when
the time budget cannot fit the next wait, that phase stops asking and
reports each remaining URL as `NOT_ASKED`. It avoids asking for one host
twice in a row when another host is waiting.

An index read gets at most 2 attempts. A capture request gets at most 3,
and is asked again only when the Archive did not take it: a transport fault
or HTTP 429. Any other HTTP answer ends the attempts for that URL in that
pass (see "The save response is a weak signal"). Backoff is 30, 90 and 180
seconds, or the server's `Retry-After` capped at 300. After four HTTP 429 answers in a row from the save endpoint, the run
stops asking that endpoint and reports each remaining URL as `NOT_ASKED`;
the index endpoint has its own count. A client that is told to slow down
and keeps asking is not polite, and the second pass is the retry.

The budget is 90 minutes of wall clock, a quarter of it held back for the
index reads. Every request runs under an absolute deadline and is abandoned
when it passes, because a socket timeout bounds one read, not a request that
trickles.

The cap is 20 URLs per pass. It is a cap on URLs, not on requests. At the
cap, with every request failing on something other than 429, the first pass
makes at most 60 capture attempts and 120 index-read attempts (open
windows, closed windows and redirect targets, two attempts each), and the
second pass 160, because it also reads the index before asking. The pending population on 2026-09-20 was 48
targets on 25 URLs and 12 hosts; its busiest day is 2026-09-30 with 15 URLs
on 10 hosts, so the cap does not bind. If it ever does, the windows that
close soonest are kept and every dropped URL is named in the report.
`tests/test_witness_registered_windows.py` fails if the committed
registrations ever put more than 20 URLs in an open window on one day.

### The invariant

No capture is requested outside a registered window. The selection filters
on the run's UTC date. A guard then runs immediately before every capture
attempt, retries included, and after the second pass's index read: one
registered window for that URL must contain the run's date, the UTC date at
that moment, and the UTC date ten minutes later. The ten minutes are there
because a capture takes time, and a request that leaves at 23:59 can be
dated the next day. A run that crosses midnight therefore stops asking for a
URL whose last window ended that day. Closed windows are read from the index
and never saved. `--date` plans another day and is accepted only with
`--dry-run`.

What the guard cannot promise is the Archive's own timing: it dates the
capture, not the request. A capture dated outside a window is simply not
counted for that window.

## Where the evidence lives

In the Internet Archive's index, and nowhere in this repository.

- The value of this custody is that a third party holds the bytes and the
  date. A manifest committed by Thesis would restate the Archive's index. It
  would add our claim about the evidence, and no evidence.
- The captures are re-derivable from the registration alone. The `sourceUrl`
  and the window give the index query. `--audit` runs that query for every
  target that has no executable plan under the rule in force when it runs,
  pending or not, whose window has started, and requests no capture. What is
  not re-derivable is the run's own history: which requests failed and how,
  what was retried, what the cap dropped. That lives in the workflow log and
  the 90-day report artifact and expires with them. It is operational
  history, not custody, and losing it changes no fact about any window.
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
  pages"). Expect `SAVE_FAILED` for an ssa.gov URL. The index is still read,
  and the Archive does hold some captures of the host: that same section
  records a 2026-07-11 capture of one SSA page. A window on its last two
  days with no capture turns the run red and opens an issue; for ssa.gov
  that alert may have no remedy, and that is then a fact for the ruling.
- **bls.gov.** The host answers non-browser clients with HTTP 403, but the
  index lists HTTP 200 captures of
  `https://www.bls.gov/web/empsit/cpseea19.htm` at 20260710110509,
  20260819191418 and 20260904170006 (read through this script on
  2026-09-20).
- **API URLs.** Several registrations bind an API query (Statistics Canada
  WDS, the ABS Data API, Eurostat SDMX). A capture of one holds a single
  response to that exact query string at one instant. It is a payload, not
  a release.
- **The save response is a weak signal, in both directions.** Three real
  runs from one machine, on 2026-09-20 and 2026-09-21, asked for the same
  four URLs. The first was answered HTTP 429 on every request. The other
  two were answered HTTP 500, with the Wayback Machine's own page as the
  body, on every save request. Yet the index lists HTTP 200 captures
  stamped within a minute of some of those requests: the Treasury page at
  2026-09-20 21:08:16 and 23:31:05, and the ABS API at 2026-09-20 23:32:07
  and 2026-09-21 15:57:07. The Statistics Canada URL has no capture at all,
  and nbb.be was captured with HTTP 204, which does not count. So a failed
  response does not show that no capture was made, and only the index shows
  that one was. This is why a save that got an HTTP answer is not asked
  again in the same pass, and why every verdict rests on the index. Whether
  a GitHub runner is answered the same way is not known until the workflow
  has run. The Archive also offers an authenticated capture API; it needs
  an account key as a repository secret and was not evaluated here.
- **Index lag.** The ABS capture stamped 2026-09-20 23:32:07 was not in the
  index when that run read it about four minutes later; it was there the
  next day. The verdict `SAVE_NOT_YET_INDEXED` says what the save request
  returned, and the next run re-reads the whole window. A window on its
  last two days is listed as awaiting the index, and raises no alert, only
  when the save response named a capture of the registered URL dated inside
  that same window.
- **Redirects.** A registered URL can redirect. The index then lists it
  with a 3xx status, which does not count: on 2026-09-21 all five rows for
  `https://www.fns.usda.gov/pd/wic-program` inside its closed window were
  HTTP 301. When the save response names an archived URL other than the
  registered one, the witness reads that URL's index too and reports
  `CAPTURED_UNDER_REDIRECT_TARGET`. That is custody of another URL. Whether
  that URL is the registered source is not the witness's call, so the
  capture counts for nothing and a closing window still raises the alert,
  with the other URL's capture linked beside it.
- **One or two captures a day.** Both passes run late in the UTC day. A
  page that changes more than once in a day is not seen each time.

### What counts as a capture

A row of the index counts toward a target's window only if all of these
hold. Everything else stays in the JSON report, uncounted.

- Its archived URL is the registered `sourceUrl`: same scheme, path and
  query string exactly; same host, compared without case and without a
  default port; an empty path equals `/`. Rows for any other URL are listed
  under `rowsForOtherUrls`. A listing that lacks the columns that identify
  a capture (timestamp, archived URL, status, digest) is treated as an
  unread index, not as custody and not as absence.
- Its timestamp, in UTC, falls inside that target's own window.
- Its status is `200`, or it is a `warc/revisit` row whose digest equals
  the digest of an HTTP 200 row of the same URL in the same listing. The
  Archive's CDX documentation describes `warc/revisit` as a duplicate that
  resolves to an original capture, and the index does list such rows with
  status `-`: the Treasury page's window holds two
  (`tests/fixtures/wayback/cdx_fiscaldata_mts_2026-09.json`). One has the
  digest of the page's HTTP 200 captures and counts. The other matches no
  page in the listing and does not. This rule can understate what the
  Archive holds. A 403 or 3xx row never counts, and is reported as
  `CAPTURED_NOT_AS_PAGE` when it is all the index has for the day.

## Reading the output

Per URL, one verdict about the run's day:

| Verdict | Meaning |
|---|---|
| `CAPTURED` | The index lists a capture of the page dated today (HTTP 200, or a revisit tied to one by digest). The text also says what the save request did, which may be that it failed. |
| `CAPTURED_UNDER_REDIRECT_TARGET` | No capture of the registered URL today; one of the URL the save response named instead. Not custody of the registered URL. |
| `CAPTURED_NOT_AS_PAGE` | The index lists today's capture only with a status that does not count. |
| `SAVE_NOT_YET_INDEXED` | The save request returned; the index does not list a capture yet. |
| `SAVE_FAILED` | Every attempt failed (the text carries the status, such as HTTP 520, 500 or 429) and the index lists nothing today. |
| `NOT_ASKED` | A capture run did not ask: the rate-limit breaker was open, the time budget was spent, or no registered window contained the moment. The text says which. |
| `INDEX_UNREAD` | The index could not be read. This is a failure to look, not a finding of absence. The report then carries no capture count for that URL, and it never counts as a custody gap. |
| `NO_CAPTURE_TODAY` | An audit, which requests nothing, found nothing dated today. |

Per target, the report gives the count of captures of the page inside its
own window so far (`pageCapturesInWindow`, split into `http200InWindow` and
`revisitsInWindow`), the first and last of them, and the number of distinct
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
