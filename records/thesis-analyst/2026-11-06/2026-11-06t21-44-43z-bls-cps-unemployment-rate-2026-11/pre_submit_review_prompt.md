# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.cps.unemployment_rate
- period: 2026-11
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "unemployment-rate-november-2026"
- country: "US"
- targetUnit: "percent"
- dataPointId: "bls.cps.unemployment_rate.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-04", "start": "2026-12-04"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-04", "start": "2026-12-04"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "LNS14000000", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/LNS14000000", "table": "Current Population Survey, unemployment rate, 16 years and over, seasonally adjusted (Employment Situation, Table A-1)", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-11-06-8358e2ebfe6499741830a52a58bab78d11dc9a134eeb3f971595cd66374212b4.json"
- targetContentHash: "8358e2ebfe6499741830a52a58bab78d11dc9a134eeb3f971595cd66374212b4"
- registrationCommit: "84eab1908fd16adb97801361aea7256ef9d70f85"
- registeredAtUtc: "2026-11-06T21:42:24Z"
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
4b91fa98559fba3f3661644aec77c8815e7e775c8d6ec94ae71185ce54c090a7

# Draft forecast response
{"slug":"unemployment-rate-november-2026","country":"US","type":"data","title":"US unemployment rate, November 2026","question":"What will the first-print BLS CPS unemployment rate, seasonally adjusted, for November 2026 be in series LNS14000000?","unit":"percent","pointEstimate":4.1,"ciLow":4,"ciHigh":4.3,"confidence":0.8,"resolutionDate":"2026-12-04","resolutionSource":"U.S. Bureau of Labor Statistics Public Data API, Current Population Survey series LNS14000000","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/LNS14000000","resolutionRule":"Resolve to the first official BLS print for November 2026 in CPS series LNS14000000, unemployment rate, 16 years and over, seasonally adjusted, reported in percent to one decimal place. Use the value first published for the Employment Situation release scheduled for December 4, 2026; do not use later revisions or same-day corrections unless they are part of that first official print.","dataPointId":"bls.cps.unemployment_rate.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":4.3},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":4.3},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":4.2},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":4.1},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":4.1},{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":4.2},{"period":{"type":"month","value":"2026-10"},"label":"October 2026","value":4.1}],"drivers":["October 2026 unemployment rate was 4.1 percent","Recent seven-month mean was 4.1857 percent","Recent month-to-month dispersion is low","Series has hovered between 4.1 and 4.3 percent since April 2026","First-print November value resolves from BLS CPS series LNS14000000"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/LNS14000000","https://api.bls.gov/publicAPI/v2/timeseries/data/LNS14000000?startyear=2019&endyear=2026","https://www.bls.gov/schedule/news_release/empsit.htm"],"runAt":"2026-11-06T21:44:52Z","reasoning":[{"kind":"heading","text":"Forecast for BLS CPS unemployment rate, November 2026"},{"kind":"text","text":"Resolver framing: the target is the BLS Current Population Survey unemployment rate for people age 16 years and over, seasonally adjusted, series LNS14000000, in percent. The variant is the seasonally adjusted CPS rate, not NSA, U-6, establishment employment, or a revised vintage. BLS schedule evidence checked this run shows the Employment Situation for November 2026 scheduled for December 4, 2026; the HTML schedule fetch receipt was not captured because BLS returned HTTP 403 to fetch_source, so the resolver remains the official BLS API series URL."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0001 to BLS public API series LNS14000000, then extract_json calls call-0006 through call-0012 for the latest seven monthly values","result":"Fetched official CPS values: October 2026 4.1, September 2026 4.2, August 2026 4.1, July 2026 4.1, June 2026 4.2, May 2026 4.3, April 2026 4.3 percent."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0017 to BLS public API series LNS14000000 with startyear=2019 and endyear=2026 for broader context","result":"Fetched longer official history including November 2024 4.2, November 2025 4.5, October 2026 4.1, September 2026 4.2, and April 2020 14.8 percent."},{"kind":"tool","tool":"official.lookup","call":"reference-class read from captured BLS API response call-0017 for same-series November and pre-pandemic anchors","result":"Same-series historical anchors fetched from call-0017 include November 2019 3.6, November 2020 6.7, November 2021 4.1, November 2022 3.6, November 2023 3.7, November 2024 4.2, and November 2025 4.5 percent."},{"kind":"tool","tool":"calculate","call":"calculate call-0019 mean(history) for April 2026 through October 2026; calculate call-0013 stdev(diff(history)); calculate call-0014 1.28*sigma; calculate call-0015 persistence point from October 2026 plus zero net adjustment","result":"Calculated recent mean 4.185714285714286, sigma 0.08164965809277289, 1.28*sigma 0.1045115623587493, and persistence point 4.1 from October 2026 value 4.1 plus adjustments 0 and 0."},{"kind":"math","text":"Prior/update/interval: base rate/reference class is same-series CPS unemployment, seasonally adjusted, with the recent official April-October 2026 level history [4.3, 4.3, 4.2, 4.1, 4.1, 4.2, 4.1]. I use a one-month persistence prior from October 2026 at 4.1, cross-checked against the seven-month mean of 4.1857. Level adjustment is 0.0 because the series is already close to the recent mean; momentum adjustment is 0.0 because the last six changes alternate around flat; one-off adjustment is 0.0 because no source-valid discrete rebenchmark belongs in this November first print. Interval method uses successive changes: diff(history) = [0.0, -0.1, -0.1, 0.0, 0.1, -0.1], sigma = 0.08164965809277289, and 1.28*sigma = 0.1045115623587493. For one-decimal official reporting and labor-market regime risk, I widen modestly from 4.1 +/- 0.1045 to an 80% interval of 4.0 to 4.3."},{"kind":"text","text":"The outside view says unemployment rates usually move slowly month to month unless a sharp labor-market break appears. The inside-view update is slightly mixed: the level has edged down from 4.3 in April-May to 4.1 in October, but September was 4.2 and the seven-month mean still sits just under 4.2, so I do not chase a further decline."},{"kind":"text","text":"Counter-considerations: upside risk for the unemployment-rate value is a weak household survey month, labor-force reentry without matching employment, or layoffs that push the first print to 4.3 or higher. Downside risk is a strong employment-population move or falling participation that would land below 4.0. A sudden household-survey shock or classification/population-control issue would be outside the interval."},{"kind":"forecast","point":4.1,"ciLow":4,"ciHigh":4.3}]}
