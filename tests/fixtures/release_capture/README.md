# Release capture fixtures

`*.raw` files are exact bodies the Internet Archive stores for one capture
(its `id_` form, before BLS's gzip is removed). Beside each is a `.json`
sidecar with the capture URL, the index row's digest and the page title.
`tests/test_release_capture_real_fixtures.py` checks each body against its
index digest, refuses any fixture whose month a reviewed contract forecasts,
and compares the pinned table cells with the release's own prose.

Present: the June 2026 CPI release (`cpi.nr0-20260720045436`), fetched
2026-10-16 over verified TLS; its digest matches the Archive's index row.

Still missing: the Employment Situation (`empsit.nr0.htm`) and JOLTS
(`jolts.nr0.htm`, `jolts.t04.htm`) pages. On 2026-10-16 from about 16:00Z,
TLS to web.archive.org on the operator's network was intercepted by a
filter presenting a "NetAlerts Services" certificate, so no verified read
was possible. Fetch one non-target month for each (the July 2026 Employment
Situation and June 2026 JOLTS releases, captured 2026-08-10 to 08-25) with
verified TLS before admission. Never fetch a capture dated inside a target
window. `tests/test_release_capture_parsers.py` covers those parsers with
synthetic layouts in the meantime.
