# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.jolts.quits_rate
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "jolts-quits-rate-september-2026"
- country: "US"
- targetUnit: "percent"
- dataPointId: "bls.jolts.quits_rate.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-11-02", "start": "2026-10-25"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-11-02", "start": "2026-10-25"}, "field": "bls.jolts.quits_rate", "releasePolicy": "first_print", "sourceSeriesId": "bls.jolts.quits_rate", "sourceUrl": "https://www.bls.gov/news.release/jolts.t04.htm", "table": "U.S. Bureau of Labor Statistics Job Openings and Labor Turnover Survey Table 4", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-74e02458a389a50401eff733c388f7e2276c14828bb9b452fa18bab5db1d8860.json"
- targetContentHash: "74e02458a389a50401eff733c388f7e2276c14828bb9b452fa18bab5db1d8860"
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
f8df56f0e44dbd60fcd79422729aad16bae994abcdee5a85de97475625349427

# Draft forecast response
{"slug":"jolts-quits-rate-september-2026","country":"US","type":"data","title":"US JOLTS quits rate, September 2026","question":"What will the U.S. Bureau of Labor Statistics JOLTS Table 4 preliminary Total quits rate, seasonally adjusted, be for September 2026 in the first official print?","unit":"percent","pointEstimate":1.9,"ciLow":1.77,"ciHigh":2.03,"confidence":0.8,"resolutionDate":"2026-11-03","resolutionSource":"U.S. Bureau of Labor Statistics Job Openings and Labor Turnover Survey Table 4","resolutionSourceUrl":"https://www.bls.gov/news.release/jolts.t04.htm","resolutionRule":"Resolve to the preliminary Total quits rate, seasonally adjusted, in BLS JOLTS Table 4 for September 2026 as first published by BLS; use the published percent rounded to one decimal and do not incorporate later revisions, annual benchmark updates, errata, or same-day corrections unless the registered target rule is amended.","dataPointId":"bls.jolts.quits_rate.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":2.0},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":1.9},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":2.0},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":1.9},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":1.9},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":2.0},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":1.9}],"drivers":["recent quits-rate persistence near 1.9 percent","no clear first-print momentum since January 2026","cool but not collapsing labor turnover","September forecast made before August JOLTS release"],"sourceContext":["https://www.bls.gov/schedule/news_release/jolts.htm","https://www.bls.gov/news.release/jolts.t04.htm","https://www.bls.gov/news.release/archives/jolts_03132026.htm","https://www.bls.gov/news.release/archives/jolts_03312026.htm","https://www.bls.gov/news.release/archives/jolts_05052026.htm","https://www.bls.gov/news.release/archives/jolts_06022026.htm","https://www.bls.gov/news.release/archives/jolts_06302026.htm","https://www.bls.gov/news.release/archives/jolts_08042026.htm","https://www.bls.gov/news.release/archives/jolts_09012026.htm"],"runAt":"2026-09-04T19:14:06Z","reasoning":[{"kind":"heading","text":"Forecast for BLS JOLTS quits rate, September 2026 first print"},{"kind":"text","text":"Resolver: BLS JOLTS Table 4, Total quits rate, seasonally adjusted, preliminary September 2026 first print. The registered target window ends 2026-11-02, but the official BLS JOLTS release calendar fetched this run lists September 2026 for release on 2026-11-03 at 10:00 a.m. ET, so I use 2026-11-03 as the verified resolutionDate while keeping the registered slug and dataPointId."},{"kind":"tool","tool":"official.lookup","call":"Fetched BLS JOLTS release calendar for the target reference month.","result":"BLS schedule lists July 2026 release on 2026-09-01, August 2026 release on 2026-09-29, September 2026 release on 2026-11-03, and October 2026 release on 2026-12-01."},{"kind":"tool","tool":"official.lookup","call":"Fetched BLS archived JOLTS Table 4 first-print releases for January through March 2026.","result":"First-print seasonally adjusted Total quits rates from BLS Table 4: January 2026 = 2.0 percent with 3,137 thousand quits; February 2026 = 1.9 percent with 2,974 thousand quits; March 2026 = 2.0 percent with 3,171 thousand quits."},{"kind":"tool","tool":"official.lookup","call":"Fetched BLS archived JOLTS Table 4 first-print releases for April through July 2026.","result":"First-print seasonally adjusted Total quits rates from BLS Table 4: April 2026 = 1.9 percent with 2,977 thousand quits; May 2026 = 1.9 percent with 3,065 thousand quits; June 2026 = 2.0 percent with 3,232 thousand quits; July 2026 = 1.9 percent with 3,056 thousand quits."},{"kind":"tool","tool":"official.lookup","call":"Fetched current BLS JOLTS Table 4 and summary for same-variant context.","result":"Current BLS July 2026 Table 4 shows Total quits rate = 1.9 percent, Total quits level = 3,056 thousand, June 2026 revised quits rate = 2.0 percent, and July quits changed by -157 thousand from June."},{"kind":"text","text":"The reference class is same-variant BLS JOLTS Table 4 Total quits rate, seasonally adjusted, first print. Base rate anchor: the seven fetched first prints since January 2026 are 2.0, 1.9, 2.0, 1.9, 1.9, 2.0, and 1.9 percent, giving a mean of 1.943 percent and a median of 1.9 percent."},{"kind":"text","text":"Level effect favors 1.9 percent because the latest first print was 1.9 and the current revised Table 4 also places July at 1.9. Momentum effect is near zero: the sequence alternates 1.9 and 2.0 with no sustained climb or fall. One-off July industry weakness argues modestly below 2.0, while the policy-mechanism context of low quits as a worker-confidence measure argues against a rapid jump."},{"kind":"math","text":"Prior/update/interval: persistence prior on the same-variant first-print quits rate uses the January-July 2026 historical sample. Adjustments are level 1.90, momentum 0.00, one-off July weakness -0.02, and mean reversion +0.02, implying point = 1.90 percent. Successive changes are -0.1, +0.1, -0.1, 0.0, +0.1, -0.1; sample sigma = 0.098 percentage point, so 1.28*sigma = 0.125. I use an 80 percent half-width of 0.13, giving 1.90 - 0.13 = 1.77 and 1.90 + 0.13 = 2.03."},{"kind":"text","text":"Counter-considerations: upside risk is a September rebound in voluntary quits from better worker confidence or service-sector churn, which would land above the interval if the first print rounds materially above 2.0 percent. Downside risk is a broader hiring slowdown or weaker labor-market confidence, which would land below the interval if the first print rounds materially below 1.8 percent. The outside the interval cases require a larger-than-recent monthly move."},{"kind":"forecast","point":1.9,"ciLow":1.77,"ciHigh":2.03}]}
