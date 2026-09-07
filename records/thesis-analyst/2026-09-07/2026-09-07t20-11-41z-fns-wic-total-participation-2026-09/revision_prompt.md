# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: fns.wic.total_participation
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "wic-participation-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "fns.wic.total_participation.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-12-30", "start": "2026-12-22"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.fns.usda.gov"], "expectedReleaseWindow": {"end": "2026-12-30", "start": "2026-12-22"}, "field": "fns.wic.total_participation", "releasePolicy": "first_print", "sourceSeriesId": "fns.wic.total_participation", "sourceUrl": "https://www.fns.usda.gov/pd/wic-program", "table": "USDA Food and Nutrition Service WIC Data Tables", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-07-6fab8f5c1804406df2cf90f0e713350509f672a7c5a08d03939b11cdc2ffb88c.json"
- targetContentHash: "6fab8f5c1804406df2cf90f0e713350509f672a7c5a08d03939b11cdc2ffb88c"
- registrationCommit: "f1baea413714fe099f71118840f6363977fcdb5c"
- registeredAtUtc: "2026-09-07T20:04:45Z"

# Source hints
- Use USDA FNS program-data pages, official data tables, and the FNS data release calendar.
- For SNAP, WIC, and QC targets, distinguish annual fiscal-year quality-control releases from monthly participation tables.
- If the catalog unit is millions, convert official person counts to millions in the emitted cell.

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
{"slug":"wic-participation-september-2026","country":"US","type":"data","title":"US WIC participation, September 2026","question":"USDA FNS WIC Program national total participation for September 2026, not seasonally adjusted, first official monthly print, converted to millions of participants.","unit":"millions","pointEstimate":6.84,"ciLow":6.658,"ciHigh":7.022,"confidence":0.8,"resolutionDate":"2026-12-30","resolutionSource":"USDA Food and Nutrition Service WIC Data Tables","resolutionSourceUrl":"https://www.fns.usda.gov/pd/wic-program","resolutionRule":"Resolve to the first USDA FNS WIC Data Tables monthly national print that includes September 2026, using the national Total Participants value for September 2026 in the WIC monthly participation table. If the official table reports participants in thousands, multiply by 0.001 to convert to millions; if it reports whole participants, divide by 1,000,000. Round the resolved millions value to three decimals and ignore later revisions, corrections, annual-summary updates, FRED, and mirrors.","dataPointId":"fns.wic.total_participation.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":6.909938},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":6.771734},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":6.712611},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":6.6963},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":6.66458},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":6.701661},{"period":{"type":"month","value":"2024-09"},"label":"September 2024","value":6.83825},{"period":{"type":"month","value":"2025-05"},"label":"May 2025","value":6.89461}],"drivers":["FY2026 participation was below the FY2025 level after a sharp October-to-February decline","March 2026 showed a partial rebound from February","September is usually at or above spring participation in the same WIC monthly total series","No direct pre-September 2026 policy mechanism was identified that would force a large discontinuity","First-print reporting and state submission timing add material uncertainty"],"sourceContext":["https://www.fns.usda.gov/pd/wic-program","https://www.fna.usda.gov/pd/wic-program","https://fns-prod.azureedge.us/sites/default/files/resource-files/37wic-monthly-6.pdf","https://fns-prod.azureedge.us/sites/default/files/resource-files/37wic-monthly-7.pdf","https://fns-prod.azureedge.us/sites/default/files/resource-files/27wilatest-7.pdf","https://www.fns.usda.gov/data-research/data-release-calendar"],"runAt":"2026-09-07T20:11:45Z","reasoning":[{"kind":"heading","text":"Forecast for September 2026 WIC total participation"},{"kind":"text","text":"Framing and exact resolver: this target is USDA FNS WIC national Total Participants for September 2026, not seasonally adjusted, in the monthly WIC Data Tables first print. The registered dataPointId is fns.wic.total_participation.2026-09.first_print, the unit is millions, and later revisions are excluded."},{"kind":"tool","tool":"official.lookup","call":"Opened the USDA FNS/FNA WIC Data Tables source surface for the official series identity and latest public monthly-table availability.","result":"The WIC page listed Monthly Data - National Level as FY 2022 through April 2026, Page updated July 15, 2026; the same page identifies WIC monthly national data tables and latest-month resources for Total Participants."},{"kind":"tool","tool":"official.lookup","call":"Inspected the official FNS WIC monthly national table values captured in public Thesis official-fetch artifacts for the latest FY2026 pre-target run of the same Total Participants variant.","result":"Fetched FY2026 Total Participants values from the official FNS monthly table: Oct 2025 6,909,938; Nov 2025 6,771,734; Dec 2025 6,712,611; Jan 2026 6,696,300; Feb 2026 6,664,580; Mar 2026 6,701,661."},{"kind":"tool","tool":"official.lookup","call":"Inspected same-series historical monthly anchors from official FNS WIC monthly tables for seasonality and level context.","result":"Fetched Total Participants values: Mar 2024 6,680,974; Jun 2024 6,736,885; Sep 2024 6,838,250; Mar 2025 6,850,836; May 2025 6,894,610; Jun 2025 6,883,200."},{"kind":"tool","tool":"official.lookup","call":"Checked the FNS data-release calendar and registered WIC source window for the first-print release-date basis.","result":"The FNS data-release calendar basis for September 2026 WIC monthly data falls in the registered 2026-12-22 to 2026-12-30 window, with the target bound to 2026-12-30; recent adjacent WIC target windows include August 2026 ending 2026-11-26 and July 2026 ending 2026-10-22."},{"kind":"text","text":"Base rate/reference class: for a monthly level series, the base rate is same-series persistence plus normal seasonal recovery from spring to late fiscal year. The latest exact FY2026 level I can use is March 2026 at 6.701661 million, after a fall from 6.909938 million in October 2025 and a partial rebound from 6.664580 million in February 2026."},{"kind":"text","text":"Level, momentum, one-off, and mechanism split: the level is materially below the FY2025 neighborhood near 6.9 million, momentum improved in March after winter attrition, the October-to-February drop may include state reporting or recertification timing as a one-off component, and the policy mechanism does not point to a mechanical September 2026 break before the FY2027 budget year."},{"kind":"math","text":"Prior/update/interval: model is seasonal persistence from the latest fetched official level. Historical sample uses same-series FY2026 successive changes and 2024 spring-to-September seasonality. Adjustment components: March 2026 level 6.701661 + Mar-to-Sep 2024 seasonal move (6.838250 - 6.680974 = 0.157276) = 6.858937; subtract 0.018937 million for the lower FY2026 level and birth/caseload normalization, giving point 6.840. Interval method uses realized successive monthly changes from fetched WIC history: +0.007963, +0.069415, -0.078428, -0.044612, +0.036426, -0.020183, +0.047568, +0.008453, +0.053049, -0.138204, -0.059123, -0.016311, -0.031720, +0.037081 million; monthly stdev is 0.058156, so six-month horizon sigma = 0.058156*sqrt(6) = 0.142274 million. The 80% half-width is 1.28*sigma = 1.28*0.142274 = 0.182111 million, so final implied bounds are 6.840 - 0.182 = 6.658 and 6.840 + 0.182 = 7.022 million."},{"kind":"text","text":"Counter-consideration: upside risk is a stronger summer enrollment rebound, state catch-up reporting, or renewed take-up growth that would land above the interval if the September first print exceeds 7.022 million. Downside risk is persistent FY2026 attrition, funding or administrative disruption, or weaker infant and child caseloads that would land below the interval if the first print is under 6.658 million. Outside the interval would require a larger move than the scaled recent same-series dispersion."},{"kind":"forecast","point":6.84,"ciLow":6.658,"ciHigh":7.022}]}

# Reviewer critique
{"summary":"The draft is mostly publication-ready, with one resolver wording issue that should be tightened to match the registered sourceBinding transform exactly.","requiredFixes":[{"rubricItem":"resolver","severity":"warning","summary":"The resolution rule adds a fallback for whole-participant reporting, while the canonical target binding specifies a fixed transform of multiplying the official extracted value by 0.001.","actionRequested":"Revise the resolver wording to follow the registered transform exactly, or explicitly state in reasoning that the ledger transform appears to encode the official table unit and the forecast remains tied to that registered target."}],"optionalSuggestions":["Remove or correct the apparent typo source URL `https://www.fna.usda.gov/pd/wic-program` in `sourceContext` so all cited source surfaces are official FNS/USDA URLs.","The prior/update/interval step is strong; consider making the release-date basis phrase explicit as `resolve-by-bound to 2026-12-30 within the registered 2026-12-22 to 2026-12-30 window`."]}

Emit the final JSON object only.
