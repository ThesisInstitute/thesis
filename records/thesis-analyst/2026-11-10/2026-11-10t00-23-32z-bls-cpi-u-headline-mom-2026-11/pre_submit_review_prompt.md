# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.cpi.u.headline_mom
- period: 2026-11
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-cpi-u-mom-november-2026"
- country: "US"
- targetUnit: "percent_growth"
- dataPointId: "bls.cpi.u.headline_mom.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-10", "start": "2026-12-10"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-10", "start": "2026-12-10"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "CUSR0000SA0", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0", "table": "Consumer Price Index for All Urban Consumers, US city average, all items, seasonally adjusted (CPI news release, Table A)", "transform": {"factor": 1, "operation": "percent_change_previous_period"}}
- targetRegistrationPath: "records/targets/2026-11-10-1063431fc3edbea30f81d65709f46ae1d1f5fb06c004730cac84e427afd85c0b.json"
- targetContentHash: "1063431fc3edbea30f81d65709f46ae1d1f5fb06c004730cac84e427afd85c0b"
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
0a052ff047f1b3861eb82509eb29be33d6b35c8c8fee07c1cae169d4cbb40719

# Draft forecast response
{"slug":"us-cpi-u-mom-november-2026","country":"US","type":"data","title":"US CPI-U MoM, Nov 2026","question":"What will the first official BLS print show for the November 2026 month-over-month percent change in seasonally adjusted CPI-U all items, U.S. city average, series CUSR0000SA0?","unit":"percent_growth","pointEstimate":0.2,"ciLow":-0.33,"ciHigh":0.73,"confidence":0.8,"resolutionDate":"2026-12-10","resolutionSource":"BLS Public Data API, CPI-U all items seasonally adjusted series CUSR0000SA0","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0","resolutionRule":"Use the first official BLS print for November 2026 CPI-U all items, U.S. city average, seasonally adjusted, series CUSR0000SA0. Compute percent_growth as 100 * (November 2026 index / October 2026 index - 1), using the initially published BLS API values for those months; do not incorporate later revisions, annual seasonal-adjustment updates, or same-day corrections unless they are already part of the first official API print.","dataPointId":"bls.cpi.u.headline_mom.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":0.64},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":0.473},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":-0.422},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":0.074},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":0.396},{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":0.649}],"drivers":["Recent CPI-U all-items SA monthly base rate is near 0.30 percent","Energy contribution is uncertain and likely softer than September","Shelter inflation remains a positive underlying contributor","Goods prices and seasonal-adjustment noise can move the first print materially"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0","https://blsmon1.bls.gov/schedule/2026/12_sched_list.htm"],"runAt":"2026-11-10T00:24:27Z","reasoning":[{"kind":"heading","text":"US CPI-U November 2026 First-Print Forecast"},{"kind":"text","text":"Framing and exact resolver: this targets BLS CPI-U all items, U.S. city average, seasonally adjusted, series CUSR0000SA0, for November 2026. The ledger transform is percent_change_previous_period, so resolution is the first-print November index divided by the first-print October index minus 1, expressed in percent_growth."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0004: BLS official release schedule page for December 2026 from blsmon1.bls.gov after direct www.bls.gov schedule fetches call-0002 and call-0003 returned 403","result":"Captured BLS schedule page bytes with status 200; the page is Schedule of Selected Releases for December 2026 and includes the Consumer Price Index for November 2026 release on December 10, 2026 at 08:30 Eastern. A hosted web search also showed the same www.bls.gov calendar row, but that separate evidence was not captured by thesis_tool_evidence."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0001: BLS Public Data API for CUSR0000SA0","result":"Fetched CPI-U all items SA index levels including 2026-09 = 336.298, 2026-08 = 334.131, 2026-07 = 332.813, 2026-06 = 332.568, 2026-05 = 333.979, 2026-04 = 332.407, and 2026-03 = 330.293."},{"kind":"tool","tool":"official.lookup","call":"extract_json calls call-0005 through call-0011 from call-0001","result":"Extracted numeric index values: Sep 2026 336.298, Aug 2026 334.131, Jul 2026 332.813, Jun 2026 332.568, May 2026 333.979, Apr 2026 332.407, Mar 2026 330.293."},{"kind":"tool","tool":"official.calculate","call":"calculate calls call-0012 through call-0017 using BLS index levels","result":"Computed same-variant CPI-U all items SA month-over-month percent changes: Apr 2026 0.6400377846336402, May 2026 0.47291422864139676, Jun 2026 -0.42248165303806484, Jul 2026 0.07366914435544825, Aug 2026 0.3960181843858157, Sep 2026 0.6485480245771891."},{"kind":"text","text":"Base rate/reference class: the recent official-source reference class is the last six available transformed monthly CPI-U all-items SA prints from BLS API series CUSR0000SA0. They average moderately positive inflation but include one negative month, so I treat the base rate as noisy rather than a stable trend."},{"kind":"math","text":"Prior/update/interval: persistence prior is the six-print BLS reference class from Apr-Sep 2026; call-0019 gives base mean 0.3014509522592375 percent. Judgment adjustments are energy -0.08, goods -0.04, and shelter/core persistence +0.02, giving call-0024 point 0.2014509522592375 percent. Interval method uses realized dispersion of the same six change prints: sigma = 0.41217059726119976 from call-0020, so 1.28*sigma = 0.5275783644943357 from call-0021. Applying that around the point gives call-0025 low -0.3261274122350982 and call-0026 high 0.7290293167535732, rounded to -0.33 and 0.73."},{"kind":"text","text":"Level, momentum, and mechanism: September's transformed print was high at 0.6485480245771891, while June was -0.42248165303806484, so the near-term level path is volatile. I put less weight on a straight September carry-forward because all-items CPI is sensitive to energy and seasonal-adjustment effects, but I keep the point above zero because shelter and services inflation usually keep headline CPI from staying negative absent a large energy drop."},{"kind":"text","text":"Counter-considerations: upside risk is a renewed gasoline or airfares spike plus sticky shelter, which would land above the interval if the first print exceeds 0.73 percent. Downside risk is a sharp energy decline or broad goods discounting, which would land below the interval if the first print is below -0.33 percent. Outside the interval would most likely require a commodity shock, a seasonal-adjustment surprise, or an unusual data/reweighting effect in the first BLS print."},{"kind":"forecast","point":0.2,"ciLow":-0.33,"ciHigh":0.73}]}
