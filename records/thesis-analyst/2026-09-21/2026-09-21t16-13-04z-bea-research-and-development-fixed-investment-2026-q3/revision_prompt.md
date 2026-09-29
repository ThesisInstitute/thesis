# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bea.research_and_development_fixed_investment
- period: 2026-Q3
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-private-research-development-fixed-investment-q3-2026"
- country: "US"
- targetUnit: "usd_billions"
- dataPointId: "bea.research_and_development_fixed_investment.2026_q3.first_print"
- publishedResolutionDate: "2026-10-29"
- expectedReleaseWindow: {"end": "2026-10-29", "start": "2026-10-29"}
- resolutionSource: "U.S. Bureau of Economic Analysis GDP advance release, NIPA Table 5.3.5 line 18"
- resolutionSourceUrl: "https://apps.bea.gov/iTable/?ReqID=19&step=3&isuri=1&nipa_table_list=145&categories=survey"
- resolutionRule: "Resolve to the first official BEA GDP advance-release print for 2026-Q3, NIPA Table 5.3.5, line 18 Research and development, nominal seasonally adjusted annual rate. Use the published table value transformed by multiplying the table's millions-of-dollars value by 0.001 to usd_billions, retaining the precision implied by the official table; do not use later second, third, annual-update, or comprehensive-revision values except insofar as BEA has already incorporated them into the first Q3 advance-release table on 2026-10-29."
- resolutionPolicy: "first_print"
- sourceBinding: {"adapter": "bea-release", "allowedHosts": ["apps.bea.gov", "www.bea.gov"], "expectedReleaseWindow": {"end": "2026-10-29", "start": "2026-10-29"}, "field": "Line 18: Research and development", "releasePolicy": "first_print", "sourceSeriesId": "T50305:L18", "sourceUrl": "https://apps.bea.gov/iTable/?ReqID=19&step=3&isuri=1&nipa_table_list=145&categories=survey", "table": "Gross Domestic Product advance release, NIPA Table 5.3.5, line 18 (Research and development)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-08-17-a80665069544aa19303c03ea1fb560eba0b15bc2443c19c8b09bfe4d9f0f3ac1.json"
- targetContentHash: "a80665069544aa19303c03ea1fb560eba0b15bc2443c19c8b09bfe4d9f0f3ac1"
- registrationCommit: "f3a73cbcc701b9315d3ec1d35ea05889b2c07f95"
- registeredAtUtc: "2026-08-17T16:54:17Z"

# Comparison target contract (machine checked)
This run is a strategy comparison against an already published forecast. The sealed cell's resolutionDate, resolutionSource, resolutionSourceUrl and resolutionRule are pinned to that forecast's published resolver; publishedResolutionDate "2026-10-29" is its resolver date. Still verify the official release schedule this run and state any discrepancy in reasoning rather than changing the target.

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

# Threshold-ladder elicitation (promptMode ladder)
This run elicits the distribution as binary exceedance questions BEFORE stating any point estimate, then derives the published numbers from the ladder.
- After research, choose 11-15 strictly increasing thresholds t in the target's print units spanning your genuine uncertainty: the first rung's cumulative probability must be <= 0.10 and the last >= 0.90.
- For each rung independently answer the binary question 'What is the probability the first print is <= t?', as if pricing a binary market. Probabilities must be non-decreasing across rungs and within [0.01, 0.99].
- Add one math reasoning step that begins 'Ladder:' and lists every rung literally as 'P(X <= t) = p' pairs.
- Derive the published numbers FROM the ladder by linear interpolation between rungs: pointEstimate at cumulative 0.50, ciLow at 0.10, ciHigh at 0.90, each rounded to the print precision. The cell fields and the final forecast step must equal these derived values exactly.
- Keep every fast-mode requirement above (sigma arithmetic, base rate, upside/downside/outside-the-interval risks). In the Prior/update/interval step, also state how the ladder-implied 80% width compares to the 1.28*sigma width.
- Add this top-level field to the cell JSON, with your actual rungs as two equal-length numeric arrays:
{
  "thresholdLadder": {
    "thresholds": [
      "strictly increasing numeric rungs"
    ],
    "cumulativeProbabilities": [
      "non-decreasing, within [0.01, 0.99]"
    ]
  }
}


# Captured tool evidence
Use the thesis_tool_evidence MCP tools for source reads and calculations.
fetch_source saves the complete public HTTPS response and returns its call ID,
hash, and a bounded excerpt. extract_json selects a JSON Pointer from a prior
fetch_source response. calculate evaluates bounded arithmetic, with named inputs
that can refer to earlier extraction/calculation results by {"callId":"call-0001"}.
Use these tools for the base rate and interval arithmetic, and cite the returned
call IDs in your trace. Keep supplied assumptions and judgment adjustments
explicit. An extraction or calculation replay verifies the operation on its
inputs; it does not independently verify those assumptions or the source's truth.
Tool calls outside this channel, including hosted web search and shell commands,
do not preserve full response receipts here. Say when evidence was not captured.
Never manufacture a tool receipt or describe model-authored text as captured
output. Failed calls remain in the record. Only public, unauthenticated HTTPS
sources are supported; do not send credentials or private URLs to these tools.


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
{"slug":"us-private-research-development-fixed-investment-q3-2026","country":"US","type":"data","title":"US R&D Fixed Investment 2026-Q3","question":"What will BEA first report for 2026-Q3 private research and development fixed investment, NIPA Table 5.3.5 line 18, nominal seasonally adjusted annual rate?","unit":"usd_billions","pointEstimate":962.0,"ciLow":934.0,"ciHigh":988.4,"confidence":0.8,"resolutionDate":"2026-10-29","resolutionSource":"U.S. Bureau of Economic Analysis GDP advance release, NIPA Table 5.3.5 line 18","resolutionSourceUrl":"https://apps.bea.gov/iTable/?ReqID=19&step=3&isuri=1&nipa_table_list=145&categories=survey","resolutionRule":"Resolve to the first official BEA GDP advance-release print for 2026-Q3, NIPA Table 5.3.5, line 18 Research and development, nominal seasonally adjusted annual rate. Use the published table value transformed by multiplying the table's millions-of-dollars value by 0.001 to usd_billions, retaining the precision implied by the official table; do not use later second, third, annual-update, or comprehensive-revision values except insofar as BEA has already incorporated them into the first Q3 advance-release table on 2026-10-29.","dataPointId":"bea.research_and_development_fixed_investment.2026_q3.first_print","historicalContext":[{"period":{"type":"quarter","value":"2023-Q1"},"label":"2023-Q1","value":757.014},{"period":{"type":"quarter","value":"2023-Q2"},"label":"2023-Q2","value":768.124},{"period":{"type":"quarter","value":"2023-Q3"},"label":"2023-Q3","value":772.65},{"period":{"type":"quarter","value":"2023-Q4"},"label":"2023-Q4","value":779.924},{"period":{"type":"quarter","value":"2024-Q1"},"label":"2024-Q1","value":790.638},{"period":{"type":"quarter","value":"2024-Q2"},"label":"2024-Q2","value":790.755},{"period":{"type":"quarter","value":"2024-Q3"},"label":"2024-Q3","value":801.362},{"period":{"type":"quarter","value":"2024-Q4"},"label":"2024-Q4","value":803.046},{"period":{"type":"quarter","value":"2025-Q1"},"label":"2025-Q1","value":806.273},{"period":{"type":"quarter","value":"2025-Q2"},"label":"2025-Q2","value":829.769},{"period":{"type":"quarter","value":"2025-Q3"},"label":"2025-Q3","value":855.584},{"period":{"type":"quarter","value":"2025-Q4"},"label":"2025-Q4","value":881.507},{"period":{"type":"quarter","value":"2026-Q1"},"label":"2026-Q1","value":909.507},{"period":{"type":"quarter","value":"2026-Q2"},"label":"2026-Q2","value":936.0}],"drivers":["recent nominal R&D investment momentum accelerated through 2026-Q2","BEA Q2 advance GDP release reported real GDP growth of 1.5 percent SAAR after 2.1 percent in Q1","intellectual-property investment tends to be smoother than structures but current-dollar levels can shift at annual update","first-print source data and BEA projections add uncertainty around the latest quarter"],"sourceContext":["https://www.bea.gov/news/schedule/full","https://api.db.nomics.world/v22/series/BEA/NIPA-T50305/Y006RC-Q?observations=1","https://www.bea.gov/news/2026/gdp-advance-estimate-2nd-quarter-2026"],"runAt":"2026-09-21T16:13:13Z","thresholdLadder":{"thresholds":[920,930,940,950,956,962,968,974,980,986,992,1000,1010],"cumulativeProbabilities":[0.04,0.08,0.13,0.25,0.38,0.5,0.62,0.73,0.82,0.88,0.93,0.97,0.99]},"reasoning":[{"kind":"heading","text":"US private research and development fixed investment, 2026-Q3 first print"},{"kind":"text","text":"Resolver framing: this is BEA NIPA Table 5.3.5 line 18, Research and development, nominal seasonally adjusted annual rate, source concept T50305:L18. The official table is in millions of dollars; the registered target unit is usd_billions, so resolution multiplies the first-print table value by 0.001. No discrepancy was found in the ledger date, unit, source, or rule."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0005 captured the BEA official full release schedule and I checked the GDP advance-estimate row for 2026-Q3.","result":"call-0005 fetched 124266 bytes from BEA's official schedule; the schedule lists GDP (Advance Estimate), 3rd Quarter 2026 on 2026-10-29 at 8:30 AM, matching the registered resolutionDate 2026-10-29."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0003 and extract_json calls call-0004, call-0007, and call-0008 captured the public BEA/DBnomics NIPA Table 5.3.5 Y006RC-Q series used as a BEA-source history mirror for line 18.","result":"call-0003 identifies provider BEA, dataset NIPA-T50305, Table 5.3.5 LastRevised August 26, 2026, and Research and development line 18 in millions of current dollars; fetched recent values were 2023-Q1 757014, 2023-Q2 768124, 2023-Q3 772650, 2023-Q4 779924, 2024-Q1 790638, 2024-Q2 790755, 2024-Q3 801362, 2024-Q4 803046, 2025-Q1 806273, 2025-Q2 829769, 2025-Q3 855584, 2025-Q4 881507, 2026-Q1 909507, and 2026-Q2 936000, transformed to 757.014 through 936.000 usd_billions."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0006 captured BEA's Q2 2026 GDP advance-estimate release for current macro context.","result":"call-0006 fetched 53098 bytes; BEA reported real GDP +1.5 percent SAAR in 2026-Q2 after +2.1 percent in 2026-Q1, and the release metadata states this was the 2nd Quarter 2026 advance estimate."},{"kind":"tool","tool":"official.calculate","call":"calculate calls call-0009 through call-0017 used the fetched 2023-Q1 through 2026-Q2 history to compute the reference-class mean change, dispersion, and ladder interpolations.","result":"call-0009 computed mean(diff(history)) = 13.768153846153846 usd_billions; call-0010 computed sigma = 10.60440005254229 usd_billions from successive changes; call-0011 computed 1.28*sigma = 13.573632067254133 usd_billions; call-0012 computed p10 = 934.0; call-0013 computed p90 = 988.4; call-0017 computed the latest five changes as 23.496, 25.815, 25.923, 28.000, and 26.493 usd_billions."},{"kind":"text","text":"Base rate/reference class: the 2023-Q1 through 2026-Q2 level history gives an outside-view quarterly increase of about +13.768 usd_billions, while the latest five changes are all much stronger at about +23.496 to +28.000 usd_billions. A simple base-rate persistence prior from 2026-Q2 is 949.768, but recent momentum points higher."},{"kind":"math","text":"Ladder: P(X <= 920) = 0.04; P(X <= 930) = 0.08; P(X <= 940) = 0.13; P(X <= 950) = 0.25; P(X <= 956) = 0.38; P(X <= 962) = 0.50; P(X <= 968) = 0.62; P(X <= 974) = 0.73; P(X <= 980) = 0.82; P(X <= 986) = 0.88; P(X <= 992) = 0.93; P(X <= 1000) = 0.97; P(X <= 1010) = 0.99. Linear interpolation gives p10 = 934.0 from call-0012, p50 = 962.0 because the 0.50 rung is exact, and p90 = 988.4 from call-0013."},{"kind":"math","text":"Prior/update/interval: persistence prior is the 2026-Q2 fetched level 936.000 plus the 2023-Q1 to 2026-Q2 mean quarterly change of 13.768, giving 949.768 in call-0014. Adjustment components are +12.232 for the stronger recent run of +23.496 to +28.000 quarterly changes and ongoing nominal intellectual-property investment strength, tempered by first-print source-data risk and possible annual-update rebasing before the Q3 advance release. Interval method is threshold-ladder interpolation, checked against realized dispersion: sigma = 10.604 usd_billions from call-0010, so 1.28*sigma = 13.574 from call-0011; the ladder-implied 80% width is 54.400 from call-0015, or half-width 27.200, about 2.00 times 1.28*sigma from call-0016, widened because the target is a first print that may incorporate annual-update level shifts as well as Q3 source-data surprises."},{"kind":"text","text":"Upside risk: continued software, data-center, and R&D investment strength or an upward annual-update level shift would land above the interval. Downside risk: slower nominal IPP spending, weaker corporate investment budgets, or downward rebasing would land below the interval. An outside the interval outcome would most likely require both a large annual-update level shift and an unusually large Q3 source-data surprise."},{"kind":"forecast","point":962.0,"ciLow":934.0,"ciHigh":988.4}]}

# Reviewer critique
{"summary":"The draft satisfies the resolver contract and gives a coherent prior, update, interval, tails, and final JSON for the sealed target.","requiredFixes":[],"optionalSuggestions":["Consider stating the BEA schedule check in sourceContext as the official confirmation for the 2026-10-29 8:30 AM GDP advance release.","The update rationale would be slightly stronger if it separated pure recent-change persistence from broader IPP/macroeconomic context."]}

Emit the final JSON object only.
