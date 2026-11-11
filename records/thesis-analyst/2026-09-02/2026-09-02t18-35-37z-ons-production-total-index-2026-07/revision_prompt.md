# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: ons.production.total_index
- period: 2026-07
- conditionalOn: null

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

# Source hints
- Use ONS time-series pages, ONS API, and ONS release calendar.
- UK CPI/CPIH prints to one decimal; labour-market rates print to one decimal.
- Resolution source should be the relevant ONS release or time-series page.

# Default promoted forecasting practices
- Resolve the exact first-print target before inside-view evidence.
- Fetch and state the recent official-source reference class: at least 6 distinct prints are MANDATORY whenever the official source exposes them.
- Anchor on the outside-view base rate before current-release adjustments.
- Separate level, momentum, one-off, and policy-mechanism effects before combining them.
- Include one public reasoning step beginning "Prior/update/interval:" that names the model or persistence prior, historical sample, adjustment components, interval method, and final implied bounds.
- For strict first-print or original-vintage targets, keep the ledger resolver in substance and do not add same-day correction or release-day grace exceptions unless the target rule includes them.
- Size the 80% interval from realized dispersion and SHOW the arithmetic in the Prior/update/interval step: compute sigma from the fetched history (successive changes for level/rate series; the values themselves for change/flow series), state it literally as "sigma = X", and derive the half-width as roughly 1.28*sigma. If you widen or narrow beyond about 0.75x-1.75x of that half-width, state the regime or mechanism reason in the same step. Never default to a round hedged band.
- When a release has variants (gross vs smoothed/synthetic, SA vs NSA, flash vs final), the resolution rule must name the variant and every anchor and historical value must come from that same variant; say so once in a text step.
- resolutionSourceUrl must be the most specific stable page for the exact series (release page, table, or databrowser query with the series code), never a portal or theme landing page; state the series code or table id in a text step when one exists.
- Name concrete upside, downside, and outside-the-interval scenarios, using the literal phrases "upside risk", "downside risk", and "outside the interval" (or "would land above/below the interval") so the falsification step is machine-checkable.

# Required JSON shape
{
  "slug": "kebab-case-unique-vs-catalog",
  "country": "US|UK|CA|AU|EA|JP",
  "type": "data",
  "title": "Short display title",
  "question": "Exact agency series, period, adjustment, first print",
  "unit": "the registered targetUnit, byte-for-byte",
  "pointEstimate": 0,
  "ciLow": 0,
  "ciHigh": 0,
  "confidence": 0.8,
  "resolutionDate": "YYYY-MM-DD",
  "resolutionSource": "Official agency release",
  "resolutionSourceUrl": "https://official-source.example",
  "resolutionRule": "First-print rule with rounding and revision policy",
  "dataPointId": "agency.dataset.concept.period.first_print",
  "historicalContext": [
    {
      "period": {
        "type": "month",
        "value": "2026-04"
      },
      "label": "Human-readable period label",
      "value": 0
    }
  ],
  "drivers": [
    "short driver phrases"
  ],
  "sourceContext": [
    "https://urls-actually-used"
  ],
  "runAt": "date -u +%Y-%m-%dT%H:%M:%SZ",
  "reasoning": [
    {
      "kind": "heading",
      "text": "Forecast title"
    },
    {
      "kind": "text",
      "text": "Framing and exact resolver"
    },
    {
      "kind": "tool",
      "tool": "official.lookup",
      "call": "source lookup description",
      "result": "fetched numbers"
    },
    {
      "kind": "math",
      "text": "point and 80% interval calculation"
    },
    {
      "kind": "forecast",
      "point": 0,
      "ciLow": 0,
      "ciHigh": 0
    }
  ]
}

# Validation rules
- Use confidence 0.8 exactly.
- ciLow < pointEstimate < ciHigh, except discrete policy-rate targets may put the modal point at an interval edge if needed.
- historicalContext must contain at least 6 distinct numeric fetched prints. Every entry needs a canonical period object: type month with YYYY-MM, quarter with YYYY-Q1..Q4, year/fiscal_year with YYYY, or week_ending with YYYY-MM-DD. Its label must unambiguously name that same period. The whole trimmed label must be one closed printable-ASCII form: YYYY-MM, Month YYYY, YYYY Month, YYYY-QN, YYYY QN, QN YYYY, YYYY, calendar year YYYY, FY2026, fiscal year YYYY, YYYY-MM-DD, or week ending YYYY-MM-DD. Never add source names, first-print or revision prose, ranges, or a second period cue to the label. Relative, contradictory, non-ASCII, and multi-period labels refuse. Alternate labels do not make duplicate canonical periods distinct. Validation refuses fewer unless the sealed checkout carries the reviewed authorization below.
- Only when the official source exposes fewer than 6 prints, fetch all available prints and add this top-level audit commentary (replace 5 with the actual count and give a nonempty detail): {"historyAvailability": {"status": "official_source_exposes_fewer_than_six_prints", "availablePrintCount": 5, "detail": "Series began recently; the official source exposes only these five prints."}}
  This model-authored commentary never authorizes an exception: a reviewed docket entry in the sealed checkout must independently list the exact target period, available count, and canonical periods.
