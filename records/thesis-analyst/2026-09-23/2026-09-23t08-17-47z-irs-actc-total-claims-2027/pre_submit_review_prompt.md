# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: irs.actc.total_claims
- period: 2027
- conditional: No legislation enacted by 2027-12-31 changes the IRC §24(d)(1)(B)(i) earned-income threshold of $2,500 for tax year 2027; current law holds. The $2,500 operative amount is applied by IRC §24(h)(6), while §24(d)(1)(B)(i) contains the underlying $3,000 amount.


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "additional-child-tax-credit-total-claims-ty2027-current-law"
- country: "US"
- targetUnit: "millions"
- dataPointId: "irs.actc.total_claims.2027.first_print.current_law"
- resolutionDate: "2029-12-31"
- publishedResolutionDate: "2029-12-31"
- resolutionDateBasis: "resolve-by-bound"
- expectedReleaseWindow: {"end": "2029-12-31", "start": "2029-01-01"}
- resolutionSource: "Internal Revenue Service, SOI Individual Income Tax Returns Complete Report (Publication 1304), Table 3.3"
- resolutionSourceUrl: "https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304"
- resolutionRule: "Resolve from the first IRS SOI Publication 1304 Table 3.3 print for tax year 2027: All returns, total row; Refundable child tax credit or additional child tax credit; Number of returns. Multiply the published whole-return count by 0.000001 and retain six decimal places in millions. Later revisions are irrelevant. The registered IRS release window is 2029-01-01 through 2029-12-31, with 2029-12-31 retained as the registered resolutionDate because no exact IRS publication-calendar day is registered. Evaluate the condition on 2027-12-31; if the condition fails, mark this conditional cell unresolved rather than resolving it from the tax-year print."
- resolutionPolicy: "first_print"
- sourceBinding: {"adapter": "irs-soi-pub1304", "allowedHosts": ["www.irs.gov"], "expectedReleaseWindow": {"end": "2029-12-31", "start": "2029-01-01"}, "field": "refundable_child_tax_credit_returns", "releasePolicy": "first_print", "sourceSeriesId": "irs.actc.total_claims", "sourceUrl": "https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304", "table": "IRS SOI Individual Income Tax Returns Complete Report (Publication 1304), Table 3.3, all returns total row, refundable child tax credit or additional child tax credit, number of returns", "transform": {"factor": 1e-06, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-08-03-b92e9752beaf38a9e2e735c5066e7c741e29436546e7fab2c8d0568f05355909.json"
- targetContentHash: "b92e9752beaf38a9e2e735c5066e7c741e29436546e7fab2c8d0568f05355909"
- registrationCommit: "a4f59c018641c8d772975263735424cb5d46bb25"
- registeredAtUtc: "2026-08-03T20:13:09Z"
- conditional: "No legislation enacted by 2027-12-31 changes the IRC \u00a724(d)(1)(B)(i) earned-income threshold of $2,500 for tax year 2027; current law holds. The $2,500 operative amount is applied by IRC \u00a724(h)(6), while \u00a724(d)(1)(B)(i) contains the underlying $3,000 amount."

Reviewed anchors are cross-checks, not the full historical reference class or a history-floor waiver. Fetch at least six distinct canonical official prints when available, including earlier years if the recent table exposes fewer. Do not count an anchor as a fetched print without its official source.

# Comparison target contract (machine checked)
This run is a strategy comparison against an already published forecast. The sealed cell's resolutionDate, resolutionSource, resolutionSourceUrl and resolutionRule are pinned to that forecast's published resolver; publishedResolutionDate "2029-12-31" is its resolver date. Still verify the official release schedule this run and state any discrepancy in reasoning rather than changing the target.

# Resolve-by-bound target contract (machine checked)
- registeredResolveByBound: "2029-12-31"
- officialAnnouncementUrl: "https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304"
The bound and expected release window are Thesis lab commitments, not timing claims made by the announcement. The announcement authenticates methodology identity only; it does not establish the bound or expected release window. This is an outer bound, not a scheduled release day. resolutionDate must byte-echo the registered resolve-by bound; never infer a more specific day from cadence.
resolutionSourceUrl must byte-echo officialAnnouncementUrl. Call `thesis_announcement_fetch.fetch_official_announcement` with that exact URL. The publisher authenticates the structured draft/final tool event; a reasoning-token claim, search result, same-host page, or prose citation cannot substitute for it.
Base rate during a methodology transition: while NO official print under the announced revised methodology exists — including revised historical or backcast estimates — the CURRENT official series is the admissible base rate: fetch it from its official source, name its vintage explicitly, and state the announced transition as the regime consideration in the sigma step. Do not refuse for lack of the unpublished revised series, and do not fabricate or pre-apply revision adjustments. The moment any revised-methodology official print exists, revised prints are required and old-methodology history stops being admissible.

# Resolution-grade base-rate fetch (captured workbook extraction)
For each of the latest six published tax years, call fetch_source on https://www.irs.gov/pub/irs-soi/YYin33ar.xls (YY is the two-digit tax year), then use that returned call ID in:
  extract_irs_soi({"sourceCallId":"FETCH_CALL_ID","seriesId":"irs.actc.total_claims","year":"YYYY"})   # YYYY is that workbook's four-digit tax year
The tool replays the registered adapter against the complete captured bytes and returns rawValue plus value in the target unit. Use value directly; do not apply the transform twice. Use the extraction call IDs as calculate inputs for the base rate and interval arithmetic. Preserve the exact extracted values and year identities in historicalContext through review and revision. A binary fetch excerpt is not a parsed table. Do not guess a value from it or substitute a rounded bulletin number. Parser errors describe an extraction failure, not unavailability of that official year. Record the refusal and keep the run failed if canonical history cannot be extracted. Four verified anchors do not mean only four years exist. Fetch earlier official workbooks to retain at least six canonical prints; do not replace them with a history waiver.
Use these MCP calls in the native captured lane; shell network access and package installation are unavailable there.
This count is TOTAL ACTC claiming returns at the reviewed plain Additional child tax credit concept header. The separate refundable portion and used to offset other taxes columns are different subsets; never substitute them.
# Rubric
Check these items and name concrete fixes when needed:
1. Exact resolver, source, first-print rule, and resolution date.
2. Base-rate or persistence prior stated before inside-view updates.
3. Time-series/model prior used or explicitly ruled out.
4. Current evidence justifies material movement from the prior.
5. Interval size comes from realized volatility or explicit uncertainty.
6. A compact Prior/update/interval step names the prior, historical sample, adjustment components, interval method, and implied bounds.
7. Tail scenarios are concrete and tied to the target.
8. Point, interval, final forecast step, and JSON fields are coherent.
9. No leakage, catalog point/interval circularity, subjective resolver, or unit ambiguity.

# Required response
Return JSON only, with this shape:
{
  "summary": "one sentence",
  "requiredFixes": [
    {
      "rubricItem": "resolver|base_rate|model_prior|update|interval|prior_update_interval|tails|coherence|leakage",
      "severity": "warning|blocking",
      "summary": "specific issue",
      "actionRequested": "specific change requested"
    }
  ],
  "optionalSuggestions": ["short suggestions"]
}

# Original forecaster prompt hash material
653d6a6b6e2178bbbb6d68fa00f3021551ecb730bd099dd3193f8eb96baf7b8a

# Draft forecast response
{"slug":"additional-child-tax-credit-total-claims-ty2027-current-law","country":"US","type":"conditional","conditionalOn":"No legislation enacted by 2027-12-31 changes the IRC §24(d)(1)(B)(i) earned-income threshold of $2,500 for tax year 2027; current law holds. The $2,500 operative amount is applied by IRC §24(h)(6), while §24(d)(1)(B)(i) contains the underlying $3,000 amount.","title":"ACTC total claims, TY2027","question":"IRS SOI Publication 1304 Table 3.3, tax year 2027 first print, all returns total row, refundable child tax credit or additional child tax credit, number of returns, under the registered current-law condition","unit":"millions","pointEstimate":15.523077,"ciLow":14.533333,"ciHigh":16.4,"confidence":0.8,"resolutionDate":"2029-12-31","resolutionSource":"Internal Revenue Service, SOI Individual Income Tax Returns Complete Report (Publication 1304), Table 3.3","resolutionSourceUrl":"https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304","resolutionRule":"Resolve from the first IRS SOI Publication 1304 Table 3.3 print for tax year 2027: All returns, total row; Refundable child tax credit or additional child tax credit; Number of returns. Multiply the published whole-return count by 0.000001 and retain six decimal places in millions. Later revisions are irrelevant. The registered IRS release window is 2029-01-01 through 2029-12-31, with 2029-12-31 retained as the registered resolutionDate because no exact IRS publication-calendar day is registered. Evaluate the condition on 2027-12-31; if the condition fails, mark this conditional cell unresolved rather than resolving it from the tax-year print.","dataPointId":"irs.actc.total_claims.2027.first_print.current_law","historicalContext":[{"period":{"type":"year","value":"2018"},"label":"2018","value":20.450468},{"period":{"type":"year","value":"2019"},"label":"2019","value":19.867646},{"period":{"type":"year","value":"2020"},"label":"2020","value":19.119249},{"period":{"type":"year","value":"2021"},"label":"2021","value":37.771612},{"period":{"type":"year","value":"2022"},"label":"2022","value":18.076696},{"period":{"type":"year","value":"2023"},"label":"2023","value":17.626084}],"drivers":["pre-2021 and post-2021 ACTC claimant decline","2021 expanded-credit outlier excluded from central trend","four-year extrapolation from latest official print","current-law threshold condition preserved"],"sourceContext":["https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304","https://www.irs.gov/pub/irs-soi/18in33ar.xls","https://www.irs.gov/pub/irs-soi/19in33ar.xls","https://www.irs.gov/pub/irs-soi/20in33ar.xls","https://www.irs.gov/pub/irs-soi/21in33ar.xls","https://www.irs.gov/pub/irs-soi/22in33ar.xls","https://www.irs.gov/pub/irs-soi/23in33ar.xls"],"runAt":"2026-09-23T08:18:09Z","thresholdLadder":{"thresholds":[14,14.4,14.8,15,15.2,15.4,15.6,15.8,16,16.2,16.4,16.7,17],"cumulativeProbabilities":[0.04,0.08,0.14,0.2,0.3,0.42,0.55,0.67,0.77,0.84,0.9,0.95,0.98]},"reasoning":[{"kind":"heading","text":"ACTC total claiming returns for tax year 2027"},{"kind":"text","text":"The resolver is the first IRS SOI Publication 1304 Table 3.3 print for tax year 2027, all returns total row, refundable child tax credit or additional child tax credit, number of returns, converted to millions. I fetched the registered announcement URL; it authenticates the Publication 1304 methodology identity but does not state an exact 2029 release date, so there is no discrepancy with the registered resolve-by-bound date of 2029-12-31."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0006 and extract_irs_soi call-0012 for 2018; fetch_source call-0005 and extract_irs_soi call-0010 for 2019","result":"IRS workbooks returned 2018 rawValue 20450468, value 20.450468 million; 2019 rawValue 19867646, value 19.867646 million."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0004 and extract_irs_soi call-0011 for 2020; fetch_source call-0003 and extract_irs_soi call-0009 for 2021","result":"IRS workbooks returned 2020 rawValue 19119249, value 19.119249 million; 2021 rawValue 37771612, value 37.771612 million."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0002 and extract_irs_soi call-0008 for 2022; fetch_source call-0001 and extract_irs_soi call-0007 for 2023","result":"IRS workbooks returned 2022 rawValue 18076696, value 18.076696 million; 2023 rawValue 17626084, value 17.626084 million."},{"kind":"text","text":"Base rate/reference class: the six official prints are 20.450468, 19.867646, 19.119249, 37.771612, 18.076696, and 17.626084 million. The 2021 value reflects the temporary expanded child tax credit regime and is not a good central-current-law analog, while the 2018-2020 and 2022-2023 values show a persistent decline in claiming returns."},{"kind":"math","text":"Prior/update/interval: persistence prior is the latest official print, 2023 = 17.626084 million; the non-2021 reference class mean from call-0017 is 19.0280286 million; the 2018-to-2023 straight-line projection to 2027 from call-0016 is 15.3665768 million. I use a small upward adjustment to 15.523077 because the recent decline may flatten as the claimant population approaches a lower current-law plateau. For annual-noise sizing I exclude the 2021 policy outlier from the sigma calculation: call-0018 gives sigma = 0.2552523201213532 million from successive changes in 2018, 2019, 2020, 2022, and 2023; 1.28*sigma from call-0021 is 0.3267229697553321 million. The ladder-implied 80% interval width is 1.866667 million from call-0025, much wider than 1.28*sigma because 2027 is four tax years beyond the latest official print and current-law participation, filing, and demographic uncertainty dominate one-year historical noise."},{"kind":"math","text":"Ladder: P(X <= 14.0) = 0.04; P(X <= 14.4) = 0.08; P(X <= 14.8) = 0.14; P(X <= 15.0) = 0.20; P(X <= 15.2) = 0.30; P(X <= 15.4) = 0.42; P(X <= 15.6) = 0.55; P(X <= 15.8) = 0.67; P(X <= 16.0) = 0.77; P(X <= 16.2) = 0.84; P(X <= 16.4) = 0.90; P(X <= 16.7) = 0.95; P(X <= 17.0) = 0.98. Linear interpolation gives p10 = 14.533333 from call-0022, p50 = 15.523077 from call-0023, and p90 = 16.400000 from call-0024."},{"kind":"text","text":"Counter-considerations: upside risk would come from faster shrinkage in eligible low-income child returns, stronger take-up erosion, or administrative/reporting changes that lower ACTC claiming returns, which would land below the interval. Downside risk would come from larger eligible-family counts, higher refundable-credit claiming, or a reversal of the recent decline, which would land above the interval. A policy change violating the condition would make this conditional cell unresolved rather than an outside-the-interval resolution."},{"kind":"forecast","point":15.523077,"ciLow":14.533333,"ciHigh":16.4}]}
