# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.employed_people_by_occupation.business_financial_operations
- period: 2026-11
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-business-financial-employment-november-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.business_financial_operations.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-04", "start": "2026-12-04"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-04", "start": "2026-12-04"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "LNU02032454", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032454", "table": "Current Population Survey, employed people, Business and financial operations occupations, total 16 years and over, not seasonally adjusted, in thousands (Employment Situation, Table A-19)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-11-10-0d76d97cc6412fa35c60f572b02c4a00c2f76ab4a3acddeeda492e79d2b815f9.json"
- targetContentHash: "0d76d97cc6412fa35c60f572b02c4a00c2f76ab4a3acddeeda492e79d2b815f9"
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
{"slug":"cps-business-financial-employment-november-2026","country":"US","type":"data","title":"US business and financial employment, Nov. 2026","question":"BLS Current Population Survey series LNU02032454, employed people in business and financial operations occupations, 16 years and over, not seasonally adjusted, November 2026 first print, converted from thousands to millions.","unit":"millions","pointEstimate":10.3,"ciLow":10.1,"ciHigh":10.5,"confidence":0.8,"resolutionDate":"2026-12-04","resolutionSource":"BLS Public Data API series LNU02032454, Employment Situation Table A-19","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032454","resolutionRule":"Resolve to the first BLS public API value for series LNU02032454, period 2026 M11, field value, as first printed for the Employment Situation release scheduled for December 4, 2026. The API value is in thousands; multiply by 0.001 and report in millions. Do not use later revisions, corrected same-day values, or alternate seasonal-adjustment variants unless the registered resolver changes.","dataPointId":"bls.cps.employed_people_by_occupation.business_financial_operations.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":10.251},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":10.212},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":10.23},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":10.192},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":10.195},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":10.133},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":10.033},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":9.72},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":9.835},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":10.167},{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":10.268},{"period":{"type":"month","value":"2026-10"},"label":"October 2026","value":10.337}],"drivers":["October 2026 level was 10.337 million after applying the registered thousands-to-millions transform","Recent 12-print reference class is centered near 10.2 million with mild positive drift","NSA occupation detail is noisy month to month, including a June 2026 trough and August rebound","A small November seasonal drag is plausible, based partly on the 2024 October-to-November decline","Resolution calendar is verified from BLS calendar pages for the November 2026 Employment Situation release"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032454","https://blsmon1.bls.gov/schedule/2026/12_sched_list.htm","https://blsmon1.bls.gov/schedule/news_release/bls.ics"],"runAt":"2026-11-10T00:28:55Z","reasoning":[{"kind":"heading","text":"BLS CPS Business And Financial Occupation Employment Forecast"},{"kind":"text","text":"The target is BLS CPS series LNU02032454, Current Population Survey employed people in business and financial operations occupations, total 16 years and over, not seasonally adjusted, Table A-19. The source series is in thousands and the registered resolver converts to millions with factor 0.001."},{"kind":"text","text":"BLS schedule evidence was captured from the December 2026 selected-release page as call-0004 and the BLS calendar feed as call-0005; hosted search also showed the official BLS Employment Situation schedule listing November 2026 for Dec. 04, 2026 at 08:30 AM, while direct fetches of www.bls.gov schedule pages returned 403 in call-0002 and call-0003."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0001 and extract_json call-0006 for BLS Public Data API series LNU02032454","result":"Fetched official values include October 2026 = 10337 thousand, September 2026 = 10268 thousand, August 2026 = 10167 thousand, July 2026 = 9835 thousand, June 2026 = 9720 thousand, and May 2026 = 10033 thousand."},{"kind":"tool","tool":"official.lookup","call":"read older observations from captured BLS API payload call-0001/call-0006","result":"Additional fetched official values include April 2026 = 10133 thousand, March 2026 = 10195 thousand, February 2026 = 10192 thousand, January 2026 = 10230 thousand, December 2025 = 10212 thousand, and November 2025 = 10251 thousand."},{"kind":"tool","tool":"official.lookup","call":"same-series context from captured BLS API payload call-0001/call-0006","result":"The same official BLS response shows 2025 October unavailable, September 2025 = 10194 thousand, August 2025 = 10114 thousand, July 2025 = 10298 thousand, June 2025 = 10205 thousand, and November 2024 = 9892 thousand; the 2025 lapse note makes October 2025 unsuitable as an October-to-November anchor."},{"kind":"math","text":"The base rate reference class is the recent same-series NSA level history from November 2025 through October 2026, excluding unavailable October 2025. Converted to millions, the chronological history is 10.251, 10.212, 10.230, 10.192, 10.195, 10.133, 10.033, 9.720, 9.835, 10.167, 10.268, 10.337."},{"kind":"math","text":"Prior/update/interval: persistence prior uses latest official level 10.337 million plus the mean recent monthly change from call-0009, +0.0078 million, giving 10.3448 million in call-0010; I apply a -0.045 million judgmental November NSA seasonal adjustment because 2024 October-to-November fell from 10.001 to 9.892 million and 2025 October is unavailable, yielding point 10.2998 million in call-0011. The interval method uses successive changes from the 12-print history; call-0007 gives sigma = 0.1590 million, so 1.28*sigma = 0.2035 million in call-0008, with bounds 10.0963 and 10.5034 from call-0012 and call-0013."},{"kind":"text","text":"Upside risk is another late-2026 occupation-specific rebound like August 2026, which would land above the interval if November prints above 10.5 million. Downside risk is renewed weakness like the June 2026 drop or a compositional decline in this occupation category, which would land outside the interval below 10.1 million."},{"kind":"forecast","point":10.3,"ciLow":10.1,"ciHigh":10.5}]}

# Reviewer critique
{
  "summary": "Draft is publication-ready on the review rubric, with resolver, unit, prior/update math, interval method, tails, and JSON fields aligned to the registered target.",
  "requiredFixes": [],
  "optionalSuggestions": [
    "Consider noting that the November seasonal adjustment is judgmental and based on sparse Oct-to-Nov evidence, but the current text is sufficient.",
    "If space permits, mention the exact latest-observation date used for the persistence prior: October 2026 first available API value."
  ]
}

Emit the final JSON object only.
