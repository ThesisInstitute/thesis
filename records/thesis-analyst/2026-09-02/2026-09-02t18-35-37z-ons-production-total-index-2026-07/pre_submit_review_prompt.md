# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: ons.production.total_index
- period: 2026-07
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "uk-production-output-index-july-2026"
- country: "UK"
- targetUnit: "index_points"
- dataPointId: "ons.production.total_index.2026_07.first_print"
- expectedReleaseWindow: {"end": "2026-09-11", "start": "2026-09-11"}
- resolutionSourceUrl: "https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/indexofproduction"
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.ons.gov.uk"], "expectedReleaseWindow": {"end": "2026-09-11", "start": "2026-09-11"}, "field": "Total Production : Sections B, C, D and E (Index):CVM", "releasePolicy": "first_print", "sourceSeriesId": "L2KQ", "sourceUrl": "https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/indexofproduction", "table": "Index of Production time series (DIOP)", "transform": {"factor": 1, "operation": "identity"}}
- targetRegistrationPath: "records/targets/2026-09-02-ac5b9a119c865fcf52c49a16a8e8598a8318cdd6bf67a9446158dbb5a666e37a.json"
- targetContentHash: "ac5b9a119c865fcf52c49a16a8e8598a8318cdd6bf67a9446158dbb5a666e37a"
- registrationCommit: "e915c43aeba83b903f1c01b7fd2df8ed8e2c8391"
- registeredAtUtc: "2026-09-02T18:31:06Z"
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
685c4d6f3e63de380936feb0d485972ee3834cab4e7acee0f60c4fefbb182f23

