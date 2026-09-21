# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.unemployment_rate
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "unemployment-rate-september-2026"
- country: "US"
- targetUnit: "percent"
- dataPointId: "bls.cps.unemployment_rate.september_2026.first_print"
- publishedResolutionDate: "2026-10-02"
- expectedReleaseWindow: {"end": "2026-10-08", "start": "2026-09-30"}
- resolutionSource: "U.S. Bureau of Labor Statistics Employment Situation"
- resolutionSourceUrl: "https://www.bls.gov/news.release/empsit.nr0.htm"
- resolutionRule: "Resolve to the first-print seasonally adjusted unemployment rate for total civilian labor force, 16 years and over, in BLS Employment Situation household survey table A-1 for September 2026, as initially published on October 2, 2026. Use the value rounded to one decimal percent as printed by BLS; do not use later revisions, annual seasonal-factor revisions, corrected subsequent database vintages, or same-day corrections unless BLS replaces the initial release before public availability."
- resolutionPolicy: "first_print"
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-08", "start": "2026-09-30"}, "field": "bls.cps.unemployment_rate", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.unemployment_rate", "sourceUrl": "https://www.bls.gov/news.release/empsit.nr0.htm", "table": "U.S. Bureau of Labor Statistics Employment Situation (Current Population Survey)", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-4f9351e9599bb007177abdf8c158ee801328243b30407e6ff10d9b25084c2d8a.json"
- targetContentHash: "4f9351e9599bb007177abdf8c158ee801328243b30407e6ff10d9b25084c2d8a"
- registrationCommit: "baad7107ac843adbbb7a8038e4138d5e24100521"
- registeredAtUtc: "2026-09-04T19:02:52Z"

