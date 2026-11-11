# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.telework_share
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-telework-rate-september-2026"
- country: "US"
- targetUnit: "percent"
- dataPointId: "bls.cps.telework_share.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-10-08", "start": "2026-09-30"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-08", "start": "2026-09-30"}, "field": "bls.cps.telework_share", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.telework_share", "sourceUrl": "https://www.bls.gov/web/empsit/cpseea41.htm", "table": "U.S. Bureau of Labor Statistics, Employment Situation, CPS Table A-41", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-0bc190e7fe95e2a7812ba70143f1394069f3cc59c61671e6021c2283181fc418.json"
- targetContentHash: "0bc190e7fe95e2a7812ba70143f1394069f3cc59c61671e6021c2283181fc418"
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
{"slug":"us-telework-rate-september-2026","country":"US","type":"data","title":"US telework rate, September 2026","question":"What will the U.S. Bureau of Labor Statistics first report for the not seasonally adjusted CPS telework rate, Total 16 years and over, percent of people at work who teleworked or worked at home for pay, in September 2026?","unit":"percent","pointEstimate":21.9,"ciLow":21.3,"ciHigh":22.5,"confidence":0.8,"resolutionDate":"2026-10-02","resolutionSource":"U.S. Bureau of Labor Statistics, Employment Situation, CPS Table A-41","resolutionSourceUrl":"https://www.bls.gov/web/empsit/cpseea41.htm","resolutionRule":"Resolve to the first official BLS print in CPS Table A-41 for September 2026: Total, 16 years and over; Percent distribution; People who teleworked or worked at home for pay. Use the not seasonally adjusted percent shown by BLS, in percent and rounded as published, normally to one decimal place. Do not use later revisions or same-day corrections unless the original first-print table is unavailable and BLS explicitly replaces it before any public archived or witnessed copy can identify the first print.","dataPointId":"bls.cps.telework_share.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2026-03"},"label":"2026-03","value":22.6},{"period":{"type":"month","value":"2026-04"},"label":"2026-04","value":21.7},{"period":{"type":"month","value":"2026-05"},"label":"2026-05","value":21.8},{"period":{"type":"month","value":"2026-06"},"label":"2026-06","value":21.7},{"period":{"type":"month","value":"2026-07"},"label":"2026-07","value":22.2},{"period":{"type":"month","value":"2026-08"},"label":"2026-08","value":21.6}],"drivers":["Recent 2026 level is near 22 percent","August 2026 dipped to 21.6 percent","September has shown modest positive seasonality in available telework history","Monthly CPS telework readings are noisy by several tenths","No known policy break before the September reference week"],"sourceContext":["https://www.bls.gov/schedule/news_release/empsit.htm","https://www.bls.gov/schedule/2026/","https://data.bls.gov/timeseries/LNU0201B46B","https://www.bls.gov/web/empsit/cpseea41.htm","https://www.bls.gov/cps/telework.htm"],"runAt":"2026-09-04T19:17:08Z","reasoning":[{"kind":"heading","text":"US CPS Telework Share Forecast"},{"kind":"text","text":"Resolver framing: this targets the BLS CPS Table A-41 national, not seasonally adjusted telework rate for September 2026, Total 16 years and over, percent of people at work who teleworked or worked at home for pay. The exact BLS series page identifies series LNU0201B46B as Percent, Persons who teleworked; percent of total at work."},{"kind":"tool","tool":"official.lookup","call":"Checked the official BLS Employment Situation release schedule for the September 2026 reference month and cross-checked the current Table A-41 page.","result":"BLS schedules Employment Situation for September 2026 on 2026-10-02 at 08:30 AM Eastern; the current A-41 August 2026 table shows Total, 16 years and over telework share of 21.6 percent, with 155,455 thousand total people at work and 33,633 thousand teleworking."},{"kind":"tool","tool":"official.lookup","call":"Fetched recent BLS data-series values from data.bls.gov/timeseries/LNU0201B46B.","result":"Recent official values for LNU0201B46B were 2026-01 23.0, 2026-02 22.7, 2026-03 22.6, 2026-04 21.7, 2026-05 21.8, 2026-06 21.7, and 2026-07 22.2 percent."},{"kind":"tool","tool":"official.lookup","call":"Fetched latest BLS A-41 first-print table value and compared it with the series history.","result":"The BLS A-41 August 2026 table reports 21.6 percent for Total, 16 years and over; recent same-series context includes 2026-03 22.6, 2026-04 21.7, 2026-05 21.8, 2026-06 21.7, and 2026-07 22.2 percent."},{"kind":"tool","tool":"official.lookup","call":"Fetched older same-series monthly values to form a reference class for seasonality and level.","result":"Same-series annual September anchors were 2023-09 19.8, 2024-09 23.7, and 2025-09 22.3 percent; recent August-to-September moves were +0.3 in 2023, +0.9 in 2024, and +0.2 in 2025."},{"kind":"text","text":"Base rate/reference class: the recent 2026 level is a little below the 2024-2025 plateau, but the last six observed prints average 21.93 percent and September has usually not been lower than August in the short telework series. I therefore start from persistence around 21.6 to 22.0 rather than extrapolating the April-August dip linearly."},{"kind":"math","text":"Prior/update/interval: persistence prior from the last official print is 21.6 percent; historical sample for uncertainty is the 2026 Jan-Aug sequence 23.0, 22.7, 22.6, 21.7, 21.8, 21.7, 22.2, 21.6. Adjustments are +0.2 for September seasonality, +0.1 for mean reversion toward the last-six-print average of 21.93, and 0.0 for policy-mechanism effects, giving 21.9. Successive changes are -0.3, -0.1, -0.9, +0.1, -0.1, +0.5, -0.6, so sigma = 0.46 percentage point using the sample standard deviation; 1.28*sigma = 0.59, rounded to a 0.6-point half-width, implying 21.3 to 22.5."},{"kind":"text","text":"Counter-considerations: upside risk is a September rebound like 2024, which would land above the interval if telework jumps roughly 1.0 point or more from August. Downside risk is a renewed office-return or composition move that pushes the rate below 21.3. Outside the interval would most likely require a large month-specific CPS composition shift rather than a visible policy change."},{"kind":"forecast","point":21.9,"ciLow":21.3,"ciHigh":22.5}]}

# Reviewer critique
{"summary":"Draft is methodologically usable, but it has a blocking mismatch with the ledger resolution date contract.","requiredFixes":[{"rubricItem":"resolver","severity":"blocking","summary":"The draft sets resolutionDate to 2026-10-02, but the ledger target contract uses the bounded expectedReleaseWindow ending 2026-10-08 for this registered target.","actionRequested":"Change the JSON resolutionDate to 2026-10-08 while keeping the same BLS A-41 first-print resolver and noting any release-calendar discrepancy in reasoning rather than changing the target."}],"optionalSuggestions":["Mention that the 0.46-point sigma is based on a very short Jan-Aug 2026 change sample, so the interval is a deliberately recent-volatility interval rather than a long-run model interval."]}

Emit the final JSON object only.
