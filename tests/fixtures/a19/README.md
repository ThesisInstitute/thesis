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

The Archive's index listed exactly these three HTTP 200 captures of the page between
2026-07-01 and 2026-09-19 (CDX query, 2026-09-19).


## Two captures for month labels (added with the `bls-cps-a19` adapter)

The header parser maps BLS's month labels to months, and two of the twelve had
never been read from a capture: "Oct." and "May". October is the first month
the registrable adapter resolves. Both were read on 2026-09-21 through the
resolver's own reader, `a19_read_capture`, which fetches the Archive's stored
response (`/web/<timestamp>id_/<url>`): these are BLS's bytes, so the hashes
below are reproducible, unlike the replay hashes above. The fixtures keep only
the table element, verbatim.

| Data month | Capture (UTC) | Capture URL | Stored response |
|---|---|---|---|
| 2023-10 | 2023-11-30 07:04:42 | https://web.archive.org/web/20231130070442/https://www.bls.gov/web/empsit/cpseea19.htm | 103,959 bytes, SHA-256 `c92f7bf57e7c4a41ab80e11898eaeaaa8b76424a6fb82a94de4b4a33c6ec56c1` |
| 2026-05 | 2026-06-13 10:10:41 | https://web.archive.org/web/20260613101041/https://www.bls.gov/web/empsit/cpseea19.htm | 105,438 bytes, SHA-256 `d9fbf4fb9fc8a9cd16e5b2711b6c8d6604f2a06498e2fd270cdcd38751ec951e` |

Their headers read "Oct. 2022 / Oct. 2023" and "May 2025 / May 2026", and the
parser reads all six rows from each. They are label and parser evidence only:
neither month is a registered target, and the 2023 capture predates every
registration.

BLS served the 2023 page with CRLF line endings (612 carriage returns in the
stored response, 483 of them inside the table); the 2026 tables are LF-only.
The 2023 fixture keeps its carriage returns, as "verbatim" requires, so
`git diff --check` reports every line of it as trailing whitespace. That is the
file's provenance, not a defect, and `.gitattributes` keeps every fixture here
from being rewritten at checkout.
