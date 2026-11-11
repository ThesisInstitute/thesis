# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.real_earnings.avg_hourly_mom
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-real-avg-hourly-earnings-mom-september-2026"
- country: "US"
- targetUnit: "percent"
- dataPointId: "bls.real_earnings.avg_hourly_mom.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-10-15", "start": "2026-10-07"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-15", "start": "2026-10-07"}, "field": "bls.real_earnings.avg_hourly_mom", "releasePolicy": "first_print", "sourceSeriesId": "bls.real_earnings.avg_hourly_mom", "sourceUrl": "https://www.bls.gov/news.release/realer.t01.htm", "table": "U.S. Bureau of Labor Statistics Real Earnings Table A-1", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-1582708c2cc6b8acb7d01ea1b2fdfa1d0ab9ad44f085d9e41317c8017d3fef25.json"
- targetContentHash: "1582708c2cc6b8acb7d01ea1b2fdfa1d0ab9ad44f085d9e41317c8017d3fef25"
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
{"slug":"us-real-avg-hourly-earnings-mom-september-2026","country":"US","type":"data","title":"US real average hourly earnings MoM, September 2026","question":"What will the BLS first print for seasonally adjusted real average hourly earnings of all employees on private nonfarm payrolls, over-the-month percent change, be for September 2026?","unit":"percent","pointEstimate":0,"ciLow":-0.6,"ciHigh":0.6,"confidence":0.8,"resolutionDate":"2026-10-15","resolutionSource":"U.S. Bureau of Labor Statistics Real Earnings Table A-1","resolutionSourceUrl":"https://www.bls.gov/news.release/realer.t01.htm","resolutionRule":"Resolve to the first BLS Real Earnings Table A-1 print for September 2026, row 'Real average hourly earnings' under 'OVER-THE-MONTH PERCENT CHANGE' for all employees on private nonfarm payrolls, seasonally adjusted. Use the value as published in percent, normally to one decimal place, on the registered October 15, 2026 resolution date; ignore later revisions.","dataPointId":"bls.real_earnings.avg_hourly_mom.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":0},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":0.3},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":0.2},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":-0.6},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":-0.5},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":-0.1},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":0.8},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":-0.1}],"drivers":["Recent real hourly earnings changes are centered near zero","September nominal wage growth likely near CPI inflation","August payroll report showed firmer jobs and 0.3 percent wage growth","Energy and CPI volatility dominate one-month real earnings noise","Current BLS calendar shows a one-day discrepancy versus the registered ledger date"],"sourceContext":["https://www.bls.gov/schedule/news_release/realer.htm","https://www.bls.gov/schedule/2026/","https://www.bls.gov/news.release/realer.t01.htm","https://www.bls.gov/news.release/archives/realer_08122026.htm","https://www.bls.gov/news.release/archives/realer_07142026.htm","https://www.bls.gov/news.release/archives/realer_06102026.htm","https://www.bls.gov/news.release/archives/realer_05122026.htm","https://www.bls.gov/news.release/archives/realer_04102026.htm","https://www.bls.gov/news.release/archives/realer_03112026.htm","https://www.bls.gov/news.release/archives/realer_02132026.htm","https://www.bls.gov/news.release/archives/realer_01132026.htm","https://www.bls.gov/news.release/archives/empsit_09042026.htm"],"runAt":"2026-09-04T19:15:18Z","reasoning":[{"kind":"heading","text":"Forecast for BLS real average hourly earnings MoM, September 2026"},{"kind":"text","text":"Framing and exact resolver: this targets BLS Real Earnings Table A-1, all employees on private nonfarm payrolls, seasonally adjusted, row 'Real average hourly earnings' under over-the-month percent change for September 2026. The target is the first-print release-table value, not a later revised CES/CPI database reconstruction."},{"kind":"text","text":"Variant discipline: all historical anchors are the same all-employees, private nonfarm payrolls, seasonally adjusted real average hourly earnings MoM variant deflated by CPI-U in BLS Real Earnings Table A-1."},{"kind":"tool","tool":"official.lookup","call":"Checked BLS Real Earnings release schedule and current-year calendar for the September 2026 reference month.","result":"BLS schedule lists Real Earnings for September 2026 on Oct. 14, 2026 at 08:30 AM, and the BLS 2026 calendar lists Wednesday, October 14, 2026 08:30 AM Real Earnings for September 2026. The registered ledger contract supplied for this run sets resolutionDate to 2026-10-15, so I keep 2026-10-15 and flag the one-day discrepancy."},{"kind":"tool","tool":"official.lookup","call":"Fetched current BLS Real Earnings Table A-1, July 2026 release.","result":"Latest Table A-1 showed all-employees real average hourly earnings of $11.30 in July 2026, over-the-month real average hourly earnings -0.1 percent, CPI-U +0.1 percent, average hourly earnings +0.1 percent, and average weekly hours 0.0 percent."},{"kind":"tool","tool":"official.lookup","call":"Fetched BLS archived Real Earnings releases for the recent first-print reference class.","result":"Archived first-print all-employees real average hourly earnings MoM values were December 2025 0.0, January 2026 0.3, February 2026 0.2, March 2026 -0.6, April 2026 -0.5, May 2026 -0.1, June 2026 0.8, and July 2026 -0.1 percent."},{"kind":"tool","tool":"official.lookup","call":"Fetched BLS Employment Situation for August 2026 for the latest nominal wage setup before September.","result":"The August 2026 Employment Situation reported total nonfarm payroll employment +162,000, unemployment rate 4.1 percent, average hourly earnings for all employees on private nonfarm payrolls +10 cents or +0.3 percent to $37.75, and average weekly hours +0.1 hour to 34.4."},{"kind":"text","text":"Base rate/reference class: the recent official first-print real hourly earnings MoM sample is centered at zero: [0.0, 0.3, 0.2, -0.6, -0.5, -0.1, 0.8, -0.1] has mean approximately 0.00 percent and median -0.10 percent. This is already a change series, so the sample values themselves are the dispersion input."},{"kind":"math","text":"Prior/update/interval: persistence/reference-class prior is the recent BLS first-print sample from December 2025 through July 2026 with mean = 0.00 and median = -0.10. Adjustment components: level is near zero after July -0.1; momentum is modestly positive because August nominal AHE rose 0.3 percent to $37.75; one-off CPI risk is still two-sided because September CPI could absorb most wage growth; policy-mechanism effect is none because this is a data print. I assume September nominal AHE about +0.3 percent and September CPI-U about +0.3 percent, giving real hourly earnings about 0.3 - 0.3 = 0.0 percent. Sample standard deviation gives sigma = 0.45 percentage points, so the 80 percent half-width is about 1.28*sigma = 1.28*0.45 = 0.58 percentage points; centered on 0.0, rounded bounds are -0.6 to 0.6."},{"kind":"text","text":"Upside risk is a soft September CPI print or another strong nominal wage month, which would land above the interval if real average hourly earnings rose more than 0.6 percent. Downside risk is a gasoline or shelter-driven CPI surprise or weak mix-adjusted wages, which would land below the interval if the first-print real change is less than -0.6 percent. Outside the interval would likely require an inflation or composition shock larger than ordinary recent monthly noise."},{"kind":"forecast","point":0,"ciLow":-0.6,"ciHigh":0.6}]}

# Reviewer critique
{"summary":"The draft is publishable: it matches the ledger target, states a defensible zero-centered prior, uses current public evidence without leakage, and derives the interval from recent realized volatility.","requiredFixes":[],"optionalSuggestions":["Clarify that 2026-10-15 is the ledger resolutionDate while the cited BLS schedule appears to list the release on 2026-10-14, so readers do not confuse the administrative target date with the expected publication timestamp.","Consider saying explicitly that no richer time-series model was used because the recent first-print sample is short and dominated by one-month CPI/wage noise."]}

Emit the final JSON object only.
