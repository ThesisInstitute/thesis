# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.employed_people_by_occupation.business_financial_operations
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-business-financial-employment-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.business_financial_operations.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-10-15", "start": "2026-10-07"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-15", "start": "2026-10-07"}, "field": "Business and financial operations occupations", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.employed_people_by_occupation.business_financial_operations", "sourceUrl": "https://www.bls.gov/web/empsit/cpseea19.htm", "table": "CPS Employment Situation Table A-19, employed persons by occupation, not seasonally adjusted (thousands)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-4a874f0646368ee8601b3024fdbb32c0d0c49672cb9facd396ffca1e87f35626.json"
- targetContentHash: "4a874f0646368ee8601b3024fdbb32c0d0c49672cb9facd396ffca1e87f35626"
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
{"slug":"cps-business-financial-employment-september-2026","country":"US","type":"data","title":"US business and financial operations employment, September 2026","question":"What will the U.S. Bureau of Labor Statistics first report in CPS Employment Situation Table A-19 for employed people in Business and financial operations occupations, total age 16 years and over, not seasonally adjusted, for September 2026, in millions?","unit":"millions","pointEstimate":10.16,"ciLow":9.838,"ciHigh":10.482,"confidence":0.8,"resolutionDate":"2026-10-15","resolutionSource":"U.S. Bureau of Labor Statistics Employment Situation, Table A-19","resolutionSourceUrl":"https://www.bls.gov/web/empsit/cpseea19.htm","resolutionRule":"Resolve to the first value published by BLS for September 2026 in CPS Employment Situation Table A-19, row 'Business and financial operations occupations,' Total age 16 years and over, not seasonally adjusted, reported in thousands and multiplied by 0.001 to millions. Use the first official print without later revisions. The official BLS Employment Situation schedule fetched this run lists September 2026 for Oct. 02, 2026 at 08:30 AM, while the registered Thesis target contract sets resolutionDate to 2026-10-15 and expectedReleaseWindow 2026-10-07 to 2026-10-15; this cell preserves the registered target date and records the discrepancy.","dataPointId":"bls.cps.employed_people_by_occupation.business_financial_operations.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":10.291},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":10.195},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":10.033},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":9.72},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":9.835},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":10.167}],"drivers":["latest same-row A-19 value rose to 10.167 million in August 2026","same-row first-print history remains noisy around 10 million","August payroll report showed unemployment unchanged at 4.1 percent","financial activities payrolls fell while professional and business services rose slightly","registered resolutionDate conflicts with official Oct. 02 release date and is preserved"],"sourceContext":["https://www.bls.gov/web/empsit/cpseea19.htm","https://www.bls.gov/schedule/news_release/empsit.htm","https://www.bls.gov/news.release/archives/empsit_09042026.htm","https://www.bls.gov/cps/cpsaat12.htm"],"runAt":"2026-09-11T19:26:53Z","reasoning":[{"kind":"heading","text":"BLS CPS A-19 occupation employment forecast"},{"kind":"text","text":"The target is the BLS CPS Employment Situation Table A-19 row 'Business and financial operations occupations,' total age 16 years and over, not seasonally adjusted, for September 2026, first print, transformed from thousands to millions. The resolver is the A-19 NSA detailed occupation table, not the broader A-13 occupation category."},{"kind":"tool","tool":"web.open","call":"Open BLS Employment Situation schedule at https://www.bls.gov/schedule/news_release/empsit.htm","result":"BLS schedule lists August 2026 release Sep. 04, 2026 at 08:30 AM; September 2026 release Oct. 02, 2026 at 08:30 AM; October 2026 release Nov. 06, 2026 at 08:30 AM. The registered target's 2026-10-15 resolutionDate conflicts with the official Sep. 2026 release date, so I preserve the target contract and state the discrepancy."},{"kind":"tool","tool":"web.open","call":"Open current BLS CPS Employment Situation Table A-19 at https://www.bls.gov/web/empsit/cpseea19.htm","result":"Current BLS Table A-19, Last Modified Date September 04, 2026: Business and financial operations occupations row has Aug. 2025 total 10,114 thousand and Aug. 2026 total 10,167 thousand, equal to 10.114 and 10.167 million after multiplying by 0.001."},{"kind":"tool","tool":"local.repo.inspect","call":"Inspect public Thesis generated forecast artifacts that recorded same-row BLS A-19 snapshot values for prior 2026 first prints","result":"Public generated artifact recorded same-row BLS Table A-19 snapshot values: January 2026 10,291 thousand, March 2026 10,195 thousand, May 2026 10,033 thousand, June 2026 9,720 thousand, and July 2026 9,835 thousand, equal to 10.291, 10.195, 10.033, 9.720, and 9.835 million."},{"kind":"tool","tool":"web.search","call":"Fetch current Employment Situation release context for August 2026 from BLS archive","result":"BLS August 2026 Employment Situation reports total nonfarm payroll employment +162,000, unemployment rate 4.1 percent, financial activities employment -11,000, and professional and business services employment +10,000 in August 2026."},{"kind":"tool","tool":"web.search","call":"Fetch BLS annual CPS occupation context table cpsaat12","result":"BLS annual average table cpsaat12 reports Business and financial operations occupations at 9,945 thousand in 2024 and 10,173 thousand in 2025, equal to 9.945 and 10.173 million."},{"kind":"text","text":"Base rate / reference class: the recent same-row A-19 reference class available here is 10.291, 10.195, 10.033, 9.720, 9.835, and 10.167 million. Last-print persistence from August 2026 is 10.167 million, the annual 2025 average is 10.173 million, and the recent range is 9.720 to 10.291 million. I treat the August rebound as real but noisy and do not extrapolate it further."},{"kind":"text","text":"Level, momentum, one-off, and policy mechanisms: level starts at August's 10.167 million. Momentum from June to August is positive after the June trough, but the first half of 2026 had a declining sequence. One-off effects are dominated by CPS occupation-cell sampling noise. Policy mechanism is neutral because no discrete policy change was identified that would shift this occupation count before the September survey."},{"kind":"math","text":"Prior/update/interval: prior = persistence.last_print from August 2026 = 10.167 million; historical sample = same-row A-19 levels 2026-01, 2026-03, 2026-05, 2026-06, 2026-07, 2026-08; successive fetched-print changes = -0.096, -0.162, -0.313, +0.115, +0.332 million, so sigma = 0.252 million using sample standard deviation. Update components = -0.007 million, combining +0.010 million level support from the 2025 annual average and August rebound, -0.015 million from weak financial activities payroll context, -0.002 million residual rounding/noise discipline. Point = 10.167 - 0.007 = 10.160 million. Interval method = realized same-row change dispersion; 80% half-width = 1.28*sigma = 1.28*0.252 = 0.322 million, so bounds are 10.160 - 0.322 = 9.838 and 10.160 + 0.322 = 10.482 million."},{"kind":"text","text":"Counter-consideration: downside risk outside the interval would come from a renewed occupation-cell drop like May-to-June plus broader household employment weakness, which would land below 9.838 million. Upside risk outside the interval would come from another August-sized rebound together with stronger white-collar classification mix, which would land above 10.482 million."},{"kind":"forecast","point":10.16,"ciLow":9.838,"ciHigh":10.482}]}

# Reviewer critique
{"summary":"Draft is publishable as a target-tied forecast, with the main caveat that it records a concrete ledger/calendar discrepancy for the resolution date.","requiredFixes":[],"optionalSuggestions":["Consider adding a short note explaining why February and April 2026 same-row observations are absent from the historical sample if they were unavailable rather than intentionally excluded.","Before publication, separately review the registered target window/date because the draft reports an official BLS September 2026 release date of 2026-10-02 while the ledger contract uses 2026-10-15."]}

Emit the final JSON object only.
