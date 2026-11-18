# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.employed_people_by_occupation.computer_mathematical
- period: 2026-11
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-computer-math-employment-november-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.computer_mathematical.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-04", "start": "2026-12-04"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-04", "start": "2026-12-04"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "LNU02032455", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032455", "table": "Current Population Survey, employed people, Computer and mathematical occupations, total 16 years and over, not seasonally adjusted, in thousands (Employment Situation, Table A-19)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-11-10-52e4aa7d06ffc1fcfac9b349051fab7a2493eb7dee2fb4be2f88971178dba154.json"
- targetContentHash: "52e4aa7d06ffc1fcfac9b349051fab7a2493eb7dee2fb4be2f88971178dba154"
- registrationCommit: "48d10b11037d587eff33b6a8fe1deff8357a60d7"
- registeredAtUtc: "2026-11-10T00:21:03Z"

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


# Captured tool evidence
Use the thesis_tool_evidence MCP tools for source reads and calculations.
fetch_source saves the complete public HTTPS response and returns its call ID,
hash, and a bounded excerpt. extract_json selects a JSON Pointer from a prior
fetch_source response. extract_irs_soi replays the reviewed IRS Table 3.3
parser on a prior captured workbook, selecting the exact series and tax year;
its numeric value is already in the registered unit. calculate evaluates
bounded arithmetic, with named inputs
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
{"slug":"cps-computer-math-employment-november-2026","country":"US","type":"data","title":"US computer and mathematical employment, November 2026","question":"What will BLS first print for Current Population Survey employed people in computer and mathematical occupations, total 16 years and over, not seasonally adjusted, for November 2026?","unit":"millions","pointEstimate":7.05,"ciLow":6.919404275040192,"ciHigh":7.180595724959808,"confidence":0.8,"resolutionDate":"2026-12-04","resolutionSource":"U.S. Bureau of Labor Statistics public API, Current Population Survey Table A-19 series LNU02032455","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032455","resolutionRule":"Resolve to the first official BLS public API value for series LNU02032455 for 2026 M11, Current Population Survey Table A-19, not seasonally adjusted, in thousands, multiplied by 0.001 to millions. Use the first print available after the Employment Situation for November 2026 is released on 2026-12-04; do not use later revisions, same-day corrections, or alternative adjusted series.","dataPointId":"bls.cps.employed_people_by_occupation.computer_mathematical.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"2026-01","value":6.632},{"period":{"type":"month","value":"2026-02"},"label":"2026-02","value":6.692},{"period":{"type":"month","value":"2026-03"},"label":"2026-03","value":6.574},{"period":{"type":"month","value":"2026-04"},"label":"2026-04","value":6.834},{"period":{"type":"month","value":"2026-05"},"label":"2026-05","value":6.903},{"period":{"type":"month","value":"2026-06"},"label":"2026-06","value":6.95},{"period":{"type":"month","value":"2026-07"},"label":"2026-07","value":6.924},{"period":{"type":"month","value":"2026-08"},"label":"2026-08","value":7.01},{"period":{"type":"month","value":"2026-09"},"label":"2026-09","value":7.004},{"period":{"type":"month","value":"2026-10"},"label":"2026-10","value":7.03}],"drivers":["October 2026 level was 7.030 million after the registered transform","Recent three-month mean was 7.0147 million","Occupation employment has risen versus November 2025 but remains monthly-noisy in the NSA CPS series","November target is not seasonally adjusted, so month-specific sampling and seasonal noise matter"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032455","https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032455?startyear=2016&endyear=2026","https://www.bls.gov/schedule/news_release/empsit.htm"],"runAt":"2026-11-10T00:30:06Z","reasoning":[{"kind":"heading","text":"Forecast for CPS computer and mathematical employment, November 2026"},{"kind":"text","text":"Resolver framing: the target is BLS CPS series LNU02032455, Current Population Survey Table A-19, employed people in computer and mathematical occupations, total 16 years and over, not seasonally adjusted. The registered source value is in thousands and the target unit is millions, so each API value is multiplied by 0.001. The official BLS Employment Situation schedule for this run lists November 2026 for release on 2026-12-04 at 08:30 Eastern; an evidence fetch to the schedule page was blocked with HTTP 403, so the date verification used the official BLS schedule result available to the run rather than a captured full-page receipt."},{"kind":"tool","tool":"mcp__thesis_tool_evidence.fetch_source","call":"fetch_source https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032455","result":"call-0001 captured the official BLS API response for LNU02032455: October 2026=7030 thousand, September 2026=7004 thousand, August 2026=7010 thousand, July 2026=6924 thousand, June 2026=6950 thousand, May 2026=6903 thousand, April 2026=6834 thousand."},{"kind":"tool","tool":"mcp__thesis_tool_evidence.fetch_source","call":"fetch_source https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032455?startyear=2016&endyear=2026","result":"call-0010 captured the longer official BLS API history, including November 2025=6632 thousand and November 2024=6483 thousand; the API message reported the year range was reduced to the system-allowed 10-year limit."},{"kind":"tool","tool":"mcp__thesis_tool_evidence.calculate","call":"calculate recent level, year-over-year, and volatility from captured BLS values","result":"call-0012 calculated the recent three-month mean from 7.010, 7.004, and 7.030 million as 7.014666666666667; call-0017 calculated October 2026 minus November 2025 as 0.3980000000000006 million; call-0024 calculated November 2025 minus November 2024 as 149 thousand."},{"kind":"text","text":"Reference class and base rate: for this level series, the practical base rate is persistence around the latest official level with CPS sampling and NSA seasonal noise. The current October level of 7.030 million is above the April-October 2026 mean of 6.9507 million and above November 2025 by about 0.398 million, so I start from October persistence and allow a small positive November update rather than reverting all the way to the spring average."},{"kind":"math","text":"Prior/update/interval: persistence prior = October 2026 level 7.030 million; historical sample = January-October 2026 official BLS values after the registered transform [6.632, 6.692, 6.574, 6.834, 6.903, 6.950, 6.924, 7.010, 7.004, 7.030]; adjustment components = +0.020 million for the recent upward level and November seasonal/reference-class tendency, with no policy mechanism adjustment; interval method = sample standard deviation of successive monthly changes from call-0013, sigma = 0.10202791012484985 million, so 1.28*sigma from call-0018 = 0.1305957249598078 million; final point from call-0025 = 7.050 million, final implied bounds from call-0022 and call-0023 = 6.919404275040192 to 7.180595724959808 million."},{"kind":"text","text":"Counter-considerations: upside risk would come from another strong CPS occupation sample or continued tech/professional hiring that pushes the first print above 7.1806 million. Downside risk would come from mean reversion after October, a weaker November household-survey sample, or occupation reclassification noise that would land below 6.9194 million. A large CPS sampling surprise is the main outside the interval scenario."},{"kind":"forecast","point":7.05,"ciLow":6.919404275040192,"ciHigh":7.180595724959808}]}

# Reviewer critique
{
  "summary": "Draft is publishable with the target contract, prior, update, interval, tails, and JSON fields broadly coherent.",
  "requiredFixes": [],
  "optionalSuggestions": [
    "Tighten the +0.020 million update by separating recent-level momentum from the claimed November seasonal/reference-class tendency, since the seasonal component is asserted but not quantified.",
    "If possible, replace the blocked schedule-page note with the exact official schedule evidence artifact or state that the ledger registration supplies the release date."
  ]
}

Emit the final JSON object only.
