# Release capture fixtures

`*.raw` files are exact bodies the Internet Archive stores for one capture
(its `id_` form, before BLS's gzip is removed). Beside each is a `.json`
sidecar with the capture URL, the index row's digest, the page title and a
note. Every sidecar but CPI's also records the figure an independent source
(an ALFRED first-print vintage) gives for the same cell.
`tests/test_release_capture_real_fixtures.py` checks each body against its
index digest and refuses any fixture whose month a reviewed contract
forecasts. It compares each pinned figure with a second source: the
release's own prose for CPI, and the ALFRED vintage for the rest.

| Fixture | Page | Release |
|---|---|---|
| `cpi.nr0-20260720045436` | CPI summary, HTML Table A | June 2026 |
| `empsit.nr0-20260810222604` | Employment Situation summary, prose only | July 2026 |
| `jolts.nr0-20260810093236` | JOLTS summary, prose only | June 2026 |
| `jolts.t04-20260816021553` | JOLTS Table 4, HTML table | June 2026 |

The CPI fixture was fetched 2026-10-16. The other three were fetched
2026-10-22, once the TLS filter that blocked web.archive.org on 10-16 was
gone. All four came over verified TLS. Each capture was selected from the
Archive's index alone (timestamp, status, digest), dated before every target
window for its page. Never fetch a capture dated inside a target window.

The Employment Situation and JOLTS summaries print no table. Their figures
are read from the release's prose (`PROSE_PARSERS` in
`scripts/legacy_release_parsers.py`). The JOLTS summary states total job
openings only to 0.1 million: "7.4 million" for June 2026, where ALFRED's
first-print vintage has 7,359 thousand. Both openings contracts read a
thousands figure, so the resolver holds them
(`LEGACY_RELEASE_PRECISION_HELD`) until ruling d1856.

`cdx/` holds the Archive's index for each no-custody void of ruling d1633
(`scripts/voided_targets.py`): the registered page and release window, the
exact query the leg sends, and the body served on 2026-10-24 (an empty
index, `[]`). An index read lists timestamps, statuses and digests; no
capture was opened. `tests/test_voided_targets.py` replays each read through
the leg's own discovery.
