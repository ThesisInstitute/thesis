# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: ssa.ssi.total_recipients
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "ssi-recipients-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "ssa.ssi.total_recipients.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-11-08", "start": "2026-10-31"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.ssa.gov"], "expectedReleaseWindow": {"end": "2026-11-08", "start": "2026-10-31"}, "field": "ssa.ssi.total_recipients", "releasePolicy": "first_print", "sourceSeriesId": "ssa.ssi.total_recipients", "sourceUrl": "https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2026-07/table02.html", "table": "Social Security Administration SSI Monthly Statistics", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-07-9509b1552284e3dcd59b3e1c6a6752efb3be2cf74e57824022343f3a837dde2f.json"
- targetContentHash: "9509b1552284e3dcd59b3e1c6a6752efb3be2cf74e57824022343f3a837dde2f"
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
4c82966320e1ef84ba85cad9daf0f5147f19c0495bf2fe7cc7a89bd1abb74b6b

# Draft forecast response
{"slug":"ssi-recipients-september-2026","country":"US","type":"data","title":"SSI recipients, September 2026","question":"Social Security Administration SSI Monthly Statistics Table 2, total number of recipients for all federally administered payments, September 2026, first print, converted to millions.","unit":"millions","pointEstimate":7.326,"ciLow":7.292,"ciHigh":7.36,"confidence":0.8,"resolutionDate":"2026-11-08","resolutionSource":"Social Security Administration SSI Monthly Statistics","resolutionSourceUrl":"https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2026-09/table02.html","resolutionRule":"Resolve to the first published September 2026 value in SSA SSI Monthly Statistics Table 2, row September 2026, column Total number of recipients for all federally administered payments. Use the whole-recipient first print from the Supplemental Security Record, 100 percent data, convert to millions by dividing by 1,000,000, and report to three decimals. Ignore later revisions or adjusted checks after the first September 2026 table is posted. The registered expected release window ends 2026-11-08; SSA's Publishing Schedule was checked this run and lists SSI Monthly Statistics as a monthly publication but did not expose a more specific September 2026 release day in the fetched text.","dataPointId":"ssa.ssi.total_recipients.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2025-07"},"label":"2025-07","value":7.394877},{"period":{"type":"month","value":"2025-08"},"label":"2025-08","value":7.405735},{"period":{"type":"month","value":"2025-09"},"label":"2025-09","value":7.436689},{"period":{"type":"month","value":"2025-10"},"label":"2025-10","value":7.393406},{"period":{"type":"month","value":"2025-11"},"label":"2025-11","value":7.391176},{"period":{"type":"month","value":"2025-12"},"label":"2025-12","value":7.392201},{"period":{"type":"month","value":"2026-01"},"label":"2026-01","value":7.36951},{"period":{"type":"month","value":"2026-02"},"label":"2026-02","value":7.358913},{"period":{"type":"month","value":"2026-03"},"label":"2026-03","value":7.351825},{"period":{"type":"month","value":"2026-04"},"label":"2026-04","value":7.338132},{"period":{"type":"month","value":"2026-05"},"label":"2026-05","value":7.322937},{"period":{"type":"month","value":"2026-06"},"label":"2026-06","value":7.323731},{"period":{"type":"month","value":"2026-07"},"label":"2026-07","value":7.300297}],"drivers":["July 2026 level fell to 7.300297 million","Recent monthly momentum is negative but not one-way","September has shown mixed but recently positive seasonal movement","No known 2026 SSI policy cliff large enough to dominate recipient counts","First-print whole-recipient SSA Table 2 value converted to millions"],"sourceContext":["https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2026-07/table02.html","https://www.ssa.gov/policy/pub_schedule.html","https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2025-09/table02.html","https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2024-09/table02.html","https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2023-09/table02.html","https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2022-09/table02.html"],"runAt":"2026-09-07T20:16:46Z","reasoning":[{"kind":"heading","text":"SSI total recipients September 2026"},{"kind":"text","text":"Exact resolver: SSA SSI Monthly Statistics Table 2, All Federally Administered Payments, Total number of recipients, September 2026 first print. The variant is unadjusted end-of-month recipients from the Supplemental Security Record, 100 percent data; all anchors below use the same Table 2 Total recipient variant."},{"kind":"tool","tool":"official.lookup","call":"Fetched SSA SSI Monthly Statistics, July 2026, Table 2 at the official ssa.gov table URL.","result":"Latest official Table 2 Total recipient prints fetched: 2026-02 7,358,913; 2026-03 7,351,825; 2026-04 7,338,132; 2026-05 7,322,937; 2026-06 7,323,731; 2026-07 7,300,297."},{"kind":"tool","tool":"official.lookup","call":"Fetched older official SSA September Table 2 pages for same-month and July-to-September reference class history.","result":"Official September Table 2 totals fetched: 2022-09 7,567,439; 2023-09 7,450,135; 2024-09 7,430,106; 2025-09 7,436,689. July-to-September changes were -22,869 in 2022, -24,600 in 2023, +20,432 in 2024, and +41,812 in 2025 recipients."},{"kind":"tool","tool":"official.lookup","call":"Checked SSA Publishing Schedule and the July 2026 SSI Monthly Statistics index for release-basis context.","result":"SSA Publishing Schedule fetched SSI Monthly Statistics as Monthly; the July 2026 SSI Monthly Statistics index says released August 2026, and its Table 2 July total is 7,300,297. The fetched schedule text did not expose a specific September 2026 release day, so I use the registered expectedReleaseWindow end 2026-11-08 as the resolutionDate bound."},{"kind":"text","text":"Base rate/reference class: the recent 13-print official Table 2 sample runs from 7.394877 million in 2025-07 to 7.300297 million in 2026-07, with average one-month change -0.007882 million. The four July-to-September same-variant moves average +0.003694 million but split between negative 2022-2023 and positive 2024-2025, so I avoid a strong seasonal lift."},{"kind":"math","text":"Prior/update/interval: Persistence prior starts from the latest same-variant SSA level, 7.300297 million in 2026-07. Historical sample is the 12 successive monthly changes in the 2025-07 through 2026-07 official Table 2 totals: mean change -0.007882 million and monthly sigma = 0.018722 million. Adjustment components: level +7.300297; momentum for two months -0.010 million, lighter than the raw recent average because September seasonality can reverse declines; seasonal/policy-mechanism add +0.036 million based on the 2024-2025 September lift and no major known eligibility-policy discontinuity. Point = 7.300297 - 0.010 + 0.036 = 7.326 million. For the two-month horizon, scaled sigma = 0.018722*sqrt(2) = 0.026477, so 1.28*sigma = 0.033891; rounded 80% bounds are 7.326 +/- 0.034 = 7.292 to 7.360 million."},{"kind":"text","text":"Counter-considerations: upside risk is another September processing jump like 2025, which would land above the interval if August and September together add more than about 60,000 recipients from July. Downside risk is continued administrative attrition like early 2026 plus weak new awards, which would land below the interval if the July level loses more than about 8,000 recipients by September. Outside the interval would require either a clear seasonal surge beyond the recent sample or another July-like monthly drop."},{"kind":"forecast","point":7.326,"ciLow":7.292,"ciHigh":7.36}]}
