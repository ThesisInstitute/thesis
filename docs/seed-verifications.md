# Recurring docket seeds

Verified on 2026-07-25. Each row is the next reference period whose official
print had not yet been released, paired with the agency's published release
date for exactly that period. The registry stores these values as
`seedPeriod`, `releaseDates[seedPeriod]`, and `releaseCalendarUrl`.

The baseline dry-run printed 63 `no published cell to step from` messages, but
that message covered two different states. After recognizing the legacy
abbreviated-month slug for `bls.lns11300000`, 21 recurring entries have no
published cursor, while 42 already-published entries merely have no successor
inside the period horizon. Only the 21 genuinely cursorless entries below
receive recurring seeds. The six annual USAspending entries already use the
separate reviewed `registered_query_snapshot` seed contract.

| Series | Seed period | Release date | Official calendar |
|---|---:|---:|---|
| `fed.g17.manufacturing_production_mom` | `2026-07` | 2026-08-18 | [Federal Reserve G.17 release dates](https://www.federalreserve.gov/releases/g17/release_dates.htm) |
| `fed.g17.capacity_utilization.manufacturing` | `2026-07` | 2026-08-18 | [Federal Reserve G.17 release dates](https://www.federalreserve.gov/releases/g17/release_dates.htm) |
| `census.housing.permits_saar` | `2026-07` | 2026-08-18 | [Census Survey of Construction schedule](https://www.census.gov/construction/soc/schedule.html) |
| `census.housing.completions_saar` | `2026-07` | 2026-08-18 | [Census Survey of Construction schedule](https://www.census.gov/construction/soc/schedule.html) |
| `census.m3.durable_goods_new_orders_mom` | `2026-06` | 2026-07-27 | [Census M3 release schedule](https://www.census.gov/manufacturing/m3/release_schedule.html) |
| `census.m3.durable_goods_shipments_mom` | `2026-06` | 2026-07-27 | [Census M3 release schedule](https://www.census.gov/manufacturing/m3/release_schedule.html) |
| `census.construction_spending.total_mom` | `2026-06` | 2026-08-03 | [Census Construction Spending schedule](https://www.census.gov/construction/c30/release.html) |
| `bls.export_prices.all_commodities_mom` | `2026-07` | 2026-08-18 | [BLS Import/Export Price Index schedule](https://www.bls.gov/schedule/news_release/ximpim.htm) |
| `bls.eci.total_compensation_private_industry_qoq` | `2026-Q2` | 2026-07-31 | [BLS Employment Cost Index schedule](https://www.bls.gov/schedule/news_release/eci.htm) |
| `bls.eci.private_wages_salaries_qoq` | `2026-Q2` | 2026-07-31 | [BLS Employment Cost Index schedule](https://www.bls.gov/schedule/news_release/eci.htm) |
| `bls.productivity.nonfarm_unit_labor_costs_qoq_prelim` | `2026-Q2` | 2026-08-06 | [BLS Productivity and Costs schedule](https://www.bls.gov/schedule/news_release/prod2.htm) |
| `fed.g19.consumer_credit_total_annual_rate` | `2026-06` | 2026-08-07 | [Federal Reserve August 2026 calendar](https://www.federalreserve.gov/newsevents/2026-august.htm) |
| `fed.g19.consumer_credit_revolving_annual_rate` | `2026-06` | 2026-08-07 | [Federal Reserve August 2026 calendar](https://www.federalreserve.gov/newsevents/2026-august.htm) |
| `fed.g19.consumer_credit_nonrevolving_annual_rate` | `2026-06` | 2026-08-07 | [Federal Reserve August 2026 calendar](https://www.federalreserve.gov/newsevents/2026-august.htm) |
| `bls.cpi.shelter_mom` | `2026-07` | 2026-08-12 | [BLS Consumer Price Index schedule](https://www.bls.gov/schedule/news_release/cpi.htm) |
| `bls.cpi.rent_primary_residence_mom` | `2026-07` | 2026-08-12 | [BLS Consumer Price Index schedule](https://www.bls.gov/schedule/news_release/cpi.htm) |
| `bls.cpi.owners_equivalent_rent_mom` | `2026-07` | 2026-08-12 | [BLS Consumer Price Index schedule](https://www.bls.gov/schedule/news_release/cpi.htm) |
| `bls.cpi.services_less_energy_mom` | `2026-07` | 2026-08-12 | [BLS Consumer Price Index schedule](https://www.bls.gov/schedule/news_release/cpi.htm) |
| `bls.cpi.services_less_rent_shelter_mom` | `2026-07` | 2026-08-12 | [BLS Consumer Price Index schedule](https://www.bls.gov/schedule/news_release/cpi.htm) |
| `bls.jolts.hires_rate` | `2026-06` | 2026-08-04 | [BLS JOLTS schedule](https://www.bls.gov/schedule/news_release/jolts.htm) |
| `bls.cps.u6_underemployment_rate` | `2026-07` | 2026-08-07 | [BLS Employment Situation schedule](https://www.bls.gov/schedule/news_release/empsit.htm) |

## Calendar interpretation

- Census M3 rows use the 2026-07-27 advance report because it is the first
  print for both durable-goods new orders and shipments. Their registry
  bindings name that advance report explicitly.
- The BLS productivity row uses the preliminary (`P`) second-quarter release
  on 2026-08-06, matching the registry's `qoq_prelim` contract.
- The Federal Reserve's August calendar identifies G.19 on 2026-08-07 and
  G.17 on 2026-08-18. The dedicated G.17 schedule independently lists the
  same August date.

No cursorless recurring series was omitted for lack of a verifiable calendar.
`bls.lns11300000` is intentionally not seeded: the witnessed catalog already
contains its December 2026 published cell, whose `dec` slug is now recognized
by the ordinary cursor.

## Calendar refresh, 2026-11-02

Nothing refreshes `releaseDates`. Someone reads each agency's calendar and
commits the dates by a reviewed edit. Before this refresh, 25 of the 51
calendar-gated series had published nothing after 2026-07, and only 3 could roll
on 2026-11-02. The roller skips a calendar-gated period that has no date, so
those series stopped registering, and the rolls of 2026-10-23, 2026-10-26 and
2026-10-30 selected nothing the registrar would keep. `scripts/docket_health.py`
now raises an issue 21 days before a series' committed dates run out.

This refresh only adds dates: every date already in the registry stayed as it
was, and every read that covered an existing date agreed with it. BLS answers
`curl` with a 403, so the BLS rows come from a browser's fetch of the page.
Sizes and digests are of the bytes as read on 2026-11-02.

| Release | Calendar read | Bytes | SHA-256 | Committed for | Periods |
|---|---|---:|---|---|---|
| Consumer Price Index | https://www.bls.gov/schedule/news_release/cpi.htm | 55,389 | `cece37b1f964eed1cd51215764a55fb26e310da31b441ab9c65758989c9afc17` | Five `bls.cpi.*_mom` subseries | 2026-10 to 2026-12 |
| Employment Situation | https://www.bls.gov/schedule/news_release/empsit.htm | 55,395 | `939d7d01d2d4e136e54f7fec49ea3108e73dfcf9f50dba383fc7c723e21a556e` | `bls.cps.u6_underemployment_rate`, `bls.ces.nonfarm_payrolls.change`, `bls.ces.average_hourly_earnings_private` | U-6 2026-10 to 2026-11; payrolls 2026-12; earnings 2026-11 to 2026-12 |
| BLS 2026 schedule | https://www.bls.gov/schedule/2026/home.htm | 100,563 | `1bfb9d805fb7b419504962aa22773506b558534daac3b47d72c9de99fd16acac` | The CPI, U-6, price and JOLTS series above and below | Past prints: 2026-07 to 2026-09 |
| JOLTS | https://www.bls.gov/schedule/news_release/jolts.htm | 54,102 | `b7c2d3192c8a5df69581b477bc5c36d671df3c0201ebfbe51102486e02c53501` | `bls.jolts.hires_rate` | 2026-09 to 2026-10 |
| U.S. import and export prices | https://www.bls.gov/schedule/news_release/ximpim.htm | 55,425 | `64a46ab0b77adfcb23ca19f6fbf32ff368f84e76d44708572d1ba91bdc8b4638` | Import and export price series | 2026-10 to 2027-05 |
| Employment Cost Index | https://www.bls.gov/schedule/news_release/eci.htm | 54,500 | `4c7b8a2252c44227278c77aad6c8ca00cf8be929a992995bba4bf12adf23ee52` | Two `bls.eci.*` series | 2026-Q4 |
| Productivity and costs | https://www.bls.gov/schedule/news_release/prod2.htm | 55,088 | `057691c2a21a34e1130a667dee54d04030754941cdddc60a9e25489635df6d50` | `bls.productivity.nonfarm_unit_labor_costs_qoq_prelim` | 2026-Q3 to 2026-Q4 |
| G.17 release dates | https://www.federalreserve.gov/releases/g17/release_dates.htm | 119,379 | `1773731a0cc7fa11d1234a293359cd7734e990464ff7284133b9c05a2442aa1f` | Four `fed.g17.*` series | 2026-08 to 2027-05 |
| Federal Reserve calendar, September 2026 | https://www.federalreserve.gov/newsevents/2026-september.htm | 108,932 | `069b170f91414248f4c89a8fe0079a6a8b5123a130fecc0ebfdaf7563da44a1f` | Three `fed.g19.*` series | 2026-07 |
| Federal Reserve calendar, October 2026 | https://www.federalreserve.gov/newsevents/2026-october.htm | 106,934 | `97734581abc61b8cce0865a034f6537bd562a93241ed5d492561cd40d4a70d83` | Three `fed.g19.*` series | 2026-08 |
| Federal Reserve calendar, November 2026 | https://www.federalreserve.gov/newsevents/2026-november.htm | 96,741 | `f4b3ef733e0056ab49f1953434c45e413d8be189decad8e316b62d41aa51f800` | Three `fed.g19.*` series | 2026-09 |
| Federal Reserve calendar, December 2026 | https://www.federalreserve.gov/newsevents/2026-december.htm | 95,224 | `91e11c1a86ebaf7d48399286f03f913e8fa67425882ba88ee2a5058a46ab5864` | Three `fed.g19.*` series | 2026-10 |
| Census new residential construction and sales | https://www.census.gov/construction/soc/schedule.html | 60,805 | `6813151fce8ecc303bc01c55e3667b44b56b6e76a4714066675ca13243bbe5a0` | Housing starts, permits, completions, new home sales | 2026-08 to 2027-05 |
| Census M3 | https://www.census.gov/manufacturing/m3/release_schedule.html | 54,025 | `562d10538d60f3e1e62439b13ec6c19f6e7cd2c3cb1f83f5a8b871865d8133ac` | Two `census.m3.*` series | 2026-07 to 2027-05 |
| Census construction spending | https://www.census.gov/construction/c30/release.html | 49,408 | `8c4b307b6b5efa93245ccc6aaea53afe348c489edbde4edcc5cab34e9e2fb819` | `census.construction_spending.total_mom` | 2026-07 to 2027-04 |
| Census 2026 economic indicator list | https://www.census.gov/economic-indicators/calendar-listview-2026.html | 89,306 | `adffdae3825f87a059f9633f4cb1f42a1e428c32f5ad71d743b4669519789b8a` | `census.mtis.total_business_inventories_level` | 2026-10 |
| BEA release schedule | https://www.bea.gov/news/schedule | 70,025 | `133066738912d328c807b6ee9d499ba8472b4135b5447f5778fc070b85b2985b` | Trade balance, two fixed-investment series, personal transfer payments | See the next two rows |
| BEA release dates (JSON, `file_last_updated` 2026-10-22) | https://apps.bea.gov/API/signup/release_dates.json | 12,096 | `5774525c10ec63520b36b7647a11fad4d192f5d1d609074109f692acd29ce721` | `bea.trade.goods_services_deficit`, `bea.ita.personal_transfer_payments` | Trade 2026-08 to 2027-04; transfers 2026-Q3 |
| BEA release calendar feed | https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics | 43,220 | `81be5c35e43d4a5209536a542012ef406b66a20db7d4e065cf0f73f8d5e6a81d` | Two `bea.*_fixed_investment` series | 2026-Q4 advance GDP, 2027-01-28 |
| ABS Consumer Price Index release page | https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia | 146,483 | `ff24add11ac281427b10f48259cc66103bd05a8cbdd4fbbfadbe3495cbb2ab47` | `abs.cpi.all_groups.yoy` | 2026-10 to 2027-03 |
| ABS Labour Force release page | https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia | 157,823 | `65b5fe8a0fd0cdd17fd961183d4771e8dd0c7ddcde9614ee4e388ec99645df04` | `abs.labour.unemployment_rate` | 2026-10 to 2027-03 |
| ABS latest CPI release | https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/latest-release | 418,418 | `267bcfd17e63f3f30c25fef349a864262370c81b1c8f307095f78e6862dc7cc9` | `abs.cpi.all_groups.yoy` | Past print: 2026-09, released 28/10/2026 |
| ABS latest Labour Force release | https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/latest-release | 579,286 | `e6e3197bc72e6b3124984c83367ea9cd890e7cae1f953d90bb1261c9018976b2` | `abs.labour.unemployment_rate` | Past print: 2026-09, released 15/10/2026 |

The G.17 page's first column names the release month, so a row for a release in
one month carries the prior month's data. The Census construction schedule lists
new home sales in its third column, a week after housing starts.

Two series gain seeds, because neither had a published cursor and each has an
official date within 75 days: `bls.ces.average_hourly_earnings_private` at
2026-11 and `census.mtis.total_business_inventories_level` at 2026-10. The three
`fed.g19.*` entries move their `releaseCalendarUrl` from the single-month page
`2026-august.htm` to `newsevents/calendar.htm`, which rolls forward.

These stay off the calendar on purpose:

- `bls.ppi.final_demand_monthly_change`: the gate refuses its next id,
  `bls.wp.WPSFD4.<period>.first_print`, because no resolver family routes that
  legacy stem. A date cannot help until a change moves the stem.
- `bls.lns11300000`: the live catalog holds no published link for this series,
  so the note above about its `dec` slug no longer holds. A roll to December
  would collide with the static cell `labor-force-participation-dec-2026`.
- `eurostat.hicp.flash.yoy`: its entry has no target unit, and Eurostat's
  calendar shows both 3 and 4 November for the October flash.
- JOLTS openings and quits for 2026-11: BLS lists nothing past October 2026.
- Unemployment for 2026-12, and CPI headline and core past 2026-12: these cross
  an annual revision, so `docs/anchor-verifications.md` requires re-verified
  anchors in the same change. The BLS calendar rows for those series need that
  work in January 2027.
- The six Table A-19 rows: they stay on `registration_hold` (decision d397).
- Quarterly 2027-Q1 and personal transfer payments for 2026-Q4: a date this far
  out would register more than 100 days before its print.
