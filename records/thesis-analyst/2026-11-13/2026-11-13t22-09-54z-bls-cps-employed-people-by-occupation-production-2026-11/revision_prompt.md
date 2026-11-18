# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.employed_people_by_occupation.production
- period: 2026-11
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-production-employment-november-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.production.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-04", "start": "2026-12-04"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-04", "start": "2026-12-04"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "LNU02032213", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032213", "table": "Current Population Survey, employed people, Production occupations, total 16 years and over, not seasonally adjusted, in thousands (Employment Situation, Table A-19)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-11-13-27dc574fa31145e815c71df2e66a54f9d3551f032d0f3c370b2358e1a3f7a75a.json"
- targetContentHash: "27dc574fa31145e815c71df2e66a54f9d3551f032d0f3c370b2358e1a3f7a75a"
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
{"slug":"cps-production-employment-november-2026","country":"US","type":"data","title":"US CPS production employment, Nov 2026","question":"What will the BLS Current Population Survey first print report for LNU02032213, employed people in production occupations, total 16 years and over, not seasonally adjusted, for November 2026?","unit":"millions","pointEstimate":7.998,"ciLow":7.601,"ciHigh":8.395,"confidence":0.8,"resolutionDate":"2026-12-04","resolutionSource":"U.S. Bureau of Labor Statistics public API, Current Population Survey series LNU02032213","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032213","resolutionRule":"Resolve to the first value BLS reports for CPS series LNU02032213, period 2026 M11, Current Population Survey employed people in Production occupations, total 16 years and over, not seasonally adjusted, Table A-19. The BLS API value is in thousands; multiply by 0.001 and report in millions. Use the first official print from the scheduled Employment Situation release on 2026-12-04 and do not incorporate later revisions or same-day corrections unless they replace the first public value before capture.","dataPointId":"bls.cps.employed_people_by_occupation.production.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":7.883},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":7.912},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":7.759},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":8.121},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":7.716},{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":7.775},{"period":{"type":"month","value":"2026-10"},"label":"October 2026","value":8.192}],"drivers":["CPS production-occupation employment is a noisy not-seasonally-adjusted level series","October 2026 was elevated relative to the April-October mean","Recent prints imply substantial month-to-month dispersion","November seasonal anchor is close to the recent mean"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032213?startyear=2025&endyear=2026","https://www.bls.gov/schedule/2026/12_sched_list.htm"],"runAt":"2026-11-13T22:10:05Z","reasoning":[{"kind":"heading","text":"Forecast for CPS production-occupation employment, November 2026"},{"kind":"text","text":"Framing and exact resolver: target is BLS CPS series LNU02032213, Table A-19, not seasonally adjusted, in thousands at source and converted to millions. The registered first-print target is November 2026, dataPointId bls.cps.employed_people_by_occupation.production.2026_11.first_print."},{"kind":"text","text":"Release-date check: the official BLS schedule page for December 2026 lists Employment Situation for November 2026 on Friday, December 4, 2026 at 8:30 AM Eastern. The MCP fetch_source call to the BLS schedule page was blocked with HTTP 403, so that schedule evidence was verified this run from the public BLS web index but not captured as a receipt."},{"kind":"tool","tool":"official.lookup","call":"fetch_source https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032213?startyear=2025&endyear=2026","result":"call-0002 captured BLS API response sha256 41afb08cdf98783bcdfbf3f9506249c62ea20c6e5ffc47297374fec0a2a6390a with fetched source values in thousands including 2026 M10 8192, 2026 M09 7775, 2026 M08 7716, 2026 M07 8121, 2026 M06 7759, 2026 M05 7912, 2026 M04 7883, and 2025 M11 7967."},{"kind":"tool","tool":"evidence.calculate","call":"calculate mean(history_millions) from 2026 April-October fetched BLS values converted by multiplying by 0.001","result":"call-0007 used fetched values 7.883, 7.912, 7.759, 8.121, 7.716, 7.775, 8.192 and returned base rate mean 7.908285714285714 million."},{"kind":"tool","tool":"evidence.calculate","call":"calculate stdev(diff(history_millions)) from the same fetched monthly level series","result":"call-0008 used fetched values 7.883, 7.912, 7.759, 8.121, 7.716, 7.775, 8.192 and returned sigma = 0.310088858232604 million for successive monthly changes."},{"kind":"tool","tool":"evidence.calculate","call":"calculate 1.28*sigma, then point and bounds with judgment adjustments","result":"call-0009 returned 80% half-width 0.39691373853773315; call-0010 returned point 7.998285714285714 from base 7.908285714285714 plus 0.07 October momentum adjustment plus 0.02 November seasonal-anchor adjustment; call-0011 returned low 7.601371975747981 and call-0012 returned high 8.395199452823448."},{"kind":"text","text":"The reference class is recent official BLS API prints for the identical NSA CPS variant, not a seasonally adjusted or payroll-employment proxy. The base rate is the April-October 2026 mean of 7.908 million, with 2025 November at 7.967 million as a same-month cross-check rather than a separate source of truth."},{"kind":"math","text":"Prior/update/interval: persistence/base-rate prior is the 2026 April-October same-series official-history mean of 7.908 million; adjustment components are +0.070 million for October's elevated 8.192 million print carrying some momentum into November but with regression, and +0.020 million because the latest observed November anchor, 2025 November at 7.967 million, is slightly above the recent mean. For the interval, using successive changes in the fetched level series gives sigma = 0.310088858232604, so 1.28*sigma = 0.39691373853773315; point 7.998285714285714 minus/plus that half-width gives 7.601371975747981 to 8.395199452823448, rounded to 7.601 to 8.395."},{"kind":"text","text":"Counter-considerations: upside risk is a continuation of October's unusually high production-occupation employment or a strong goods-sector hiring month, which would land above the interval if the first print exceeds 8.395 million. Downside risk is reversal of October's jump, sampling noise, or weakness in manufacturing and production jobs, which would land below the interval if the first print is under 7.601 million. A normal regression from October toward the 2026 mean remains inside the interval."},{"kind":"forecast","point":7.998,"ciLow":7.601,"ciHigh":8.395}]}

# Reviewer critique
{"summary":"The draft is publishable with no blocking issues; it matches the target contract and gives a coherent prior, update, and volatility-based interval, but the model-prior language could be made more explicit.","requiredFixes":[{"rubricItem":"model_prior","severity":"warning","summary":"The forecast uses a recent same-series mean/persistence prior, but does not explicitly say whether a formal time-series model was used or ruled out.","actionRequested":"Add one sentence stating that no separate ARIMA/ETS/regression model was used, and that the April-October same-series mean plus persistence/momentum adjustment is the chosen time-series prior."}],"optionalSuggestions":["Note that the November seasonal adjustment rests on only the 2025 November same-month anchor, so it is a weak adjustment.","Tighten the first-print wording by saying later revisions are excluded even if they appear after the first captured official value."]}

Emit the final JSON object only.
