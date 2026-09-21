# Internet Archive index fixtures

`cdx_fiscaldata_mts_2026-09.json` is the Archive's CDX index listing for
`https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/` between
2026-09-13 and 2026-09-21, read on 2026-09-21 with the query
`scripts/witness_registered_windows.py` builds (`output=json`,
`fl=timestamp,original,statuscode,mimetype,digest,length`). The rows are
verbatim. It is kept because it shows two things the witness has to handle:
`warc/revisit` rows whose status is `-`, and one revisit digest that matches a
later HTTP 200 row while the other matches nothing in the window.
