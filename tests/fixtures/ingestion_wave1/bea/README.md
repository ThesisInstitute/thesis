# BEA current-release resolver fixtures

Fetched unmodified from the official BEA hosts on 2026-08-07 UTC, while the
2026 Q2 advance estimate was still the current GDP print and before the second
estimate scheduled for 2026-08-26. These are parser fixtures, not a claim that
Thesis witnessed the files on their 2026-07-30 release day.

- `gdp-advance-2026-q2.html`: GET
  `https://www.bea.gov/news/2026/gdp-advance-estimate-2nd-quarter-2026`;
  52,640 bytes; SHA-256
  `4636dc341d7cd1a53196fdf0ad529143b0e8b2d0db874f6086ca9b8ebf23cf5d`.
- `nipa-table-5-3-5-2026-q2.json`: POST (raw double-encoded response: a JSON string wrapping the object)
  `https://apps.bea.gov/iTablecore/data/app/GetStep` with app 19, step 3,
  category `Survey`, table key `145`, first/last year `2026`, scale `-6`,
  series `Q`, and select-all-years `0`; 46,905 bytes; SHA-256
  `59e5f1ab0eeaa76cdca566383c66eab7787214216ffcbe35aa4c1793a894750d`.
- `ita-table-5-1-2026-q1-qsa.json.base64`: the exact raw GetStep response,
  base64-encoded so its original no-final-newline byte sequence is preserved.
  A live official fetch on 2026-08-12 UTC POSTed app `62`, step `2`, product
  `1`, table list `62`, year selector `1` (authenticated by the returned
  prompt catalog as 2026), QSA selector `1`, and line selector `18` to
  `https://apps.bea.gov/iTablecore/data/app/GetStep`; the decoded fixture is
  16,089 bytes with SHA-256
  `d482e10713b19c01824882b6e6f7ee01d06619222d35b27cb6f97fa95fdf0f35`.
  It prints 2026 Q1 Table 5.1 line 18 `Personal transfers` as `18,511`
  million dollars. The official release notice is
  `https://www.bea.gov/news/2026/us-international-transactions-and-investment-position-1st-quarter-2026-and-annual-update`.
  This retrospective fixture verifies the current retrieval and parse path;
  it is not evidence that Thesis captured the table on its 2026-06-24 release
  day.
- `ita-prompt-catalog-2026-q1.json.base64`: the exact unfiltered GetStep
  response to app `62`, step `2`, product `1`, and table list `62`, fetched
  live from the same official endpoint on 2026-08-12 UTC. The decoded fixture
  is 84,950 bytes with SHA-256
  `9da6f369b0182f85102a9f5b83518ba0e0afaf6065f698f9cb69a5e319156b36`;
  its 28-row by 7-column table shape is distinct from the selected response's
  6-row by 3-column shape. The canonical 68-byte catalog request has SHA-256
  `18ea74bc5703892851fa9a21f85b34d616d1c9b19cee06a31da47d8775bd15ca`.
  The canonical 123-byte selected-table request has SHA-256
  `752aff73c31aec17c829529964998148d805d2b060f48513ea9afbf7c290f3d9`.
  A live Product `5` replay returned bytes identical to Product `1`, so the
  product selector is authenticated by the outbound request, not by the
  response body.
- `ita-iip-release-2026-q1.html.base64`: GET of the official release notice
  linked above, fetched live on 2026-08-12 UTC and base64-encoded to preserve
  its exact bytes; 58,604 decoded bytes; SHA-256
  `617c9229ac39ded608b64a71bc30c3c10d713cb1885ee53344d6fb3bc4dd227d`.

- `nipa-table-5-3-5-2024-core-endpoint.json`: the raw double-encoded
  response to the same app 19, step 3 request for first/last year `2024`
  (scale `-6`, series `Q`, select-all-years `0`), POSTed on 2026-11-05 at
  19:47:50 UTC to `https://apps.bea.gov/iTable/core/data/app/GetStep`, where
  BEA now serves the data service; 62,019 bytes; SHA-256
  `c9ea303119e3fc39ec412159f92494d9d32c9b4457f98ec48e0c6b944657daef`. Its
  description reads `Last Revised on: October 29, 2026 - Next Release Date
  November 25, 2026`, and it prints 2024 Q3 at 4,143,523 on line 2 and
  819,357 on line 18. It holds no 2025 or 2026 quarter. The same request to
  the old `/iTablecore/` path that day returned HTTP 200 with the site's
  28,185-byte HTML "BEA: Data Tools" page instead of JSON, which is why the
  resolver posts to `/iTable/core/` now. The fixtures above were fetched from
  the old path while it still served GetStep.

The 2026 Q2 response (`nipa-table-5-3-5-2026-q2.json`) prints 2026 Q2 in
millions at 4,623,657 on Table 5.3.5 line 2
(`Nonresidential`) and 937,772 on line 18 (`Research and development`), which
the registered 0.001 transform converts to 4,623.657 and 937.772 USD billions.
The resolver archives both fetched responses together; ALFRED remains only the
dated-vintage mirror used for history and anchor pins.
