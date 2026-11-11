# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: statbel.cpi.headline_yoy
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "belgium-cpi-annual-rate-september-2026"
- country: "BE"
- targetUnit: "percent"
- dataPointId: "statbel.cpi.headline_yoy.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-10-07", "start": "2026-09-29"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["statbel.fgov.be"], "expectedReleaseWindow": {"end": "2026-10-07", "start": "2026-09-29"}, "field": "statbel.cpi.headline_yoy", "releasePolicy": "first_print", "sourceSeriesId": "statbel.cpi.headline_yoy", "sourceUrl": "https://statbel.fgov.be/en/themes/consumer-prices/consumer-price-index", "table": "Statbel Consumer Price Index - Health Index release", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-f8846f2d36a637da92d8f74483a96279b757ff255008a02e7ae348f5f4bed77d.json"
- targetContentHash: "f8846f2d36a637da92d8f74483a96279b757ff255008a02e7ae348f5f4bed77d"
- registrationCommit: "f527f4e54f1df0156366f87eeb5dd630eeb66fe4"
- registeredAtUtc: "2026-09-11T19:13:41Z"
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
2a469ae79168da783208ce656e4a523218c3559d40f676851e2464f728f0ae95

# Draft forecast response
{"slug":"belgium-cpi-annual-rate-september-2026","country":"BE","type":"data","title":"Belgium CPI Inflation September 2026","question":"What will Statbel first report as Belgium's national Consumer Price Index headline annual inflation rate for September 2026, not HICP and not the health index?","unit":"percent","pointEstimate":3.85,"ciLow":2.81,"ciHigh":4.89,"confidence":0.8,"resolutionDate":"2026-09-29","resolutionSource":"Statbel Consumer Price Index - Health Index first release and be.STAT CPI inflation table","resolutionSourceUrl":"https://bestat.statbel.fgov.be/bestat/crosstable.xhtml?view=bee1820f-cbdb-4705-aac4-cfcf40680eb7","resolutionRule":"Resolve on the first official Statbel print for Consumer Price Index - Health Index, m-2026-09, using the national CPI headline annual inflation percentage for September 2026 as printed by Statbel, rounded to two decimals. Exclude HICP, health-index inflation, smoothed health index, and later revisions.","dataPointId":"statbel.cpi.headline_yoy.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2025-08"},"label":"August 2025","value":1.91},{"period":{"type":"month","value":"2025-09"},"label":"September 2025","value":2.12},{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":2},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":2.4},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":2.06},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":1.1},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":1.45},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":1.65},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":4.01},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":4.08},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":3.4},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":3.56},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":3.97}],"drivers":["August headline CPI inflation was 3.97 percent","Energy inflation rose to 16.47 percent in August","Core inflation eased to 2.99 percent","September 2025 denominator was low","Recent monthly changes are volatile"],"sourceContext":["https://statbel.fgov.be/en/calendar","https://statbel.fgov.be/en/themes/consumer-prices/consumer-price-index","https://bestat.statbel.fgov.be/bestat/crosstable.xhtml?view=bee1820f-cbdb-4705-aac4-cfcf40680eb7","https://bestat.statbel.fgov.be/bestat/crosstable.xhtml?view=6354a929-6969-4172-8143-e57aab550cc3"],"runAt":"2026-09-11T19:16:49Z","reasoning":[{"kind":"heading","text":"Belgium September 2026 headline CPI inflation forecast"},{"kind":"text","text":"This forecast targets Statbel's national Consumer Price Index headline annual inflation rate for September 2026, first print, in percent. The variant is the national CPI headline inflation series, not HICP, not health-index inflation, and not the smoothed health index."},{"kind":"tool","tool":"official.lookup","call":"Checked the Statbel release calendar for the September 2026 CPI release date and adjacent CPI/HICP items.","result":"The official calendar lists Consumer Price Index - Health Index for m-2026-09 on 29 September 2026, HICP for m-2026-09 on 15 October 2026, and Consumer Price Index - Health Index for m-2026-10 on 29 October 2026."},{"kind":"tool","tool":"official.lookup","call":"Fetched Statbel be.STAT annual inflation rate table for special aggregates, latest 13 months, and selected the headline national CPI column.","result":"Fetched headline CPI annual inflation prints: August 2025 1.91, September 2025 2.12, October 2025 2.00, November 2025 2.40, December 2025 2.06, January 2026 1.10, February 2026 1.45, March 2026 1.65, April 2026 4.01, May 2026 4.08, June 2026 3.40, July 2026 3.56, August 2026 3.97 percent."},{"kind":"tool","tool":"official.lookup","call":"Fetched the official Statbel August 2026 CPI release page for current-release detail and drivers.","result":"August 2026 headline inflation was 3.97 percent versus 3.56 percent in July and 3.40 percent in June; CPI rose 0.41 index points or 0.40 percent month on month; energy inflation was 16.47 percent, natural gas rose 9.8 percent month on month, and motor fuels rose 4.7 percent month on month."},{"kind":"tool","tool":"official.lookup","call":"Fetched the Statbel CPI index table to cross-check the annual-rate identity and recent index levels.","result":"The headline CPI index was 103.26 in May 2026, 102.95 in June 2026, 103.60 in July 2026, and 104.01 in August 2026 on the 2025=100 basis; the September 2025 headline CPI index in the same table was 99.74."},{"kind":"text","text":"The base rate/reference class is the last 13 official headline CPI annual inflation prints. Their mean is 2.59 percent, their median is 2.12 percent, but the post-April energy-regime sample is materially higher: April-August prints are 4.01, 4.08, 3.40, 3.56, and 3.97 percent. I therefore put more weight on near-term persistence than on the full-sample mean."},{"kind":"math","text":"Prior/update/interval: persistence prior is August headline CPI inflation at 3.97 percent. Historical sample is the 13 official headline prints from August 2025 through August 2026, with successive monthly changes of +0.21, -0.12, +0.40, -0.34, -0.96, +0.35, +0.20, +2.36, +0.07, -0.68, +0.16, and +0.41 percentage points. Adjustment components: -0.20 pp for likely partial reversal/normalization of August energy and fuel jumps, +0.08 pp for the low September 2025 denominator and still-firm core, giving 3.97 - 0.20 + 0.08 = 3.85 percent. Interval method: sample standard deviation of successive changes gives sigma = 0.814, so the 80 percent half-width is about 1.28*sigma = 1.28*0.814 = 1.04 pp; final implied bounds are 3.85 - 1.04 = 2.81 and 3.85 + 1.04 = 4.89 percent."},{"kind":"text","text":"Upside risk is another rise in natural gas, electricity, or motor fuels after August's already large energy contribution, which would land above the interval if combined with broad services inflation. Downside risk is a sharp reversal in energy and travel-related prices plus softer food and rent components, which would land below the interval if the September index falls much more than the prior-year September base."},{"kind":"forecast","point":3.85,"ciLow":2.81,"ciHigh":4.89}]}
