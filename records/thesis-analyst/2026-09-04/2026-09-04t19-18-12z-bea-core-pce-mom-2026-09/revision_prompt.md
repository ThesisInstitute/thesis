# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bea.core_pce.mom
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-core-pce-mom-september-2026"
- country: "US"
- targetUnit: "percent_growth"
- dataPointId: "us.bea.core_pce.mom_sa.2026-09"
- expectedReleaseWindow: {"end": "2026-11-03", "start": "2026-10-26"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bea.gov"], "expectedReleaseWindow": {"end": "2026-11-03", "start": "2026-10-26"}, "field": "bea.core_pce.mom", "releasePolicy": "first_print", "sourceSeriesId": "bea.core_pce.mom", "sourceUrl": "https://www.bea.gov/data/personal-consumption-expenditures-price-index-excluding-food-and-energy", "table": "U.S. Bureau of Economic Analysis, Personal Income and Outlays, August 2026", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-3bd901a59b3f149888eacc83e718008b02d127934c70cbb885ff940917443558.json"
- targetContentHash: "3bd901a59b3f149888eacc83e718008b02d127934c70cbb885ff940917443558"
- registrationCommit: "baad7107ac843adbbb7a8038e4138d5e24100521"
- registeredAtUtc: "2026-09-04T19:02:52Z"

# Source hints
- Use the official agency release calendar, not inferred cadence.
- FRED may be used as a history mirror, but resolution cites the agency.
- For FOMC targets, resolve to the target range upper bound after the announcement.
- For DOL claims, name the week-ending date and cite the release date.

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
{"slug":"us-core-pce-mom-september-2026","country":"US","type":"data","title":"US core PCE MoM September 2026","question":"What will the U.S. Bureau of Economic Analysis report as the first-print seasonally adjusted monthly percent change in the PCE price index excluding food and energy for September 2026?","unit":"percent_growth","pointEstimate":0.24,"ciLow":0.1,"ciHigh":0.38,"confidence":0.8,"resolutionDate":"2026-10-29","resolutionSource":"U.S. Bureau of Economic Analysis, Personal Income and Outlays, September 2026","resolutionSourceUrl":"https://www.bea.gov/news/2026/personal-income-and-outlays-september-2026","resolutionRule":"Resolve to the first BEA Personal Income and Outlays September 2026 release value for the seasonally adjusted PCE price index excluding food and energy, percent change from the preceding month, as shown in the release text or Table 2.8.7. Use the first public print only; do not use later revisions, annual updates after first publication, or same-day correction exceptions unless BEA explicitly replaces the release before public posting. Record in percent_growth, using BEA's reported rounding.","dataPointId":"us.bea.core_pce.mom_sa.2026-09","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":0.4},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":0.4},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":0.3},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":0.2},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":0.3},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":0.1},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":0.2}],"drivers":["Recent first-print core PCE monthly values averaged 0.27 percent","June and July cooled to 0.1 and 0.2 percent after firmer first-quarter prints","Sticky services inflation keeps the point estimate above a clean 0.2 percent persistence forecast","No August or September PCE release information is public yet, so the forecast leans on BEA first-print history"],"sourceContext":["https://www.bea.gov/news/schedule","https://www.bea.gov/data/personal-consumption-expenditures-price-index-excluding-food-and-energy","https://www.bea.gov/news/2026/personal-income-and-outlays-january-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-february-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-march-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-april-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-may-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-june-2026","https://www.bea.gov/news/2026/personal-income-and-outlays-july-2026"],"runAt":"2026-09-04T19:18:21Z","reasoning":[{"kind":"heading","text":"US core PCE MoM September 2026 forecast"},{"kind":"text","text":"Framing and exact resolver: this targets BEA's first-print seasonally adjusted monthly percent change for the PCE price index excluding food and energy for September 2026, the same variant as BEA NIPA Table 2.8.7, Percent Change From Preceding Period in Prices for PCE by Major Type of Product. The registered ledger sourceBinding table text says August 2026, but the target period and dataPointId are September 2026 and the BEA schedule verifies the September 2026 Personal Income and Outlays release on 2026-10-29; I keep the forecast tied to the registered September target and treat the August table label as a ledger-label discrepancy."},{"kind":"tool","tool":"official.lookup","call":"BEA release schedule lookup for Personal Income and Outlays, September 2026","result":"BEA schedule lists Personal Income and Outlays, September 2026 on October 29, 2026 at 8:30 AM; the same schedule lists the August 2026 release on September 30, 2026 at 8:30 AM."},{"kind":"tool","tool":"official.lookup","call":"BEA January-March 2026 Personal Income and Outlays releases, core PCE price index excluding food and energy, percent change from preceding month","result":"Fetched first-print same-variant values: January 2026 = 0.4 percent, February 2026 = 0.4 percent, March 2026 = 0.3 percent."},{"kind":"tool","tool":"official.lookup","call":"BEA April-June 2026 Personal Income and Outlays releases, core PCE price index excluding food and energy, percent change from preceding month","result":"Fetched first-print same-variant values: April 2026 = 0.2 percent, May 2026 = 0.3 percent, June 2026 = 0.1 percent."},{"kind":"tool","tool":"official.lookup","call":"BEA July 2026 Personal Income and Outlays release and core PCE series page","result":"Fetched latest first-print same-variant value: July 2026 core PCE price index excluding food and energy = 0.2 percent month over month; BEA's core PCE series page shows July 2026 year-over-year = 3.3 percent and next release = September 30, 2026."},{"kind":"text","text":"Base rate / reference class: the recent official first-print reference class is January through July 2026, with values 0.4, 0.4, 0.3, 0.2, 0.3, 0.1, and 0.2 percent. The simple base rate mean is 1.9 / 7 = 0.271 percent, while the most recent three prints average (0.3 + 0.1 + 0.2) / 3 = 0.200 percent."},{"kind":"math","text":"Prior/update/interval: persistence prior is the recent first-print mean, historical sample is seven BEA same-variant monthly core PCE prints from 2026-01 through 2026-07, adjustment components are -0.04 percentage point for cooling June-July momentum, +0.01 for sticky services/core inflation persistence, and about 0.00 for one-off release mechanics because no September CPI/PPI bridge data are yet available. Point = 0.271 - 0.04 + 0.01 = 0.241, rounded to 0.24. For a change/flow series, use the values themselves for dispersion: sample sigma = 0.111 from [0.4, 0.4, 0.3, 0.2, 0.3, 0.1, 0.2]. The 80 percent half-width is roughly 1.28*sigma = 1.28*0.111 = 0.142, so bounds are 0.24 - 0.142 = 0.098 and 0.24 + 0.142 = 0.382, rounded to 0.10 and 0.38."},{"kind":"text","text":"Upside risk: a renewed firming in core services, medical services, portfolio-management fees, or September source-data surprises would land above the interval if BEA prints about 0.4 percent or higher. Downside risk: weaker goods prices, softer shelter-related imputations, or broad disinflation in services would land below the interval if the first print is about 0.1 percent or lower. Outside the interval would most likely require a source-data shock rather than ordinary month-to-month noise."},{"kind":"forecast","point":0.24,"ciLow":0.1,"ciHigh":0.38}]}

