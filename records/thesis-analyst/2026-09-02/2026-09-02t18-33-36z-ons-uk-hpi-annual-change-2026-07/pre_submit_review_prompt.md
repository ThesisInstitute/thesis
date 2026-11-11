# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: ons.uk_hpi.annual_change
- period: 2026-07
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "uk-house-price-index-annual-rate-july-2026"
- country: "UK"
- targetUnit: "percent"
- dataPointId: "ons.uk_hpi.annual_change.2026_07.first_print"
- expectedReleaseWindow: {"end": "2026-09-16", "start": "2026-09-16"}
- resolutionSourceUrl: "https://www.gov.uk/government/collections/uk-house-price-index-reports"
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.gov.uk"], "expectedReleaseWindow": {"end": "2026-09-16", "start": "2026-09-16"}, "field": "Annual Change", "releasePolicy": "first_print", "sourceSeriesId": "UKHPI:K02000001:all-property-types:annual-change", "sourceUrl": "https://www.gov.uk/government/collections/uk-house-price-index-reports", "table": "UK House Price Index full file, United Kingdom row", "transform": {"factor": 1, "operation": "identity"}}
- targetRegistrationPath: "records/targets/2026-09-02-07be653389c2ef5984ed0ae11abda329a931f1585747e491ec5bbe0cc22d6670.json"
- targetContentHash: "07be653389c2ef5984ed0ae11abda329a931f1585747e491ec5bbe0cc22d6670"
- registrationCommit: "e915c43aeba83b903f1c01b7fd2df8ed8e2c8391"
- registeredAtUtc: "2026-09-02T18:31:06Z"
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
8b70ca65863f813000b9637878918bc4659a7ca9d7f5a92be79d1a1236f3b222

