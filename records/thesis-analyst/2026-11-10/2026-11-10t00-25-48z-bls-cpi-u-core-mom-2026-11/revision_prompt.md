# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cpi.u.core_mom
- period: 2026-11
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-core-cpi-mom-november-2026"
- country: "US"
- targetUnit: "percent_growth"
- dataPointId: "bls.cpi.u.core_mom.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-10", "start": "2026-12-10"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-10", "start": "2026-12-10"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "CUSR0000SA0L1E", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0L1E", "table": "Consumer Price Index for All Urban Consumers, US city average, all items less food and energy, seasonally adjusted (CPI news release, Table A)", "transform": {"factor": 1, "operation": "percent_change_previous_period"}}
- targetRegistrationPath: "records/targets/2026-11-10-b6068648fdcbd4b3bb8812e6021b494ec63fe253ee56207d81321d4ee4aa36ce.json"
- targetContentHash: "b6068648fdcbd4b3bb8812e6021b494ec63fe253ee56207d81321d4ee4aa36ce"
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
{"slug":"us-core-cpi-mom-november-2026","country":"US","type":"data","title":"US Core CPI MoM, November 2026","question":"What will the first-print November 2026 month-over-month percent change be for BLS CPI-U all items less food and energy, seasonally adjusted, U.S. city average, series CUSR0000SA0L1E?","unit":"percent_growth","pointEstimate":0.26,"ciLow":0.08,"ciHigh":0.44,"confidence":0.8,"resolutionDate":"2026-12-10","resolutionSource":"Official agency release","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0L1E","resolutionRule":"Use the first BLS public print for November 2026 series CUSR0000SA0L1E, Consumer Price Index for All Urban Consumers, U.S. city average, all items less food and energy, seasonally adjusted. Compute percent_growth as 100 * (November 2026 index / October 2026 index - 1) from the first published BLS API values. Do not use later revisions, annual seasonal-adjustment revisions, same-day corrections, or alternate CPI variants.","dataPointId":"bls.cpi.u.core_mom.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":0.376460730477457},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":0.20809544962627768},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":-0.016660666843182348},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":0.2154345141564873},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":0.2897956881014574},{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":0.3348481932704761}],"drivers":["Recent core CPI monthly run rate remains near 0.23 percent","Shelter and core services inflation are still sticky enough to keep the point above the six-month mean","Goods disinflation and month-to-month noise limit the upside","October 2026 CPI was not yet printed at run time, so the forecast leans on April-September official history"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0L1E","https://www.bls.gov/schedule/news_release/cpi.htm?brd=2"],"runAt":"2026-11-10T00:25:58Z","reasoning":[{"kind":"heading","text":"US core CPI-U month-over-month forecast for November 2026"},{"kind":"text","text":"Framing and exact resolver: the target is BLS CPI-U all items less food and energy, U.S. city average, seasonally adjusted, series CUSR0000SA0L1E. The target unit is percent_growth, and the resolver should use the first official BLS API print and the transform percent_change_previous_period for November 2026 over October 2026."},{"kind":"text","text":"Release-date check: the BLS CPI release calendar lists November 2026 CPI for Dec. 10, 2026 at 08:30 Eastern. The evidence fetch tool was blocked by BLS with HTTP 403 for the calendar page in call-0002, so the calendar page bytes were not archived by the evidence tool; the date was verified from the public BLS schedule page outside the capture channel."},{"kind":"tool","tool":"official.lookup","call":"fetch_source https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0L1E","result":"call-0001 archived the BLS API response for CUSR0000SA0L1E: September 2026 index 338.896, August 2026 index 337.765, July 2026 index 336.789, June 2026 index 336.065, May 2026 index 336.121, April 2026 index 335.423, March 2026 index 334.165."},{"kind":"tool","tool":"official.lookup","call":"extract_json and calculate month-over-month percent changes from call-0001 levels","result":"call-0015 April 2026 = 0.376460730477457; call-0014 May 2026 = 0.20809544962627768; call-0016 June 2026 = -0.016660666843182348; call-0018 July 2026 = 0.2154345141564873; call-0017 August 2026 = 0.2897956881014574; call-0019 September 2026 = 0.3348481932704761."},{"kind":"tool","tool":"calculate","call":"mean and sample stdev of the six fetched monthly percent-growth observations","result":"call-0023 mean = 0.23466231813149552; call-0022 sigma = 0.13958684574837305; call-0024 1.28*sigma = 0.1786711625579175."},{"kind":"text","text":"Base rate/reference class: the recent official-source reference class is the six available 2026 monthly changes from April through September for the same seasonally adjusted core CPI-U series. I use the 0.23466231813149552 base rate as the starting point, not the existing local catalog forecast."},{"kind":"math","text":"Prior/update/interval: persistence prior = six-month official BLS API mean for CUSR0000SA0L1E, historical sample = April-September 2026 percent changes [0.376460730477457, 0.20809544962627768, -0.016660666843182348, 0.2154345141564873, 0.2897956881014574, 0.3348481932704761], adjustment components = +0.0253376818685045 for sticky shelter/core services momentum partly offset by goods volatility, interval method = sample dispersion of monthly change values; sigma = 0.13958684574837305, so the 80% half-width is roughly 1.28*sigma = 0.1786711625579175. call-0025 gives point = 0.26; call-0026 gives lower = 0.0813288374420825 and call-0027 gives upper = 0.4386711625579175, rounded to 0.08 and 0.44."},{"kind":"text","text":"Upside risk: a renewed shelter acceleration, medical care services jump, or airfare/auto insurance rebound could put the first print above 0.44 and would land above the interval. Downside risk: another goods-price decline plus softer shelter could put the print below 0.08 and would land outside the interval on the low side."},{"kind":"forecast","point":0.26,"ciLow":0.08,"ciHigh":0.44}]}

# Reviewer critique
{"summary":"Draft is publication-ready aside from a small evidentiary gap around the discretionary upward adjustment from the six-month persistence prior.","requiredFixes":[{"rubricItem":"update","severity":"warning","summary":"The +0.025 adjustment for sticky shelter/core services is asserted but not tied to a cited metric or calculation beyond the April-September core CPI sample.","actionRequested":"Either quantify the adjustment from the cited CPI components/history, add a cited public source supporting the services/shelter momentum claim, or reduce the text to a clearly labeled judgmental nudge."}],"optionalSuggestions":["Since the BLS calendar fetch was blocked, explicitly state that the canonical registered target fixes the 2026-12-10 resolution date, with the BLS schedule page as supporting context.","Consider noting that the interval is based on only six observations, so the 80% range is intentionally approximate."]}

Emit the final JSON object only.
