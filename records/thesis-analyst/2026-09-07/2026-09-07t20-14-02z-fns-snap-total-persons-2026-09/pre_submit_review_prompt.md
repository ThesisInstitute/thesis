# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: fns.snap.total_persons
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "snap-participation-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "usda.fns.snap.persons.september_2026"
- expectedReleaseWindow: {"end": "2027-02-15", "start": "2027-02-07"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.fns.usda.gov"], "expectedReleaseWindow": {"end": "2027-02-15", "start": "2027-02-07"}, "field": "Persons", "releasePolicy": "first_print", "sourceSeriesId": "fns.snap.total_persons", "sourceUrl": "https://www.fns.usda.gov/pd/supplemental-nutrition-assistance-program-snap", "table": "FNS SNAP data tables, national monthly participation (thousands)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-07-c75aaa27f9ca01b95b9261fe1d397216de66021ff374c9ad807e6ca69dca9672.json"
- targetContentHash: "c75aaa27f9ca01b95b9261fe1d397216de66021ff374c9ad807e6ca69dca9672"
- registrationCommit: "f1baea413714fe099f71118840f6363977fcdb5c"
- registeredAtUtc: "2026-09-07T20:04:45Z"
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
99f674c34e4037362710d5ee91276f4e82a1f53e19ba344f17ec49ae00d0b6a9

# Draft forecast response
{"slug":"snap-participation-september-2026","country":"US","type":"data","title":"US SNAP participation, September 2026","question":"USDA FNS SNAP Data Tables national monthly Persons for September 2026, first print, converted to millions","unit":"millions","pointEstimate":34.422,"ciLow":33.819,"ciHigh":35.026,"confidence":0.8,"resolutionDate":"2027-02-15","resolutionSource":"FNS SNAP data tables, national monthly participation (thousands)","resolutionSourceUrl":"https://www.fns.usda.gov/pd/supplemental-nutrition-assistance-program-snap","resolutionRule":"Resolve to the first value published by USDA FNS for September 2026 in the SNAP Data Tables national monthly Persons field in the Persons, Households, Benefits, and Average Monthly Benefit per Person and Household table. Express the published Persons count in millions, rounded to three decimals for display. Use the first official print only and ignore later revisions, backfills, same-day corrections, or subsequent workbook/PDF updates.","dataPointId":"usda.fns.snap.persons.september_2026","historicalContext":[{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":41.09666},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":39.99989},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":39.207898},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":38.552133},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":37.947123},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":37.531152},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":37.078596},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":36.562128}],"drivers":["latest official May 2026 level was 36.562 million persons","recent monthly declines averaged about 0.498 million over January-May 2026","large FY2026 downtrend dominates short-horizon persistence","policy and administrative tightening risk further participation losses","first-print target uses unrevised FNS monthly national Persons table"],"sourceContext":["https://www.fna.usda.gov/pd/supplemental-nutrition-assistance-program-snap","https://fns-prod.azureedge.us/sites/default/files/resource-files/snap-4fymonthly-8.pdf","https://www.fna.usda.gov/data-research"],"runAt":"2026-09-07T20:14:23Z","reasoning":[{"kind":"heading","text":"September 2026 SNAP persons forecast"},{"kind":"text","text":"Framing and exact resolver: this targets the USDA FNS SNAP national monthly Persons field for September 2026, first print only, from the SNAP Data Tables. The current FNS PDF displays Persons as whole-person counts, for example 36,562,128 for May 2026; I convert those counts to millions for this cell while preserving the registered target unit and dataPointId."},{"kind":"tool","tool":"official.lookup","call":"Opened the current FNA SNAP Data Tables page for source identity and latest available monthly table.","result":"The official SNAP Data Tables page says the FY 23 through FY 26 National View Summary has Latest Available Month: May 2026, and the page was updated August 20, 2026."},{"kind":"tool","tool":"official.lookup","call":"Opened the August 2026 SNAP national monthly participation PDF and read FY2026 monthly Persons values.","result":"The PDF is Data as of August 14, 2026 and reports FY2026 Persons of 41,096,660 in Oct 2025, 39,999,890 in Nov 2025, 39,207,898 in Dec 2025, and 38,552,133 in Jan 2026."},{"kind":"tool","tool":"official.lookup","call":"Read the latest FY2026 monthly Persons values from the same SNAP national monthly participation PDF.","result":"The same PDF reports Persons of 37,947,123 in Feb 2026, 37,531,152 in Mar 2026, 37,078,596 in Apr 2026, and 36,562,128 in May 2026."},{"kind":"tool","tool":"official.calendar","call":"Checked official FNA data-and-research publication listings and the registered bounded target schedule for release timing.","result":"The official FNA listing shows May 2026 Keydata Report dated 08/10/2026, May 2026 Performance Report dated 08/12/2026, April 2026 Keydata Report dated 07/15/2026, and March 2026 reports dated 06/18/2026; the registered target window for September 2026 is 2027-02-07 to 2027-02-15, so this cell keeps the registered resolutionDate 2027-02-15."},{"kind":"text","text":"The outside-view base rate/reference class is a short monthly persistence model on the same official FNS national Persons variant. The latest level is 36.562128 million in May 2026, with seven observed month-to-month changes from October 2025 through May 2026: -1.096770, -0.791992, -0.655765, -0.605010, -0.415971, -0.452556, and -0.516468 million."},{"kind":"text","text":"Level effect starts at 36.562128 million. Momentum effect uses the more recent four-change average from Jan-May 2026, -0.497501 million per month, rather than the full seven-change mean of -0.647790 because the earliest FY2026 drops look unusually front-loaded. One-off/policy mechanism adds -0.150 million by September for continued eligibility and administrative tightening, but no separate disaster-assistance adjustment is added."},{"kind":"math","text":"Prior/update/interval: persistence prior = latest official May 2026 level of 36.562128 million; historical sample = Oct 2025-May 2026 same-table Persons values listed above. Successive changes are -1.096770, -0.791992, -0.655765, -0.605010, -0.415971, -0.452556, and -0.516468 million; their sample standard deviation gives sigma = 0.235716 million. Point = 36.562128 + 4*(-0.497501) - 0.150 = 34.422123 million, rounded to 34.422. The one-month 80% half-width is 1.28*sigma = 1.28*0.235716 = 0.301717 million; for a four-month horizon I scale by sqrt(4), giving 0.603434 million. Bounds are 34.422123 - 0.603434 = 33.818689 and 34.422123 + 0.603434 = 35.025557, rounded to 33.819 and 35.026."},{"kind":"text","text":"Upside risk is that the early FY2026 enrollment drop stabilizes quickly, state backlogs or recertifications raise the September count, or disaster-related reporting adds participants; that would land above the interval if September exceeds 35.026 million. Downside risk is faster eligibility loss, stronger work-requirement implementation, or administrative churn continuing near the Oct-Jan decline pace; that would land below the interval if September is under 33.819 million. The outside the interval cases are therefore a clear stabilization above 35.026 or an accelerated drop below 33.819."},{"kind":"forecast","point":34.422,"ciLow":33.819,"ciHigh":35.026}]}
