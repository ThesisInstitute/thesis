# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.cps.employed_people_by_occupation.transportation_material_moving
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-transport-material-moving-employment-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.transportation_material_moving.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-10-14", "start": "2026-10-06"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-14", "start": "2026-10-06"}, "field": "Transportation and material moving occupations", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.employed_people_by_occupation.transportation_material_moving", "sourceUrl": "https://www.bls.gov/web/empsit/cpseea19.htm", "table": "CPS Employment Situation Table A-19, employed persons by occupation, not seasonally adjusted (thousands)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-14-d6e9c92086ea70e8b59790dcc9ac070c7eb079e22a59c17d88d559ebccc62072.json"
- targetContentHash: "d6e9c92086ea70e8b59790dcc9ac070c7eb079e22a59c17d88d559ebccc62072"
- registrationCommit: "0f2c009b27e9b65c2aeb9b253934fd8b301b787e"
- registeredAtUtc: "2026-09-14T20:23:15Z"
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
fa4a7a2192dbd44d72d88aa5b22b316acb9ec411de6db5395fc58442b5908cab

# Draft forecast response
{"slug":"cps-transport-material-moving-employment-september-2026","country":"US","type":"data","title":"CPS transportation/material moving employment, Sep 2026","question":"What will the first official BLS CPS Employment Situation Table A-19 not-seasonally-adjusted employed people count be for Transportation and material moving occupations, total 16 years and over, in September 2026?","unit":"millions","pointEstimate":12.096,"ciLow":11.891,"ciHigh":12.301,"confidence":0.8,"resolutionDate":"2026-10-14","resolutionSource":"BLS Employment Situation Table A-19","resolutionSourceUrl":"https://www.bls.gov/web/empsit/cpseea19.htm","resolutionRule":"Resolve to the first official BLS CPS Employment Situation Table A-19, employed people by occupation, sex, and age, not seasonally adjusted, row Transportation and material moving occupations, Total 16 years and over column for September 2026, reported in thousands; multiply by 0.001 to convert to millions and round to three decimals. Use the first print only, with no later revisions or same-day correction grace unless the registered target is updated.","dataPointId":"bls.cps.employed_people_by_occupation.transportation_material_moving.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":12.214},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":12.127},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":12.12},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":12.01},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":12.223},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":12.011}],"drivers":["CPS household-survey occupation series is noisy month to month","not-seasonally-adjusted September level usually near late-summer level","August 2026 latest official table value was 12.011 million","recent six-print level centered near 12.118 million","transportation and warehousing payrolls showed little change in the latest Employment Situation narrative"],"sourceContext":["https://www.bls.gov/web/empsit/cpseea19.htm","https://www.bls.gov/schedule/news_release/empsit.htm","https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032214","https://fred.stlouisfed.org/series/LNU02032214","https://www.bls.gov/news.release/archives/empsit_11202025.htm","https://www.bls.gov/news.release/archives/empsit_10042024.htm","https://www.bls.gov/news.release/archives/empsit_10062023.htm","https://www.bls.gov/news.release/archives/empsit_10072022.htm"],"runAt":"2026-09-14T20:33:28Z","reasoning":[{"kind":"heading","text":"Forecast for September 2026 CPS transportation and material moving employment"},{"kind":"text","text":"The target is the BLS CPS household-survey occupation line, not seasonally adjusted, Table A-19 row Transportation and material moving occupations, total 16 years and over. The resolving public series corresponds to source code LNU02032214, reported in thousands and converted to millions by multiplying by 0.001."},{"kind":"tool","tool":"official.lookup","call":"Fetched the current BLS Table A-19 page at https://www.bls.gov/web/empsit/cpseea19.htm and read the Transportation and material moving occupations row.","result":"Current Table A-19 shows Transportation and material moving occupations total 16 years and over at Aug. 2025 = 11,647 thousand and Aug. 2026 = 12,011 thousand; the broader Production, transportation, and material moving occupations row is Aug. 2026 = 19,727 thousand."},{"kind":"tool","tool":"official.lookup","call":"Checked the BLS Employment Situation release calendar for the September 2026 reference month.","result":"The BLS schedule lists September 2026 Employment Situation release date Oct. 02, 2026 at 08:30 AM. The registered Thesis target has resolutionDate 2026-10-14 and expectedReleaseWindow 2026-10-06 to 2026-10-14, which appears inconsistent with the official calendar; I keep the registered resolutionDate because the prompt instructs using the ledger target contract."},{"kind":"tool","tool":"official.lookup","call":"Used the BLS public API series endpoint for LNU02032214 and the FRED mirror of that BLS source to assemble recent monthly official-source history.","result":"Recent LNU02032214 values are Mar 2026 = 12,214 thousand, Apr 2026 = 12,127 thousand, May 2026 = 12,120 thousand, Jun 2026 = 12,010 thousand, Jul 2026 = 12,223 thousand, and Aug 2026 = 12,011 thousand."},{"kind":"tool","tool":"official.lookup","call":"Fetched archived BLS Employment Situation releases to check same-month September reference values for the occupation line.","result":"Archived BLS releases show Transportation and material moving occupations employment at Sep 2022 = 11,866 thousand, Sep 2023 = 11,761 thousand, Sep 2024 = 12,217 thousand, and Sep 2025 = 11,910 thousand."},{"kind":"text","text":"For the base rate and reference class, I anchor on a persistence prior from the latest same-variant NSA CPS occupation level plus the recent six-print distribution. The six recent values average about 12.118 million, while the latest August 2026 level is 12.011 million. September 2025 was 0.263 million above August 2025, but this line has high sampling noise and the current August-to-July move was negative, so I only partially apply a September seasonal lift."},{"kind":"math","text":"Prior/update/interval: persistence prior = Aug 2026 value 12.011 million; historical sample = Mar-Aug 2026 official-source values 12.214, 12.127, 12.120, 12.010, 12.223, 12.011. Adjustment components: +0.054 million toward the recent six-print mean, +0.031 million for September seasonal risk from 2025 Sep-Aug behavior but damped for noise and weak latest momentum, for point 12.096 million. Successive changes are -0.087, -0.007, -0.110, +0.213, -0.212 million, so sigma = 0.160 million; 1.28*sigma = 0.205 million. Applying that half-width gives 12.096 +/- 0.205 = [11.891, 12.301]."},{"kind":"text","text":"Upside risk would be a normal September pickup in logistics, warehousing, and school-related transport categories plus household-survey rotation noise, which would land above the interval if the first print exceeds 12.301 million. Downside risk would be another large CPS occupation-allocation reversal or softer goods-movement employment, which would land below the interval if the first print is under 11.891 million."},{"kind":"forecast","point":12.096,"ciLow":11.891,"ciHigh":12.301}]}
