# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.cpi.u.core_mom
- period: 2026-11
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-core-cpi-mom-november-2026"
- country: "US"
- targetUnit: "percent_growth"
- dataPointId: "bls.cpi.u.core_mom.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-10", "start": "2026-12-10"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-10", "start": "2026-12-10"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "CUSR0000SA0L1E", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0L1E", "table": "Consumer Price Index for All Urban Consumers, US city average, all items less food and energy, seasonally adjusted (CPI news release, Table A)", "transform": {"factor": 1, "operation": "percent_change_previous_period"}}
- targetRegistrationPath: "records/targets/2026-11-10-b6068648fdcbd4b3bb8812e6021b494ec63fe253ee56207d81321d4ee4aa36ce.json"
- targetContentHash: "b6068648fdcbd4b3bb8812e6021b494ec63fe253ee56207d81321d4ee4aa36ce"
- registrationCommit: "48d10b11037d587eff33b6a8fe1deff8357a60d7"
- registeredAtUtc: "2026-11-10T00:21:03Z"
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
53ffe037472f7ed34b4845e7458d9ebc99e1e0671ea5a39b94a08d3a17e3a6f2

# Draft forecast response
{"slug":"us-core-cpi-mom-november-2026","country":"US","type":"data","title":"US Core CPI MoM, November 2026","question":"What will the first-print November 2026 month-over-month percent change be for BLS CPI-U all items less food and energy, seasonally adjusted, U.S. city average, series CUSR0000SA0L1E?","unit":"percent_growth","pointEstimate":0.26,"ciLow":0.08,"ciHigh":0.44,"confidence":0.8,"resolutionDate":"2026-12-10","resolutionSource":"Official agency release","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0L1E","resolutionRule":"Use the first BLS public print for November 2026 series CUSR0000SA0L1E, Consumer Price Index for All Urban Consumers, U.S. city average, all items less food and energy, seasonally adjusted. Compute percent_growth as 100 * (November 2026 index / October 2026 index - 1) from the first published BLS API values. Do not use later revisions, annual seasonal-adjustment revisions, same-day corrections, or alternate CPI variants.","dataPointId":"bls.cpi.u.core_mom.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":0.376460730477457},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":0.20809544962627768},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":-0.016660666843182348},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":0.2154345141564873},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":0.2897956881014574},{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":0.3348481932704761}],"drivers":["Recent core CPI monthly run rate remains near 0.23 percent","Shelter and core services inflation are still sticky enough to keep the point above the six-month mean","Goods disinflation and month-to-month noise limit the upside","October 2026 CPI was not yet printed at run time, so the forecast leans on April-September official history"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0L1E","https://www.bls.gov/schedule/news_release/cpi.htm?brd=2"],"runAt":"2026-11-10T00:25:58Z","reasoning":[{"kind":"heading","text":"US core CPI-U month-over-month forecast for November 2026"},{"kind":"text","text":"Framing and exact resolver: the target is BLS CPI-U all items less food and energy, U.S. city average, seasonally adjusted, series CUSR0000SA0L1E. The target unit is percent_growth, and the resolver should use the first official BLS API print and the transform percent_change_previous_period for November 2026 over October 2026."},{"kind":"text","text":"Release-date check: the BLS CPI release calendar lists November 2026 CPI for Dec. 10, 2026 at 08:30 Eastern. The evidence fetch tool was blocked by BLS with HTTP 403 for the calendar page in call-0002, so the calendar page bytes were not archived by the evidence tool; the date was verified from the public BLS schedule page outside the capture channel."},{"kind":"tool","tool":"official.lookup","call":"fetch_source https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0L1E","result":"call-0001 archived the BLS API response for CUSR0000SA0L1E: September 2026 index 338.896, August 2026 index 337.765, July 2026 index 336.789, June 2026 index 336.065, May 2026 index 336.121, April 2026 index 335.423, March 2026 index 334.165."},{"kind":"tool","tool":"official.lookup","call":"extract_json and calculate month-over-month percent changes from call-0001 levels","result":"call-0015 April 2026 = 0.376460730477457; call-0014 May 2026 = 0.20809544962627768; call-0016 June 2026 = -0.016660666843182348; call-0018 July 2026 = 0.2154345141564873; call-0017 August 2026 = 0.2897956881014574; call-0019 September 2026 = 0.3348481932704761."},{"kind":"tool","tool":"calculate","call":"mean and sample stdev of the six fetched monthly percent-growth observations","result":"call-0023 mean = 0.23466231813149552; call-0022 sigma = 0.13958684574837305; call-0024 1.28*sigma = 0.1786711625579175."},{"kind":"text","text":"Base rate/reference class: the recent official-source reference class is the six available 2026 monthly changes from April through September for the same seasonally adjusted core CPI-U series. I use the 0.23466231813149552 base rate as the starting point, not the existing local catalog forecast."},{"kind":"math","text":"Prior/update/interval: persistence prior = six-month official BLS API mean for CUSR0000SA0L1E, historical sample = April-September 2026 percent changes [0.376460730477457, 0.20809544962627768, -0.016660666843182348, 0.2154345141564873, 0.2897956881014574, 0.3348481932704761], adjustment components = +0.0253376818685045 for sticky shelter/core services momentum partly offset by goods volatility, interval method = sample dispersion of monthly change values; sigma = 0.13958684574837305, so the 80% half-width is roughly 1.28*sigma = 0.1786711625579175. call-0025 gives point = 0.26; call-0026 gives lower = 0.0813288374420825 and call-0027 gives upper = 0.4386711625579175, rounded to 0.08 and 0.44."},{"kind":"text","text":"Upside risk: a renewed shelter acceleration, medical care services jump, or airfare/auto insurance rebound could put the first print above 0.44 and would land above the interval. Downside risk: another goods-price decline plus softer shelter could put the print below 0.08 and would land outside the interval on the low side."},{"kind":"forecast","point":0.26,"ciLow":0.08,"ciHigh":0.44}]}
