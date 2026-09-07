# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: statcan.gdp_by_industry.monthly_growth
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "canada-monthly-gdp-growth-september-2026"
- country: "CA"
- targetUnit: "percent_growth"
- dataPointId: "statcan.gdp_by_industry.monthly_growth.2026_09.first_print"
- expectedReleaseWindow: {"end": "2026-11-30", "start": "2026-11-30"}
- sourceBinding: {"adapter": "statcan-wds", "allowedHosts": ["www150.statcan.gc.ca"], "expectedReleaseWindow": {"end": "2026-11-30", "start": "2026-11-30"}, "field": "v65201210", "releasePolicy": "first_print", "sourceSeriesId": "v65201210", "sourceUrl": "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods", "table": "GDP by industry, Table 36-10-0434-01 (all industries, chained 2017 dollars, SA at annual rates)", "transform": {"factor": 1, "operation": "percent_change_previous_period"}}
- targetRegistrationPath: "records/targets/2026-09-07-5e66b8f80f1cc6a1847b0462471dc202581372c8d08b343f174d5679b35c89ba.json"
- targetContentHash: "5e66b8f80f1cc6a1847b0462471dc202581372c8d08b343f174d5679b35c89ba"
- registrationCommit: "f1baea413714fe099f71118840f6363977fcdb5c"
- registeredAtUtc: "2026-09-07T20:04:45Z"
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
6a29f59a2bfcb9d699b2ea6dc8f8dc11ca6a2e108b76dea8e11eb582ee8a801b

# Draft forecast response
{"slug":"canada-monthly-gdp-growth-september-2026","country":"CA","type":"data","title":"Canada monthly GDP growth, September 2026","question":"Statistics Canada Table 36-10-0434-01, all industries real GDP by industry, seasonally adjusted at annual rates, September 2026 first-print month-over-month percent growth computed from vector v65201210 levels.","unit":"percent_growth","pointEstimate":0.2,"ciLow":-0.1,"ciHigh":0.5,"confidence":0.8,"resolutionDate":"2026-11-30","resolutionSource":"Statistics Canada Table 36-10-0434-01, vector v65201210","resolutionSourceUrl":"https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods","resolutionRule":"Resolve to the first Statistics Canada print for September 2026 using vector v65201210 in Table 36-10-0434-01, all industries, Canada, chained 2017 dollars, seasonally adjusted at annual rates. Compute the month-over-month percent change from the August 2026 and September 2026 levels at that release vintage, round to one decimal percentage point, and ignore later revisions or later table updates.","dataPointId":"statcan.gdp_by_industry.monthly_growth.2026_09.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":0.1},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":0.2},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":-0.1},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":0.5},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":0.3},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":0.3}],"drivers":["Recent first-print monthly GDP growth averaged about 0.22%.","June 2026 was a third consecutive monthly gain, but July advance information was essentially unchanged.","Goods-sector volatility and resource-sector maintenance argue for a wide interval.","Services and public-sector activity provide a modest positive baseline."],"sourceContext":["https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf","https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods","https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3610043401","https://www150.statcan.gc.ca/n1/daily-quotidien/260331/dq260331a-eng.htm?HPA=1","https://www150.statcan.gc.ca/n1/daily-quotidien/260430/dq260430a-eng.htm","https://www150.statcan.gc.ca/n1/daily-quotidien/260529/dq260529b-eng.htm","https://www150.statcan.gc.ca/n1/daily-quotidien/260630/dq260630a-eng.htm","https://www150.statcan.gc.ca/n1/daily-quotidien/260731/dq260731a-eng.htm","https://www150.statcan.gc.ca/n1/daily-quotidien/260828/dq260828b-eng.htm"],"runAt":"2026-09-07T20:20:40Z","reasoning":[{"kind":"heading","text":"Forecast for Canada September 2026 monthly GDP by industry growth"},{"kind":"text","text":"Resolver: Statistics Canada Table 36-10-0434-01, all industries, chained 2017 dollars, seasonally adjusted at annual rates, vector v65201210. The target is the September 2026 first print, computed as the percent change from the August level to the September level at the first release vintage. Statistics Canada's 2026 release dates and the registered source binding put this release on 2026-11-30."},{"kind":"tool","tool":"official.lookup","call":"Read Statistics Canada The Daily releases for January, February, and March 2026 GDP by industry.","result":"Fetched first-print monthly changes from Table 36-10-0434-01 releases: January 2026 0.1%, February 2026 0.2%, March 2026 -0.1%; the March release also said first-quarter GDP by industry edged up 0.1%."},{"kind":"tool","tool":"official.lookup","call":"Read Statistics Canada The Daily releases for April, May, and June 2026 GDP by industry.","result":"Fetched first-print monthly changes from Table 36-10-0434-01 releases: April 2026 0.5%, May 2026 0.3%, June 2026 0.3%; the June release said 13 of 20 sectors grew and services-producing industries rose 0.4% while goods-producing industries edged down 0.1%."},{"kind":"tool","tool":"official.lookup","call":"Read the latest Statistics Canada June 2026 release for advance and sector context, using the same GDP by industry variant.","result":"Fetched advance information: real GDP was essentially unchanged in July 2026, after June 2026 official monthly growth of 0.3%; May 2026 had an advance estimate of 0.2% for June before the official June print came in at 0.3%; second-quarter 2026 GDP by industry rose 0.9%."},{"kind":"text","text":"Base rate/reference class: the six latest official first-print monthly changes available before this forecast are 0.1%, 0.2%, -0.1%, 0.5%, 0.3%, and 0.3%, all from the same seasonally adjusted real GDP by industry variant. Their mean is 0.2167%, so the outside-view base rate is a low-positive monthly gain near 0.2%."},{"kind":"text","text":"Level, momentum, one-off, and policy-mechanism effects: the level path through June was improving after March weakness; momentum is positive but likely fading because StatCan's July advance was essentially unchanged; one-off boosts from census-related public administration and deferred resource maintenance may not persist into September; policy and rate effects should lean mildly restrictive rather than recessionary."},{"kind":"math","text":"Prior/update/interval: persistence/base-rate prior uses the six official first-print monthly growth values [0.1, 0.2, -0.1, 0.5, 0.3, 0.3], mean = 0.2167. Adjustments are -0.05 for July advance stagnation, +0.02 for services/public-sector resilience, and -0.01 for one-off Q2 resource/public boosts fading, giving 0.1767, rounded to a 0.2 point forecast. For a change/flow series, compute dispersion from the values themselves: sample sigma = sqrt(sum((x - 0.2167)^2) / 5) = 0.204. The 80% half-width is about 1.28*sigma = 1.28*0.204 = 0.261; centered on 0.1767 gives [-0.084, 0.438], rounded to one-decimal target precision and slightly padded to [-0.1, 0.5]."},{"kind":"text","text":"Counter-consideration: upside risk would come from a broad September rebound in manufacturing, wholesale, and resource extraction after a flat July; downside risk would come from renewed resource-sector outages, weaker housing-linked services, or tariff-sensitive manufacturing weakness. A monthly print above 0.5% or below -0.1% would land outside the interval."},{"kind":"forecast","point":0.2,"ciLow":-0.1,"ciHigh":0.5}]}
