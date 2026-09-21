# Anchor verifications — resolver-debt lane

## EIA U.S. natural gas vented and flared (eia.ng.vented_flared.us.annual)

Status: **VERIFIED CURRENT VINTAGE** (2026-08-13 UTC), not retrospective
first-print custody. The official keyless dnav workbook was fetched from
[`N9040US2a.xls`](https://www.eia.gov/dnav/ng/hist_xls/N9040US2a.xls) as a
31,232-byte response with SHA-256
`2097906a434f257678ed09ab34cb1a5bb6bd070b9430e0edfed3a32b738b3a92`.
Its `Contents` sheet identifies one annual series named `U.S. Natural Gas
Vented and Flared (MMcf)`, latest year 2024. On `Data 1`, cell `B2` fixes the
source key as `N9040US2`, and the header at `B3` repeats the measure and MMcf
unit.

The exact selector matches the requested four-digit year displayed by the
`YYYY`-formatted cell in column A, then reads the numeric MMcf value in column
B. These three raw workbook rows reproduce the admitted anchors without a
transform:

| Annual period | Raw workbook cells (`Data 1`) | Value (MMcf) |
|---|---|---:|
| 2022 | `A90:B90` | 271,682 |
| 2023 | `A91:B91` | 324,207 |
| 2024 | `A92:B92` | 335,163 |

The workbook and its official [dnav history
page](https://www.eia.gov/dnav/ng/hist/n9040us2a.htm) share EIA's
`Last-Modified: Tue, 28 Jul 2026 17:21:06 GMT` response header. The frozen
workbook is therefore current-vintage identity and parser evidence as of the
fetch, not proof of what EIA served when each historical value first appeared.
Forward resolution must establish first-print custody by saving the first
authenticated workbook in the registered release window that contains the
target annual row.

EIA's [Natural Gas Annual](https://www.eia.gov/naturalgas/annual/) page says
the current edition contains 2024 data and the next release is October 2026;
its [upcoming reports schedule](https://www.eia.gov/reports/upcoming.php)
independently places the Natural Gas Annual in October 2026. With no official
day, the only supported 2025 window is 2026-10-01 through 2026-10-31. The
landing page's linked [annual summary
table](https://www.eia.gov/dnav/ng/ng_sum_lsum_dcu_nus_a.htm) closes the
identity chain: its `Vented and Flared` row carries the same 2020-2024 MMcf
values and links the exact `n9040us2a.htm` history page. Thesis freezes that
59,307-byte response at SHA-256
`19990844a4f4b1b961292eaed8e59e87e2a8b3b4d065db691eb1e74f23f9eb9a`.
The frozen source and schedule responses, headers, hashes, and the API's
key-gated verdict are documented in `tests/fixtures/eia_dnav/README.md`.

## QCEW aircraft manufacturing establishments (bls.qcew.aircraft_manufacturing.establishments)

Verified 2026-07-25 (UTC) by the integrating session against the live
official source, after the lane's sandbox could not reach data.bls.gov.
Row filter: area_fips=US000, own_code=5, agglvl_code=18, size_code=0,
industry_code=336411, field=qtrly_estabs.

| Quarter | Canonical key | qtrly_estabs | Source |
|---|---|---|---|
| 2024 Q3 | 2024-07 | 1314 | https://data.bls.gov/cew/data/api/2024/3/industry/336411.csv |
| 2024 Q4 | 2024-10 | 1332 | https://data.bls.gov/cew/data/api/2024/4/industry/336411.csv |
| 2025 Q1 | 2025-01 | 1379 | https://data.bls.gov/cew/data/api/2025/1/industry/336411.csv |

The runtime gate (`qcew_anchor_mismatches`) re-fetches every anchor at
resolution time and refuses the adapter on any mismatch, so these pins are
self-checking, not trusted literals.

## QCEW child day care annual-average employment (bls.qcew.child_day_care_services.annual_avg_employment)

Verified 2026-08-12 (UTC) by the integrating session against the live official
BLS annual industry-slice endpoints. The exact selector is U.S. total
(`area_fips=US000`), private ownership (`own_code=5`), NAICS 624410,
aggregation level 18, size code 0, annual row (`qtr=A`), and field
`annual_avg_emplvl`. BLS documents the [industry-slice CSV
schema](https://www.bls.gov/cew/additional-resources/open-data/csv-data-slices.htm),
[ownership codes](https://www.bls.gov/cew/classifications/ownerships/ownership-titles.htm),
[area codes](https://www.bls.gov/cew/classifications/areas/qcew-area-titles.htm),
[aggregation levels](https://www.bls.gov/cew/classifications/aggregation/agg-level-titles.htm),
and [industry titles](https://www.bls.gov/cew/classifications/industry/industry-titles.htm).

| Year | annual_avg_emplvl | Official live slice | Response SHA-256 |
|---|---:|---|---|
| 2023 | 954,796 | [2023 annual NAICS 624410 CSV](https://data.bls.gov/cew/data/api/2023/a/industry/624410.csv) | `57418afd99c331b3921f0dcd4223363b8dff33ced09fb1be88d6683c41be1ee7` |
| 2024 | 983,412 | [2024 annual NAICS 624410 CSV](https://data.bls.gov/cew/data/api/2024/a/industry/624410.csv) | `8b1901d7e70f1b7427ff4ce0c62c809c77bdd74a226ca021d2e41cce7b63e940` |
| 2025 | 991,735 | [2025 annual NAICS 624410 CSV](https://data.bls.gov/cew/data/api/2025/a/industry/624410.csv) | `a4ebb81ec1159b1c3faa1670a32dc77598cf51178d9e17c630cb289ea568c3a9` |

The 2025 response was fetched live as the committed parser fixture (537,503
bytes, 3,490 lines). The resolver nevertheless re-fetches all three official
URLs and exactly reproduces every anchor before trusting a target response;
fixture bytes are never resolution evidence.

BLS says preliminary annual averages are published with the fourth-quarter
full-data update on its [QCEW release
calendar](https://www.bls.gov/cew/release-calendar.htm). That calendar gives
2025 Q4 a release of 10:00 a.m. ET on 2026-06-02, corroborated by the [archived
Q4 2025 release](https://www.bls.gov/news.release/archives/cewqtr_06022026.pdf).
The docket derives the 2025 expected release date from that explicit calendar
slot. As of the verification date, BLS lists Q4 2026 as “To be determined,
2027,” so the docket carries no invented 2026 date and the calendar gate
refuses to roll that period until BLS posts one.

## FSA CRP total enrolled acres (usda.fsa.crp.enrolled_acres_total)

Status: **VERIFIED** (integrator, source path reverified 2026-08-13). FSA's
old statistics URL now 301-redirects to the recovered official landing page:

https://www.fsa.usda.gov/tools/informational/reports/conservation-statistics/crp

The recovered page returned 200 and exposes a `Monthly Summaries` table. Each
target Month/Year row's `Summary` cell links a dated `/documents/...` page,
which links the `/sites/default/files/YYYY-MM/...pdf` artifact. The adapter
authenticates and fetches exactly that three-hop chain without redirects; the
old `/resources/programs/conservation-reserve-program/statistics` path is
historical evidence and is deliberately refused as an adapter entry point.

Three anchors are read directly from the official page-1 TOTAL CRP Acres cell:

- 2025-11: 26,317,011 acres — https://www.fsa.usda.gov/sites/default/files/2026-03/CRPMonthlyNovember2025WithPageNumbers.pdf
- 2026-03: 26,203,615 acres — https://www.fsa.usda.gov/sites/default/files/2026-06/CRPMonthlyMarch2026WithPageNumbers.pdf
- 2026-04: 26,182,019 acres — https://www.fsa.usda.gov/sites/default/files/2026-07/CRPMonthlyApril2026WithPageNumbers.pdf

Protocol notes: use the printed TOTAL CRP Acres cell, never derived sums
(March cross-foots one acre under the printed total because FSA sums unrounded
acreage). Publication lag is about three months (April's summary is stored
under `/2026-07/`), so the fresh target uses a reviewed outer release bound
rather than inferring a day from cadence. Runtime resolution re-fetches and
exactly reproduces all three admitted anchors before reading a target month.

The 2026-08-13 recovery fixtures archive the exact landing HTML (121,040
bytes, SHA-256
`f0e572b484359368042634d7413937acd174d53434667f55b092382b8a73c181`),
April document HTML (62,639 bytes, SHA-256
`6b076bd7e94e13bc3d32ddf9663c80201c2c94f6a1c3eebf6ce4a5ce064df695`),
and April PDF (5,356,828 bytes, SHA-256
`03ac66bd80f263cdaa221295eb17963fbb9be0574b846fd11f6024ca0ee4e373`).
The artifact is the April 2026 observation vintage, created/modified in July
2026, and prints 26,182,019 acres. See
`tests/fixtures/fsa_crp/README.md` for URLs, HTTP metadata, and the archived
stale-path 301 response.

## CPI-U annual average (bls.cpi.u.annual_pct_change)

The lane pinned 2022=8.0, 2023=4.1, 2024=2.9, 2025=2.6 (annual-average
percent change). The first three match BLS's published annual averages;
all four are recomputed from live monthly data by
`bls_annual_anchor_mismatches` at resolution time, which refuses on drift.

---

# Anchor verifications — ALFRED US docket expansion

Verified 2026-07-25 by the integrating session through the resolver's
own transport (alfredgraph.csv vintage CSV) after the drafting sandbox
could not reach ALFRED. Each series carries three anchors: the value the
adapter produces at a historical vintage inside (or, where flagged, just
after) the period's first-print window, alongside today's revised value.
Every anchor is reproducible by anyone from the same public vintages.
`VERIFIED-LATE-VINTAGE` = one of the three anchors was only reachable at
a vintage past the first-release window and may reflect a revised print;
the transport, series id, and transform are proven regardless, and
forward resolution always captures inside the release window.

| Series | ALFRED id | Status | Anchors (period → first-print @ vintage) |
|---|---|---|---|
| `bea.trade.goods_services_deficit` | `BOPGSTB` | VERIFIED | 2026-02→-57347.0@2026-04-20; 2026-03→-60307.0@2026-05-20; 2026-04→-55881.0@2026-06-20 |
| `bls.ces.average_hourly_earnings_private` | `CES0500000003` | VERIFIED | 2026-03→0.241352@2026-04-30; 2026-04→0.160643@2026-05-31; 2026-05→0.32077@2026-06-30 |
| `bls.cpi.owners_equivalent_rent_mom` | `CUSR0000SEHC` | VERIFIED | 2026-03→0.284067@2026-04-30; 2026-04→0.532661@2026-05-31; 2026-05→0.296783@2026-06-30 |
| `bls.cpi.rent_primary_residence_mom` | `CUSR0000SEHA` | VERIFIED | 2026-03→0.190103@2026-04-30; 2026-04→0.545058@2026-05-31; 2026-05→0.361927@2026-06-30 |
| `bls.cpi.services_less_energy_mom` | `CUSR0000SASLE` | VERIFIED | 2026-03→0.225476@2026-04-30; 2026-04→0.499602@2026-05-31; 2026-05→0.294706@2026-06-30 |
| `bls.cpi.services_less_rent_shelter_mom` | `CUSR0000SASL2RS` | VERIFIED | 2026-03→0.334302@2026-04-30; 2026-04→0.384796@2026-05-31; 2026-05→0.548374@2026-06-30 |
| `bls.cpi.shelter_mom` | `CUSR0000SAH1` | VERIFIED | 2026-03→0.266467@2026-04-30; 2026-04→0.606741@2026-05-31; 2026-05→0.317831@2026-06-30 |
| `bls.cps.u6_underemployment_rate` | `U6RATE` | VERIFIED | 2026-03→8.0@2026-04-30; 2026-04→8.2@2026-05-31; 2026-05→8.1@2026-06-30 |
| `bls.eci.private_wages_salaries_qoq` | `ECIWAG` | VERIFIED-LATE-VINTAGE | 2025-04→1.027939@2025-08-15; 2025-10→0.731049@2026-02-15; 2025-07→0.799696@2025-12-15 ⚠︎late |
| `bls.eci.total_compensation_private_industry_qoq` | `ECICOM` | VERIFIED-LATE-VINTAGE | 2025-04→0.964539@2025-08-15; 2025-10→0.732326@2026-02-15; 2025-07→0.795518@2025-12-15 ⚠︎late |
| `bls.export_prices.all_commodities_mom` | `IQ` | VERIFIED | 2026-03→1.641414@2026-04-30; 2026-04→3.29602@2026-05-31; 2026-05→1.261261@2026-06-30 |
| `bls.import_price_index.all_imports_mom` | `IR` | VERIFIED | 2026-03→0.766551@2026-04-30; 2026-04→1.933702@2026-05-31; 2026-05→1.895735@2026-06-30 |
| `bls.jolts.hires_rate` | `JTSHIR` | VERIFIED | 2026-02→3.1@2026-04-20; 2026-03→3.5@2026-05-20; 2026-04→3.2@2026-06-20 |
| `bls.lns11300000` | `CIVPART` | VERIFIED | 2026-03→61.9@2026-04-30; 2026-04→61.8@2026-05-31; 2026-05→61.8@2026-06-30 |
| `bls.ppi.final_demand_monthly_change` | `PPIFIS` | VERIFIED | 2026-03→0.512332@2026-04-30; 2026-04→1.375897@2026-05-31; 2026-05→1.056336@2026-06-30 |
| `bls.productivity.nonfarm_unit_labor_costs_qoq_prelim` | `PRS85006112` | VERIFIED-LATE-VINTAGE | 2025-04→1.0@2025-09-15; 2025-10→2.8@2026-03-15; 2025-07→-1.9@2026-01-14 ⚠︎late |
| `census.construction_spending.total_mom` | `TTLCONS` | VERIFIED-LATE-VINTAGE | 2026-03→0.564239@2026-05-20; 2026-04→0.366047@2026-06-20; 2026-02→-0.224922@2026-05-20 ⚠︎late |
| `census.housing.completions_saar` | `COMPUTSA` | VERIFIED | 2026-03→1366.0@2026-04-30; 2026-04→1449.0@2026-05-31; 2026-05→1313.0@2026-06-30 |
| `census.housing.permits_saar` | `PERMIT` | VERIFIED | 2026-03→1372.0@2026-04-30; 2026-04→1423.0@2026-05-31; 2026-05→1410.0@2026-06-30 |
| `census.housing_starts.saar` | `HOUST` | VERIFIED | 2026-03→1502.0@2026-04-30; 2026-04→1465.0@2026-05-31; 2026-05→1177.0@2026-06-30 |
| `census.m3.durable_goods_new_orders_mom` | `DGORDER` | VERIFIED | 2026-03→0.832891@2026-04-30; 2026-04→7.946631@2026-05-31; 2026-05→-4.478479@2026-06-30 |
| `census.m3.durable_goods_shipments_mom` | `AMDMVS` | VERIFIED | 2026-03→0.684932@2026-04-30; 2026-04→0.537878@2026-05-31; 2026-05→0.993027@2026-06-30 |
| `census.mtis.total_business_inventories_level` | `BUSINV` | VERIFIED-LATE-VINTAGE | 2026-03→2709734.0@2026-05-20; 2026-04→2726588.0@2026-06-20; 2026-02→2686792.0@2026-05-02 ⚠︎late |
| `census.new_residential_sales.new_single_family_houses_sold_saar` | `HSN1F` | VERIFIED-LATE-VINTAGE | 2026-04→622.0@2026-05-31; 2026-05→580.0@2026-06-30; 2026-02→635.0@2026-05-05 ⚠︎late |
| `fed.g17.capacity_utilization.manufacturing` | `MCUMFN` | VERIFIED | 2026-03→75.2054@2026-04-30; 2026-04→75.6621@2026-05-31; 2026-05→75.5701@2026-06-30 |
| `fed.g17.capacity_utilization.total_industry` | `TCU` | VERIFIED | 2026-03→75.6596@2026-04-30; 2026-04→76.1194@2026-05-31; 2026-05→76.1663@2026-06-30 |
| `fed.g17.industrial_production.total_index_mom` | `INDPRO` | VERIFIED | 2026-03→-0.541507@2026-04-30; 2026-04→0.678054@2026-05-31; 2026-05→0.13511@2026-06-30 |
| `fed.g17.manufacturing_production_mom` | `IPMAN` | VERIFIED | 2026-03→-0.167076@2026-04-30; 2026-04→0.615175@2026-05-31; 2026-05→0.048992@2026-06-30 |
| `fed.g19.consumer_credit_nonrevolving_annual_rate` | `NONREVSLAR` | VERIFIED | 2026-02→2.79@2026-04-20; 2026-03→4.69@2026-05-20; 2026-04→2.88@2026-06-20 |
| `fed.g19.consumer_credit_revolving_annual_rate` | `REVOLSLAR` | VERIFIED | 2026-02→0.64@2026-04-20; 2026-03→9.07@2026-05-20; 2026-04→10.44@2026-06-20 |
| `fed.g19.consumer_credit_total_annual_rate` | `TOTALSLAR` | VERIFIED | 2026-02→2.23@2026-04-20; 2026-03→5.83@2026-05-20; 2026-04→4.85@2026-06-20 |

Raw results: anchor_results.json (kept out of the commit; the table above is the record).

## BEA private nonresidential fixed investment

Status: **VERIFIED** (integrator, 2026-08-07 UTC). ALFRED metadata identifies
`PNFI` as quarterly private nonresidential fixed investment in billions of
dollars at a seasonally adjusted annual rate. Three exact-period ALFRED
responses preserve genuine first prints:

| Observation | First vintage | Value (USD billions, SAAR) | Frozen fixture | SHA-256 |
|---|---|---:|---|---|
| 2025 Q2 (`2025-04-01`) | 2025-07-30 | 4,203.220 | `pnfi-2025-q2-first-print.csv` (51 bytes) | `9f550bc31dca1359e70ddf7e9588ef9b67c901ed3eed1c1da8b610aad37b890f` |
| 2025 Q3 (`2025-07-01`) | 2025-12-23 | 4,291.558 | `pnfi-2025-q3-first-print.csv` (51 bytes) | `b588e9e3e0735b6a145285c529c02344f037303249b175d33a301e39b7f38a52` |
| 2025 Q4 (`2025-10-01`) | 2026-02-20 | 4,378.954 | `pnfi-2025-q4-first-print.csv` (51 bytes) | `05b9718a7ab180b5f8aa5028dbdc04291f5e76c69ebacd0214239d5c57d4df92` |

[BEA's official 2025-07-30 advance
release](https://www.bea.gov/news/2025/gross-domestic-product-2nd-quarter-2025-advance-estimate)
authenticates the Q2 first-print date. Its [shutdown-delayed 2025-12-23 initial
estimate](https://www.bea.gov/news/2025/gross-domestic-product-3rd-quarter-2025-initial-estimate-and-corporate-profits)
explicitly replaced the canceled Q3 advance and second estimates, so it is the
first Q3 print. The [2026-02-20 advance
release](https://www.bea.gov/news/2026/gdp-advance-estimate-4th-quarter-and-year-2025)
authenticates Q4. Fresh preceding-day ALFRED parses confirmed each observation
row was absent; the request verification records those response hashes and
last available dates. The executable fixture test therefore clears the
three-first-print admission gate.

The ALFRED history mirror is already in `usd_billions` and uses identity for
these pins. The official `bea-release` runtime binding reads BEA's
million-dollar Table 5.3.5 line 2 and multiplies by 0.001 into `usd_billions`.
The official BEA schedule was re-fetched the same session and still lists
`GDP (Advance Estimate), 3rd Quarter 2026` for 2026-10-29 at 8:30 AM ET, so
the quarterly seed uses the default `release-calendar` basis.

## BEA private research and development fixed investment

Status: **VERIFIED** (integrator, 2026-08-07 UTC). ALFRED metadata identifies
`Y006RC1Q027SBEA` as quarterly private research and development fixed
investment in billions of dollars at a seasonally adjusted annual rate. The
same three BEA first-release dates yield three independently frozen pins:

| Observation | First vintage | Value (USD billions, SAAR) | Frozen fixture | SHA-256 |
|---|---|---:|---|---|
| 2025 Q2 (`2025-04-01`) | 2025-07-30 | 821.083 | `bea-rd-2025-q2-first-print.csv` (61 bytes) | `555e5af679223e3365edff09947b29e6d1e78e4ed978cd7553d15da3730ac61e` |
| 2025 Q3 (`2025-07-01`) | 2025-12-23 | 855.863 | `bea-rd-2025-q3-first-print.csv` (61 bytes) | `25499799f3ed33b75e0a715248a83fa7d865a5ff84c323fd4f5cfceff3cee2c6` |
| 2025 Q4 (`2025-10-01`) | 2026-02-20 | 885.955 | `bea-rd-2025-q4-first-print.csv` (61 bytes) | `1e7e49c3d4c3468182298f1ec511bb38cafbb1a96d0a83a3f62414b729de01f1` |

The same official Q2 advance, shutdown-delayed Q3 initial, and Q4 advance
release notices authenticate the vintage dates. Fresh preceding-day ALFRED
parses confirmed that each exact observation row was absent. The request
verification records those absence checks, and the executable test reproduces
all three values and hashes.

The ALFRED history mirror is already in `usd_billions` and uses identity for
these pins. The official `bea-release` runtime binding reads BEA's
million-dollar Table 5.3.5 line 18 and multiplies by 0.001 into `usd_billions`.
The official BEA schedule was re-fetched the same session and still lists
`GDP (Advance Estimate), 3rd Quarter 2026` for 2026-10-29 at 8:30 AM ET, so
the quarterly seed uses the default `release-calendar` basis.

## BEA ITA personal-transfer payments

Status: **VERIFIED CURRENT PRINT** (integrator, 2026-08-12 UTC), not a
retrospective first-print-custody claim. A fresh exact POST to BEA's
[International Transactions Table 5.1 iTable](https://apps.bea.gov/iTable/?ReqID=62&step=6&isuri=1&tablelist=62&product=1)
used application 62, product 1, table-list 62, the prompt-catalog key that
mapped to 2026, quarterly seasonally adjusted selector 1, and line selector
18. The canonical 123-byte selected request had SHA-256
`752aff73c31aec17c829529964998148d805d2b060f48513ea9afbf7c290f3d9`;
the 16,089-byte response had SHA-256
`d482e10713b19c01824882b6e6f7ee01d06619222d35b27cb6f97fa95fdf0f35`
and printed `18,511` million dollars for 2026 Q1 at line 18, `Personal
transfers`. The exact response is the decoded content of
`tests/fixtures/ingestion_wave1/bea/ita-table-5-1-2026-q1-qsa.json.base64`.
The separately archived unfiltered prompt catalog is 84,950 bytes with
SHA-256
`9da6f369b0182f85102a9f5b83518ba0e0afaf6065f698f9cb69a5e319156b36`.
A live Product 5 replay returned byte-identical response bytes, so Product 1
is outbound-request custody only; the response does not authenticate it.

BEA's [2026 Q1 ITA/IIP release
notice](https://www.bea.gov/news/2026/us-international-transactions-and-investment-position-1st-quarter-2026-and-annual-update)
authenticates the June 24, 2026 release date, title, and release family. Since
the fixture was fetched later, it proves the table identity and parser path
but not the bytes served on June 24. The adapter therefore admits the value
only as a historical validation anchor and will capture future tables solely
on the registered release day. BEA's [official release
schedule](https://www.bea.gov/news/schedule) lists `U.S. International
Transactions and Investment Position, 2nd Quarter 2026` for September 24,
2026 at 8:30 AM, which supplies the Q2 seed's release-calendar date.

---

# USAspending FY2026 query anchors

Checked 2026-07-24. These are transaction-level, awarding-agency queries for
prime contract award type codes `A`, `B`, `C`, and `D`, with action dates from
2025-10-01 through 2026-09-30. The reviewed source bindings preserve these
query plans in `scripts/docket_series.json`; the resolver reconstructs the
requests from those bindings and refuses any seven-key registry drift.

The current official endpoint contracts confirm that
`/api/v2/search/spending_by_category/recipient/` is a POST endpoint with
recipient IDs and `page_metadata.hasNext`, and that
`/api/v2/search/spending_over_time/` is a POST endpoint returning
`aggregated_amount` by fiscal year:

- https://raw.githubusercontent.com/fedspendingtransparency/usaspending-api/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_category/recipient.md
- https://raw.githubusercontent.com/fedspendingtransparency/usaspending-api/master/usaspending_api/api_contracts/contracts/v2/search/spending_over_time.md

The current official website mapping identifies `small_business` as the
API token for “Small Business”:

- https://github.com/fedspendingtransparency/usaspending-website/blob/master/src/js/dataMapping/search/recipientType.js

## DHS Title VI award-transaction obligations

Checked 2026-08-06 against
`https://api.usaspending.gov/api/v2/search/spending_over_time/`. The reviewed
POST plan fixes all award-type codes and filters award transactions to five
Title VI Treasury-account components (`070-0530`, `070-0532`, `070-0509`,
`070-0510`, and `070-0413`), each with 2025/2029 availability and subaccount
`000`, plus dedicated account `070-0722`. The fiscal-year action-date bounds
are derived mechanically.

The unmodified FY2026 response is the 1,146-byte fixture
`tests/fixtures/ingestion_wave1/usaspending/dhs-title-vi-fy2026.json`, SHA-256
`dd51e2eb947fc8b302fe9c33297c85989b542c933801dcb0729edf39ba157720`.
It contains one FY2026 award-transaction row with `aggregated_amount`
**32,171,899,636.26 USD**. A same-day replay returned byte-identical evidence.
This fixture verifies the award-transaction query and parser; it does not
represent all obligations recorded in the named financial accounts. The
target outcome remains the separately captured response inside the registered
2026-10-15 through 2026-10-22 snapshot window, not a first-print claim.

## Unique identifiable prime-contract recipients

Endpoint:
`https://api.usaspending.gov/api/v2/search/spending_by_category/recipient/`

Canonical first-page body (subsequent bodies change only `page`):

```json
{"category":"recipient","filters":{"agencies":[{"name":"Department of Defense","tier":"toptier","type":"awarding"}],"award_type_codes":["A","B","C","D"],"time_period":[{"end_date":"2026-09-30","start_date":"2025-10-01"}]},"limit":100,"page":1,"spending_level":"transactions"}
```

Derivation: retrieve pages through the first response with `hasNext: false`,
then count distinct, non-null `results[].recipient_id` values. This excludes
the API’s null-ID aggregate such as `MULTIPLE RECIPIENTS`. The metric therefore
counts identifiable USAspending recipient-profile IDs, not adjudicated legal
entities.

Probe value: **not obtained**. At 2026-07-24T18:03:41Z the exact POST attempt
failed before connection with `Could not resolve host:
api.usaspending.gov`. The separate network runtime also returned `fetch
failed`, and no controllable signed-in browser session was available.

## Small-business share of prime-contract obligations

Endpoint:
`https://api.usaspending.gov/api/v2/search/spending_over_time/`

Canonical denominator body:

```json
{"filters":{"agencies":[{"name":"Department of Defense","tier":"toptier","type":"awarding"}],"award_type_codes":["A","B","C","D"],"time_period":[{"end_date":"2026-09-30","start_date":"2025-10-01"}]},"group":"fiscal_year","spending_level":"transactions"}
```

Canonical numerator body:

```json
{"filters":{"agencies":[{"name":"Department of Defense","tier":"toptier","type":"awarding"}],"award_type_codes":["A","B","C","D"],"recipient_type_names":["small_business"],"time_period":[{"end_date":"2026-09-30","start_date":"2025-10-01"}]},"group":"fiscal_year","spending_level":"transactions"}
```

Derivation: select the unique FY2026 `aggregated_amount` from each response and
compute `100 * numerator / denominator`. The resolver refuses missing,
duplicate, non-finite, negative, zero-denominator, or numerator-above-
denominator inputs.

Probe values:

- All DoD prime-contract obligations: **not obtained**
- Small-business DoD prime-contract obligations: **not obtained**
- Derived share: **not obtained**

The same 2026-07-24 network constraint blocked both exact POSTs. The
brief’s 2026-07-15 `$246.9B` FY2026-to-date reference is deliberately not
carried forward as a current value or substituted for the contract-only
denominator.

## Landing check

Before landing, rerun the three canonical POST bodies above in a networked
review environment and record the timestamped recipient count, numerator,
denominator, and derived percentage here. No code path treats an unverified
anchor as a resolved outcome: the production resolver will run only inside the
preregistered 2026-10-15 through 2026-10-22 snapshot window and archives every
request body and response.

---

# Census SPM corrected-methodology anchors

Status: **pending; adapter deliberately unarmed**.

Census's [17 July 2026 statement](https://www.census.gov/newsroom/press-releases/2026/statement-on-supplemental-poverty-measure.html)
authenticates the identity of a forthcoming correction to the 2019–2024
Supplemental Poverty Measure estimates. It does not authenticate the Thesis
lab's CY2027 release window or resolve-by deadline. As of 5 August 2026, the
promised corrected working-paper values were not yet public, so
`census.spm.child_poverty_rate` remains `PENDING_REVISED_PRINT` and refuses all
network resolution attempts.

The adapter is admitted only after an integrator verifies the complete six-year
2019–2024 vector from the corrected official artifact. The 2019 and 2020 child
rates must discriminate the corrected series from the known legacy transition
values: 2019 cannot be 12.5% or 12.6%, and 2020 cannot be 9.7%.

Two official Table B-2 workbooks are committed as parser and rejection
fixtures, not as corrected anchors:

| Vintage | Official workbook | Bytes | SHA-256 | Parsed child series |
| --- | --- | ---: | --- | --- |
| P60-283 | [Table B-2](https://www2.census.gov/programs-surveys/demo/tables/p60/283/tableB-2.xlsx) | 41,756 | `c5938c06302e547583d35fc8d1480b6b726b288501c46b99d5965f517b4a245e` | 2019 12.6%; 2020 9.7%; 2021 5.2%; 2022 12.4%; 2023 13.7% |
| P60-287 | [Table B-2](https://www2.census.gov/programs-surveys/demo/tables/p60/287/tableB-2.xlsx) | 43,484 | `8cdb688380c543c1bd3bc47e2124ec6872511eff8c03c8340b1adacdbd1525fe` | Same through 2023; 2024 13.4% |

Both vintages contain two ALL RACES 2019 rows. The parser selects the 12.6%
row only after matching its footnote to the workbook text that explicitly says
the row implements revised SPM methodology; it refuses ambiguity if that
footnote identity is absent or duplicated. The plain 12.5% row remains visible
as legacy rejection evidence.

---

# International adapter anchor verification

Verified on 25 July 2026. An adapter is executable only when its parser and
transform reproduce at least three recent official first prints from captured
official response bytes. The `got` column below is the value produced by
`scripts/resolve_pending.py` from the corresponding trimmed fixture in
`tests/fixtures/international/`; it is not copied from the expected value.
Fixture provenance and the SHA-256 of each full archived response are recorded
in `tests/fixtures/international/README.md`.

Aliases that share the same source identifier, parser, transform, and fixture
count as one `(series, adapter)` pair. Five unique pairs (12 data-point-id
stems) pass the admission rule. These fixed periods are immutable admission
evidence, not recurring live sentinels: bounded latest-N responses eventually
age them out. Live execution instead requires the exact response
vector/dataflow/dataset identity, registered unit and binding, official release
window, and (for Eurostat flash) estimate status.

| Pair | Executable stems | Official request | Release calendar |
| --- | --- | --- | --- |
| Statistics Canada CPI all-items YoY | `statcan.cpi.allitems.yoy`; `statcan.cpi.all_items_annual_rate.canada` | WDS vector `41690973` | [Statistics Canada 2026 release dates](https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf) |
| Statistics Canada monthly GDP growth | `statcan.gdp_by_industry.monthly_growth`; `statcan.36-10-0434-01.all_industries.month_to_month_percent_change` | WDS vector `65201210` | [Statistics Canada 2026 release dates](https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf) |
| ABS monthly CPI annual rate | `abs.cpi.all_groups.yoy`; `abs.cpi.all_groups_annual_rate.australia`; `abs.cpi_indicator.allgroups.yoy` | `CPI/3.10001.10.50.M` | [Consumer Price Index, Australia](https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia) |
| ABS unemployment rate, seasonally adjusted | `abs.labour.unemployment_rate`; `abs.labour.unemployment_rate.australia` | `LF/M13.3.1599.20.AUS.M` | [Labour Force, Australia](https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia) |
| Eurostat euro-area HICP flash YoY | `eurostat.hicp.flash.yoy`; `eurostat.ea.hicp.flash.yoy`; `eurostat.hicp.all_items_annual_rate.euro_area` | `prc_hicp_minr/M.RCH_A.TOTAL.EA21` | [Euro indicators release calendar](https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar) |

## Verified first prints

| Pair | Period | Expected | Got | Official first-print evidence |
| --- | --- | ---: | ---: | --- |
| Statistics Canada CPI all-items YoY | 2026-02 | 1.8 | 1.8 | [The Daily, 16 March 2026](https://www150.statcan.gc.ca/n1/daily-quotidien/260316/dq260316a-eng.htm) |
| Statistics Canada CPI all-items YoY | 2026-03 | 2.4 | 2.4 | [The Daily, 20 April 2026](https://www150.statcan.gc.ca/n1/daily-quotidien/260420/dq260420a-eng.htm) |
| Statistics Canada CPI all-items YoY | 2026-04 | 2.8 | 2.8 | [The Daily, 19 May 2026](https://www150.statcan.gc.ca/n1/daily-quotidien/260519/dq260519a-eng.htm) |
| Statistics Canada CPI all-items YoY | 2026-05 | 3.2 | 3.2 | [The Daily, 22 June 2026](https://www150.statcan.gc.ca/n1/daily-quotidien/260622/dq260622a-eng.htm) |
| Statistics Canada monthly GDP growth | 2026-02 | 0.2 | 0.2 | [The Daily, 30 April 2026](https://www150.statcan.gc.ca/n1/daily-quotidien/260430/dq260430a-eng.htm) |
| Statistics Canada monthly GDP growth | 2026-03 | -0.1 | -0.1 | [The Daily, 29 May 2026](https://www150.statcan.gc.ca/n1/daily-quotidien/260529/dq260529b-eng.htm) |
| Statistics Canada monthly GDP growth | 2026-04 | 0.5 | 0.5 | [The Daily, 30 June 2026](https://www150.statcan.gc.ca/n1/daily-quotidien/260630/dq260630a-eng.htm) |
| ABS monthly CPI annual rate | 2026-02 | 3.7 | 3.7 | [Monthly CPI, February 2026](https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/monthly-consumer-price-index-indicator/feb-2026) |
| ABS monthly CPI annual rate | 2026-03 | 4.6 | 4.6 | [Monthly CPI, March 2026](https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/monthly-consumer-price-index-indicator/mar-2026) |
| ABS monthly CPI annual rate | 2026-04 | 4.2 | 4.2 | [Monthly CPI, April 2026](https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/monthly-consumer-price-index-indicator/apr-2026) |
| ABS monthly CPI annual rate | 2026-05 | 4.0 | 4.0 | [Monthly CPI, May 2026](https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/monthly-consumer-price-index-indicator/may-2026) |
| ABS unemployment rate, seasonally adjusted | 2026-03 | 4.3 | 4.3 | [Labour Force, March 2026](https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/mar-2026) |
| ABS unemployment rate, seasonally adjusted | 2026-04 | 4.5 | 4.5 | [Labour Force, April 2026](https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/apr-2026) |
| ABS unemployment rate, seasonally adjusted | 2026-05 | 4.4 | 4.4 | [Labour Force, May 2026](https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/may-2026) |
| Eurostat euro-area HICP flash YoY | 2026-04 | 3.0 | 3.0 | [Eurostat flash estimate, 30 April 2026](https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-30042026-ap) |
| Eurostat euro-area HICP flash YoY | 2026-05 | 3.2 | 3.2 | [Eurostat flash estimate, 2 June 2026](https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-02062026-ap) |
| Eurostat euro-area HICP flash YoY | 2026-06 | 2.8 | 2.8 | [Eurostat flash estimate, 1 July 2026](https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-01072026-ap) |

Statistics Canada CPI and ABS original-series CPI are treated as non-revised
apart from explicit corrections. Statistics Canada GDP and ABS Labour Force
can revise: the archived API payload proves parser agreement, the period's
release page establishes the first print, and resolution is limited to the
registered first-print window. Eurostat flash resolution additionally requires
the target observation's estimate flag (`e`); the June fixture retains it.

For recurring docket targets, `scripts/docket_series.json` records exact
period-to-release-date mappings from the calendar linked above. The roller
copies that date into `expectedReleaseDate`; registration creates an exact
one-day release window and refuses native targets without a valid HTTPS
calendar citation. A period missing from the finite published schedule is
skipped rather than extrapolated from cadence.

## Explicitly unverified

ABS published a June 2026 seasonally adjusted unemployment rate of 4.4 on
[23 July 2026](https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/jun-2026),
but the real ABS API response archived on 10 July ends at May. Network access
to `data.api.abs.gov.au` was unavailable after the June release. June is
therefore **UNVERIFIED through the adapter**, has no `got` value, and is not in
the executable adapter's anchor set. No release-page value was projected into
synthetic API JSON.

The following candidate families are also **UNVERIFIED and not executable**.
Candidate metadata or values observed on a current page do not substitute for
three captured first-print payloads.

| Agency | Candidate series | Admission blocker |
| --- | --- | --- |
| Statistics Canada | LFS unemployment rate, LFS employment change, EI regular beneficiaries | Fewer than three captured release-vintage payloads proving first-print extraction for each revision-prone series |
| ABS | Employment change, quarterly CPI, total-dwellings building approvals | No three-period captured fixture set; the approvals release-page snapshot covers only one period |
| Eurostat | Unemployment, industrial production, construction production, retail volume | No three-period captured first-print fixture set for the exact candidate |
| ONS | CPI, claimant count, retail sales, public-sector net borrowing | No captured ONS JSON fixture set; current mutable series are insufficient for revision-prone first prints |
| Statistics Bureau of Japan / e-Stat | Tokyo CPI, national LFS, household spending | The e-Stat JSON API requires an application ID per the [official API documentation](https://www.e-stat.go.jp/api/api/api/index.php/en/api-dev/how_to_use). Per the lane contract, no e-Stat adapter or release-artifact parser was added. |

## IRS SOI Publication 1304 Table 3.3 ACTC claimant returns (irs.actc.total_claims)

Status: **VERIFIED** (integrator, 2026-08-01). Four anchors read directly
off the official Publication 1304 Table 3.3 workbooks, live-fetched from
www.irs.gov and parsed at the "All returns, total" row's "Number of
returns" column under the "Refundable child tax credit or additional child
tax credit" header ("Additional child tax credit" in the TY2020 print —
the same statistic under IRS's pre-ARPA label). Values are printed
whole-return counts, never derived sums; the registered transform divides
by 1,000,000 for the millions-unit cells.

- TY2020: 19,119,249 returns — https://www.irs.gov/pub/irs-soi/20in33ar.xls
- TY2021: 37,771,612 returns — https://www.irs.gov/pub/irs-soi/21in33ar.xls
  (ARPA policy-anomaly year: fully refundable credit, no earned-income floor)
- TY2022: 18,076,696 returns — https://www.irs.gov/pub/irs-soi/22in33ar.xls
- TY2023: 17,626,084 returns — https://www.irs.gov/pub/irs-soi/23in33ar.xls

The workbooks fetched on 2026-08-01 are frozen as parser fixtures under
`tests/fixtures/irs_soi_pub1304/` (SHA-256):

- `20in33ar.xls` 7abb8cf1f6f124e1ef481db562d622f46155effe98dad72bd82d0844996dabaa
- `21in33ar.xls` b8e3e7ca7bc048dca2b554e78359e4944ce429b4a58c5ea9cbc7e39d71f7ea75
- `22in33ar.xls` f04012c527c5bf40e412e112597038d70fd79c017d9476c07eebc3b59e3766a4
- `23in33ar.xls` e749d3e9636d9784e2a5e8639f49ce5389a4ca0aaeedca6c671cee0b71264c04

The runtime gate (`irs_soi_pub1304_anchor_mismatches`) re-fetches every
anchor workbook at resolution time and refuses the adapter on any
mismatch, so these pins are self-checking, not trusted literals. The same
counts (divided to millions) are pinned as `anchors` in the docket entry's
target context, so a preregistered analyst run whose fetched base-rate
history contradicts the official prints fails validation at spawn time.

The `{yy}in33ar.xls` URLs are tax-year-specific but not versioned. These
fixtures verify parser identity and the values retrieved on their stated
dates; the URL shape alone does not authenticate release-time first-print
custody. Future resolution therefore captures only inside the registered
window and fails closed afterward. Late resolution would require a future
adapter that authenticates witnessed or versioned first-print custody.

## IRS SOI Table 3.3 clean vehicle credit claimant returns

Status: **VERIFIED** (integrator, 2026-08-06). The same four official
Publication 1304 workbooks and hashes above reproduce the positive whole-return
count in the `All returns, total` row under `Number of returns`. The exact
concept label is `Qualified plug-in electric vehicle credit` for TY2020–2022
and `Clean vehicle credit` for TY2023:

- TY2020: 61,793 returns (`20in33ar.xls`, `TBL33!AC10`)
- TY2021: 166,244 returns (`21in33ar.xls`, `TBL33!AE10`)
- TY2022: 248,052 returns (`22in33ar.xls`, `TBL33!AE10`)
- TY2023: 493,953 returns (`23in33ar.xls`, `TBL33!AE10`)

The registered transform is identity (`factor: 1`) and the target unit is
`count`. The official 2026 SOI release-list workbook, fetched 2026-08-06
(36,090 bytes; SHA-256
`5ceb7a39fe09f0f12416da0e3eb3b80a227eb4475c8f9fe776ebbfab47070f1e`),
contains one Publication 1304 row: program year 2023, released 2026-03-26. It
contains no TY2024 row or future exact date. The TY2027 docket target therefore
uses a conservative Publication 1304 resolve-by window
(`2029-01-01`–`2030-12-31`); no day is inferred from annual cadence. The outer
bound allows more than the roughly 27 months between the end of TY2023 and
the official 2026-03-26 release, avoiding a scoring split before a comparably
lagged TY2027 print.

## IRS SOI Table 3.3 clean vehicle credit total credit amount

Status: **VERIFIED** (integrator, 2026-08-06). The same four official
Publication 1304 workbooks and SHA-256 pins above reproduce the positive
whole-thousand-dollar amount in the `All returns, total` row under `Amount`.
The exact concept label is `Qualified plug-in electric vehicle credit` for
TY2020–2022 and `Clean vehicle credit` for TY2023:

- TY2020: 313,118 thousand dollars = 313.118 USD millions
  (`20in33ar.xls`, `TBL33!AD10`)
- TY2021: 1,037,358 thousand dollars = 1,037.358 USD millions
  (`21in33ar.xls`, `TBL33!AF10`)
- TY2022: 1,652,554 thousand dollars = 1,652.554 USD millions
  (`22in33ar.xls`, `TBL33!AF10`)
- TY2023: 3,231,102 thousand dollars = 3,231.102 USD millions
  (`23in33ar.xls`, `TBL33!AF10`)

The parser authenticates the complete thousand-dollar declaration at
`TBL33!A2` before reading the adjacent `Amount` subcolumn. The registered
transform multiplies the printed integer by `0.001` with no further rounding.
The TY2027 target uses the same reviewed Publication 1304 resolve-by window
documented above; no exact future release day is inferred from cadence.

## IRS SOI Table 3.3 ACTC total credit amount

Status: **VERIFIED** (integrator, 2026-08-06). The same four official
Publication 1304 workbooks and hashes above reproduce the positive
whole-thousand-dollar amount in the `All returns, total` row under `Amount`.
The accepted concept label is `Additional child tax credit` for TY2020 and
`Refundable child tax credit or additional child tax credit` for TY2021–2023:

- TY2020: 33,664,804 thousand dollars = 33,664.804 USD millions
  (`20in33ar.xls`, `TBL33!AN10`)
- TY2021: 115,869,125 thousand dollars = 115,869.125 USD millions
  (`21in33ar.xls`, `TBL33!AN10`)
- TY2022: 34,843,071 thousand dollars = 34,843.071 USD millions
  (`22in33ar.xls`, `TBL33!AN10`)
- TY2023: 34,533,251 thousand dollars = 34,533.251 USD millions
  (`23in33ar.xls`, `TBL33!AN10`)

Each workbook's `TBL33!A2` is exactly `(All figures are estimates based on
samples—money amounts are in thousands of dollars)`. The parser requires that
complete declaration at that exact cell before reading the adjacent `Amount`
subcolumn, and the registered transform multiplies the published integer by
`0.001` with no further rounding. The TY2027 target uses
the same reviewed Publication 1304 resolve-by window documented above; the
2026 release-list workbook provides no TY2024 date from which to infer a
future exact day.

---

# Anchor verifications — aging/disability batch (2026-08-23)

Integrator session, 2026-08-23 UTC. Four resolver families were wired for
the aging/disability cells whose resolution dates had passed while the
ledger still held only the two CMS Care Compare observations. Every value
below was reproduced from the live official source on 2026-08-23 and is
re-verified at every resolver run (anchor gates refuse on drift).

## BLS Public Data API: CPS, CES, LAUS (BLS_API_ADAPTERS)

Status: **VERIFIED** against the keyless API
(`https://api.bls.gov/publicAPI/v2/timeseries/data/<series>`) and
cross-checked against the cells' own recorded histories. CPS rows carry
no preliminary footnote at any vintage (every `footnotes` entry is
`[{}]`), so the two CPS specs declare `first_print_gate: "latest_month"`;
BLS's methodology page states the policy that makes that window a
first-print window: "BLS policy is to not revise previous months' official
seasonally adjusted CPS estimates as new data become available during the
year. Instead, revisions are introduced for the most recent 5 years of data
at the end of each year"
(https://www.bls.gov/cps/seasonal-adjustment-methodology.htm, read
2026-08-23). CES and LAUS carry `P` on the latest month and use the default
latest-preliminary gate.

| Series | API id | Anchors (period → API value) | Cell history cross-check |
|---|---|---|---|
| `bls.cps.lfpr_55_plus` | `LNS11324230` | 2025-06→38.0; 2025-12→37.9; 2026-04→37.1; 2026-06→37.1 | cell: 2026-03 37.2, 04 37.1, 05 37.1, 06 37.1 — identical |
| `bls.cps.LNU02374597` | `LNU02374597` | 2025-06→22.7; 2025-12→23.4; 2026-04→21.8; 2026-06→21.8 | cell: 2026-03 22.2, 04 21.8, 05 21.7, 06 21.8 — identical |
| `bls.ces.home_health_care_services.employment` | `CES6562160001` | 2025-06→1778.8; 2025-12→1830.3; 2026-04→1868.0; 2026-05→1878.0 | cell first prints: 05 1877.5, 06 1880.8 vs API 1878.0/1881.5 (second estimates, +0.03%) |
| `bls.laus.colorado.labor_force` | `LASST080000000000006` (persons; spec scales ×0.001, rounds 1) | 2025-06→3,258,203; 2025-12→3,254,073; 2026-04→3,215,558; 2026-06→3,193,312 | cell: 03 3227.9, 04 3215.6, 05 3206.2, 06 3193.3 thousand — identical |

Dry-run 2026-08-23 resolved all four July 2026 cells while July was still
the latest month: LFPR 55+ 36.9, disability EPOP 22.3, home health 1886.1,
Colorado labor force 3189.0.

## VA VBA Monday Morning Workload Report (VA_MMWR_ADAPTERS)

Status: **VERIFIED** from the official workbooks the VBA Detailed Claims
Data page (https://www.benefits.va.gov/REPORTS/detailed_claims_data.asp)
links under each Monday report-date label. The page label is the Monday
report date; the file is named by the preceding Saturday's data-through
date. The `Transformation` sheet, "Compensation and Pension Rating Bundle
Metrics" / National View, "Compensation and Pension Rating Bundle" +
"Total" row, `# Pending` column (cached value of a formula cell) is the
page's headline "Pending Claims" status card (601,630 on the 07/06/2026
report; 632,308 on 08/17/2026, matching the live card's alt text).

| Report date (page label) | Workbook | Reporting through | # Pending | # Pending > 125 | Last-Modified |
|---|---|---|---|---|---|
| 06/22/2026 | `MMWR-06-20-2026.xlsx` | June 20, 2026 | 593,770 | 70,879 | Mon, 22 Jun 2026 15:42:38 GMT |
| 06/29/2026 | `MMWR-06-27-2026.xlsx` | June 27, 2026 | 589,026 | 68,207 | Mon, 29 Jun 2026 14:06:57 GMT |
| 07/06/2026 | `MMWR-07-04-2026.xlsx` | July 04, 2026 | 601,630 | 69,193 | Tue, 07 Jul 2026 19:33:23 GMT |
| 07/13/2026 (target) | `MMWR-07-11-2026.xlsx` | July 11, 2026 | 600,878 | 69,481 | Mon, 13 Jul 2026 17:30:32 GMT |

The three anchors above are the runtime gate. The first-posting gate
requires the workbook's `Last-Modified` day to lie within 7 days after the
report date (every observed 2026 report was posted on its Monday; the July
4 holiday week on the Tuesday) and refuses later re-posts.

**Cell history not used as anchors.** The forecasting cell
`va-pending-disability-claims-2026-07-13` recorded a "fetched" history of
594,080 / 596,291 / 599,020 / 601,630 for the 06/15–07/06 reports. Only
601,630 (the status card visible on the HTML page at run time) exists; the
official workbooks give 586,502 / 593,770 / 589,026 for the other three,
and the recorded numbers appear nowhere in any MMWR file (the only byte
matches are `<row r="594080">` row-number attributes in empty-row padding).
The run's trace shows its sandbox `python`/`curl | rg` calls failing and the
web tool unable to open `.xlsx`; the smooth +2.2/+2.7/+2.6 thousand "trend"
was invented. Same failure class as the 2026-07-24 broadband rejection
(fetch-blind runs fabricate official-looking values); the cell stays
published and scores against the official 600,878 first print.

## SSA official pages (SSA_OFFICIAL_ADAPTERS)

Transport: ssa.gov (Akamai Bot Manager) answers every non-browser TLS
client with HTTP 403 — curl and urllib with full browser headers, from a
laptop and from a GitHub Actions runner, and the Wayback Machine's Save
Page Now (HTTP 520 "Job failed" on every attempt 2026-08-23). A headless
Chromium (Playwright 1.62.0) with the transparent User-Agent suffix
`thesis-resolver/1.0 (+https://app.thesisinstitute.org)` is served normally
from the same runner (CI probe 2026-08-23: HTTP 200 on all five URLs);
`robots.txt` disallows none of `/policy/` or `/appeals/`. The family fetches
through `scripts/official_browser_fetch.py`, records engine, UA, headers and
hashes in each `ssa_official_page_capture_v1` envelope, and uses Wayback
captures only as corroboration (a capture that parses to a different value
refuses the resolution).

First-print basis: SSI Monthly Statistics and Monthly Statistical Snapshot
editions live at per-period URLs and overlapping months are identical
across editions — May 2026 total recipients 7,322,937 in the May, June and
July editions' Table 2; the July edition's June row (7,323,731) equals
June's Table 1 "All recipients"; July Table 4 "All areas" (7,300,297) equals
July Table 2 — so a capture of an edition page reproduces its first print.
Each spec re-reads the prior edition's anchor at capture time:

| Series | Reader | Anchor (prior edition) | Target read 2026-08-23 | Wayback |
|---|---|---|---|---|
| `ssa.ssi.recipients_aged_65_plus` | Table 1, Number of recipients / Total / 65 or older | 2026-05 → 2,501,549 (cell history 2501.549) | 2026-06 → 2,505,847 (2505.847 thousand) | no capture |
| `ssa.ssi.recipients.colorado` | Table 4, Colorado / Total | 2026-06 → 66,417 (cell history 66.417) | 2026-07 → 66,284 | no capture |
| `ssa.ssi.recipients.colorado.aged_65_plus` | Table 4, Colorado / 65 or older | 2026-06 → 23,063 (cell history 23063) | 2026-07 → 23,094 | no capture |
| `ssa.ssi.total_recipients` | Table 2, edition month / Total | 2026-06 → 7,323,731 | 2026-07 → 7,300,297 (7.300297 million) | no capture |
| `ssa.oasdi.disabled_worker_beneficiaries` | Snapshot Table 2, Disability Insurance / Disabled workers / Number (thousands) | 2026-05 → 7,029 (cell history 7029) | 2026-06 → 7,006 | 2026-07-11T20:40:33Z capture reads 7,006 |

Row/column identities checked on every read: Table 1 and Table 4 age
columns and eligibility columns each sum to the row total; Table 2 payment
types sum to Total; Snapshot program components sum to the program total
(±1 per rounded part) and OASI + DI = Total (±2).

## SSA hearings average processing time (ssa.hearings.average_processing_time_days)

Status: **SOURCE PUBLISHES NO NATIONAL AGGREGATE.** The cell binds
`https://www.ssa.gov/appeals/DataSets/02_HO_Workload_Data.html`, whose
table is loaded from `02_HO_Workload_Data.xml`. The live file on
2026-08-23 (`created="07/10/2026"`, `RPTG_PRD_ENDT 06/26/2026`, 165 rows)
and its Wayback captures (2026-06-24: through 05/29/2026, 166 rows;
2026-08-02/08-07/08-14: through 06/26/2026) carry one row per hearing office
(plus NHC units, NATL ADJUDICATION TEAM, SPECIAL REVIEW CADRE) and no
national row; the Average Processing Time Ranking Report XML likewise; SSA's
data dictionary defines `DSPN_AVGPT` only for "Hearing Office Workload Data,
Hearing Office Average Processing Time Ranking Report". The cell's recorded
history (279 → 322 days, Oct 2025–May 2026) is not reproducible from these
files (a dispositions-weighted mean of the June file is 266 days and is not a
published figure). The adapter reads the witnessed file, authenticates the
reporting period, and refuses with `SOURCE PUBLISHES NO NATIONAL AGGREGATE`
rather than computing a derived national statistic the resolver never
defined.

---

# BLS CPS Table A-19 employed persons by occupation

Status: **VERIFIED from Internet Archive captures** (2026-09-20). The six
`bls.cps.employed_people_by_occupation.*` cells bind
`https://www.bls.gov/web/empsit/cpseea19.htm`, which BLS overwrites with each
Employment Situation and which answers non-browser clients with HTTP 403. The
Internet Archive's captures are therefore the custody: the Archive timestamps
each one independently, and the resolver checks the capture's own
current-month column header against the target month before reading a row
(`a19_snapshot_period`), so a capture of any other month refuses.

BLS's release schedule, [archived 2026-07-31](https://web.archive.org/web/20260731041428/https://www.bls.gov/schedule/news_release/empsit.htm),
gives the Employment Situation dates: June 2026 on 2026-07-02, July on
2026-08-07, August on 2026-09-04, September on 2026-10-02. Each capture below
falls between its month's release and the next, and its header names that
month. Values are the printed "Total, 16 years and over" current-month cells,
in thousands, not seasonally adjusted.

| Row | 2026-06 @ [2026-07-10](https://web.archive.org/web/20260710110509/https://www.bls.gov/web/empsit/cpseea19.htm) | 2026-07 @ [2026-08-19](https://web.archive.org/web/20260819191418/https://www.bls.gov/web/empsit/cpseea19.htm) | 2026-08 @ [2026-09-04](https://web.archive.org/web/20260904170006/https://www.bls.gov/web/empsit/cpseea19.htm) |
|---|---:|---:|---:|
| Business and financial operations occupations | 9,720 | 9,835 | 10,167 |
| Computer and mathematical occupations | 6,950 | 6,924 | 7,010 |
| Healthcare support occupations | 5,691 | 5,797 | 5,709 |
| Office and administrative support occupations | 16,184 | 16,457 | 16,154 |
| Production occupations | 7,759 | 8,121 | 7,716 |
| Transportation and material moving occupations | 12,010 | 12,223 | 12,011 |

The June column equals the six observations the ledger already records from
the same capture. `tests/fixtures/a19/` holds each capture's table element and
`tests/test_a19_adapter.py` reproduces all 18 cells from them.

Unit contract: BLS prints thousands. Cells that predate registration stay in
thousands. The docket registers these series in `millions` with
`valueScale: 0.001` and transform `multiply 0.001`; for such a contract the
executor emits millions, rounded to the three decimals the printed integer
carries. The registration selects one of two reviewed unit contracts
(`A19_REGISTERED_SCALES`); any other unit, scale, row, page or release policy
refuses.

Registered contract: a registered cell executes only if its binding is exactly
the reviewed one (adapter `generic-url`, this page, this table string, this
row, this series, host `www.bls.gov`, `first_print`), as the other reviewed
exceptions are pinned (the ABS content hash, QCEW, SBA, IRS). The release
window is the one free field. `FAMILY_ADAPTERS["a19"]` is `{"generic-url"}`.

Which capture: a registered target resolves only from a capture dated inside
its registered `expectedReleaseWindow`, and from the earliest such capture
whose header names the target month. The resolver asks the Archive for the
capture's stored response (`/web/<timestamp>id_/<url>`), so the hash recorded
with the fact covers BLS's bytes and anyone can reproduce it; the Archive
passes BLS's gzip through and the resolver decompresses it. Asked for a
timestamp it holds no capture of, the Archive answers HTTP 200 with the
nearest capture and rewrites the path (seen 2026-09-20: `20260901000000`
returned the `20260904170006` capture). The resolver therefore requires the
final URL to name the timestamp it asked for and refuses otherwise, so the
window is judged on the capture that was actually served.

What the row claims: the value BLS's page showed for the month at the capture
instant, after that month was published and before the next month replaced
it. It does not claim the bytes served at the moment of release. For a
registered cell the fact's `observed_at` is the capture's date, not the
forecast's `resolutionDate` (which for these contracts is the window's end).
Nothing here asserts a BLS revision policy for this table. Two comparisons
exist: in review, two captures 18 days apart that both print September 2025
had identical tables; and the capture of 2026-09-21 15:46 UTC is byte-identical
to the pinned 2026-09-04 17:00 UTC capture (both 104,872 bytes, SHA-256
`de8c3051667136d95cf3311f221f060752f970666414e9e556c98dd4c90fb915`, read through
`a19_read_capture`). Those are instances, not a policy.

The twelve overdue cells. The six August 2026 cells (windows 2026-09-02/03 to
2026-09-10/11) are satisfied by the release-day capture, 2026-09-04 17:00 UTC,
four and a half hours after the 08:30 ET release. The six July 2026 cells
registered 2026-07-29 to 2026-08-06, which closed the day before BLS published
July. No capture of the July table can be dated inside that window, so they
refuse with `FIRST-PRINT WINDOW MISSED` and await a disposition ruling. That
refusal is reserved for one finding: the window is closed, the whole index for
it was read, and nothing in it prints the month. A capped scan or a failed
read reports itself instead. The 2026-07 pin is kept as custody evidence for
the ruling and is never read for a registered cell, because it is dated
outside the window. August resolving and July refusing say nothing about any
other `generic-url` registration.

Without a usable pin, a registered target looks up the Archive's index for
captures dated inside its window. From the day the window opens (not the
forecast's `resolutionDate`, which would leave a single attempt on the last
day), each daily run that finds no capture printing the month asks the Archive
to capture the page, once per run, and defers. An error from the save endpoint
still counts as that run's request and is reported as "outcome unknown": on
2026-09-21 three save requests were answered HTTP 500, and the index then held
a new capture, which read back through the resolver's own reader. The six September 2026 cells
register three different windows (2026-09-30 to 10-08, 10-06 to 10-14, 10-07
to 10-15) around a 2026-10-02 release, so four of them can only resolve from a
capture taken four or more days after the release.
