# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bea.core_pce.mom
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-core-pce-mom-september-2026"
- country: "US"
- targetUnit: "percent_growth"
- dataPointId: "us.bea.core_pce.mom_sa.2026-09"
- expectedReleaseWindow: {"end": "2026-11-03", "start": "2026-10-26"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bea.gov"], "expectedReleaseWindow": {"end": "2026-11-03", "start": "2026-10-26"}, "field": "bea.core_pce.mom", "releasePolicy": "first_print", "sourceSeriesId": "bea.core_pce.mom", "sourceUrl": "https://www.bea.gov/data/personal-consumption-expenditures-price-index-excluding-food-and-energy", "table": "U.S. Bureau of Economic Analysis, Personal Income and Outlays, August 2026", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-3bd901a59b3f149888eacc83e718008b02d127934c70cbb885ff940917443558.json"
- targetContentHash: "3bd901a59b3f149888eacc83e718008b02d127934c70cbb885ff940917443558"
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
5654a55b251f2fd6565c1c87bd85beed10823d6914ebc0e6206282de6658c3b3

# Draft forecast response
{"slug":"us-core-pce-mom-september-2026","country":"US","type":"data","title":"US core PCE MoM September 2026","question":"What will the U.S. Bureau of Economic Analysis report as the first-print seasonally adjusted monthly percent change in the PCE price index excluding food and energy for September 2026?","unit":"percent_growth","pointEstimate":0.24,"ciLow":0.1,"ciHigh":0.38,"confidence":0.8,"resolutionDate":"2026-10-29","resolutionSource":"U.S. Bureau of Economic Analysis, Personal Income and Outlays, September 2026","resolutionSourceUrl":"https://www.bea.gov/news/2026/personal-income-and-outlays-september-2026","resolutionRule":"Resolve to the first BEA Personal Income and Outlays September 2026 release value for the seasonally adjusted PCE price index excluding food and energy, percent change from the preceding month, as shown in the release text or Table 2.8.7. Use the first public print only; do not use later revisions, annual updates after first publication, or same-day correction exceptions unless BEA explicitly replaces the release before public posting. Record in percent_growth, using BEA's reported rounding.","dataPointId":"us.bea.core_pce.mom_sa.2026-09","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":0.4},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":0.4},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":0.3},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":0.2},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":0.3},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":0.1},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":0.2}],"drivers":["Recent first-print core PCE monthly values averaged 0.27 percent","June and July cooled to 0.1 and 0.2 percent after firmer first-quarter prints","Sticky services inflation keeps the point estimate above a clean 0.2 percent persistence forecast","No August or September PCE release information is public yet, so the forecast leans on BEA first-print history"],"sourceContext":["https://www.bea.gov/news/schedule","https://www.bea.gov/data/personal-consumption-expenditures-price-index-excluding-food-and-energy","https://www.bea.gov/news/2026/personal-income-and-outlays-january-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-february-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-march-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-april-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-may-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-june-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-july-2026"],"runAt":"2026-09-04T19:18:21Z","reasoning":[{"kind":"heading","text":"US core PCE MoM September 2026 forecast"},{"kind":"text","text":"Framing and exact resolver: this targets BEA's first-print seasonally adjusted monthly percent change for the PCE price index excluding food and energy for September 2026, the same variant as BEA NIPA Table 2.8.7, Percent Change From Preceding Period in Prices for PCE by Major Type of Product. The registered ledger sourceBinding table text says August 2026, but the target period and dataPointId are September 2026 and the BEA schedule verifies the September 2026 Personal Income and Outlays release on 2026-10-29; I keep the forecast tied to the registered September target and treat the August table label as a ledger-label discrepancy."},{"kind":"tool","tool":"official.lookup","call":"BEA release schedule lookup for Personal Income and Outlays, September 2026","result":"BEA schedule lists Personal Income and Outlays, September 2026 on October 29, 2026 at 8:30 AM; the same schedule lists the August 2026 release on September 30, 2026 at 8:30 AM."},{"kind":"tool","tool":"official.lookup","call":"BEA January-March 2026 Personal Income and Outlays releases, core PCE price index excluding food and energy, percent change from preceding month","result":"Fetched first-print same-variant values: January 2026 = 0.4 percent, February 2026 = 0.4 percent, March 2026 = 0.3 percent."},{"kind":"tool","tool":"official.lookup","call":"BEA April-June 2026 Personal Income and Outlays releases, core PCE price index excluding food and energy, percent change from preceding month","result":"Fetched first-print same-variant values: April 2026 = 0.2 percent, May 2026 = 0.3 percent, June 2026 = 0.1 percent."},{"kind":"tool","tool":"official.lookup","call":"BEA July 2026 Personal Income and Outlays release and core PCE series page","result":"Fetched latest first-print same-variant value: July 2026 core PCE price index excluding food and energy = 0.2 percent month over month; BEA's core PCE series page shows July 2026 year-over-year = 3.3 percent and next release = September 30, 2026."},{"kind":"text","text":"Base rate / reference class: the recent official first-print reference class is January through July 2026, with values 0.4, 0.4, 0.3, 0.2, 0.3, 0.1, and 0.2 percent. The simple base rate mean is 1.9 / 7 = 0.271 percent, while the most recent three prints average (0.3 + 0.1 + 0.2) / 3 = 0.200 percent."},{"kind":"math","text":"Prior/update/interval: persistence prior is the recent first-print mean, historical sample is seven BEA same-variant monthly core PCE prints from 2026-01 through 2026-07, adjustment components are -0.04 percentage point for cooling June-July momentum, +0.01 for sticky services/core inflation persistence, and about 0.00 for one-off release mechanics because no September CPI/PPI bridge data are yet available. Point = 0.271 - 0.04 + 0.01 = 0.241, rounded to 0.24. For a change/flow series, use the values themselves for dispersion: sample sigma = 0.111 from [0.4, 0.4, 0.3, 0.2, 0.3, 0.1, 0.2]. The 80 percent half-width is roughly 1.28*sigma = 1.28*0.111 = 0.142, so bounds are 0.24 - 0.142 = 0.098 and 0.24 + 0.142 = 0.382, rounded to 0.10 and 0.38."},{"kind":"text","text":"Upside risk: a renewed firming in core services, medical services, portfolio-management fees, or September source-data surprises would land above the interval if BEA prints about 0.4 percent or higher. Downside risk: weaker goods prices, softer shelter-related imputations, or broad disinflation in services would land below the interval if the first print is about 0.1 percent or lower. Outside the interval would most likely require a source-data shock rather than ordinary month-to-month noise."},{"kind":"forecast","point":0.24,"ciLow":0.1,"ciHigh":0.38}]}
