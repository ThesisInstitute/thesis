# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.cpi.u.core_mom
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-core-cpi-mom-september-2026"
- country: "US"
- targetUnit: "percent_growth"
- dataPointId: "bls.cpi.u.core_mom.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-10-15", "start": "2026-10-07"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-15", "start": "2026-10-07"}, "field": "bls.cpi.u.core_mom", "releasePolicy": "first_print", "sourceSeriesId": "bls.cpi.u.core_mom", "sourceUrl": "https://www.bls.gov/news.release/cpi.nr0.htm", "table": "U.S. Bureau of Labor Statistics Consumer Price Index news release", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-666261cec19a56b9b6ecf64c9af43bfa61c5ba5cc0df43fdb99d3830912c1d37.json"
- targetContentHash: "666261cec19a56b9b6ecf64c9af43bfa61c5ba5cc0df43fdb99d3830912c1d37"
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
0e081c9eefd605a88df65d3534586df23552c23806b520e388cab7549367bbbb

# Draft forecast response
{"slug":"us-core-cpi-mom-september-2026","country":"US","type":"data","title":"US Core CPI MoM, Sep 2026","question":"What will the U.S. Bureau of Labor Statistics report as the September 2026 seasonally adjusted 1-month percent change in CPI-U all items less food and energy in the first CPI news release?","unit":"percent_growth","pointEstimate":0.25,"ciLow":0.1,"ciHigh":0.4,"confidence":0.8,"resolutionDate":"2026-10-14","resolutionSource":"U.S. Bureau of Labor Statistics Consumer Price Index news release","resolutionSourceUrl":"https://www.bls.gov/news.release/cpi.nr0.htm","resolutionRule":"Resolve to the first BLS Consumer Price Index news release for September 2026, Table A, CPI-U U.S. city average, seasonally adjusted change from preceding month, row 'All items less food and energy'. Use the initially published one-decimal percent value; ignore later revisions or corrected historical vintages unless BLS replaces the first print before public release.","dataPointId":"bls.cpi.u.core_mom.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":0.3},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":0.2},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":0.2},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":0.4},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":0.2},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":0},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":0.2}],"drivers":["recent core prints centered near 0.2 percent","shelter still positive but cooling","core services ex-energy remain sticky","goods disinflation limits upside","August print not yet released at run time"],"sourceContext":["https://www.bls.gov/news.release/cpi.nr0.htm","https://www.bls.gov/schedule/news_release/cpi.htm"],"runAt":"2026-09-04T19:07:25Z","reasoning":[{"kind":"heading","text":"Forecast for September 2026 core CPI-U month-over-month"},{"kind":"text","text":"The resolver is BLS CPI-U, U.S. city average, all items less food and energy, seasonally adjusted change from the preceding month, first September 2026 CPI Summary print. The ledger window ends 2026-10-15, but the official BLS CPI release schedule fetched this run lists the September 2026 CPI release on 2026-10-14 at 08:30 ET; I keep the registered slug, unit, and dataPointId while using the official calendar date."},{"kind":"tool","tool":"official.lookup","call":"Opened BLS CPI release schedule and current CPI Summary page to verify target timing and latest available release vintage.","result":"Fetched BLS schedule: September 2026 CPI release date 2026-10-14, release time 08:30 AM; current CPI Summary is July 2026, released 2026-08-12, with core CPI-U month-over-month at 0.2 percent."},{"kind":"tool","tool":"official.lookup","call":"Read BLS CPI Summary Table A for the same variant: CPI-U all items less food and energy, seasonally adjusted changes from preceding month.","result":"Fetched Table A core CPI-U MoM values: January 2026 0.3, February 2026 0.2, March 2026 0.2, April 2026 0.4, May 2026 0.2, June 2026 0.0, July 2026 0.2 percent."},{"kind":"tool","tool":"official.lookup","call":"Read the July 2026 BLS CPI Summary component narrative for current-release momentum and one-off contributors.","result":"Fetched July 2026 BLS component numbers: all items 0.1 percent, energy -1.5 percent, all items less food and energy 0.2 percent, shelter 0.1 percent, medical care 0.4 percent, airline fares 2.2 percent, motor vehicle insurance -0.3 percent."},{"kind":"text","text":"The reference class and base rate are the latest seven official first-print-style monthly core CPI readings available in the BLS release table for this exact SA CPI-U core variant. Their mean is about 0.21 percent, with most readings between 0.0 and 0.4 percent."},{"kind":"math","text":"Prior/update/interval: persistence prior is the recent official-reference-class mean of Jan-Jul 2026 core CPI MoM, (0.3+0.2+0.2+0.4+0.2+0.0+0.2)/7 = 0.214 percent. Updates: shelter cooling and July shelter 0.1 subtract about 0.02; sticky core services and medical care add about 0.03; no clear energy direct effect because this is ex-food-energy; modest goods stabilization adds about 0.02. Point rounds to 0.25 percent. For a change/flow series, interval sigma uses the fetched values themselves: sample sigma = 0.12 from [0.3,0.2,0.2,0.4,0.2,0.0,0.2], so 1.28*sigma = 0.15. Applying that half-width to 0.25 gives final implied bounds 0.10 to 0.40 percent."},{"kind":"text","text":"Upside risk is a renewed jump in core services, medical care, insurance, or airfare that would land above the interval. Downside risk is another broad services pause plus softer shelter and goods deflation that would land below the interval; an outside the interval print would likely need several large components to move in the same direction."},{"kind":"forecast","point":0.25,"ciLow":0.1,"ciHigh":0.4}]}
