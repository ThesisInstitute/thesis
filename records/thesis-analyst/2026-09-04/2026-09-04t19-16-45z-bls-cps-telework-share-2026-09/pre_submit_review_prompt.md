# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.cps.telework_share
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-telework-rate-september-2026"
- country: "US"
- targetUnit: "percent"
- dataPointId: "bls.cps.telework_share.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-10-08", "start": "2026-09-30"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-08", "start": "2026-09-30"}, "field": "bls.cps.telework_share", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.telework_share", "sourceUrl": "https://www.bls.gov/web/empsit/cpseea41.htm", "table": "U.S. Bureau of Labor Statistics, Employment Situation, CPS Table A-41", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-0bc190e7fe95e2a7812ba70143f1394069f3cc59c61671e6021c2283181fc418.json"
- targetContentHash: "0bc190e7fe95e2a7812ba70143f1394069f3cc59c61671e6021c2283181fc418"
- registrationCommit: "baad7107ac843adbbb7a8038e4138d5e24100521"
- registeredAtUtc: "2026-09-04T19:02:52Z"
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
f38e694763f338d70138311d55147d0dbabcab1aff2b808495f87aeb2a0f101c

# Draft forecast response
{"slug":"us-telework-rate-september-2026","country":"US","type":"data","title":"US telework rate, September 2026","question":"What will the U.S. Bureau of Labor Statistics first report for the not seasonally adjusted CPS telework rate, Total 16 years and over, percent of people at work who teleworked or worked at home for pay, in September 2026?","unit":"percent","pointEstimate":21.9,"ciLow":21.3,"ciHigh":22.5,"confidence":0.8,"resolutionDate":"2026-10-02","resolutionSource":"U.S. Bureau of Labor Statistics, Employment Situation, CPS Table A-41","resolutionSourceUrl":"https://www.bls.gov/web/empsit/cpseea41.htm","resolutionRule":"Resolve to the first official BLS print in CPS Table A-41 for September 2026: Total, 16 years and over; Percent distribution; People who teleworked or worked at home for pay. Use the not seasonally adjusted percent shown by BLS, in percent and rounded as published, normally to one decimal place. Do not use later revisions or same-day corrections unless the original first-print table is unavailable and BLS explicitly replaces it before any public archived or witnessed copy can identify the first print.","dataPointId":"bls.cps.telework_share.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2026-03"},"label":"2026-03","value":22.6},{"period":{"type":"month","value":"2026-04"},"label":"2026-04","value":21.7},{"period":{"type":"month","value":"2026-05"},"label":"2026-05","value":21.8},{"period":{"type":"month","value":"2026-06"},"label":"2026-06","value":21.7},{"period":{"type":"month","value":"2026-07"},"label":"2026-07","value":22.2},{"period":{"type":"month","value":"2026-08"},"label":"2026-08","value":21.6}],"drivers":["Recent 2026 level is near 22 percent","August 2026 dipped to 21.6 percent","September has shown modest positive seasonality in available telework history","Monthly CPS telework readings are noisy by several tenths","No known policy break before the September reference week"],"sourceContext":["https://www.bls.gov/schedule/news_release/empsit.htm","https://www.bls.gov/schedule/2026/","https://data.bls.gov/timeseries/LNU0201B46B","https://www.bls.gov/web/empsit/cpseea41.htm","https://www.bls.gov/cps/telework.htm"],"runAt":"2026-09-04T19:17:08Z","reasoning":[{"kind":"heading","text":"US CPS Telework Share Forecast"},{"kind":"text","text":"Resolver framing: this targets the BLS CPS Table A-41 national, not seasonally adjusted telework rate for September 2026, Total 16 years and over, percent of people at work who teleworked or worked at home for pay. The exact BLS series page identifies series LNU0201B46B as Percent, Persons who teleworked; percent of total at work."},{"kind":"tool","tool":"official.lookup","call":"Checked the official BLS Employment Situation release schedule for the September 2026 reference month and cross-checked the current Table A-41 page.","result":"BLS schedules Employment Situation for September 2026 on 2026-10-02 at 08:30 AM Eastern; the current A-41 August 2026 table shows Total, 16 years and over telework share of 21.6 percent, with 155,455 thousand total people at work and 33,633 thousand teleworking."},{"kind":"tool","tool":"official.lookup","call":"Fetched recent BLS data-series values from data.bls.gov/timeseries/LNU0201B46B.","result":"Recent official values for LNU0201B46B were 2026-01 23.0, 2026-02 22.7, 2026-03 22.6, 2026-04 21.7, 2026-05 21.8, 2026-06 21.7, and 2026-07 22.2 percent."},{"kind":"tool","tool":"official.lookup","call":"Fetched latest BLS A-41 first-print table value and compared it with the series history.","result":"The BLS A-41 August 2026 table reports 21.6 percent for Total, 16 years and over; recent same-series context includes 2026-03 22.6, 2026-04 21.7, 2026-05 21.8, 2026-06 21.7, and 2026-07 22.2 percent."},{"kind":"tool","tool":"official.lookup","call":"Fetched older same-series monthly values to form a reference class for seasonality and level.","result":"Same-series annual September anchors were 2023-09 19.8, 2024-09 23.7, and 2025-09 22.3 percent; recent August-to-September moves were +0.3 in 2023, +0.9 in 2024, and +0.2 in 2025."},{"kind":"text","text":"Base rate/reference class: the recent 2026 level is a little below the 2024-2025 plateau, but the last six observed prints average 21.93 percent and September has usually not been lower than August in the short telework series. I therefore start from persistence around 21.6 to 22.0 rather than extrapolating the April-August dip linearly."},{"kind":"math","text":"Prior/update/interval: persistence prior from the last official print is 21.6 percent; historical sample for uncertainty is the 2026 Jan-Aug sequence 23.0, 22.7, 22.6, 21.7, 21.8, 21.7, 22.2, 21.6. Adjustments are +0.2 for September seasonality, +0.1 for mean reversion toward the last-six-print average of 21.93, and 0.0 for policy-mechanism effects, giving 21.9. Successive changes are -0.3, -0.1, -0.9, +0.1, -0.1, +0.5, -0.6, so sigma = 0.46 percentage point using the sample standard deviation; 1.28*sigma = 0.59, rounded to a 0.6-point half-width, implying 21.3 to 22.5."},{"kind":"text","text":"Counter-considerations: upside risk is a September rebound like 2024, which would land above the interval if telework jumps roughly 1.0 point or more from August. Downside risk is a renewed office-return or composition move that pushes the rate below 21.3. Outside the interval would most likely require a large month-specific CPS composition shift rather than a visible policy change."},{"kind":"forecast","point":21.9,"ciLow":21.3,"ciHigh":22.5}]}
