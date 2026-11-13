# BEA Data Archive fixtures

Official bytes from BEA's Data Archive (<https://apps.bea.gov/histdata/>) for
the 2026 Q2 advance estimate of GDP, which BEA released on 2026-07-30. Both
files are unmodified responses. Thesis fetched them after the release day, so
they are parser fixtures, not a claim that Thesis captured anything on
2026-07-30.

- `section5-2026-q2-advance.xlsx`: GET
  `https://apps.bea.gov/histdata/Files/Releases/GDP_and_PI/2026/Q2/Advance_July-30-2026/Section5all_xls.xlsx`,
  saved 2026-11-05 19:50:22 UTC; 1,807,316 bytes; SHA-256
  `5d0bc3fd1d1fe216418dc5dfe3c5737fbe240086dd5f3a2cd77d7ed6ceaf8439`. A second
  GET at 2026-11-08 18:22:35 UTC returned identical bytes with
  `content-type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`,
  `last-modified: Thu, 30 Jul 2026 13:48:02 GMT` and
  `etag: "73a973a2a20dd1:0"`. Its sheet `T50305-Q` is NIPA Table 5.3.5 as
  BEA published it that day. The sheet's fifth line reads
  `Data published July 30, 2026`, its sixth `File created Jul 29 2026 11:34AM`,
  and its newest column is `2026Q2`. It prints 4,623,657 on line 2
  (`Nonresidential`, series `A008RC`) and 937,772 on line 18
  (`Research and development\6\`, series `Y006RC`): the same millions as the
  live iTable response captured on 2026-08-07, before the second estimate
  (`tests/fixtures/ingestion_wave1/bea/nipa-table-5-3-5-2026-q2.json`).
- `index-2026-q2.json`: GET
  `https://apps.bea.gov/histdata/core/data/Fea_DisplayChildrenC/?HistMainId=7&thePath=%2FInetpub%2Fwwwroot%2Fwebsite%2Fwebsite%2FHistData%2FFiles%2FReleases%2FGDP_and_PI%5C2026%5CQ2&getFiles=false&getDirs=true`,
  the URL `bea_archive_index_url("2026-04")` builds, at 2026-11-08 18:25:21
  UTC (`content-type: application/json`); 2,469 bytes; SHA-256
  `dacf6b33932a14c73236f144451576f952207702a2e27c775686ae72eec93191`. The same
  request with lower-case percent escapes, at 18:13:02 UTC, returned identical
  bytes. The index names `National Accounts (NIPA)` and the folder pattern
  `GDP_and_PI\dataYear\Quarter\vintage_NewReleaseDate`, and lists the folders
  `Advance_July-30-2026`, `Second_August-26-2026` and
  `Third_September-30-2026`, each with a `UND` subfolder.

On 2026-11-08, before 18:10 UTC, HEAD requests for `Section5all_xls.xlsx` in
eight estimate folders each answered HTTP 200 with a `last-modified` header
dated the folder's own release day:

| Folder | `last-modified` |
|---|---|
| `2024/Q4/Advance_January-31-2025` | Fri, 31 Jan 2025 14:20:34 GMT |
| `2025/Q1/Advance_April-30-2025` | Wed, 30 Apr 2025 14:35:20 GMT |
| `2025/Q4/Advance_February-20-2026` | Fri, 20 Feb 2026 14:35:41 GMT |
| `2025/Q4/Third_April-09-2026` | Thu, 09 Apr 2026 13:40:06 GMT |
| `2026/Q1/Advance_April-30-2026` | Thu, 30 Apr 2026 19:25:08 GMT |
| `2026/Q1/Second_May-28-2026` | Thu, 28 May 2026 17:35:09 GMT |
| `2026/Q2/Advance_July-30-2026` | Thu, 30 Jul 2026 13:48:02 GMT |
| `2026/Q3/Advance_October-29-2026` | Thu, 29 Oct 2026 13:44:57 GMT |

The 2026 Q3 workbook was read by HEAD only, so its values stayed unseen until
the resolver reads them.
