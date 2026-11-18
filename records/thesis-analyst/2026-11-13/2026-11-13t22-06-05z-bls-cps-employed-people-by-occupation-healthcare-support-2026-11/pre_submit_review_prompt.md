# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.cps.employed_people_by_occupation.healthcare_support
- period: 2026-11
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-healthcare-support-employment-november-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.healthcare_support.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-04", "start": "2026-12-04"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-04", "start": "2026-12-04"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "LNU02032463", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032463", "table": "Current Population Survey, employed people, Healthcare support occupations, total 16 years and over, not seasonally adjusted, in thousands (Employment Situation, Table A-19)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-11-13-e478a512ee0229a7fc3fa616b12ece177c57c5b24fcdaa060cb6a91298985653.json"
- targetContentHash: "e478a512ee0229a7fc3fa616b12ece177c57c5b24fcdaa060cb6a91298985653"
- registrationCommit: "5cb6b72d8468fd0f460d6919a14de9921b0dcd7c"
- registeredAtUtc: "2026-11-13T22:03:59Z"
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
78c439756424514d4d5f9429f33465b8087c52cb6e4d530e416b226c10f7c7f0

# Draft forecast response
{"slug":"cps-healthcare-support-employment-november-2026","country":"US","type":"data","title":"US healthcare support employment, November 2026","question":"What will the BLS first print be for CPS series LNU02032463, employed people in healthcare support occupations, total 16 years and over, not seasonally adjusted, November 2026, in millions?","unit":"millions","pointEstimate":5.79,"ciLow":5.651,"ciHigh":5.929,"confidence":0.8,"resolutionDate":"2026-12-04","resolutionSource":"Bureau of Labor Statistics public API, Current Population Survey series LNU02032463","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032463","resolutionRule":"Resolve to the first official BLS public value for CPS series LNU02032463 for period 2026 M11, employed people in healthcare support occupations, total 16 years and over, not seasonally adjusted, as released with the Employment Situation for November 2026. Use the BLS value in thousands from the first print, multiply by 0.001 to millions, and do not incorporate later revisions, corrections, or subsequent API vintages.","dataPointId":"bls.cps.employed_people_by_occupation.healthcare_support.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":5.692},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":5.786},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":5.691},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":5.797},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":5.709},{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":5.649},{"period":{"type":"month","value":"2026-10"},"label":"October 2026","value":5.757}],"drivers":["BLS October 2026 level was 5.757 million after applying the registered thousands-to-millions transform","Historical October-to-November changes since 2018 average about +0.033 million, excluding the unavailable October 2025 value","Recent month-to-month dispersion is about 0.10 million, so sampling volatility dominates the point adjustment","Healthcare support employment is a small CPS occupation cell, making month-to-month noise material"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032463?startyear=2025&endyear=2026","https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032463?startyear=2016&endyear=2026","https://www.bls.gov/schedule/news_release/empsit.htm","https://www.bls.gov/schedule/2026/12_sched_list.htm"],"runAt":"2026-11-13T22:06:17Z","reasoning":[{"kind":"heading","text":"Forecast for BLS CPS healthcare support employment, November 2026"},{"kind":"text","text":"The resolver is the BLS CPS not seasonally adjusted occupation series LNU02032463, Table A-19, for November 2026. The registered unit is millions, so each BLS API value in thousands is multiplied by 0.001."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0002 to BLS public API LNU02032463 for 2025-2026, then extract_json call-0003 through call-0010","result":"Fetched recent official values in thousands: October 2026 5757, September 2026 5649, August 2026 5709, July 2026 5797, June 2026 5691, May 2026 5786, April 2026 5692, and November 2025 5561."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0011 to BLS public API LNU02032463 for 2016-2026","result":"Fetched longer official history; usable October-to-November changes in thousands were 2018 +19, 2019 +70, 2020 +170, 2021 +28, 2022 -46, 2023 -149, and 2024 +138. October 2025 was unavailable due to the 2025 lapse in appropriations."},{"kind":"tool","tool":"official.lookup","call":"official BLS release-calendar lookup via hosted web search; MCP fetch_source attempts call-0001, call-0021, call-0022, and call-0023 returned HTTP 403, so the schedule evidence is not captured in the MCP archive","result":"The BLS Employment Situation schedule listed November 2026 for release on Dec. 04, 2026 at 08:30 AM, and the December 2026 BLS selected release schedule listed Employment Situation for November 2026 on Friday, December 04, 2026 at 08:30 AM."},{"kind":"tool","tool":"calculate","call":"calculate call-0013 and call-0014 on recent values [5692,5786,5691,5797,5709,5649,5757]","result":"Recent successive changes had mean +0.010833333333333334 million and sample stdev 0.10139115674784792 million."},{"kind":"tool","tool":"calculate","call":"calculate call-0015, call-0016, call-0017, call-0018, call-0019, and call-0020 on October-to-November changes [19,70,170,28,-46,-149,138] and October 2026 value 5757","result":"Month-specific October-to-November base rate mean was +0.032857142857142856 million, sigma was 0.10858856381072636 million, point was 5.7898571428571435 million, half-width was 0.13899336167772974 million, lower bound was 5.650863781179414 million, and upper bound was 5.928850504534873 million."},{"kind":"text","text":"Reference class: I anchor on the October-to-November change base rate for the same NSA CPS occupation series, because the target is a level series and the seasonal transition from October to November is more relevant than the full-month average change."},{"kind":"math","text":"Prior/update/interval: persistence prior is October 2026 at 5.757 million; historical sample is same-series October-to-November changes from 2018-2024 with 2025 omitted because October was unavailable; adjustment components are +0.0329 million seasonal base-rate change and no extra policy or one-off adjustment; interval method uses the month-specific change dispersion, sigma = 0.1086 million, so 1.28*sigma = 0.1390 million; final implied bounds are 5.7899 - 0.1390 = 5.6509 and 5.7899 + 0.1390 = 5.9289 million."},{"kind":"text","text":"Upside risk is a broad CPS rebound or unusually strong healthcare support hiring that would land above the interval, roughly above 5.929 million. Downside risk is sampling noise or a November pullback similar to 2023 that would land below the interval, roughly below 5.651 million. Outside the interval would most likely reflect CPS sampling volatility in this small occupation cell rather than a true monthly structural break."},{"kind":"forecast","point":5.79,"ciLow":5.651,"ciHigh":5.929}]}
