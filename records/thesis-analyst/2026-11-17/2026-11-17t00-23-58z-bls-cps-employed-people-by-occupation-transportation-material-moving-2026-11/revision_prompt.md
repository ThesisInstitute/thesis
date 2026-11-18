# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.employed_people_by_occupation.transportation_material_moving
- period: 2026-11
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-transport-material-moving-employment-november-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.transportation_material_moving.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-04", "start": "2026-12-04"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-04", "start": "2026-12-04"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "LNU02032214", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032214", "table": "Current Population Survey, employed people, Transportation and material moving occupations, total 16 years and over, not seasonally adjusted, in thousands (Employment Situation, Table A-19)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-11-17-239c2e6beadd5de01b638fd4d98f233416b53c195c18fd4b630d298399980bd5.json"
- targetContentHash: "239c2e6beadd5de01b638fd4d98f233416b53c195c18fd4b630d298399980bd5"
- registrationCommit: "fe467bb10a37b726dd31de03db0184d1f5273f46"
- registeredAtUtc: "2026-11-17T00:21:28Z"

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
{"slug":"cps-transport-material-moving-employment-november-2026","country":"US","type":"data","title":"US transportation/material moving employment, Nov 2026","question":"What will BLS first report for Current Population Survey employed people in transportation and material moving occupations, total 16 years and over, not seasonally adjusted, series LNU02032214, November 2026?","unit":"millions","pointEstimate":12.18,"ciLow":11.91,"ciHigh":12.45,"confidence":0.8,"resolutionDate":"2026-12-04","resolutionSource":"Bureau of Labor Statistics Employment Situation release / public API","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032214","resolutionRule":"Resolve to the first BLS public API value for CPS series LNU02032214, period 2026 M11, as published with the Employment Situation for November 2026. The source value is in thousands and is multiplied by 0.001 to the registered unit, millions. Use the first official print only; ignore later revisions, corrections, or benchmark updates unless the first print itself is replaced before publication is complete.","dataPointId":"bls.cps.employed_people_by_occupation.transportation_material_moving.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":12.127},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":12.12},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":12.01},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":12.223},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":12.011},{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":12.318},{"period":{"type":"month","value":"2026-10"},"label":"October 2026","value":12.256}],"drivers":["October 2026 latest level is high at 12.256 million","Historical October-to-November seasonal move averages -0.085 million","Recent six-month average is 12.156 million","NSA CPS occupation series is noisy month to month","2025 October is unavailable, so the direct 2025 October-to-November seasonal pair is skipped"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032214?startyear=2025&endyear=2026","https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032214?startyear=2016&endyear=2026","https://blsmon1.bls.gov/schedule/2026/12_sched_list.htm","https://blsmon1.bls.gov/schedule/news_release/bls.ics"],"runAt":"2026-11-17T00:24:08Z","reasoning":[{"kind":"heading","text":"CPS transportation and material moving employment, November 2026 first print"},{"kind":"text","text":"The target is BLS CPS series LNU02032214, Current Population Survey employed people in transportation and material moving occupations, total 16 years and over, not seasonally adjusted, Table A-19. The API reports thousands; the registered unit is millions, so all history and the forecast apply the 0.001 transform."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0001: BLS public API LNU02032214, startyear=2025, endyear=2026","result":"Fetched recent official values in thousands including 2026-10 = 12256, 2026-09 = 12318, 2026-08 = 12011, 2026-07 = 12223, 2026-06 = 12010, 2026-05 = 12120, and 2026-04 = 12127; transformed values are 12.256, 12.318, 12.011, 12.223, 12.010, 12.120, and 12.127 million."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0007 and extract_json call-0008: BLS public API LNU02032214 historical monthly data","result":"Fetched same-series official history in thousands. Usable October-to-November changes in millions were 2016: 9.443-9.614 = -0.171, 2017: 9.245-9.554 = -0.309, 2018: 9.837-10.112 = -0.275, 2019: 10.093-10.083 = 0.010, 2020: 10.837-10.809 = 0.028, 2021: 11.785-11.733 = 0.052, 2022: 11.771-11.944 = -0.173, 2023: 12.007-11.668 = 0.339, and 2024: 11.844-12.113 = -0.269; 2025 October was unavailable."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0009 and call-0012: BLS December 2026 release schedule page and BLS iCalendar","result":"Fetched BLS release-calendar material for the Employment Situation schedule; the November 2026 Employment Situation release is scheduled for 2026-12-04 at 08:30 Eastern, matching the registered resolution date 2026-12-04."},{"kind":"text","text":"The reference class is same-series October-to-November movements because the target is NSA and the latest observed month is October 2026. The base rate from 2016-2024, skipping the unavailable 2025 pair, is an average October-to-November change of -0.085 million."},{"kind":"tool","tool":"calculate","call":"calculate call-0014, call-0015, call-0016, call-0017, call-0020, call-0019, call-0021","result":"Calculated mean October-to-November change = -0.0853333333 million; October 2026 plus that seasonal delta = 12.1706666667 million; last-six-month mean = 12.1563333333 million; sigma = 0.2108346509 million; 1.28*sigma = 0.2698683531 million; 12.18 +/- 0.2698683531 gives 11.9101316469 to 12.4498683531 million."},{"kind":"math","text":"Prior/update/interval: Persistence prior is latest official level, 12.256 million for October 2026. Historical sample is same-series October-to-November changes from 2016-2024, excluding 2025 because BLS marks October 2025 unavailable. Seasonal base-rate adjustment is -0.085 million, giving 12.171 million. Current-release adjustment is a small +0.009 million judgment because recent six-month level is 12.156 million while September-October remains elevated at 12.318 and 12.256 million, so point rounds to 12.18 million. Interval method uses realized dispersion of same-month seasonal changes: sigma = 0.2108 million, and the 80% half-width is roughly 1.28*sigma = 0.270 million, giving 11.91 to 12.45 million after rounding."},{"kind":"text","text":"Upside risk is a hiring or classification rebound like 2023, where November ran 0.339 million above October; repeating that from 12.256 million would land above the interval near 12.595 million. Downside risk is a seasonal pullback like 2017 or 2024, where November fell about 0.27-0.31 million from October; a larger labor-demand softening or survey-noise drop would land below the interval. Outside the interval would therefore require either a strong November occupation gain above roughly +0.19 million from October or a drop worse than roughly -0.35 million from October."},{"kind":"forecast","point":12.18,"ciLow":11.91,"ciHigh":12.45}]}

# Reviewer critique
{"summary":"The draft is publishable: resolver contract, first-print source, unit transform, prior/update/interval logic, tails, and JSON fields are coherent with the registered target.","requiredFixes":[],"optionalSuggestions":["Tighten the resolutionRule wording by dropping the ambiguous caveat about replacement before publication is complete, or explicitly define it as the first official BLS API value captured for 2026 M11 at release time.","Mention the small sample size for the October-to-November volatility estimate, since the 80% interval rests on nine usable seasonal changes."]}

Emit the final JSON object only.
