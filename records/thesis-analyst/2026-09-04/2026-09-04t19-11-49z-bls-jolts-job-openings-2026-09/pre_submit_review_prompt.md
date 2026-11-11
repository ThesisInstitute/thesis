# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.jolts.job_openings
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "jolts-openings-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.jolts.job_openings.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-11-09", "start": "2026-11-01"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-11-09", "start": "2026-11-01"}, "field": "bls.jolts.job_openings", "releasePolicy": "first_print", "sourceSeriesId": "bls.jolts.job_openings", "sourceUrl": "https://www.bls.gov/news.release/jolts.nr0.htm", "table": "U.S. Bureau of Labor Statistics Job Openings and Labor Turnover Survey first-print release", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-25f383726a59f3170ab6359a0393aae5291197c2654c5e5ad362fcc4e0fef3f9.json"
- targetContentHash: "25f383726a59f3170ab6359a0393aae5291197c2654c5e5ad362fcc4e0fef3f9"
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
5282ea35dde5c16971488bedc674d9d1c1ac02f2557279a41605d33ed6125092

# Draft forecast response
{"slug":"jolts-openings-september-2026","country":"US","type":"data","title":"US JOLTS job openings, September 2026","question":"What will BLS first report for total nonfarm job openings, seasonally adjusted, for September 2026 in the Job Openings and Labor Turnover Survey release?","unit":"millions","pointEstimate":7.32,"ciLow":6.69,"ciHigh":7.95,"confidence":0.8,"resolutionDate":"2026-11-03","resolutionSource":"U.S. Bureau of Labor Statistics Job Openings and Labor Turnover Survey first-print release","resolutionSourceUrl":"https://www.bls.gov/news.release/jolts.nr0.htm","resolutionRule":"Resolve to the first-published preliminary BLS Job Openings and Labor Turnover Survey total nonfarm job openings level, seasonally adjusted, for September 2026, from Table A or Table 1 of the initial release. The printed level is in thousands and is multiplied by 0.001 to millions. Ignore later monthly revisions, annual benchmark revisions, corrections after the first official print, and database values revised after the release.","dataPointId":"bls.jolts.job_openings.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":6.542},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":6.946},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":6.882},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":6.866},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":7.618},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":7.594},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":7.359},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":7.271}],"drivers":["July first-print openings were 7.271 million, close to the recent 7.3 million center","Recent first-print changes are volatile, with a 0.752 million April jump followed by smaller declines","August payroll growth of 162000 and 4.1 percent unemployment reduce near-term downside pressure","Low-hire, low-fire conditions argue against a sharp September breakout"],"sourceContext":["https://www.bls.gov/schedule/news_release/jolts.htm?stream=business","https://www.bls.gov/news.release/archives/jolts_02052026.htm","https://www.bls.gov/news.release/archives/jolts_03132026.htm","https://www.bls.gov/news.release/archives/jolts_03312026.htm","https://www.bls.gov/news.release/archives/jolts_05052026.htm","https://www.bls.gov/news.release/archives/jolts_06022026.htm","https://www.bls.gov/news.release/archives/jolts_06302026.htm","https://www.bls.gov/news.release/archives/jolts_08042026.htm","https://www.bls.gov/news.release/archives/jolts_09012026.htm","https://www.bls.gov/news.release/archives/empsit_09042026.htm","https://www.bls.gov/news.release/jolts.nr0.htm"],"runAt":"2026-09-04T19:12:19Z","reasoning":[{"kind":"heading","text":"September 2026 BLS JOLTS job openings forecast"},{"kind":"text","text":"The resolver is the BLS JOLTS first-print preliminary total nonfarm job openings level, seasonally adjusted, for September 2026. The BLS schedule page lists September 2026 JOLTS for release on November 3, 2026 at 10:00 AM ET, so resolutionDate is 2026-11-03."},{"kind":"text","text":"Variant discipline: all anchors use the seasonally adjusted total nonfarm job openings level from BLS JOLTS Table A or equivalent first-print release table. The printed unit is thousands; this cell reports millions using the registered 0.001 transform."},{"kind":"tool","tool":"official.lookup","call":"BLS JOLTS release calendar lookup for September 2026","result":"Fetched schedule rows: July 2026 release Sep. 01, 2026 at 10:00 AM; August 2026 release Sep. 29, 2026 at 10:00 AM; September 2026 release Nov. 03, 2026 at 10:00 AM."},{"kind":"tool","tool":"official.lookup","call":"BLS archived JOLTS Table A first-print total job openings for late 2025 and early 2026","result":"Fetched first-print total job openings, seasonally adjusted, in thousands: December 2025 6542, January 2026 6946, February 2026 6882, March 2026 6866."},{"kind":"tool","tool":"official.lookup","call":"BLS archived JOLTS Table A first-print total job openings for April through July 2026","result":"Fetched first-print total job openings, seasonally adjusted, in thousands: April 2026 7618, May 2026 7594, June 2026 7359, July 2026 7271."},{"kind":"tool","tool":"official.lookup","call":"BLS Employment Situation August 2026 labor-market cross-check","result":"Fetched August 2026 labor-market values: total nonfarm payroll employment increased 162000, unemployment rate was 4.1 percent, June payroll change was revised to +31000, and July payroll change was revised to +21000."},{"kind":"text","text":"The reference class and base rate are recent same-series first prints: December 2025 through July 2026 total openings ran from 6.542 million to 7.618 million, with the latest July print at 7.271 million. A persistence prior around 7.27 million is more relevant than a long-run average because JOLTS is a level series with strong local persistence."},{"kind":"math","text":"Prior/update/interval: persistence prior is July 2026 first print 7.271 million; historical sample is BLS first-print monthly openings from December 2025 through July 2026; adjustment components are +0.03 million for the August payroll rebound and stable 4.1 percent unemployment, +0.02 million for current openings still above early-2026 levels, and roughly 0.00 million for policy mechanism effects because no direct September hiring mandate applies. Successive changes were +0.404, -0.064, -0.016, +0.752, -0.024, -0.235, -0.088 million; one-month sample stdev is 0.347, so two-month horizon sigma = sqrt(2)*0.347 = 0.490. The 80 percent half-width is 1.28*sigma = 1.28*0.490 = 0.627 million. Point is 7.271 + 0.05 = 7.32; interval is 7.32 +/- 0.63 = [6.69, 7.95]."},{"kind":"text","text":"Upside risk would come from August and September openings rising alongside the 162000 August payroll gain, especially in food services, education, construction, or health care; a September first print near 8.0 million or above would land above the interval. Downside risk is renewed hiring freezes or a pullback in professional and business services; a broad demand drop below about 6.7 million would land outside the interval on the low side."},{"kind":"forecast","point":7.32,"ciLow":6.69,"ciHigh":7.95}]}
