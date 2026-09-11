# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.employed_people_by_occupation.office_administrative_support
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-office-admin-employment-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.office_administrative_support.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-10-15", "start": "2026-10-07"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-15", "start": "2026-10-07"}, "field": "Office and administrative support occupations", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.employed_people_by_occupation.office_administrative_support", "sourceUrl": "https://www.bls.gov/web/empsit/cpseea19.htm", "table": "CPS Employment Situation Table A-19, employed persons by occupation, not seasonally adjusted (thousands)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-10f4f7438b667b1f32e0e88a703dd95f27dbe44a6f2754ec09627e470eca77b3.json"
- targetContentHash: "10f4f7438b667b1f32e0e88a703dd95f27dbe44a6f2754ec09627e470eca77b3"
- registrationCommit: "f527f4e54f1df0156366f87eeb5dd630eeb66fe4"
- registeredAtUtc: "2026-09-11T19:13:41Z"

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
{"slug":"cps-office-admin-employment-september-2026","country":"US","type":"data","title":"CPS office admin employment, September 2026","question":"What will BLS first publish for September 2026 in CPS Employment Situation Table A-19, row 'Office and administrative support occupations,' Total, 16 years and over, not seasonally adjusted, reported in thousands and converted to millions?","unit":"millions","pointEstimate":16.22,"ciLow":15.87,"ciHigh":16.57,"confidence":0.8,"resolutionDate":"2026-10-15","resolutionSource":"BLS CPS Employment Situation Table A-19","resolutionSourceUrl":"https://www.bls.gov/web/empsit/cpseea19.htm","resolutionRule":"Resolve from https://www.bls.gov/web/empsit/cpseea19.htm to the first value published by BLS for September 2026 in CPS Employment Situation Table A-19, row 'Office and administrative support occupations,' Total, 16 years and over, not seasonally adjusted, reported in thousands and multiplied by 0.001 to millions. Use the first official print only, with no later revisions or later correction exceptions. The BLS Employment Situation calendar fetched this run lists September 2026 for release on October 2, 2026 at 08:30 AM; the registered Thesis target contract sets resolutionDate to 2026-10-15, so this cell preserves the registered date and records the discrepancy.","dataPointId":"bls.cps.employed_people_by_occupation.office_administrative_support.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":16.563},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":16.471},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":16.335},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":16.184},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":16.457},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":16.154},{"period":{"type":"month","value":"2025-09"},"label":"September 2025","value":16.608}],"drivers":["latest August 2026 BLS table value was low at 16.154 million","recent 2026 values sit mostly between 16.18 and 16.56 million","August-to-September seasonal evidence is mixed but slightly positive in recent prints","office administrative support has a mild year-over-year downtrend","CPS occupation rows are noisy at monthly frequency"],"sourceContext":["https://www.bls.gov/web/empsit/cpseea19.htm","https://www.bls.gov/schedule/news_release/empsit.htm","https://data.bls.gov/timeseries/LNU02032207","https://fred.stlouisfed.org/series/LNU02032207","https://fred.stlouisfed.org/data/LNU02032207"],"runAt":"2026-09-11T19:35:27Z","reasoning":[{"kind":"heading","text":"September 2026 CPS office administrative support employment"},{"kind":"text","text":"Framing and exact resolver: this targets BLS CPS Employment Situation Table A-19, row 'Office and administrative support occupations,' Total, 16 years and over, not seasonally adjusted, in thousands converted to millions. The BLS/FRED source code for the same not seasonally adjusted employment-level series is LNU02032207; resolution remains the BLS Table A-19 first print."},{"kind":"tool","tool":"official.lookup","call":"Opened the BLS Employment Situation release calendar page for the September 2026 reference month.","result":"Fetched schedule row: September 2026 release date Oct. 02, 2026 and release time 08:30 AM. The registered target contract instead sets resolutionDate to 2026-10-15, a ledger-date discrepancy preserved in this cell."},{"kind":"tool","tool":"official.lookup","call":"Opened BLS CPS Employment Situation Table A-19 at https://www.bls.gov/web/empsit/cpseea19.htm and read the current row for Office and administrative support occupations.","result":"Fetched BLS Table A-19 row: Aug. 2025 Total 16 years and over = 16,415 thousand and Aug. 2026 Total 16 years and over = 16,154 thousand; converted values are 16.415 million and 16.154 million. Last Modified Date was September 04, 2026."},{"kind":"tool","tool":"official.lookup","call":"Queried the public BLS-series mirror and BLS-linked metadata for LNU02032207 to assemble recent history for the same NSA employment-level series.","result":"Fetched recent LNU02032207 values in thousands: 2026-01 16,291, 2026-02 16,380, 2026-03 16,563, 2026-04 16,471, 2026-05 16,335, 2026-06 16,184, 2026-07 16,457, 2026-08 16,154."},{"kind":"tool","tool":"official.lookup","call":"Checked longer recent LNU02032207 history for September seasonality and missing observations.","result":"Fetched values in thousands: 2024-08 15,902, 2024-09 15,845, 2025-08 16,415, 2025-09 16,608, 2025-10 missing '.', 2025-11 17,102, and 2025-12 16,344."},{"kind":"text","text":"Base rate and reference class: the base rate is last-print persistence for a noisy CPS level series, using recent monthly LNU02032207 values rather than a structural extrapolation. The recent reference class has values mostly in a 16.18 to 16.56 million band, with the latest official August 2026 print at 16.154 million and no current official evidence of a discrete September break."},{"kind":"text","text":"Level, momentum, and mechanism: the August 2026 level was 0.261 million below August 2025, so I keep a modest downtrend relative to September 2025's 16.608 million. Momentum is mixed because July 2026 rose to 16.457 million and August fell to 16.154 million. One-off and policy mechanisms are weak here; this is a CPS occupation classification row, not a direct policy decision level."},{"kind":"math","text":"Prior/update/interval: persistence prior = August 2026 LNU02032207 at 16.154 million; historical sample = recent same-variant official/BLS-sourced monthly values from 2024-01 through 2026-08, excluding the missing 2025-10 observation and using only consecutive monthly changes; adjustment components = +0.068 million for the average of recent August-to-September moves (-0.057 in 2024 and +0.193 in 2025), rounded against mild year-over-year softness to point 16.220 million. Interval method = RMS of 29 recent consecutive monthly changes; sigma = sqrt(sum(change^2)/29) = 0.248 million, so 1.28*sigma = 0.317 million; rounding and recent volatility give 80% bounds of 15.87 to 16.57 million."},{"kind":"text","text":"Counter-considerations: upside risk would be a rebound toward the March 2026 level near 16.563 million or a repeat of September 2025's positive seasonal move, which could land above the interval. Downside risk is another CPS-sample drop from automation-sensitive clerical categories or weak total household employment, which could land below the interval. Outside the interval would most likely require a monthly move larger than about 0.35 million from August."},{"kind":"forecast","point":16.22,"ciLow":15.87,"ciHigh":16.57}]}

