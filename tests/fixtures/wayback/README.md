# Internet Archive index fixtures

Verbatim rows of the Archive's CDX index, read with the query
`scripts/witness_registered_windows.py` builds (`output=json`,
`fl=timestamp,original,statuscode,mimetype,digest,length`). They are public
index metadata, not page content.

- `cdx_fiscaldata_mts_2026-09.json`:
  `https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/`,
  2026-09-13 to 2026-09-21, read 2026-09-21. It shows two things the witness
  has to handle: `warc/revisit` rows whose status is `-`, and one revisit
  digest that matches a later HTTP 200 row while the other matches nothing in
  the window.
- `cdx_bls_cpseea19_2026-07_09.json`:
  `https://www.bls.gov/web/empsit/cpseea19.htm`, 2026-07-10 to 2026-09-04, read
  2026-09-20. bls.gov answers non-browser clients with HTTP 403; these three
  HTTP 200 rows are the evidence for the note the witness prints beside every
  bls.gov URL.