- sourceContext must contain at least 2 source URLs actually used.
- sourceContext, reasoning, drivers, and tool calls must not cite or use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or non-public local files.
- reasoning must contain at least 7 steps, at least 3 tool steps whose result strings include fetched numbers, one explicit base-rate or reference-class step (literally say "base rate" or "reference class"), one math step, one counter-consideration that states what would land outside the 80% interval (literally use "upside risk", "downside risk", or "outside the interval"), one step beginning Prior/update/interval:, and a final forecast step whose numbers exactly match the cell.
- Every tool step result must include at least one fetched numeric value — an actual statistic from the source, not just field names or identifiers. Definitional lookups (data dictionaries, field definitions, methodology pages) belong in text steps, as do other qualitative source notes. Numbers may come from official public sources or inspected local run/model artifacts, but the provenance must be clear.
- resolutionDate must be verified from an official release calendar or announcement schedule this run. Do not infer it from cadence.
- Do not use existing local catalog point estimates or intervals as forecast evidence. If inspected, treat them only as non-authoritative prior strategy context and keep them out of tool-result evidence.
- runAt must be the actual UTC date command output from this run.
- Slug should be stable and descriptive; if the same target already exists, reuse the obvious canonical slug rather than inventing a near-duplicate.

Emit the final JSON object only. (agent thesis.analyst v2.5.11, prompt 87db344b803f, tools 024388e49298, promptMode fast)


# Pre-submit review loop

You already drafted the response below. A reviewer then checked the draft against the Thesis rubric. Produce the final JSON forecast now.

Rules for the final submission:
- Return exactly one JSON object and no Markdown.
- Use only pre-resolution public evidence available to the draft.
- Accept reviewer fixes only when they improve resolver clarity, source grounding, base-rate discipline, uncertainty calibration, or internal coherence.
- Add a public reasoning text step beginning with "Review disposition:" that states which critique items were accepted or rejected. Keep this concise; do not reveal hidden chain-of-thought.
- Put the Review disposition text step before the final forecast step.
- The final reasoning step must be the forecast step, and its numbers must exactly match pointEstimate, ciLow, and ciHigh.

