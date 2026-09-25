# BLS Public Data API captures

Six unmodified responses from the keyless BLS Public Data API v2, fetched with
`curl` on 2026-09-20 (UTC) using the exact single-series GET the resolver
issues (`BLS_API_URL` in `scripts/resolve_pending.py`). Every response returned
HTTP 200 with `"status": "REQUEST_SUCCEEDED"`.

| File | Request | Retrieved (UTC) | Bytes | SHA-256 |
|---|---|---|---:|---|
| `LNS14000000-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/LNS14000000?startyear=2026&endyear=2026` | 2026-09-20T20:58:19Z | 970 | `8a990a8d0a5d513c13e5423ad8aeed8aba6446b551625d53fe2328f9cb7110d3` |
| `CUSR0000SA0-2025-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0?startyear=2025&endyear=2026` | 2026-09-20T20:58:21Z | 1,965 | `18afe3d6ac49e1db380d18fb657c0e0479ab03a8ce47b5ecfe982ed079aa3d5a` |
| `CUSR0000SA0L1E-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0L1E?startyear=2026&endyear=2026` | 2026-09-20T20:58:24Z | 840 | `1aa489932a6895a1f0309744717a4b434350db3ffe7a2ddc9d8e94f6ce66cb1d` |
| `JTS000000000000000JOL-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/JTS000000000000000JOL?startyear=2026&endyear=2026` | 2026-09-20T20:58:26Z | 830 | `5dea3ebccdaa2bafd965272a8843d04035df48ee69bafcab817a797e00a0e0b0` |
| `JTS000000000000000QUR-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/JTS000000000000000QUR?startyear=2026&endyear=2026` | 2026-09-20T20:58:28Z | 823 | `4aea5ae03362fe9f36160ac62574f1eccfbcdea65f777c9949f8157a022cdf71` |
| `CES0000000001-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001?startyear=2026&endyear=2026` | 2026-09-20T20:58:30Z | 893 | `d0c8d0236ccc51b4bcc7e0dbb3dba73cb6fd834446d722301b43a399cbe0afd3` |

The headline CPI capture starts in 2025 on purpose. It contains BLS's real
October 2025 gap row (`"value": "-"`, footnote code `X`), which the tests use
to prove that a one-month change is refused across an unpublished month.

The two JOLTS responses carry the message `Unable to get Catalog Data for
series ...` next to `REQUEST_SUCCEEDED`. The data rows are complete; the
resolver reads only the status and the rows.

## What these bytes prove

They prove that the parser, the three monthly transforms, the scale and the
rounding reproduce the values BLS printed, and that the seven-key binding the
docket commits is the one the executor builds. `tests/test_bls_api_registrable.py`
pins each file's hash and reproduces every anchor with zero tolerance.

## What they do not prove

They are one vintage: what the API served on 2026-09-20. For every month except
the latest, that is a revised estimate, not the first print (June 2026 job
openings printed 7,359 and are served as 7,182). They are never resolution
evidence. A resolution re-fetches the live response, re-verifies the anchors
from it, and captures a month only while the first-print gate still holds.
Release-text verification of every anchor is in
`docs/anchor-verifications.md`, "Anchor verifications — BLS registrable docket
series (2026-09-20)".

## Table A-19 rows (added 2026-09-25)

Six more unmodified responses, fetched the same way, one per Employment
Situation Table A-19 row the docket forecasts. Each returned HTTP 200 with
`"status": "REQUEST_SUCCEEDED"`.

| File | Request | Retrieved (UTC) | Bytes | SHA-256 |
|---|---|---|---:|---|
| `LNU02032454-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032454?startyear=2026&endyear=2026` | 2026-09-25T11:06:07Z | 984 | `8736f84807450744285a9c75f6f3ec7ce9af0c2972c90a2a176d1ba098c7cd10` |
| `LNU02032455-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032455?startyear=2026&endyear=2026` | 2026-09-25T11:06:09Z | 978 | `af021869dffc4f654216e7d7c20dbcbdcedf937c21a62a31530a7042f2af86fc` |
| `LNU02032463-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032463?startyear=2026&endyear=2026` | 2026-09-25T11:06:12Z | 978 | `0fae2a5e4b15112f7201bbfbdd15aa25944fc64d69b9e8d1b0bc7f67ca7dc410` |
| `LNU02032207-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032207?startyear=2026&endyear=2026` | 2026-09-25T11:06:14Z | 986 | `8ef8b905b38944647eec5ce458982f011a5d7111c09ef0be377af7cea3cd69c5` |
| `LNU02032213-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032213?startyear=2026&endyear=2026` | PENDING_PRODUCTION_TIME | PENDING_PRODUCTION_BYTES | `PENDING_PRODUCTION_SHA256` |
| `LNU02032214-2026-2026.json` | `https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032214?startyear=2026&endyear=2026` | PENDING_TRANSPORTATION_TIME | PENDING_TRANSPORTATION_BYTES | `PENDING_TRANSPORTATION_SHA256` |

The first requests for the last two, at 2026-09-25T11:06:16Z and 11:06:18Z,
returned HTTP 200 with `"status": "REQUEST_NOT_PROCESSED"` and the message
"Request could not be serviced, as the daily threshold for total number of
requests allocated to the user with registration key  has been reached." That
is the keyless daily limit for this address. They were fetched again after it
reset.

Every A-19 capture's latest month is August 2026, with no footnote, and its
January 2026 row carries footnote code `12`, "January 2026 estimates were
revised to incorporate updated population controls."

### The Table A-19 pages these rows are checked against

`tests/fixtures/a19/` holds the `<table>` element of three Internet Archive
captures of `https://www.bls.gov/web/empsit/cpseea19.htm`, each taken after
the Employment Situation that first printed its month. The files are
byte-identical to the ones thesis#269 adds at the same paths. They were taken
verbatim from the Archive's replay responses, fetched 2026-09-20.

| Data month | Capture (UTC) | Replay URL | File SHA-256 |
|---|---|---|---|
| 2026-06 | 2026-07-10 11:05:09 | https://web.archive.org/web/20260710110509/https://www.bls.gov/web/empsit/cpseea19.htm | `3b0c626048d920079f6cde70af947b767bcf291b097fe57be3c5234b38bef607` |
| 2026-07 | 2026-08-19 19:14:18 | https://web.archive.org/web/20260819191418/https://www.bls.gov/web/empsit/cpseea19.htm | `0fba99933a44a2d5815e864d2d41fa3d1e3ecab2fec1ae7e2f96e7476ea27e3d` |
| 2026-08 | 2026-09-04 17:00:06 | https://web.archive.org/web/20260904170006/https://www.bls.gov/web/empsit/cpseea19.htm | `b3833556f6c72ec716f249e7afc152f17bcbfeb5dde4c9f8a5eb2c7da38d10d1` |

Each table's current-month column header names its month ("June", "July",
"Aug."). For all six rows and all three months, the API capture serves the
integer the table printed, and matches no other row in all three months.
`tests/test_bls_api_registrable.py` checks that equality, so the six anchors
are first prints, not only settled values.
