# Registry enrichment fixtures

All files are real output from PolicyEngine/chronicle at commit 8c4a0f86 (ledger branch `codex/thesis-ledger-facts`, 2026-10-16). They were produced by running Chronicle's own `scripts/build_series_catalog.py` in a scratch copy of that commit.

- `base_registry.jsonl`: `ledger/series_uuid_registry.jsonl` at 8c4a0f86, verbatim (283 lines, sha256 272d8fd6b2e82151…).
- `base_catalog_docket_rows.json`: the 44 docket-only rows of `ledger/series_catalog.json` at 8c4a0f86, verbatim. Every other row is omitted.
- `cdfi_tail.jsonl`: the lines the generator appended to the registry when one usaspending.cdfi.assistance_transaction_obligations FY2026 row (country/0100000US/current, economy/aggregate) was added to `ledger/official_observations.jsonl`.
- `sweep_tail.jsonl` and `sweep_rows.json`: the same run with one row for each of the 25 docket-only rows that have a geography and no entity, apart from usaspending.dod.prime_award_obligations (25 retire + succeeds pairs). `sweep_rows.json` lists the appended row ids.
- `dod_tail.jsonl`: the lines for one usaspending.dod.prime_award_obligations FY2026 row. The generator was patched to drop `owner_key == prior_own_key` in `_plan_enrichment`; unpatched, it refuses that row before writing anything.

The rows were synthetic and the outputs are real. Only the identity fields (id, geography, entity, unit, period) mattered to the generator.