# Draft forecast response
{"slug":"uk-house-price-index-annual-rate-july-2026","country":"UK","type":"data","title":"UK HPI Annual Change, July 2026","question":"First-print UK House Price Index full file Annual Change for the United Kingdom all-property-types series for July 2026, percent, not revised after first publication.","unit":"percent","pointEstimate":2.1,"ciLow":0.4,"ciHigh":3.8,"confidence":0.8,"resolutionDate":"2026-09-16","resolutionSource":"HM Land Registry UK House Price Index full file, United Kingdom row","resolutionSourceUrl":"https://www.gov.uk/government/collections/uk-house-price-index-reports","resolutionRule":"Resolve to the Annual Change value in the first official July 2026 UK House Price Index full file for sourceSeriesId UKHPI:K02000001:all-property-types:annual-change, United Kingdom row. Use the first print published on 2026-09-16 and do not incorporate later revisions, same-day corrections, or replacement files unless the original first print is withdrawn before a numeric value is available. Record the published percent value as reported.","dataPointId":"ons.uk_hpi.annual_change.2026_07.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":1.3},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":1.2},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":0.0},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":3.8},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":2.7},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":2.0}],"drivers":["June first-print persistence near 2.0 percent","July 2025 base month was a modest 0.3 percent monthly rise","Mortgage approvals softened in July","Transactions data mixed with seasonally adjusted decline but non-seasonally adjusted rise","April-to-June annual-rate volatility driven by SDLT base effects"],"sourceContext":["https://www.gov.uk/government/collections/uk-house-price-index-reports","https://www.gov.uk/government/publications/about-the-uk-house-price-index/about-the-uk-house-price-index","https://www.gov.uk/government/statistical-data-sets/uk-house-price-index-data-downloads-june-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-june-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-may-2026/uk-house-price-index-summary-may-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-april-2026/uk-house-price-index-summary-april-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-march-2026/uk-house-price-index-summary-march-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-february-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-january-2026/uk-house-price-index-summary-january-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-july-2025/uk-house-price-index-summary-july-2025","https://www.bankofengland.co.uk/statistics/money-and-credit/2026/july-2026","https://www.gov.uk/government/statistics/monthly-property-transactions-completed-in-the-uk-with-value-40000-or-above/uk-monthly-property-transactions-commentary--2"],"runAt":"2026-09-02T18:34:15Z","reasoning":[{"kind":"heading","text":"UK HPI July 2026 annual-change forecast"},{"kind":"text","text":"Framing and exact resolver: the target is the UK House Price Index full-file Annual Change field for sourceSeriesId UKHPI:K02000001:all-property-types:annual-change, United Kingdom row, July 2026, first print only. The registered ledger source URL is the GOV.UK UK HPI reports collection; the exact resolving artifact should be the July 2026 data-download full file linked from that collection."},{"kind":"tool","tool":"official.lookup","call":"Checked GOV.UK About the UK House Price Index calendar release dates and UK HPI reports collection.","result":"The official calendar lists July 2026 UK HPI publication at 9:30am on 16 September 2026; the reports collection also states the July 2026 UK HPI will be published at 9.30am on Wednesday 16 September 2026."},{"kind":"tool","tool":"official.lookup","call":"Fetched recent official UK HPI headline annual-change prints for the UK from GOV.UK UK HPI monthly summary/report pages.","result":"Recent UK annual price-change prints fetched: January 2026 1.3%, February 2026 1.2%, March 2026 0.0%, April 2026 3.8%, May 2026 2.7%, June 2026 2.0%; June also reported monthly change 0.1% and average price GBP272,000."},{"kind":"tool","tool":"official.lookup","call":"Fetched base-effect anchors from GOV.UK UK HPI July 2025 summary and June 2026 report.","result":"July 2025 UK HPI summary reported annual change 2.8%, monthly change 0.3%, and average price GBP270,000; June 2026 report reported annual change 2.0%, monthly change 0.1%, and noted the rate was down from a revised May 2026 estimate of 3.0%."},{"kind":"tool","tool":"official.lookup","call":"Fetched housing-demand and transactions indicators from Bank of England Money and Credit July 2026 and HMRC monthly property transactions commentary.","result":"Bank of England reported house-purchase mortgage approvals decreased to 56,100 in July 2026 from 58,200 in June, net mortgage borrowing decreased to GBP4.3bn from GBP7.7bn, and the newly drawn mortgage rate rose to 4.45% from 4.35%; HMRC reported July 2026 seasonally adjusted residential transactions of 96,710, 2% lower than June 2026, and non-seasonally adjusted residential transactions of 106,620, 3% higher than June 2026."},{"kind":"math","text":"Prior/update/interval: persistence prior is the June 2026 UK HPI annual change of 2.0%, with a reference class/base rate from the six recent first-print annual changes [1.3, 1.2, 0.0, 3.8, 2.7, 2.0], whose mean is 1.83%. For the level-to-annual update, June annual 2.0 plus forecast July 2026 monthly change 0.4 minus July 2025 monthly base 0.3 gives 2.1%. Components: level 2.0, momentum +0.1 from normal summer monthly gain versus the 0.3% base month, one-off SDLT base effect mostly fading after the April spike, policy/credit mechanism -0.1 from softer approvals and higher mortgage rates, offset by still-positive completions. Interval method uses the fetched annual-change values themselves because this is a change-rate series: sample sigma = 1.32, so 1.28*sigma = 1.69; point 2.1 +/- 1.7 gives an 80% interval of 0.4 to 3.8 after rounding."},{"kind":"text","text":"Counter-considerations: upside risk is a stronger-than-assumed July NSA price gain if late spring completions and Northern Ireland/Scotland strength lift the UK aggregate, which would land above the interval if the first-print annual change exceeds 3.8%. Downside risk is a sharper credit-led fall or weak London/southern England mix effect, which would land outside the interval below 0.4%. The most important falsifier is a large July 2026 monthly move rather than a revision, because resolution is first print only."},{"kind":"forecast","point":2.1,"ciLow":0.4,"ciHigh":3.8}]}
