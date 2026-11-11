# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: bls.cps.employed_people_by_occupation.production
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-production-employment-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.production.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-10-14", "start": "2026-10-06"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-14", "start": "2026-10-06"}, "field": "Production occupations", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.employed_people_by_occupation.production", "sourceUrl": "https://www.bls.gov/web/empsit/cpseea19.htm", "table": "CPS Employment Situation Table A-19, employed persons by occupation, not seasonally adjusted (thousands)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-509aaff9e5589d155465f734902b0c02b366eb09226d957107fa7091bf786808.json"
- targetContentHash: "509aaff9e5589d155465f734902b0c02b366eb09226d957107fa7091bf786808"
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
8a68b049e45341beb17931bdf400eb4ca7b1021628af8f1daf3b8bb430090f83

# Draft forecast response
{"slug":"cps-production-employment-september-2026","country":"US","type":"data","title":"US CPS production occupations employment, September 2026","question":"What will BLS first report in CPS Employment Situation Table A-19 for September 2026 employed people age 16 and over in Production occupations, not seasonally adjusted, in millions?","unit":"millions","pointEstimate":7.556,"ciLow":7.264,"ciHigh":7.848,"confidence":0.8,"resolutionDate":"2026-10-02","resolutionSource":"U.S. Bureau of Labor Statistics Employment Situation, CPS Table A-19","resolutionSourceUrl":"https://www.bls.gov/web/empsit/cpseea19.htm","resolutionRule":"Resolve to the first official BLS value published for September 2026 in CPS Employment Situation Table A-19, row 'Production occupations,' Total, 16 years and over, not seasonally adjusted, reported in thousands. Multiply the published thousands value by 0.001 and report millions rounded to three decimals. Use the first official print only, with no later revisions or later correction exceptions. The official BLS Employment Situation calendar fetched this run lists September 2026 for October 2, 2026 at 08:30 AM ET; this conflicts with the registered target window ending 2026-10-14, but the slug and dataPointId remain tied to the registered target.","dataPointId":"bls.cps.employed_people_by_occupation.production.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":7.786},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":7.742},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":7.685},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":7.883},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":7.912},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":7.759},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":8.121},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":7.716}],"drivers":["August 2026 A-19 level","Recent CPS occupation volatility","Typical August-to-September NSA softening","No discrete policy mechanism"],"sourceContext":["https://www.bls.gov/web/empsit/cpseea19.htm","https://www.bls.gov/schedule/news_release/empsit.htm","https://fred.stlouisfed.org/series/LNU02032213","https://fred.stlouisfed.org/data/LNU02032213","https://alfred.stlouisfed.org/series?seid=LNU02032213"],"runAt":"2026-09-11T19:37:22Z","reasoning":[{"kind":"heading","text":"September 2026 CPS production occupations employment forecast"},{"kind":"text","text":"Framing and exact resolver: this is the CPS household-survey Production occupations row, not seasonally adjusted, Total age 16 years and over, reported by BLS in thousands in Employment Situation Table A-19 and converted to millions by multiplying by 0.001. The matching BLS/FRED source code for the same Production occupations employment level is LNU02032213; FRED/ALFRED are used only as public history mirrors, while resolution uses the BLS A-19 page."},{"kind":"tool","tool":"official.lookup","call":"Fetch current BLS CPS Employment Situation Table A-19 row for Production occupations from https://www.bls.gov/web/empsit/cpseea19.htm.","result":"BLS Table A-19 reports Production occupations at 7,716 thousand for August 2026 and 7,482 thousand for August 2025, equal to 7.716 million and 7.482 million after the 0.001 transform."},{"kind":"tool","tool":"history.lookup","call":"Fetch recent BLS-source LNU02032213 history from FRED/ALFRED history pages and current series page.","result":"The BLS-source LNU02032213 history gives January 2026 7,786 thousand, February 2026 7,742 thousand, March 2026 7,685 thousand, April 2026 7,883 thousand, May 2026 7,912 thousand, June 2026 7,759 thousand, July 2026 8,121 thousand, and August 2026 7,716 thousand."},{"kind":"tool","tool":"official.lookup","call":"Verify the Employment Situation release date from the BLS schedule page for September 2026.","result":"The BLS schedule lists Reference Month September 2026 with Release Date Oct. 02, 2026 and Release Time 08:30 AM; the registered sourceBinding window says 2026-10-06 to 2026-10-14, so the official calendar is earlier by 4 to 12 days."},{"kind":"text","text":"Base rate / reference class: the strongest simple prior is latest-level persistence from the same CPS production occupations series, anchored on August 2026 at 7.716 million. The recent reference class is January-August 2026 exact-series values of 7.786, 7.742, 7.685, 7.883, 7.912, 7.759, 8.121, and 7.716 million, with the year staying mostly in a 7.7-8.1 million band but noisy month-to-month movement."},{"kind":"text","text":"Level, momentum, one-off, and policy effects: level starts at the August 2026 first print of 7.716 million. Momentum is mixed because July's spike to 8.121 was followed by August's fall to 7.716. One-off CPS sampling noise is large for this occupation subgroup, so I do not extrapolate the full July-to-August drop. Policy mechanism is neutral; no discrete public policy event changes the September CPS occupation count."},{"kind":"math","text":"Prior/update/interval: persistence prior = 7.716 million from August 2026; historical sample = January-August 2026 values 7.786, 7.742, 7.685, 7.883, 7.912, 7.759, 8.121, and 7.716 million; adjustment components = -0.160 million for typical August-to-September NSA softening, +0.000 one-off, +0.000 policy, yielding point = 7.716 - 0.160 = 7.556 million. Interval method = RMS successive changes from the fetched 2026 history: changes are -0.044, -0.057, +0.198, +0.029, -0.153, +0.362, and -0.405 million, so sigma = sqrt((0.044^2 + 0.057^2 + 0.198^2 + 0.029^2 + 0.153^2 + 0.362^2 + 0.405^2)/7) = 0.228 million. The 80% half-width is roughly 1.28*sigma = 1.28*0.228 = 0.292 million; 7.556 - 0.292 = 7.264 and 7.556 + 0.292 = 7.848."},{"kind":"text","text":"Upside risk is a rebound in the September CPS sample, stronger goods-sector labor demand, or occupational reclassification back into production work, which would land above the interval at more than 7.848 million. Downside risk is another adverse CPS sample, deeper manufacturing weakness, or a larger seasonal September decline, which would land below 7.264 million and outside the interval."},{"kind":"forecast","point":7.556,"ciLow":7.264,"ciHigh":7.848}]}
