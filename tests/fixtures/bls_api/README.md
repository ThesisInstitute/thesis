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
