# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: statbel.cpi.headline_yoy
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "belgium-cpi-annual-rate-september-2026"
- country: "BE"
- targetUnit: "percent"
- dataPointId: "statbel.cpi.headline_yoy.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-10-07", "start": "2026-09-29"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["statbel.fgov.be"], "expectedReleaseWindow": {"end": "2026-10-07", "start": "2026-09-29"}, "field": "statbel.cpi.headline_yoy", "releasePolicy": "first_print", "sourceSeriesId": "statbel.cpi.headline_yoy", "sourceUrl": "https://statbel.fgov.be/en/themes/consumer-prices/consumer-price-index", "table": "Statbel Consumer Price Index - Health Index release", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-f8846f2d36a637da92d8f74483a96279b757ff255008a02e7ae348f5f4bed77d.json"
- targetContentHash: "f8846f2d36a637da92d8f74483a96279b757ff255008a02e7ae348f5f4bed77d"
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
{"slug":"belgium-cpi-annual-rate-september-2026","country":"BE","type":"data","title":"Belgium CPI Inflation September 2026","question":"What will Statbel first report as Belgium's national Consumer Price Index headline annual inflation rate for September 2026, not HICP and not the health index?","unit":"percent","pointEstimate":3.85,"ciLow":2.81,"ciHigh":4.89,"confidence":0.8,"resolutionDate":"2026-09-29","resolutionSource":"Statbel Consumer Price Index - Health Index first release and be.STAT CPI inflation table","resolutionSourceUrl":"https://bestat.statbel.fgov.be/bestat/crosstable.xhtml?view=bee1820f-cbdb-4705-aac4-cfcf40680eb7","resolutionRule":"Resolve on the first official Statbel print for Consumer Price Index - Health Index, m-2026-09, using the national CPI headline annual inflation percentage for September 2026 as printed by Statbel, rounded to two decimals. Exclude HICP, health-index inflation, smoothed health index, and later revisions.","dataPointId":"statbel.cpi.headline_yoy.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2025-08"},"label":"August 2025","value":1.91},{"period":{"type":"month","value":"2025-09"},"label":"September 2025","value":2.12},{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":2},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":2.4},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":2.06},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":1.1},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":1.45},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":1.65},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":4.01},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":4.08},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":3.4},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":3.56},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":3.97}],"drivers":["August headline CPI inflation was 3.97 percent","Energy inflation rose to 16.47 percent in August","Core inflation eased to 2.99 percent","September 2025 denominator was low","Recent monthly changes are volatile"],"sourceContext":["https://statbel.fgov.be/en/calendar","https://statbel.fgov.be/en/themes/consumer-prices/consumer-price-index","https://bestat.statbel.fgov.be/bestat/crosstable.xhtml?view=bee1820f-cbdb-4705-aac4-cfcf40680eb7","https://bestat.statbel.fgov.be/bestat/crosstable.xhtml?view=6354a929-6969-4172-8143-e57aab550cc3"],"runAt":"2026-09-11T19:16:49Z","reasoning":[{"kind":"heading","text":"Belgium September 2026 headline CPI inflation forecast"},{"kind":"text","text":"This forecast targets Statbel's national Consumer Price Index headline annual inflation rate for September 2026, first print, in percent. The variant is the national CPI headline inflation series, not HICP, not health-index inflation, and not the smoothed health index."},{"kind":"tool","tool":"official.lookup","call":"Checked the Statbel release calendar for the September 2026 CPI release date and adjacent CPI/HICP items.","result":"The official calendar lists Consumer Price Index - Health Index for m-2026-09 on 29 September 2026, HICP for m-2026-09 on 15 October 2026, and Consumer Price Index - Health Index for m-2026-10 on 29 October 2026."},{"kind":"tool","tool":"official.lookup","call":"Fetched Statbel be.STAT annual inflation rate table for special aggregates, latest 13 months, and selected the headline national CPI column.","result":"Fetched headline CPI annual inflation prints: August 2025 1.91, September 2025 2.12, October 2025 2.00, November 2025 2.40, December 2025 2.06, January 2026 1.10, February 2026 1.45, March 2026 1.65, April 2026 4.01, May 2026 4.08, June 2026 3.40, July 2026 3.56, August 2026 3.97 percent."},{"kind":"tool","tool":"official.lookup","call":"Fetched the official Statbel August 2026 CPI release page for current-release detail and drivers.","result":"August 2026 headline inflation was 3.97 percent versus 3.56 percent in July and 3.40 percent in June; CPI rose 0.41 index points or 0.40 percent month on month; energy inflation was 16.47 percent, natural gas rose 9.8 percent month on month, and motor fuels rose 4.7 percent month on month."},{"kind":"tool","tool":"official.lookup","call":"Fetched the Statbel CPI index table to cross-check the annual-rate identity and recent index levels.","result":"The headline CPI index was 103.26 in May 2026, 102.95 in June 2026, 103.60 in July 2026, and 104.01 in August 2026 on the 2025=100 basis; the September 2025 headline CPI index in the same table was 99.74."},{"kind":"text","text":"The base rate/reference class is the last 13 official headline CPI annual inflation prints. Their mean is 2.59 percent, their median is 2.12 percent, but the post-April energy-regime sample is materially higher: April-August prints are 4.01, 4.08, 3.40, 3.56, and 3.97 percent. I therefore put more weight on near-term persistence than on the full-sample mean."},{"kind":"math","text":"Prior/update/interval: persistence prior is August headline CPI inflation at 3.97 percent. Historical sample is the 13 official headline prints from August 2025 through August 2026, with successive monthly changes of +0.21, -0.12, +0.40, -0.34, -0.96, +0.35, +0.20, +2.36, +0.07, -0.68, +0.16, and +0.41 percentage points. Adjustment components: -0.20 pp for likely partial reversal/normalization of August energy and fuel jumps, +0.08 pp for the low September 2025 denominator and still-firm core, giving 3.97 - 0.20 + 0.08 = 3.85 percent. Interval method: sample standard deviation of successive changes gives sigma = 0.814, so the 80 percent half-width is about 1.28*sigma = 1.28*0.814 = 1.04 pp; final implied bounds are 3.85 - 1.04 = 2.81 and 3.85 + 1.04 = 4.89 percent."},{"kind":"text","text":"Upside risk is another rise in natural gas, electricity, or motor fuels after August's already large energy contribution, which would land above the interval if combined with broad services inflation. Downside risk is a sharp reversal in energy and travel-related prices plus softer food and rent components, which would land below the interval if the September index falls much more than the prior-year September base."},{"kind":"forecast","point":3.85,"ciLow":2.81,"ciHigh":4.89}]}

