# BLS CPS Table A-19 capture fixtures

The `<table>` element of three Internet Archive captures of
`https://www.bls.gov/web/empsit/cpseea19.htm`, fetched 2026-09-20 from the
replay URLs below. bls.gov answers non-browser clients with HTTP 403, and BLS
overwrites this page with each Employment Situation, so the Archive's captures
are the copies of a past month's table this resolver can retrieve.

| Data month | Capture (UTC) | Replay URL | Full replay response |
|---|---|---|---|
| 2026-06 | 2026-07-10 11:05:09 | https://web.archive.org/web/20260710110509/https://www.bls.gov/web/empsit/cpseea19.htm | 116,589 bytes, SHA-256 `ae3e1daba25fab765a4ce6549c220676b2d4da60d2523a9c1ca05689c4b07421` |
| 2026-07 | 2026-08-19 19:14:18 | https://web.archive.org/web/20260819191418/https://www.bls.gov/web/empsit/cpseea19.htm | 116,627 bytes, SHA-256 `f568751ffcb4bd656d7a94e533252ab8947ff158d799116427138c1f7c9a2fc5` |
| 2026-08 | 2026-09-04 17:00:06 | https://web.archive.org/web/20260904170006/https://www.bls.gov/web/empsit/cpseea19.htm | 116,641 bytes, SHA-256 `356aa54112d8ac92ca300863e530dbcd2d6422d95f3ac08edba10acb0985282a` |

The replay response wraps BLS's page in the Archive's toolbar and rewrites
links, so its hash identifies this fetch, not BLS's bytes; a later fetch of the
same capture can differ outside the table. The fixtures keep only the table
element, verbatim. They are parser and identity evidence. The resolver does
not read the replay form: it fetches the capture's stored response
(`/web/<timestamp>id_/<url>`), which is BLS's own bytes, and archives that.

On 2026-09-19 a CDX query for the page between 2026-07-01 and 2026-09-19,
filtered to HTTP 200, listed exactly these three captures. That query was
filtered; it says nothing about rows with other statuses in that span. The
resolver's own queries are unfiltered and report every row
(`a19_window_captures`).
