# ACTC strategy publication failure: 35808962969, attempt 1

This directory preserves the exact available generation log, trusted selection,
and diagnostic inventory for the September 23, 2026 replacement attempt. It is
outside `records/` and is never a publisher input. Both forecasts returned
`ok: true` and empty validation errors, but publication stopped at its secret
scan. No forecasts, custody-complete run set, or recorder snapshot were published.

The diagnostic upload retained 81 files (artifact 10729375949) but deliberately
omitted three complete tool-evidence JSON files because they matched a possible
secret. Their custody commitments survive. The omitted bytes and exact original
match location are unavailable; they must never be reconstructed. The diagnostic
artifact and its expiration are listed in `failure.json`; the downloaded retained
files also remain in the task's temporary diagnostic directory.

A separate fresh fetch of the public IRS 2022 Table 3.3 workbook reproduced a
base64-only AWS-pattern match. Its SHA-256 agrees with the workbook response hash
in all three omitted stages. The new diagnostic report records its own retrieval
time. This identifies a sufficient false-positive mechanism, not the absence of
other matches and not recovery of the missing historical files. No matched
credential-shaped value is included here. The code regression uses synthetic
bytes instead of modifying or reconstructing the failed evidence.

The original failed attempt 35689483342 remains a separate preserved failure.
