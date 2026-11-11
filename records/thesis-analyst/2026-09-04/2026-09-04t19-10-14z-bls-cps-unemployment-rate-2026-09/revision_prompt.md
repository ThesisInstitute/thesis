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
- expectedReleaseWindow: {"end": "2026-10-08", "start": "2026-09-30"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-08", "start": "2026-09-30"}, "field": "bls.cps.unemployment_rate", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.unemployment_rate", "sourceUrl": "https://www.bls.gov/news.release/empsit.nr0.htm", "table": "U.S. Bureau of Labor Statistics Employment Situation (Current Population Survey)", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-4f9351e9599bb007177abdf8c158ee801328243b30407e6ff10d9b25084c2d8a.json"
- targetContentHash: "4f9351e9599bb007177abdf8c158ee801328243b30407e6ff10d9b25084c2d8a"
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
{"slug":"unemployment-rate-september-2026","country":"US","type":"data","title":"US unemployment rate, September 2026","question":"What will the U.S. Bureau of Labor Statistics report as the seasonally adjusted civilian unemployment rate for September 2026 in the Current Population Survey, first print?","unit":"percent","pointEstimate":4.1,"ciLow":4.0,"ciHigh":4.2,"confidence":0.8,"resolutionDate":"2026-10-02","resolutionSource":"U.S. Bureau of Labor Statistics Employment Situation","resolutionSourceUrl":"https://www.bls.gov/news.release/empsit.nr0.htm","resolutionRule":"Resolve to the first-print seasonally adjusted unemployment rate for total civilian labor force, 16 years and over, in BLS Employment Situation household survey table A-1 for September 2026, as initially published on October 2, 2026. Use the value rounded to one decimal percent as printed by BLS; do not use later revisions, annual seasonal-factor revisions, corrected subsequent database vintages, or same-day corrections unless BLS replaces the initial release before public availability.","dataPointId":"bls.cps.unemployment_rate.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":4.3},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":4.4},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":4.3},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":4.3},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":4.3},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":4.2},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":4.1},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":4.1}],"drivers":["latest first print held at 4.1 percent","recent payroll growth improved in August","labor force participation still soft versus January","CPS monthly unemployment changes usually move by 0.0 to 0.1 point near this level"],"sourceContext":["https://www.bls.gov/schedule/news_release/empsit.htm","https://www.bls.gov/cps/publications/release-calendar.htm","https://www.bls.gov/news.release/empsit.nr0.htm","https://www.bls.gov/news.release/archives/empsit_02112026.htm","https://www.bls.gov/news.release/archives/empsit_03062026.htm","https://www.bls.gov/news.release/archives/empsit_04032026.htm","https://www.bls.gov/news.release/archives/empsit_05082026.htm","https://www.bls.gov/news.release/archives/empsit_06052026.htm","https://www.bls.gov/news.release/archives/empsit_07022026.htm","https://www.bls.gov/news.release/archives/empsit_08072026.htm"],"runAt":"2026-09-04T19:10:30Z","reasoning":[{"kind":"heading","text":"September 2026 BLS CPS unemployment-rate forecast"},{"kind":"text","text":"The target is the BLS Current Population Survey seasonally adjusted unemployment rate, total civilian labor force age 16 and over, table A-1, for September 2026. The resolving page is the Employment Situation first print, not FRED or a later BLS database revision."},{"kind":"tool","tool":"official.lookup","call":"Read BLS Employment Situation release schedule for September 2026 reference month.","result":"BLS schedule lists Employment Situation for September 2026 on October 2, 2026 at 08:30 AM ET; CPS release calendar also lists Oct. 02, 2026 for September 2026."},{"kind":"tool","tool":"official.lookup","call":"Read BLS January and February 2026 Employment Situation archive releases for CPS unemployment-rate first prints.","result":"January 2026 first print unemployment rate was 4.3 percent with 7.4 million unemployed; February 2026 first print unemployment rate was 4.4 percent with 7.6 million unemployed."},{"kind":"tool","tool":"official.lookup","call":"Read BLS March through May 2026 Employment Situation archive releases for CPS unemployment-rate first prints.","result":"March 2026 first print unemployment rate was 4.3 percent with 7.2 million unemployed; April 2026 was 4.3 percent with 7.4 million unemployed; May 2026 was 4.3 percent with 7.3 million unemployed."},{"kind":"tool","tool":"official.lookup","call":"Read BLS June through August 2026 Employment Situation releases for CPS unemployment-rate first prints and near-term labor indicators.","result":"June 2026 first print unemployment rate was 4.2 percent with 7.1 million unemployed and payrolls +57,000; July 2026 was 4.1 percent with 6.9 million unemployed and payrolls -23,000 first print; August 2026 was 4.1 percent with 7.0 million unemployed and payrolls +162,000."},{"kind":"text","text":"The reference class is recent first-print CPS unemployment-rate levels in the same seasonally adjusted BLS table A-1 variant. The base rate from January-August 2026 is a stable 4.1 to 4.4 percent range, with the last two prints at 4.1 percent."},{"kind":"math","text":"Prior/update/interval: persistence prior uses the latest official first print, August 2026 = 4.1 percent. Historical sample is Jan-Aug 2026 first prints: 4.3, 4.4, 4.3, 4.3, 4.3, 4.2, 4.1, 4.1. Adjustment components: level - latest level anchors at 4.1; momentum - small decline from 4.3 in spring to 4.1 in July-August, but no August move; one-off - July local-government weakness partly reversed in August payroll revisions and jobs; policy mechanism - no direct policy rate or eligibility rule mechanically changes CPS unemployment by September. Successive changes are +0.1, -0.1, 0.0, 0.0, -0.1, -0.1, 0.0 percentage points; sample sigma = 0.076, so 1.28*sigma = 0.097. Around point 4.1, the rounded 80 percent interval is 4.0 to 4.2 percent."},{"kind":"text","text":"Upside risk is a sharper labor-demand deterioration before the September survey week, for example weak hiring plus a rebound in labor-force participation, which could print 4.3 percent and land above the interval. Downside risk is another drop in temporary layoffs or exits from unemployment into nonparticipation, which could print 3.9 percent and land below the interval. Outside the interval would require at least about a 0.2 percentage point rounded move from August's 4.1 percent."},{"kind":"forecast","point":4.1,"ciLow":4.0,"ciHigh":4.2}]}

# Reviewer critique
{"summary":"The draft is publication-ready on resolver, prior/update logic, interval construction, tails, and field coherence; I found no blocking fixes.","requiredFixes":[],"optionalSuggestions":["Clarify the phrase about August payroll revisions: the August Employment Situation first print revises prior months, not August itself.","Consider adding the exact BLS Table A-1 label to sourceContext or reasoning for easier auditability."]}

Emit the final JSON object only.
