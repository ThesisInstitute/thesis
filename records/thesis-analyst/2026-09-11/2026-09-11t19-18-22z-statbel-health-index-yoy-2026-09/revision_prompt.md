# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: statbel.health_index.yoy
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "belgium-health-index-annual-rate-september-2026"
- country: "BE"
- targetUnit: "percent"
- dataPointId: "statbel.health_index.yoy.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-10-07", "start": "2026-09-29"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["statbel.fgov.be"], "expectedReleaseWindow": {"end": "2026-10-07", "start": "2026-09-29"}, "field": "statbel.health_index.yoy", "releasePolicy": "first_print", "sourceSeriesId": "statbel.health_index.yoy", "sourceUrl": "https://statbel.fgov.be/en/themes/consumer-prices/consumer-price-index", "table": "Statbel Consumer Price Index - Health Index release", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-eaaaec58dd39e441bfc202864aea5d116ae31c39676b46cac9aed4bccfe01c7d.json"
- targetContentHash: "eaaaec58dd39e441bfc202864aea5d116ae31c39676b46cac9aed4bccfe01c7d"
- registrationCommit: "f527f4e54f1df0156366f87eeb5dd630eeb66fe4"
- registeredAtUtc: "2026-09-11T19:13:41Z"

# Source hints
- Use the official agency data page and release calendar.
- FRED or sanctioned mirrors may be used only for history, not final resolution.
- Match the agency's published rounding precision.

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
{"slug":"belgium-health-index-annual-rate-september-2026","country":"BE","type":"data","title":"Belgium health-index inflation, September 2026","question":"What will Statbel first publish as the annual inflation rate based on the health index for September 2026, in percent, using the Health index special aggregate and not the smoothed health index?","unit":"percent","pointEstimate":3.85,"ciLow":2.96,"ciHigh":4.74,"confidence":0.8,"resolutionDate":"2026-09-29","resolutionSource":"Statbel Consumer Price Index - Health Index release","resolutionSourceUrl":"https://bestat.statbel.fgov.be/bestat/crosstable.xhtml?view=31b8021d-3fcd-4a8b-ac49-92beabf434e9","resolutionRule":"Resolve to the first Statbel-published annual inflation rate based on the Health index special aggregate for m-2026-09, reported in percent and rounded to the agency's published two-decimal precision. Use the first official print only; ignore later revisions, later database corrections, mirrors, and the smoothed health index.","dataPointId":"statbel.health_index.yoy.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2025-08"},"label":"August 2025","value":2.04},{"period":{"type":"month","value":"2025-09"},"label":"September 2025","value":2.15},{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":2.1},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":2.45},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":2.21},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":1.37},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":1.68},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":1.38},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":3.38},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":3.48},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":2.99},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":3.22},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":3.44}],"drivers":["August health-index inflation was already elevated at 3.44 percent","September 2025 base index was below August 2025, mechanically lifting September 2026 year-over-year inflation if the index is flat","Energy-related pressure was strong in August, especially natural gas and electricity","Core inflation eased but remained near 3 percent","Motor fuels affect headline CPI more than the health index because they are excluded from the health index basket"],"sourceContext":["https://statbel.fgov.be/en/calendar","https://statbel.fgov.be/en/themes/consumer-prices/consumer-price-index","https://bestat.statbel.fgov.be/bestat/crosstable.xhtml?view=31b8021d-3fcd-4a8b-ac49-92beabf434e9","https://bestat.statbel.fgov.be/bestat/crosstable.xhtml?view=e8fad1c0-5270-4d62-9118-0999ee8cb323"],"runAt":"2026-09-11T19:18:36Z","reasoning":[{"kind":"heading","text":"Belgium September 2026 health-index annual inflation forecast"},{"kind":"text","text":"Framing and exact resolver: this targets Statbel's first print of annual inflation based on the Health index special aggregate for September 2026, in percent, distinct from headline CPI, index-without-energy aggregates, and the smoothed health index."},{"kind":"tool","tool":"official.lookup","call":"Checked the Statbel release calendar for Consumer Price Index - Health Index m-2026-09.","result":"The Statbel calendar lists Consumer Price Index - Health Index for m-2026-09 on 29 September 2026; the same calendar lists m-2026-10 on 29 October 2026 and m-2026-11 on 27 November 2026."},{"kind":"tool","tool":"official.lookup","call":"Fetched Statbel be.STAT annual inflation rate by special aggregates, last 13 months, and selected the Health index column.","result":"Health index annual inflation prints were 2.04 in August 2025, 2.15 in September 2025, 2.10 in October 2025, 2.45 in November 2025, 2.21 in December 2025, 1.37 in January 2026, 1.68 in February 2026, 1.38 in March 2026, 3.38 in April 2026, 3.48 in May 2026, 2.99 in June 2026, 3.22 in July 2026, and 3.44 in August 2026."},{"kind":"tool","tool":"official.lookup","call":"Fetched Statbel health-index levels by base year, last 13 months, to identify the base effect into September.","result":"On the 2025=100 base, the health index was 100.05 in August 2025, 99.77 in September 2025, 103.24 in July 2026, and 103.49 in August 2026; on the 2013=100 base, August 2026 was 140.30 and September 2025 was 135.26."},{"kind":"tool","tool":"official.lookup","call":"Read the latest Statbel CPI release text for current drivers and cross-checking the variant.","result":"The August 2026 release states health-index inflation rose from 3.22 in July to 3.44 in August, the health index increased by 0.25 points to 103.49, headline inflation was 3.97, core inflation was 2.99, natural gas prices rose 9.8 percent month over month, electricity rose 1.0 percent, and plane tickets fell 8.4 percent."},{"kind":"text","text":"Base rate/reference class: the recent official reference class is the 13 monthly Health index annual-rate prints from August 2025 through August 2026, averaging about 2.50 percent, but the live state is higher: the last five prints are 3.38, 3.48, 2.99, 3.22, and 3.44 percent."},{"kind":"math","text":"Prior/update/interval: persistence prior starts from August 2026 health-index inflation of 3.44 percent. Level/base adjustment: September 2025 health index of 99.77 was 0.28 index points below August 2025's 100.05, so an unchanged September 2026 index of 103.49 would imply about 3.73 percent year-over-year; allowing a modest September 2026 monthly rise of about 0.12 index point implies roughly 3.85 percent. Momentum/current drivers add support from August energy pressure but are tempered by lower core inflation and the exclusion of motor fuels from the health index. Interval method: monthly changes in the fetched health-index annual-rate prints are 0.11, -0.05, 0.35, -0.24, -0.84, 0.31, -0.30, 2.00, 0.10, -0.49, 0.23, and 0.22 percentage points; sample sigma = 0.6925, so 1.28*sigma = 0.8863. Applying that half-width to 3.85 gives 2.96 to 4.74 after rounding."},{"kind":"text","text":"Counter-considerations: upside risk comes from another utility-price jump or a larger September index increase, which would land above the interval if health-index inflation exceeded 4.74 percent. Downside risk comes from a reversal in household energy prices or broad service-price softness, which would land below the interval if the annual rate fell under 2.96 percent."},{"kind":"forecast","point":3.85,"ciLow":2.96,"ciHigh":4.74}]}

# Reviewer critique
{"summary":"Draft is methodologically coherent, but it conflicts with the canonical target contract on resolver URL and resolution date.","requiredFixes":[{"rubricItem":"resolver","severity":"blocking","summary":"Draft sets resolutionDate to 2026-09-29 and resolutionSourceUrl to a be.STAT crosstable, while the ledger contract binds this target to the Statbel CPI/Health Index source URL and the registered resolution-date basis/window ending 2026-10-07.","actionRequested":"Set the JSON resolver fields to the canonical target contract: use the ledger Statbel CPI source URL and the registered resolution date/window basis rather than silently substituting the 2026-09-29 calendar date; if noting the 2026-09-29 calendar evidence, keep it in reasoning as a discrepancy or supporting release-timing note."}],"optionalSuggestions":["Keep the be.STAT crosstable as evidence/history context, not the resolver URL, unless the registered target is amended upstream.","The prior/update/interval step is strong; preserve the sigma calculation and implied bounds after resolver-field correction."]}

Emit the final JSON object only.
