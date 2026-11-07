# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.ces.nonfarm_payrolls.change
- period: 2026-11
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "nonfarm-payrolls-november-2026"
- country: "US"
- targetUnit: "thousands"
- dataPointId: "bls.ces.nonfarm_payrolls.change.2026_11.first_print"
- expectedReleaseWindow: {"end": "2026-12-04", "start": "2026-12-04"}
- sourceBinding: {"adapter": "bls-api", "allowedHosts": ["api.bls.gov"], "expectedReleaseWindow": {"end": "2026-12-04", "start": "2026-12-04"}, "field": "value", "releasePolicy": "first_print", "sourceSeriesId": "CES0000000001", "sourceUrl": "https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001", "table": "Current Employment Statistics, all employees, total nonfarm, seasonally adjusted (Employment Situation, Table B-1)", "transform": {"factor": 1, "operation": "difference_previous_period"}}
- targetRegistrationPath: "records/targets/2026-11-02-93d4fe16db30befd6cde1b23e3f396ab250a322bdd44b281003f42efb2977eea.json"
- targetContentHash: "93d4fe16db30befd6cde1b23e3f396ab250a322bdd44b281003f42efb2977eea"
- registrationCommit: "ac152d6cd8dbb730a1f6d9e9cddf26b98c4aec30"
- registeredAtUtc: "2026-11-02T23:38:32Z"

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
{"slug":"nonfarm-payrolls-november-2026","country":"US","type":"data","title":"US nonfarm payrolls, November 2026","question":"What will the first-print month-over-month change in BLS CES total nonfarm payroll employment, seasonally adjusted, CES0000000001, be for November 2026?","unit":"thousands","pointEstimate":83,"ciLow":-49,"ciHigh":215,"confidence":0.8,"resolutionDate":"2026-12-04","resolutionSource":"U.S. Bureau of Labor Statistics, Employment Situation, Current Employment Statistics Table B-1 / public API series CES0000000001","resolutionSourceUrl":"https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001","resolutionRule":"Resolve to the first official BLS print for November 2026 total nonfarm payroll employment, seasonally adjusted, CES0000000001, in thousands, as the November 2026 level minus the October 2026 level. Use the initial release-policy value available with the Employment Situation released on 2026-12-04; do not incorporate later revisions, benchmark updates, or same-day corrections unless BLS replaces the first official print before the resolver captures it.","dataPointId":"bls.ces.nonfarm_payrolls.change.2026_11.first_print","historicalContext":[{"period":{"type":"month","value":"2026-09"},"label":"September 2026","value":29},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":133},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":-10},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":31},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":63},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":148},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":214},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":-156}],"drivers":["Recent CES payroll growth is positive but uneven, with latest derived changes of 29, 133, -10, 31, 63, and 148 thousand.","The October and November prints are not yet known, so the forecast uses a current-release reference class rather than realized target-period data.","A modest positive update reflects continued expansion from the 2026 year-to-date mean, partly offset by cooling and high month-to-month noise."],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001?startyear=2025&endyear=2026","https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001?startyear=2026&endyear=2026","https://www.bls.gov/schedule/news_release/empsit.htm"],"runAt":"2026-11-02T23:41:03Z","reasoning":[{"kind":"heading","text":"November 2026 first-print nonfarm payroll forecast"},{"kind":"text","text":"The target is the first-print November 2026 month-over-month change in BLS CES total nonfarm payroll employment, seasonally adjusted, series CES0000000001, Table B-1, in thousands. The resolver should compute the difference from the first official November and October levels and ignore later revisions."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0001 to BLS public API CES0000000001 for 2025-2026","result":"Fetched official CES levels including 2026-09 = 159044, 2026-08 = 159015, 2026-07 = 158882, 2026-06 = 158892, 2026-05 = 158861, 2026-04 = 158798, 2026-03 = 158650, 2026-02 = 158436, 2026-01 = 158592, 2025-12 = 158432, 2025-11 = 158449, 2025-10 = 158408."},{"kind":"tool","tool":"official.lookup","call":"extract_json calls call-0006 through call-0017 from call-0001","result":"Extracted numeric levels: call-0006 159044, call-0007 159015, call-0009 158882, call-0008 158892, call-0010 158861, call-0011 158798, call-0012 158650, call-0013 158436, call-0016 158592, call-0015 158432, call-0014 158449, call-0017 158408."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0027 to BLS public API CES0000000001 for 2026 only","result":"Confirmed 2026 official levels in the second BLS API receipt: September 159044, August 159015, July 158882, June 158892, May 158861, April 158798, March 158650, February 158436, January 158592."},{"kind":"text","text":"Release-date check: direct evidence-tool reads of the BLS Employment Situation schedule URL returned HTTP 403 in call-0002, call-0003, and call-0004, so those attempts did not preserve official bytes. I used the sealed public repository anchor-verification record, which states the BLS Employment Situation schedule page was read from https://www.bls.gov/schedule/news_release/empsit.htm and mapped 2026-11 to 2026-12-04 at 08:30 ET; this matches the registered target window."},{"kind":"tool","tool":"official.calculate","call":"calculate call-0022 over derived BLS level differences [29,133,-10,31,63,148,214,-156,160,-17,41]","result":"The reference class mean from the fetched official CES levels is 57.81818181818182 thousand."},{"kind":"tool","tool":"official.calculate","call":"calculate calls call-0024 and call-0023 over the same derived changes","result":"The sample standard deviation is sigma = 103.14729097927699 thousand, and 1.28*sigma = 132.02853245347455 thousand."},{"kind":"math","text":"Prior/update/interval: base rate/reference class is the recent official CES0000000001 month-to-month change series derived from fetched BLS levels: 29, 133, -10, 31, 63, 148, 214, -156, 160, -17, 41 thousand, with mean 57.8. I use that as the persistence/current-release prior, add +25 thousand for level/momentum judgment because payroll growth remained mostly positive despite cooling and because two more pre-target months can normalize some recent weakness, giving point = round(57.8 + 25) = 83. For the 80% interval, sigma = 103.14729097927699 from realized changes, so half-width is roughly 1.28*sigma = 132.02853245347455; 83 - 132.0 = -49.0 and 83 + 132.0 = 215.0, rounded to [-49, 215]."},{"kind":"text","text":"Upside risk: a rebound in private services hiring, education/health care, or catch-up after weak October data would land above the interval if November payrolls exceed about 215 thousand. Downside risk: a sharp slowdown, strike effects, federal-sector drag, or a weak October base feeding into November would land below the interval if the first print is below -49 thousand. An outside the interval miss is plausible because first payroll prints are noisy and the forecast is made before the October payroll print."},{"kind":"forecast","point":83,"ciLow":-49,"ciHigh":215}]}

# Reviewer critique
{"summary":"Draft is publishable: it matches the registered BLS first-print CES resolver, states a recent-CES base-rate prior, gives a transparent update and volatility-based 80% interval, and has coherent JSON fields.","requiredFixes":[],"optionalSuggestions":["Consider splitting the +25 thousand adjustment into named numeric components if you want the update to be more auditable.","Mention explicitly that no formal time-series model beyond recent-change persistence was used."]}

Emit the final JSON object only.
