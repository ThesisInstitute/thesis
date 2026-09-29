# ACTC paired proof attempt 35820167972

The workflow completed, preserved both runs and passed full custody, but it did
not produce a successful pair or new report comparison (`PUBLISHED=0`).

- The current-law run at `04-57-05z` failed the six-print history requirement
  after its revision retained four observations.
- The enacted run at `05-01-35z` has `ok:true` in its unchanged original
  manifest. Independent source inspection found its 2018 value of 18.528360
  million and 2019 value of 19.011027 million do not match the registered total
  claimant series. The latter is a narrower refundable-portion count.
- A fresh diagnostic retrieval and the existing reviewed adapter give total
  claimant counts of 20.450468 million (2018) and 19.867646 million (2019),
  at Table 3.3 `TBL33!AM10`. All six 2018–2023 workbooks parse correctly.
  Four verified anchors are cross-checks, not an availability limit.

The original records are preserved at commit
`b77c068b316b071e08838a8cecf54f70592613d2`; attestation 49430017 binds that push.
This directory contains exact available logs, selection, selected metadata and
an explicitly new source diagnostic. The diagnostic does not reconstruct or
replace any historical captured bytes or prove their original publication vintage.
The two original forecast manifests and values remain unchanged.

Diagnostic artifact 10733406016 and publication bundle 10733925150 retain the
same 84 files with zero omissions. The selected metadata audit verifies their
archive digests and commitments; it is not a local full replay. The workflow
performed the complete native event/custody checks remotely. An automatic
record-forecasts run (35821748292) was dispatched; even a signed snapshot of this
attempt would not turn it into a successful paired proof.
