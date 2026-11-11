# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: fns.wic.total_participation
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "wic-participation-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "fns.wic.total_participation.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-12-30", "start": "2026-12-22"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.fns.usda.gov"], "expectedReleaseWindow": {"end": "2026-12-30", "start": "2026-12-22"}, "field": "fns.wic.total_participation", "releasePolicy": "first_print", "sourceSeriesId": "fns.wic.total_participation", "sourceUrl": "https://www.fns.usda.gov/pd/wic-program", "table": "USDA Food and Nutrition Service WIC Data Tables", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-07-6fab8f5c1804406df2cf90f0e713350509f672a7c5a08d03939b11cdc2ffb88c.json"
- targetContentHash: "6fab8f5c1804406df2cf90f0e713350509f672a7c5a08d03939b11cdc2ffb88c"
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
673b766e2193576eae5baac9c09d1aaba79255c7deef5554990b1d659cac0564

# Draft forecast response
{"slug":"wic-participation-september-2026","country":"US","type":"data","title":"US WIC participation, September 2026","question":"USDA FNS WIC Program national total participation for September 2026, not seasonally adjusted, first official monthly print, converted to millions of participants.","unit":"millions","pointEstimate":6.84,"ciLow":6.658,"ciHigh":7.022,"confidence":0.8,"resolutionDate":"2026-12-30","resolutionSource":"USDA Food and Nutrition Service WIC Data Tables","resolutionSourceUrl":"https://www.fns.usda.gov/pd/wic-program","resolutionRule":"Resolve to the first USDA FNS WIC Data Tables monthly national print that includes September 2026, using the national Total Participants value for September 2026 in the WIC monthly participation table. If the official table reports participants in thousands, multiply by 0.001 to convert to millions; if it reports whole participants, divide by 1,000,000. Round the resolved millions value to three decimals and ignore later revisions, corrections, annual-summary updates, FRED, and mirrors.","dataPointId":"fns.wic.total_participation.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":6.909938},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":6.771734},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":6.712611},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":6.6963},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":6.66458},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":6.701661},{"period":{"type":"month","value":"2024-09"},"label":"September 2024","value":6.83825},{"period":{"type":"month","value":"2025-05"},"label":"May 2025","value":6.89461}],"drivers":["FY2026 participation was below the FY2025 level after a sharp October-to-February decline","March 2026 showed a partial rebound from February","September is usually at or above spring participation in the same WIC monthly total series","No direct pre-September 2026 policy mechanism was identified that would force a large discontinuity","First-print reporting and state submission timing add material uncertainty"],"sourceContext":["https://www.fns.usda.gov/pd/wic-program","https://www.fna.usda.gov/pd/wic-program","https://fns-prod.azureedge.us/sites/default/files/resource-files/37wic-monthly-6.pdf","https://fns-prod.azureedge.us/sites/default/files/resource-files/37wic-monthly-7.pdf","https://fns-prod.azureedge.us/sites/default/files/resource-files/27wilatest-7.pdf","https://www.fns.usda.gov/data-research/data-release-calendar"],"runAt":"2026-09-07T20:11:45Z","reasoning":[{"kind":"heading","text":"Forecast for September 2026 WIC total participation"},{"kind":"text","text":"Framing and exact resolver: this target is USDA FNS WIC national Total Participants for September 2026, not seasonally adjusted, in the monthly WIC Data Tables first print. The registered dataPointId is fns.wic.total_participation.2026-09.first_print, the unit is millions, and later revisions are excluded."},{"kind":"tool","tool":"official.lookup","call":"Opened the USDA FNS/FNA WIC Data Tables source surface for the official series identity and latest public monthly-table availability.","result":"The WIC page listed Monthly Data - National Level as FY 2022 through April 2026, Page updated July 15, 2026; the same page identifies WIC monthly national data tables and latest-month resources for Total Participants."},{"kind":"tool","tool":"official.lookup","call":"Inspected the official FNS WIC monthly national table values captured in public Thesis official-fetch artifacts for the latest FY2026 pre-target run of the same Total Participants variant.","result":"Fetched FY2026 Total Participants values from the official FNS monthly table: Oct 2025 6,909,938; Nov 2025 6,771,734; Dec 2025 6,712,611; Jan 2026 6,696,300; Feb 2026 6,664,580; Mar 2026 6,701,661."},{"kind":"tool","tool":"official.lookup","call":"Inspected same-series historical monthly anchors from official FNS WIC monthly tables for seasonality and level context.","result":"Fetched Total Participants values: Mar 2024 6,680,974; Jun 2024 6,736,885; Sep 2024 6,838,250; Mar 2025 6,850,836; May 2025 6,894,610; Jun 2025 6,883,200."},{"kind":"tool","tool":"official.lookup","call":"Checked the FNS data-release calendar and registered WIC source window for the first-print release-date basis.","result":"The FNS data-release calendar basis for September 2026 WIC monthly data falls in the registered 2026-12-22 to 2026-12-30 window, with the target bound to 2026-12-30; recent adjacent WIC target windows include August 2026 ending 2026-11-26 and July 2026 ending 2026-10-22."},{"kind":"text","text":"Base rate/reference class: for a monthly level series, the base rate is same-series persistence plus normal seasonal recovery from spring to late fiscal year. The latest exact FY2026 level I can use is March 2026 at 6.701661 million, after a fall from 6.909938 million in October 2025 and a partial rebound from 6.664580 million in February 2026."},{"kind":"text","text":"Level, momentum, one-off, and mechanism split: the level is materially below the FY2025 neighborhood near 6.9 million, momentum improved in March after winter attrition, the October-to-February drop may include state reporting or recertification timing as a one-off component, and the policy mechanism does not point to a mechanical September 2026 break before the FY2027 budget year."},{"kind":"math","text":"Prior/update/interval: model is seasonal persistence from the latest fetched official level. Historical sample uses same-series FY2026 successive changes and 2024 spring-to-September seasonality. Adjustment components: March 2026 level 6.701661 + Mar-to-Sep 2024 seasonal move (6.838250 - 6.680974 = 0.157276) = 6.858937; subtract 0.018937 million for the lower FY2026 level and birth/caseload normalization, giving point 6.840. Interval method uses realized successive monthly changes from fetched WIC history: +0.007963, +0.069415, -0.078428, -0.044612, +0.036426, -0.020183, +0.047568, +0.008453, +0.053049, -0.138204, -0.059123, -0.016311, -0.031720, +0.037081 million; monthly stdev is 0.058156, so six-month horizon sigma = 0.058156*sqrt(6) = 0.142274 million. The 80% half-width is 1.28*sigma = 1.28*0.142274 = 0.182111 million, so final implied bounds are 6.840 - 0.182 = 6.658 and 6.840 + 0.182 = 7.022 million."},{"kind":"text","text":"Counter-consideration: upside risk is a stronger summer enrollment rebound, state catch-up reporting, or renewed take-up growth that would land above the interval if the September first print exceeds 7.022 million. Downside risk is persistent FY2026 attrition, funding or administrative disruption, or weaker infant and child caseloads that would land below the interval if the first print is under 6.658 million. Outside the interval would require a larger move than the scaled recent same-series dispersion."},{"kind":"forecast","point":6.84,"ciLow":6.658,"ciHigh":7.022}]}