# Comparison target contract (machine checked)
This run is a strategy comparison against an already published forecast. The sealed cell's resolutionDate, resolutionSource, resolutionSourceUrl and resolutionRule are pinned to that forecast's published resolver; publishedResolutionDate "2026-10-02" is its resolver date. Still verify the official release schedule this run and state any discrepancy in reasoning rather than changing the target.

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
{"slug":"unemployment-rate-september-2026","country":"US","type":"data","title":"US unemployment rate, September 2026","question":"What will the first-print seasonally adjusted unemployment rate for the total civilian labor force, 16 years and over, be in the BLS Employment Situation household survey table A-1 for September 2026?","unit":"percent","pointEstimate":4.1,"ciLow":4,"ciHigh":4.2,"confidence":0.8,"resolutionDate":"2026-10-02","resolutionSource":"U.S. Bureau of Labor Statistics Employment Situation","resolutionSourceUrl":"https://www.bls.gov/news.release/empsit.nr0.htm","resolutionRule":"Resolve to the first-print seasonally adjusted unemployment rate for total civilian labor force, 16 years and over, in BLS Employment Situation household survey table A-1 for September 2026, as initially published on October 2, 2026. Use the value rounded to one decimal percent as printed by BLS; do not use later revisions, annual seasonal-factor revisions, corrected subsequent database vintages, or same-day corrections unless BLS replaces the initial release before public availability.","dataPointId":"bls.cps.unemployment_rate.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":4.3},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":4.3},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":4.3},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":4.2},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":4.1},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":4.1}],"drivers":["Recent CPS unemployment rate has drifted down from 4.3 to 4.1 percent","Persistence is the strongest monthly prior for the unemployment rate","Payroll employment still increased through August, reducing near-term upside pressure","Household-survey sampling noise and labor-force participation moves can shift the rounded one-decimal print"],"sourceContext":["https://api.bls.gov/publicAPI/v2/timeseries/data/LNS14000000?startyear=2025&endyear=2026","https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001?startyear=2026&endyear=2026","https://www.bls.gov/schedule/news_release/empsit.htm","https://www.bls.gov/schedule/2026/10_sched_list.htm","https://www.bls.gov/news.release/empsit.nr0.htm"],"runAt":"2026-09-21T14:35:00Z","thresholdLadder":{"thresholds":[3.9,3.95,4,4.05,4.1,4.15,4.2,4.24,4.3,4.4,4.5],"cumulativeProbabilities":[0.05,0.1,0.18,0.32,0.5,0.68,0.82,0.9,0.95,0.98,0.99]},"reasoning":[{"kind":"heading","text":"Forecast for September 2026 BLS CPS unemployment rate"},{"kind":"text","text":"Resolver: use BLS Employment Situation household survey table A-1, seasonally adjusted unemployment rate for the total civilian labor force, 16 years and over, series LNS14000000, first print for September 2026, rounded to one decimal percent. The BLS schedule observed this run lists Employment Situation for September 2026 on October 2, 2026 at 8:30 a.m. ET; fetch_source calls to BLS schedule pages returned 403 in the evidence channel, so the schedule verification is from public BLS search excerpts rather than a captured response receipt."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0001 to BLS public API series LNS14000000 for 2025-2026","result":"Fetched official CPS unemployment-rate values included 2026-08 4.1, 2026-07 4.1, 2026-06 4.2, 2026-05 4.3, 2026-04 4.3, 2026-03 4.3, plus 2025-12 4.4 and 2025-11 4.5; October 2025 was unavailable due to the 2025 lapse in appropriations."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0011 to BLS public API series CES0000000001 for total nonfarm payroll employment","result":"Fetched payroll levels were 159075 thousand in 2026-08, 158913 thousand in 2026-07, 158892 thousand in 2026-06, 158861 thousand in 2026-05, 158798 thousand in 2026-04, and 158650 thousand in 2026-03."},{"kind":"text","text":"Base rate and reference class: for a monthly level rate like unemployment, the outside view is high persistence around the latest print. The six most recent official CPS unemployment observations were 4.3, 4.3, 4.3, 4.2, 4.1, and 4.1 percent from March through August 2026, all using the same seasonally adjusted CPS variant as the target."},{"kind":"tool","tool":"calculator","call":"calculate call-0006 stdev(diff(history)) using [4.3,4.3,4.3,4.2,4.1,4.1]","result":"Successive monthly changes were 0.0, 0.0, -0.1, -0.1, and 0.0 percentage point; sample sigma = 0.05477225575051666."},{"kind":"tool","tool":"calculator","call":"calculate call-0007 1.28*sigma from call-0006 and call-0008 mean(history)","result":"The recent-history 80 percent normal half-width proxy was 1.28*sigma = 0.07010848736066133, and the six-month mean level was 4.216666666666667."},{"kind":"math","text":"Ladder: P(X <= 3.9) = 0.05; P(X <= 3.95) = 0.10; P(X <= 4.0) = 0.18; P(X <= 4.05) = 0.32; P(X <= 4.1) = 0.50; P(X <= 4.15) = 0.68; P(X <= 4.2) = 0.82; P(X <= 4.24) = 0.90; P(X <= 4.3) = 0.95; P(X <= 4.4) = 0.98; P(X <= 4.5) = 0.99. Linear interpolation gives q10 = 3.95, median = 4.10, q90 = 4.24, which round to 4.0, 4.1, and 4.2 percent at the BLS print precision."},{"kind":"math","text":"Prior/update/interval: persistence prior starts at the August 2026 unemployment rate of 4.1 percent; historical sample is the March-August 2026 official CPS LNS14000000 sequence. Level effect is anchored at 4.1 after the recent 4.3 to 4.1 drift, momentum effect is modestly downward but fading because July and August were both 4.1, one-off household-survey noise is symmetric, and the payroll-policy mechanism is not signaling a sharp September break. From call-0006, sigma = 0.05477225575051666 for recent successive changes, so 1.28*sigma = 0.07010848736066133. The ladder-implied 80 percent width is 4.24 - 3.95 = 0.29, a half-width of 0.145, about 2.07 times the simple 1.28*sigma full-width comparison from call-0013; I widen because the target is a rounded first print still unreleased, household-survey sampling noise can dominate the last-six-change dispersion, and a single labor-force participation swing can move the unemployment rate by a tenth."},{"kind":"text","text":"Counter-considerations: upside risk is a September labor-force increase with weak household employment that pushes the rounded print to 4.3 or higher; downside risk is a rebound in household employment or lower participation that keeps the print at 4.0 or below. A recessionary household-employment break would land above the interval, while a large participation drop with steady employment would land below the interval."},{"kind":"forecast","point":4.1,"ciLow":4,"ciHigh":4.2}]}

# Reviewer critique
{"summary":"Draft is publishable with no blocking issues; resolver/date/unit match the target and the forecast has a clear persistence prior, update, interval method, tails, and coherent JSON fields.","requiredFixes":[{"rubricItem":"prior_update_interval","severity":"warning","summary":"The interval explanation says 1.28*sigma is a full-width comparison and references call-0013, which is not present in the draft trace.","actionRequested":"Correct the wording to distinguish half-width from full 80% width, and remove or fix the dangling call reference."}],"optionalSuggestions":["Replace the schedule-verification caveat about 403/search excerpts with a successful official BLS schedule receipt if the runner can capture one.","Clarify that the 80% interval fields are rounded printed-value bounds derived from latent q10/q90 values of 3.95 and 4.24."]}

Emit the final JSON object only.
