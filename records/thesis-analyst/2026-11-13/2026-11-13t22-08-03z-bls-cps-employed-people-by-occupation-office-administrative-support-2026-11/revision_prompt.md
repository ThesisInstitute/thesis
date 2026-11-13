# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.employed_people_by_occupation.office_administrative_support
- period: 2026-11
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-office-admin-employment-november-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.office_administrative_support.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-04", "start": "2026-12-04"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-04", "start": "2026-12-04"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "LNU02032207", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032207", "table": "Current Population Survey, employed people, Office and administrative support occupations, total 16 years and over, not seasonally adjusted, in thousands (Employment Situation, Table A-19)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-11-13-03ea7af40c5c3b6405c6aafc9e06bf5a776bba4adaff1708334c570a622f1923.json"
- targetContentHash: "03ea7af40c5c3b6405c6aafc9e06bf5a776bba4adaff1708334c570a622f1923"
- registrationCommit: "5cb6b72d8468fd0f460d6919a14de9921b0dcd7c"
- registeredAtUtc: "2026-11-13T22:03:59Z"

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
{"slug":"cps-office-admin-employment-november-2026","country":"US","type":"data","title":"US office admin employment, Nov. 2026","question":"What will BLS first print for Current Population Survey employed people in office and administrative support occupations, total 16 years and over, not seasonally adjusted, November 2026, series LNU02032207?","unit":"millions","pointEstimate":16.323,"ciLow":16.053,"ciHigh":16.593,"confidence":0.8,"resolutionDate":"2026-12-04","resolutionSource":"U.S. Bureau of Labor Statistics Employment Situation release and public API","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032207","resolutionRule":"Resolve to the first official BLS print for CPS series LNU02032207, period 2026 M11, field value in thousands, transformed by multiplying by 0.001 to millions. Use the value available in the Dec. 4, 2026 Employment Situation first release/API print; ignore later revisions, corrections, or annual rebenchmarking unless the official first-print file itself is replaced before capture.","dataPointId":"bls.cps.employed_people_by_occupation.office_administrative_support.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":16.471},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":16.335},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":16.184},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":16.457},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":16.154},{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":16.065},{"period":{"type":"month","value":"2026-10"},"label":"October 2026","value":16.201}],"drivers":["October 2026 level was 16.201 million after the registered thousands-to-millions transform","Recent April-October 2026 reference class averaged 16.267 million","Recent month-to-month changes were slightly negative on average","November NSA seasonality has upside risk, with 2024 October-to-November up 0.152 million and 2025 November at 17.102 million","2025 October was unavailable due to the lapse in appropriations, so the closest clean seasonal anchor is 2024 October-to-November"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032207","https://blsmon1.bls.gov/schedule/2026/12_sched_list.htm"],"runAt":"2026-11-13T22:08:51Z","reasoning":[{"kind":"heading","text":"Forecast for BLS CPS office and administrative support employment, November 2026"},{"kind":"text","text":"The target is BLS CPS series LNU02032207, Current Population Survey employed people in office and administrative support occupations, total 16 years and over, not seasonally adjusted, Table A-19. The registered unit is millions, so each BLS API value in thousands is multiplied by 0.001."},{"kind":"text","text":"The official BLS release calendar was checked this run: the December 2026 BLS calendar page schedules Employment Situation for November 2026 on Friday, December 4, 2026 at 8:30 AM Eastern. The direct www.bls.gov schedule fetch returned HTTP 403 in captured evidence, but the BLS blsmon1 calendar mirror fetch succeeded as call-0004; hosted search also showed the same BLS schedule text."},{"kind":"tool","tool":"official.lookup","call":"fetch_source https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032207, then extract recent monthly values","result":"Captured BLS API response call-0001, sha256 55581a6c477e66f5526f094a561f86528101c59189773940f7366371a4f0bd21. Extracted values in thousands: April 2026 16471, May 2026 16335, June 2026 16184, July 2026 16457, August 2026 16154, September 2026 16065, October 2026 16201; transformed to 16.471, 16.335, 16.184, 16.457, 16.154, 16.065, 16.201 million."},{"kind":"tool","tool":"official.lookup","call":"extract historical November and October seasonal anchors from the same BLS API response","result":"From call-0001, extracted November 2025 value 17102 thousand, November 2024 value 16066 thousand, and October 2024 value 15914 thousand. October 2025 was '-' with footnote code 9, so the clean recent October-to-November seasonal change is 16066 - 15914 = 152 thousand, or 0.152 million."},{"kind":"tool","tool":"official.calculate","call":"calculate recent base rate, momentum, sigma, point, and interval from captured BLS values","result":"Calculation receipts: call-0019 mean([16.471,16.335,16.184,16.457,16.154,16.065,16.201]) = 16.266714285714286; call-0020 mean changes [-0.136,-0.151,0.273,-0.303,-0.089,0.136] = -0.045; call-0018 sigma = stdev(diff(history)) = 0.21066656118140803; call-0021 1.28*sigma = 0.2696531983122023; call-0022 point = 16.201 + 0.152 - 0.030 = 16.323."},{"kind":"math","text":"Prior/update/interval: base rate and reference class are the seven latest official BLS prints for this exact NSA occupation series, April-October 2026, with persistence centered on October 2026 at 16.201 million and recent-level mean 16.267 million. I update by adding the clean 2024 October-to-November seasonal change of +0.152 million, then subtract a judgmental -0.030 million for the recent soft average monthly momentum, giving 16.323 million. Interval method: realized dispersion of successive changes in the April-October sequence; sigma = 0.21066656118140803, and the 80% normal half-width is 1.28*sigma = 0.2696531983122023. Bounds are 16.323 - 0.2696531983122023 = 16.0533468016878 and 16.323 + 0.2696531983122023 = 16.592653198312203, rounded to 16.053 and 16.593 million."},{"kind":"text","text":"Counter-considerations: upside risk comes from another strong November seasonal hiring/readthrough like November 2025's 17.102 million level or a broad household-survey employment rebound; that would land above the interval. Downside risk is a renewed decline in clerical/admin employment or weak household-survey employment after October; a drop larger than about 0.15 million from October would land below the interval. Outside the interval would mainly require a one-month swing larger than recent April-October dispersion or a repeat of the 2025 November outlier."},{"kind":"forecast","point":16.323,"ciLow":16.053,"ciHigh":16.593}]}

# Reviewer critique
{"summary":"The draft is publishable: it matches the registered resolver contract, states a persistence/seasonal prior, justifies the update, and keeps point, interval, unit, and JSON fields coherent.","requiredFixes":[],"optionalSuggestions":["Consider noting that the interval uses only six recent month-to-month changes, so the 80% band is mechanically tied to a small realized-volatility sample.","The tail discussion could name concrete downside/upside thresholds in millions, e.g. below 16.053 or above 16.593."]}

Emit the final JSON object only.