# Draft forecast response
{"slug":"uk-production-output-index-july-2026","country":"UK","type":"data","title":"UK production output index, July 2026","question":"What will the Office for National Statistics first print for IOP: B-E: PRODUCTION: CVMSA, seasonally adjusted total production output index, July 2026, be?","unit":"index_points","pointEstimate":98.1,"ciLow":97.0,"ciHigh":99.2,"confidence":0.8,"resolutionDate":"2026-09-11","resolutionSource":"Office for National Statistics Index of Production, UK: July 2026 and DIOP time series","resolutionSourceUrl":"https://www.ons.gov.uk/economy/economicoutputandproductivity/output/timeseries/k222/diop","resolutionRule":"Resolve to the first official ONS print for the seasonally adjusted Index of Production total production index for July 2026, IOP: B-E: PRODUCTION: CVMSA, rounded as first published in index points. Use the 11 September 2026 7:00am Index of Production, UK: July 2026 release or the associated DIOP time-series first publication; ignore later revisions or corrections unless the first-published value is withdrawn before any value is published.","dataPointId":"ons.production.total_index.2026_07.first_print","historicalContext":[{"period":{"type":"month","value":"2025-07"},"label":"July 2025","value":97.9},{"period":{"type":"month","value":"2025-08"},"label":"August 2025","value":97.8},{"period":{"type":"month","value":"2025-09"},"label":"September 2025","value":96.1},{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":97.7},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":99.1},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":98.6},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":98.4},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":98.8},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":98.7},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":99.1},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":98.5},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":98.3}],"drivers":["June level persistence near 98.3","recent monthly production softness","small mean-reversion offset","July seasonal-adjusted residual risk","manufacturing-heavy aggregate volatility"],"sourceContext":["https://www.ons.gov.uk/economy/economicoutputandproductivity/output/timeseries/k222/diop","https://www.ons.gov.uk/economy/economicoutputandproductivity/output/bulletins/indexofproduction/june2026","https://www.ons.gov.uk/releases/indexofproductionukjuly2026","https://www.ons.gov.uk/releasecalendar?page=2&release-type=type-upcoming","https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/indexofproduction"],"runAt":"2026-09-02T18:36:09Z","reasoning":[{"kind":"heading","text":"UK production output index, July 2026"},{"kind":"text","text":"Resolver framing: the registered target is ons.production.total_index.2026_07.first_print for the first official July 2026 ONS total production output index print. The ledger sourceBinding names L2KQ, but the ONS DIOP monthly total production index page for IOP: B-E: PRODUCTION: CVMSA is series K222; L2KQ is a quarterly GDP production index series. I keep the registered slug, unit, dataPointId, and date, and use the monthly K222 DIOP page as the exact source-series evidence."},{"kind":"tool","tool":"official.lookup","call":"Opened ONS release calendar and July 2026 release placeholder for Index of Production, UK: July 2026.","result":"ONS release calendar item 8 and the release placeholder both show Index of Production, UK: July 2026 scheduled for 11 September 2026 at 7:00am, confirmed/not yet published as of this run."},{"kind":"tool","tool":"official.lookup","call":"Opened ONS DIOP K222 time-series page for IOP: B-E: PRODUCTION: CVMSA.","result":"Fetched latest monthly levels from K222: 2026 JAN 98.4, 2026 FEB 98.8, 2026 MAR 98.7, 2026 APR 99.1, 2026 MAY 98.5, 2026 JUN 98.3; annual 2025 value 98.2 and quarterly 2026 Q2 value 98.6 are also shown on the same page."},{"kind":"tool","tool":"official.lookup","call":"Opened ONS Index of Production, UK: June 2026 bulletin for first-release context and component momentum.","result":"Fetched June bulletin statistics: monthly production output decreased 0.2% in June 2026 after May 2026 fell 0.7% and April 2026 rose 0.4%; Q2 2026 production had 0.0% growth; manufacturing rose 1.0% in Q2 while electricity and gas fell 2.3% and water supply and sewerage fell 3.7%."},{"kind":"tool","tool":"official.lookup","call":"Read K222 recent history for a reference class and July behavior.","result":"Fetched K222 levels around recent Julys: 2023 JUN 101.3 to JUL 100.7, 2024 JUN 98.5 to JUL 97.9, and 2025 JUN 98.5 to JUL 97.9; the last three July-minus-June changes were each -0.6 index points in the current official table."},{"kind":"text","text":"The base rate/reference class is a persistence model for a seasonally adjusted monthly level series: start from the latest official K222 level, 98.3 in June 2026, because production output levels move slowly around a mean but individual monthly changes are noisy."},{"kind":"math","text":"Prior/update/interval: persistence prior = 98.3 from K222 June 2026; historical sample = Jan 2024 through Jun 2026 K222 successive monthly changes with sample standard deviation sigma = 0.83 index points and mean change +0.01. Adjustments: recent momentum -0.15 because Apr-May-Jun moved 99.1 to 98.5 to 98.3 and the June bulletin reports -0.2% after -0.7%; July residual -0.10 because 2023-2025 July changes were all -0.6 but seasonal adjustment should already remove most calendar effects; mean reversion +0.05 because the latest level is slightly below the 2026 Q2 average 98.6. Point = 98.3 - 0.15 - 0.10 + 0.05 = 98.1. 80% half-width = 1.28*sigma = 1.28*0.83 = 1.06, rounded to 1.1, so interval = 98.1 +/- 1.1 = [97.0, 99.2]."},{"kind":"text","text":"Variant consistency: all level anchors are the same ONS DIOP seasonally adjusted CVMSA total production index variant, K222, not the annual/monthly growth-rate series and not the quarterly GDP L2KQ page."},{"kind":"text","text":"Counter-considerations: upside risk is a rebound in manufacturing or petroleum-related output after the June weakness, which would land above the interval if July prints above 99.2. Downside risk is another broad fall across manufacturing plus energy and water output, which would land below the interval if July prints below 97.0. A source-series correction or an unresolved L2KQ-vs-K222 registration dispute is outside the interval logic rather than economic signal."},{"kind":"forecast","point":98.1,"ciLow":97.0,"ciHigh":99.2}]}