# Draft forecast response
{"slug":"uk-production-output-index-july-2026","country":"UK","type":"data","title":"UK production output index, July 2026","question":"What will the Office for National Statistics first print for IOP: B-E: PRODUCTION: CVMSA, seasonally adjusted total production output index, July 2026, be?","unit":"index_points","pointEstimate":98.1,"ciLow":97.0,"ciHigh":99.2,"confidence":0.8,"resolutionDate":"2026-09-11","resolutionSource":"Office for National Statistics Index of Production, UK: July 2026 and DIOP time series","resolutionSourceUrl":"https://www.ons.gov.uk/economy/economicoutputandproductivity/output/timeseries/k222/diop","resolutionRule":"Resolve to the first official ONS print for the seasonally adjusted Index of Production total production index for July 2026, IOP: B-E: PRODUCTION: CVMSA, rounded as first published in index points. Use the 11 September 2026 7:00am Index of Production, UK: July 2026 release or the associated DIOP time-series first publication; ignore later revisions or corrections unless the first-published value is withdrawn before any value is published.","dataPointId":"ons.production.total_index.2026_07.first_print","historicalContext":[{"period":{"type":"month","value":"2025-07"},"label":"July 2025","value":97.9},{"period":{"type":"month","value":"2025-08"},"label":"August 2025","value":97.8},{"period":{"type":"month","value":"2025-09"},"label":"September 2025","value":96.1},{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":97.7},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":99.1},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":98.6},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":98.4},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":98.8},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":98.7},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":99.1},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":98.5},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":98.3}],"drivers":["June level persistence near 98.3","recent monthly production softness","small mean-reversion offset","July seasonal-adjusted residual risk","manufacturing-heavy aggregate volatility"],"sourceContext":["https://www.ons.gov.uk/economy/economicoutputandproductivity/output/timeseries/k222/diop","https://www.ons.gov.uk/economy/economicoutputandproductivity/output/bulletins/indexofproduction/june2026","https://www.ons.gov.uk/releases/indexofproductionukjuly2026","https://www.ons.gov.uk/releasecalendar?page=2&release-type=type-upcoming","https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/indexofproduction"],"runAt":"2026-09-02T18:36:09Z","reasoning":[{"kind":"heading","text":"UK production output index, July 2026"},{"kind":"text","text":"Resolver framing: the registered target is ons.production.total_index.2026_07.first_print for the first official July 2026 ONS total production output index print. The ledger sourceBinding names L2KQ, but the ONS DIOP monthly total production index page for IOP: B-E: PRODUCTION: CVMSA is series K222; L2KQ is a quarterly GDP production index series. I keep the registered slug, unit, dataPointId, and date, and use the monthly K222 DIOP page as the exact source-series evidence."},{"kind":"tool","tool":"official.lookup","call":"Opened ONS release calendar and July 2026 release placeholder for Index of Production, UK: July 2026.","result":"ONS release calendar item 8 and the release placeholder both show Index of Production, UK: July 2026 scheduled for 11 September 2026 at 7:00am, confirmed/not yet published as of this run."},{"kind":"tool","tool":"official.lookup","call":"Opened ONS DIOP K222 time-series page for IOP: B-E: PRODUCTION: CVMSA.","result":"Fetched latest monthly levels from K222: 2026 JAN 98.4, 2026 FEB 98.8, 2026 MAR 98.7, 2026 APR 99.1, 2026 MAY 98.5, 2026 JUN 98.3; annual 2025 value 98.2 and quarterly 2026 Q2 value 98.6 are also shown on the same page."},{"kind":"tool","tool":"official.lookup","call":"Opened ONS Index of Production, UK: June 2026 bulletin for first-release context and component momentum.","result":"Fetched June bulletin statistics: monthly production output decreased 0.2% in June 2026 after May 2026 fell 0.7% and April 2026 rose 0.4%; Q2 2026 production had 0.0% growth; manufacturing rose 1.0% in Q2 while electricity and gas fell 2.3% and water supply and sewerage fell 3.7%."},{"kind":"tool","tool":"official.lookup","call":"Read K222 recent history for a reference class and July behavior.","result":"Fetched K222 levels around recent Julys: 2023 JUN 101.3 to JUL 100.7, 2024 JUN 98.5 to JUL 97.9, and 2025 JUN 98.5 to JUL 97.9; the last three July-minus-June changes were each -0.6 index points in the current official table."},{"kind":"text","text":"The base rate/reference class is a persistence model for a seasonally adjusted monthly level series: start from the latest official K222 level, 98.3 in June 2026, because production output levels move slowly around a mean but individual monthly changes are noisy."},{"kind":"math","text":"Prior/update/interval: persistence prior = 98.3 from K222 June 2026; historical sample = Jan 2024 through Jun 2026 K222 successive monthly changes with sample standard deviation sigma = 0.83 index points and mean change +0.01. Adjustments: recent momentum -0.15 because Apr-May-Jun moved 99.1 to 98.5 to 98.3 and the June bulletin reports -0.2% after -0.7%; July residual -0.10 because 2023-2025 July changes were all -0.6 but seasonal adjustment should already remove most calendar effects; mean reversion +0.05 because the latest level is slightly below the 2026 Q2 average 98.6. Point = 98.3 - 0.15 - 0.10 + 0.05 = 98.1. 80% half-width = 1.28*sigma = 1.28*0.83 = 1.06, rounded to 1.1, so interval = 98.1 +/- 1.1 = [97.0, 99.2]."},{"kind":"text","text":"Variant consistency: all level anchors are the same ONS DIOP seasonally adjusted CVMSA total production index variant, K222, not the annual/monthly growth-rate series and not the quarterly GDP L2KQ page."},{"kind":"text","text":"Counter-considerations: upside risk is a rebound in manufacturing or petroleum-related output after the June weakness, which would land above the interval if July prints above 99.2. Downside risk is another broad fall across manufacturing plus energy and water output, which would land below the interval if July prints below 97.0. A source-series correction or an unresolved L2KQ-vs-K222 registration dispute is outside the interval logic rather than economic signal."},{"kind":"forecast","point":98.1,"ciLow":97.0,"ciHigh":99.2}]}

# Reviewer critique
{"summary":"Draft is mostly publication-ready, but its JSON resolver URL conflicts with the canonical ledger target contract.","requiredFixes":[{"rubricItem":"resolver","severity":"blocking","summary":"The draft sets resolutionSourceUrl to the K222 time-series page, while the ledger contract requires https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/indexofproduction.","actionRequested":"Set resolutionSourceUrl to the ledger resolutionSourceUrl exactly; keep the K222/L2KQ discrepancy explanation in reasoning or sourceContext rather than changing the target resolver field."}],"optionalSuggestions":["Make the resolver text explicitly name the ledger dataset/table field alongside the K222 evidence page to reduce ambiguity.","Keep the L2KQ-vs-K222 discrepancy visible, but avoid implying the cell has changed the registered target."]}

Emit the final JSON object only.