# Reviewer critique
{"summary":"The draft is publishable in structure but should tighten the resolver-date discrepancy and interval arithmetic before publication.","requiredFixes":[{"rubricItem":"resolver","severity":"warning","summary":"The cell matches the registered resolutionDate of 2026-10-15, but the resolutionRule embeds a conflicting claim that the BLS calendar says the September 2026 Employment Situation release is October 2, 2026.","actionRequested":"Keep resolutionDate tied to the ledger contract, but either remove the calendar-discrepancy sentence from the resolutionRule or move it to reasoning only with the exact cited evidence preserved; do not let the resolver text imply an alternate resolution date."},{"rubricItem":"interval","severity":"warning","summary":"The interval says sigma = 0.248 and 1.28*sigma = 0.317, but the published 80% bounds are roughly +/-0.35 around the point estimate.","actionRequested":"State the explicit widening rule from 0.317 to about 0.35 million, or adjust the interval to match the stated volatility method."}],"optionalSuggestions":["The prior/update/interval step is otherwise compact and useful; keeping the arithmetic visibly tied to 16.154 + 0.068 = 16.222 would make the rounded 16.22 point clearer.","The tail scenarios are adequate, but naming approximate low/high values for repeat CPS-sample drops or rebounds would make them more concrete."]}

Emit the final JSON object only.
