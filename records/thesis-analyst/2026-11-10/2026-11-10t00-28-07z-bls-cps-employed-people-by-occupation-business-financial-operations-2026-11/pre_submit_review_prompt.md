# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.cps.employed_people_by_occupation.business_financial_operations
- period: 2026-11
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-business-financial-employment-november-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.business_financial_operations.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-04", "start": "2026-12-04"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-04", "start": "2026-12-04"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "LNU02032454", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032454", "table": "Current Population Survey, employed people, Business and financial operations occupations, total 16 years and over, not seasonally adjusted, in thousands (Employment Situation, Table A-19)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-11-10-0d76d97cc6412fa35c60f572b02c4a00c2f76ab4a3acddeeda492e79d2b815f9.json"
- targetContentHash: "0d76d97cc6412fa35c60f572b02c4a00c2f76ab4a3acddeeda492e79d2b815f9"
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
e3552cd67c39fa889265fbf6bebffd444daa9e4a671ea9345faf29d4631034c1

# Draft forecast response
{"slug":"cps-business-financial-employment-november-2026","country":"US","type":"data","title":"US business and financial employment, Nov. 2026","question":"BLS Current Population Survey series LNU02032454, employed people in business and financial operations occupations, 16 years and over, not seasonally adjusted, November 2026 first print, converted from thousands to millions.","unit":"millions","pointEstimate":10.3,"ciLow":10.1,"ciHigh":10.5,"confidence":0.8,"resolutionDate":"2026-12-04","resolutionSource":"BLS Public Data API series LNU02032454, Employment Situation Table A-19","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032454","resolutionRule":"Resolve to the first BLS public API value for series LNU02032454, period 2026 M11, field value, as first printed for the Employment Situation release scheduled for December 4, 2026. The API value is in thousands; multiply by 0.001 and report in millions. Do not use later revisions, corrected same-day values, or alternate seasonal-adjustment variants unless the registered resolver changes.","dataPointId":"bls.cps.employed_people_by_occupation.business_financial_operations.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":10.251},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":10.212},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":10.23},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":10.192},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":10.195},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":10.133},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":10.033},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":9.72},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":9.835},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":10.167},{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":10.268},{"period":{"type":"month","value":"2026-10"},"label":"October 2026","value":10.337}],"drivers":["October 2026 level was 10.337 million after applying the registered thousands-to-millions transform","Recent 12-print reference class is centered near 10.2 million with mild positive drift","NSA occupation detail is noisy month to month, including a June 2026 trough and August rebound","A small November seasonal drag is plausible, based partly on the 2024 October-to-November decline","Resolution calendar is verified from BLS calendar pages for the November 2026 Employment Situation release"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032454","https://blsmon1.bls.gov/schedule/2026/12_sched_list.htm","https://blsmon1.bls.gov/schedule/news_release/bls.ics"],"runAt":"2026-11-10T00:28:55Z","reasoning":[{"kind":"heading","text":"BLS CPS Business And Financial Occupation Employment Forecast"},{"kind":"text","text":"The target is BLS CPS series LNU02032454, Current Population Survey employed people in business and financial operations occupations, total 16 years and over, not seasonally adjusted, Table A-19. The source series is in thousands and the registered resolver converts to millions with factor 0.001."},{"kind":"text","text":"BLS schedule evidence was captured from the December 2026 selected-release page as call-0004 and the BLS calendar feed as call-0005; hosted search also showed the official BLS Employment Situation schedule listing November 2026 for Dec. 04, 2026 at 08:30 AM, while direct fetches of www.bls.gov schedule pages returned 403 in call-0002 and call-0003."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0001 and extract_json call-0006 for BLS Public Data API series LNU02032454","result":"Fetched official values include October 2026 = 10337 thousand, September 2026 = 10268 thousand, August 2026 = 10167 thousand, July 2026 = 9835 thousand, June 2026 = 9720 thousand, and May 2026 = 10033 thousand."},{"kind":"tool","tool":"official.lookup","call":"read older observations from captured BLS API payload call-0001/call-0006","result":"Additional fetched official values include April 2026 = 10133 thousand, March 2026 = 10195 thousand, February 2026 = 10192 thousand, January 2026 = 10230 thousand, December 2025 = 10212 thousand, and November 2025 = 10251 thousand."},{"kind":"tool","tool":"official.lookup","call":"same-series context from captured BLS API payload call-0001/call-0006","result":"The same official BLS response shows 2025 October unavailable, September 2025 = 10194 thousand, August 2025 = 10114 thousand, July 2025 = 10298 thousand, June 2025 = 10205 thousand, and November 2024 = 9892 thousand; the 2025 lapse note makes October 2025 unsuitable as an October-to-November anchor."},{"kind":"math","text":"The base rate reference class is the recent same-series NSA level history from November 2025 through October 2026, excluding unavailable October 2025. Converted to millions, the chronological history is 10.251, 10.212, 10.230, 10.192, 10.195, 10.133, 10.033, 9.720, 9.835, 10.167, 10.268, 10.337."},{"kind":"math","text":"Prior/update/interval: persistence prior uses latest official level 10.337 million plus the mean recent monthly change from call-0009, +0.0078 million, giving 10.3448 million in call-0010; I apply a -0.045 million judgmental November NSA seasonal adjustment because 2024 October-to-November fell from 10.001 to 9.892 million and 2025 October is unavailable, yielding point 10.2998 million in call-0011. The interval method uses successive changes from the 12-print history; call-0007 gives sigma = 0.1590 million, so 1.28*sigma = 0.2035 million in call-0008, with bounds 10.0963 and 10.5034 from call-0012 and call-0013."},{"kind":"text","text":"Upside risk is another late-2026 occupation-specific rebound like August 2026, which would land above the interval if November prints above 10.5 million. Downside risk is renewed weakness like the June 2026 drop or a compositional decline in this occupation category, which would land outside the interval below 10.1 million."},{"kind":"forecast","point":10.3,"ciLow":10.1,"ciHigh":10.5}]}
