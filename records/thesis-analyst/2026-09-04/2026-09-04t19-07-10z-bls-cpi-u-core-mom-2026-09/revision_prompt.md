# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cpi.u.core_mom
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "us-core-cpi-mom-september-2026"
- country: "US"
- targetUnit: "percent_growth"
- dataPointId: "bls.cpi.u.core_mom.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-10-15", "start": "2026-10-07"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-15", "start": "2026-10-07"}, "field": "bls.cpi.u.core_mom", "releasePolicy": "first_print", "sourceSeriesId": "bls.cpi.u.core_mom", "sourceUrl": "https://www.bls.gov/news.release/cpi.nr0.htm", "table": "U.S. Bureau of Labor Statistics Consumer Price Index news release", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-666261cec19a56b9b6ecf64c9af43bfa61c5ba5cc0df43fdb99d3830912c1d37.json"
- targetContentHash: "666261cec19a56b9b6ecf64c9af43bfa61c5ba5cc0df43fdb99d3830912c1d37"
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
{"slug":"us-core-cpi-mom-september-2026","country":"US","type":"data","title":"US Core CPI MoM, Sep 2026","question":"What will the U.S. Bureau of Labor Statistics report as the September 2026 seasonally adjusted 1-month percent change in CPI-U all items less food and energy in the first CPI news release?","unit":"percent_growth","pointEstimate":0.25,"ciLow":0.1,"ciHigh":0.4,"confidence":0.8,"resolutionDate":"2026-10-14","resolutionSource":"U.S. Bureau of Labor Statistics Consumer Price Index news release","resolutionSourceUrl":"https://www.bls.gov/news.release/cpi.nr0.htm","resolutionRule":"Resolve to the first BLS Consumer Price Index news release for September 2026, Table A, CPI-U U.S. city average, seasonally adjusted change from preceding month, row 'All items less food and energy'. Use the initially published one-decimal percent value; ignore later revisions or corrected historical vintages unless BLS replaces the first print before public release.","dataPointId":"bls.cpi.u.core_mom.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":0.3},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":0.2},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":0.2},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":0.4},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":0.2},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":0},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":0.2}],"drivers":["recent core prints centered near 0.2 percent","shelter still positive but cooling","core services ex-energy remain sticky","goods disinflation limits upside","August print not yet released at run time"],"sourceContext":["https://www.bls.gov/news.release/cpi.nr0.htm","https://www.bls.gov/schedule/news_release/cpi.htm"],"runAt":"2026-09-04T19:07:25Z","reasoning":[{"kind":"heading","text":"Forecast for September 2026 core CPI-U month-over-month"},{"kind":"text","text":"The resolver is BLS CPI-U, U.S. city average, all items less food and energy, seasonally adjusted change from the preceding month, first September 2026 CPI Summary print. The ledger window ends 2026-10-15, but the official BLS CPI release schedule fetched this run lists the September 2026 CPI release on 2026-10-14 at 08:30 ET; I keep the registered slug, unit, and dataPointId while using the official calendar date."},{"kind":"tool","tool":"official.lookup","call":"Opened BLS CPI release schedule and current CPI Summary page to verify target timing and latest available release vintage.","result":"Fetched BLS schedule: September 2026 CPI release date 2026-10-14, release time 08:30 AM; current CPI Summary is July 2026, released 2026-08-12, with core CPI-U month-over-month at 0.2 percent."},{"kind":"tool","tool":"official.lookup","call":"Read BLS CPI Summary Table A for the same variant: CPI-U all items less food and energy, seasonally adjusted changes from preceding month.","result":"Fetched Table A core CPI-U MoM values: January 2026 0.3, February 2026 0.2, March 2026 0.2, April 2026 0.4, May 2026 0.2, June 2026 0.0, July 2026 0.2 percent."},{"kind":"tool","tool":"official.lookup","call":"Read the July 2026 BLS CPI Summary component narrative for current-release momentum and one-off contributors.","result":"Fetched July 2026 BLS component numbers: all items 0.1 percent, energy -1.5 percent, all items less food and energy 0.2 percent, shelter 0.1 percent, medical care 0.4 percent, airline fares 2.2 percent, motor vehicle insurance -0.3 percent."},{"kind":"text","text":"The reference class and base rate are the latest seven official first-print-style monthly core CPI readings available in the BLS release table for this exact SA CPI-U core variant. Their mean is about 0.21 percent, with most readings between 0.0 and 0.4 percent."},{"kind":"math","text":"Prior/update/interval: persistence prior is the recent official-reference-class mean of Jan-Jul 2026 core CPI MoM, (0.3+0.2+0.2+0.4+0.2+0.0+0.2)/7 = 0.214 percent. Updates: shelter cooling and July shelter 0.1 subtract about 0.02; sticky core services and medical care add about 0.03; no clear energy direct effect because this is ex-food-energy; modest goods stabilization adds about 0.02. Point rounds to 0.25 percent. For a change/flow series, interval sigma uses the fetched values themselves: sample sigma = 0.12 from [0.3,0.2,0.2,0.4,0.2,0.0,0.2], so 1.28*sigma = 0.15. Applying that half-width to 0.25 gives final implied bounds 0.10 to 0.40 percent."},{"kind":"text","text":"Upside risk is a renewed jump in core services, medical care, insurance, or airfare that would land above the interval. Downside risk is another broad services pause plus softer shelter and goods deflation that would land below the interval; an outside the interval print would likely need several large components to move in the same direction."},{"kind":"forecast","point":0.25,"ciLow":0.1,"ciHigh":0.4}]}

# Reviewer critique
{
  "summary": "The draft is publishable with one warning: it should make the model-prior choice more explicit.",
  "requiredFixes": [
    {
      "rubricItem": "model_prior",
      "severity": "warning",
      "summary": "The draft uses a recent persistence mean, but does not explicitly say whether a broader time-series/model prior was considered and ruled out.",
      "actionRequested": "Add one sentence stating that no separate statistical model prior was used beyond the Jan-Jul 2026 persistence prior, or name the model prior if one was used."
    }
  ],
  "optionalSuggestions": [
    "The resolution-date discrepancy is handled clearly; keep the explanation tied to the official BLS release calendar.",
    "Consider noting that BLS will publish the resolving value to one decimal even though the point estimate is expressed as 0.25."
  ]
}

Emit the final JSON object only.
