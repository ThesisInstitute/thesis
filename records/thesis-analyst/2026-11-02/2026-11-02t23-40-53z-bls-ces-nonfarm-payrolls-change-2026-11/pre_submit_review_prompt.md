# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.ces.nonfarm_payrolls.change
- period: 2026-11
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "nonfarm-payrolls-november-2026"
- country: "US"
- targetUnit: "thousands"
- dataPointId: "bls.ces.nonfarm_payrolls.change.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-04", "start": "2026-12-04"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-04", "start": "2026-12-04"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "CES0000000001", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001", "table": "Current Employment Statistics, all employees, total nonfarm, seasonally adjusted (Employment Situation, Table B-1)", "transform": {"factor": 1, "operation": "difference_previous_period"}}
- targetRegistrationPath: "records/targets/2026-11-02-93d4fe16db30befd6cde1b23e3f396ab250a322bdd44b281003f42efb2977eea.json"
- targetContentHash: "93d4fe16db30befd6cde1b23e3f396ab250a322bdd44b281003f42efb2977eea"
- registrationCommit: "ac152d6cd8dbb730a1f6d9e9cddf26b98c4aec30"
- registeredAtUtc: "2026-11-02T23:38:32Z"
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
0828125be414401778c259fb1afe6dc4c75b2ff8c571dfa73f350a0da2cfa4bd

# Draft forecast response
{"slug":"nonfarm-payrolls-november-2026","country":"US","type":"data","title":"US nonfarm payrolls, November 2026","question":"What will the first-print month-over-month change in BLS CES total nonfarm payroll employment, seasonally adjusted, CES0000000001, be for November 2026?","unit":"thousands","pointEstimate":83,"ciLow":-49,"ciHigh":215,"confidence":0.8,"resolutionDate":"2026-12-04","resolutionSource":"U.S. Bureau of Labor Statistics, Employment Situation, Current Employment Statistics Table B-1 / public API series CES0000000001","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001","resolutionRule":"Resolve to the first official BLS print for November 2026 total nonfarm payroll employment, seasonally adjusted, CES0000000001, in thousands, as the November 2026 level minus the October 2026 level. Use the initial release-policy value available with the Employment Situation released on 2026-12-04; do not incorporate later revisions, benchmark updates, or same-day corrections unless BLS replaces the first official print before the resolver captures it.","dataPointId":"bls.ces.nonfarm_payrolls.change.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":29},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":133},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":-10},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":31},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":63},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":148},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":214},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":-156}],"drivers":["Recent CES payroll growth is positive but uneven, with latest derived changes of 29, 133, -10, 31, 63, and 148 thousand.","The October and November prints are not yet known, so the forecast uses a current-release reference class rather than realized target-period data.","A modest positive update reflects continued expansion from the 2026 year-to-date mean, partly offset by cooling and high month-to-month noise."],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001?startyear=2025&endyear=2026","https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001?startyear=2026&endyear=2026","https://www.bls.gov/schedule/news_release/empsit.htm"],"runAt":"2026-11-02T23:41:03Z","reasoning":[{"kind":"heading","text":"November 2026 first-print nonfarm payroll forecast"},{"kind":"text","text":"The target is the first-print November 2026 month-over-month change in BLS CES total nonfarm payroll employment, seasonally adjusted, series CES0000000001, Table B-1, in thousands. The resolver should compute the difference from the first official November and October levels and ignore later revisions."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0001 to BLS public API CES0000000001 for 2025-2026","result":"Fetched official CES levels including 2026-09 = 159044, 2026-08 = 159015, 2026-07 = 158882, 2026-06 = 158892, 2026-05 = 158861, 2026-04 = 158798, 2026-03 = 158650, 2026-02 = 158436, 2026-01 = 158592, 2025-12 = 158432, 2025-11 = 158449, 2025-10 = 158408."},{"kind":"tool","tool":"official.lookup","call":"extract_json calls call-0006 through call-0017 from call-0001","result":"Extracted numeric levels: call-0006 159044, call-0007 159015, call-0009 158882, call-0008 158892, call-0010 158861, call-0011 158798, call-0012 158650, call-0013 158436, call-0016 158592, call-0015 158432, call-0014 158449, call-0017 158408."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0027 to BLS public API CES0000000001 for 2026 only","result":"Confirmed 2026 official levels in the second BLS API receipt: September 159044, August 159015, July 158882, June 158892, May 158861, April 158798, March 158650, February 158436, January 158592."},{"kind":"text","text":"Release-date check: direct evidence-tool reads of the BLS Employment Situation schedule URL returned HTTP 403 in call-0002, call-0003, and call-0004, so those attempts did not preserve official bytes. I used the sealed public repository anchor-verification record, which states the BLS Employment Situation schedule page was read from https://www.bls.gov/schedule/news_release/empsit.htm and mapped 2026-11 to 2026-12-04 at 08:30 ET; this matches the registered target window."},{"kind":"tool","tool":"official.calculate","call":"calculate call-0022 over derived BLS level differences [29,133,-10,31,63,148,214,-156,160,-17,41]","result":"The reference class mean from the fetched official CES levels is 57.81818181818182 thousand."},{"kind":"tool","tool":"official.calculate","call":"calculate calls call-0024 and call-0023 over the same derived changes","result":"The sample standard deviation is sigma = 103.14729097927699 thousand, and 1.28*sigma = 132.02853245347455 thousand."},{"kind":"math","text":"Prior/update/interval: base rate/reference class is the recent official CES0000000001 month-to-month change series derived from fetched BLS levels: 29, 133, -10, 31, 63, 148, 214, -156, 160, -17, 41 thousand, with mean 57.8. I use that as the persistence/current-release prior, add +25 thousand for level/momentum judgment because payroll growth remained mostly positive despite cooling and because two more pre-target months can normalize some recent weakness, giving point = round(57.8 + 25) = 83. For the 80% interval, sigma = 103.14729097927699 from realized changes, so half-width is roughly 1.28*sigma = 132.02853245347455; 83 - 132.0 = -49.0 and 83 + 132.0 = 215.0, rounded to [-49, 215]."},{"kind":"text","text":"Upside risk: a rebound in private services hiring, education/health care, or catch-up after weak October data would land above the interval if November payrolls exceed about 215 thousand. Downside risk: a sharp slowdown, strike effects, federal-sector drag, or a weak October base feeding into November would land below the interval if the first print is below -49 thousand. An outside the interval miss is plausible because first payroll prints are noisy and the forecast is made before the October payroll print."},{"kind":"forecast","point":83,"ciLow":-49,"ciHigh":215}]}