# Reviewer critique
{
  "summary": "Draft is methodologically coherent, but it does not exactly match the ledger resolver/source and likely resolution-date contract.",
  "requiredFixes": [
    {
      "rubricItem": "resolver",
      "severity": "blocking",
      "summary": "Resolution source URL and resolver text do not match the canonical ledger sourceBinding, which names the Statbel consumer-price-index page as sourceUrl and the Statbel Consumer Price Index - Health Index release as the table.",
      "actionRequested": "Change resolutionSourceUrl to the ledger sourceUrl and align resolutionSource/resolutionRule with the registered resolver text while keeping the target as headline national CPI annual inflation, not HICP or health index."
    },
    {
      "rubricItem": "resolver",
      "severity": "blocking",
      "summary": "resolutionDate is 2026-09-29, but the provided canonical target context says to use the ledger fields as the resolutionDate contract and only provides the registered expectedReleaseWindow ending 2026-10-07.",
      "actionRequested": "Set resolutionDate to the registered ledger resolution date if present in the target file; if the ledger truly uses the window end as the bound, use 2026-10-07 and mention the Statbel calendar's 2026-09-29 planned release as evidence rather than silently changing the contract."
    }
  ],
  "optionalSuggestions": [
    "The prior/update/interval step is strong; keep the stated persistence prior, 13-month sample, adjustment components, sigma method, and implied bounds.",
    "Consider noting that be.STAT is supporting cross-check evidence, not the registered resolver URL, if it remains in sourceContext."
  ]
}

Emit the final JSON object only.