# Reviewer critique
{
  "summary": "Draft is publishable after a small resolver/source cleanup; the forecast logic is otherwise coherent and traceable.",
  "requiredFixes": [
    {
      "rubricItem": "resolver",
      "severity": "warning",
      "summary": "The draft correctly identifies the BEA first-print September 2026 Personal Income and Outlays release date as 2026-10-29, but its `resolutionSourceUrl` is a future news-release URL while the ledger binding currently names the BEA core PCE series page and has an August table-label discrepancy.",
      "actionRequested": "Align the resolver fields with the registered source binding where possible, and keep the explicit reasoning note that the ledger table label says August 2026 while the target period, slug, and dataPointId are September 2026."
    },
    {
      "rubricItem": "update",
      "severity": "warning",
      "summary": "The +0.01 sticky-services adjustment is directionally plausible but not tied to a concrete cited component value or named BEA table observation.",
      "actionRequested": "Either cite the specific BEA component evidence supporting sticky services/core persistence or describe the +0.01 as a judgmental residual rather than evidence-driven movement."
    }
  ],
  "optionalSuggestions": [
    "State that the seven-month volatility sample is intentionally short because it uses same-year first prints, or add a longer historical volatility cross-check if available.",
    "Make the final forecast step repeat the rounded implied bounds 0.10 to 0.38 so the JSON interval and reasoning are visibly identical."
  ]
}

Emit the final JSON object only.
