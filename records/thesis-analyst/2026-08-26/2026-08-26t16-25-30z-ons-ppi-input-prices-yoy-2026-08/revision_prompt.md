# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: ons.ppi.input_prices_yoy
- period: 2026-08
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "uk-ppi-input-prices-annual-rate-august-2026"
- country: "UK"
- targetUnit: "percent_growth"
- dataPointId: "ons.ppi.input_prices_yoy.2026_08.first_print"
- expectedReleaseWindow: {"end": "2026-09-16", "start": "2026-09-16"}
- resolutionSourceUrl: "https://www.ons.gov.uk/releases/producerpriceinflationukaugust2026timeseries"
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.ons.gov.uk"], "expectedReleaseWindow": {"end": "2026-09-16", "start": "2026-09-16"}, "field": "Total input producer prices, 12-month percentage change", "releasePolicy": "first_print", "sourceSeriesId": "PPI:GHIP", "sourceUrl": "https://www.ons.gov.uk/releases/producerpriceinflationukaugust2026timeseries", "table": "Producer price inflation time series", "transform": {"factor": 1, "operation": "identity"}}
- targetRegistrationPath: "records/targets/2026-08-26-2c4797e85af3bb173fcc595dd241efba3eea6d9f2c854085b8195f60588ba1b6.json"
- targetContentHash: "2c4797e85af3bb173fcc595dd241efba3eea6d9f2c854085b8195f60588ba1b6"
- registrationCommit: "b4f1d890f91c9ece5fc1e068a92fbe28ea25be43"
- registeredAtUtc: "2026-08-26T16:23:02Z"

# Source hints
- Use ONS time-series pages, ONS API, and ONS release calendar.
- UK CPI/CPIH prints to one decimal; labour-market rates print to one decimal.
- Resolution source should be the relevant ONS release or time-series page.

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
{"slug":"uk-ppi-input-prices-annual-rate-august-2026","country":"UK","type":"data","title":"UK PPI Input Prices Annual Rate, August 2026","question":"What will the Office for National Statistics first report for the UK Producer Price Inflation total input producer prices 12-month percentage change, All materials and fuels purchased (GHIP), for August 2026?","unit":"percent_growth","pointEstimate":5.1,"ciLow":0.6,"ciHigh":9.6,"confidence":0.8,"resolutionDate":"2026-09-16","resolutionSource":"Office for National Statistics Producer price inflation, UK: August 2026 time series","resolutionSourceUrl":"https://www.ons.gov.uk/releases/producerpriceinflationukaugust2026timeseries","resolutionRule":"Resolve to the first value published by ONS for August 2026 in Producer price inflation, UK: August 2026 time series for Total input producer prices, 12-month percentage change, All materials and fuels purchased (GHIP), in percent_growth and rounded as printed by ONS, normally one decimal place. Use the first official print only and ignore later revisions, corrections, and superseded versions.","dataPointId":"ons.ppi.input_prices_yoy.2026_08.first_print","historicalContext":[{"period":{"type":"month","value":"2025-08"},"label":"August 2025","value":0.3},{"period":{"type":"month","value":"2025-09"},"label":"September 2025","value":0.9},{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":0.9},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":1.1},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":0.5},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":-0.2},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":0.7},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":5.5},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":8.1},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":9.2},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":7.4},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":4.9}],"drivers":["July GHIP annual rate fell to 4.9% after 7.4% in June","July GHIP index of 164.5 against August 2025 index of 156.8 implies about 4.9% year-over-year if August 2026 is flat on the month","Recent monthly input PPI momentum was negative at -1.9% in June and -1.7% in July","Crude oil drove the July decline with an 18.0% monthly fall but other input groups remained mostly positive on an annual basis","Metals and chemicals still supported the annual rate at 8.4% and 6.1% in July"],"sourceContext":["https://www.ons.gov.uk/releases/producerpriceinflationukaugust2026timeseries","https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/producerpriceinflation/july2026","https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/ghip/ppi"],"runAt":"2026-08-26T16:25:41Z","reasoning":[{"kind":"heading","text":"UK PPI Input Prices Annual Rate, August 2026"},{"kind":"text","text":"Framing and resolver: the target is the ONS first print for the August 2026 total input producer prices 12-month percentage change, All materials and fuels purchased, series/table GHIP, in percent_growth. The registered August 2026 release page says this not-yet-published time series release is scheduled for 16 September 2026 at 7:00am, so I keep the ledger resolutionDate and first-print-only rule."},{"kind":"tool","tool":"official.lookup","call":"Open ONS August 2026 PPI time series release placeholder","result":"Fetched ONS release page for Producer price inflation, UK: August 2026 time series: release date 16 September 2026 7:00am; page status says not yet published; registered target field remains GHIP August 2026 first print."},{"kind":"tool","tool":"official.lookup","call":"Read ONS Producer price inflation, UK: July 2026 Table 1 for GHIP annual rates","result":"Fetched GHIP annual inflation rates from ONS Table 1: August 2025 0.3, September 2025 0.9, October 2025 0.9, November 2025 1.1, December 2025 0.5, January 2026 -0.2, February 2026 0.7, March 2026 5.5, April 2026 8.1, May 2026 9.2, June 2026 7.4, July 2026 4.9 percent."},{"kind":"tool","tool":"official.lookup","call":"Read ONS Producer price inflation, UK: July 2026 Table 1 for GHIP index and monthly-rate mechanics","result":"Fetched GHIP index and monthly rates: July 2025 index 156.7 with monthly rate 0.6 and annual rate -0.1; August 2025 index 156.8 with monthly rate 0.0 and annual rate 0.3; June 2026 index 167.3 with monthly rate -1.9 and annual rate 7.4; July 2026 index 164.5 with monthly rate -1.7 and annual rate 4.9."},{"kind":"tool","tool":"official.lookup","call":"Read ONS July 2026 input-price component discussion for current-release drivers","result":"Fetched component drivers from ONS July 2026 release: crude oil input prices fell 18.0% on the month and were up 10.6% on the year; metals and non-metallic mineral products were up 8.4% on the year; chemicals were up 6.1%; domestic food was down 1.6%; imported food was up 1.0%."},{"kind":"text","text":"Base rate / reference class: for the same GHIP annual-rate variant, the latest 12 official monthly annual rates average 3.275 percentage points, but that mixes a low-inflation period through February with a March-May jump and a June-July unwind. A persistence base rate from the July 2026 annual rate of 4.9% is more targeted for a one-month-ahead first print, while the 12-month sample controls the interval width."},{"kind":"math","text":"Prior/update/interval: persistence prior = July 2026 GHIP annual rate 4.9%; historical sample = August 2025 through July 2026 annual rates [0.3, 0.9, 0.9, 1.1, 0.5, -0.2, 0.7, 5.5, 8.1, 9.2, 7.4, 4.9]; adjustment components = +0.2 percentage point because July's index 164.5 over the August 2025 base index 156.8 mechanically gives 4.9% if August is flat, while non-oil inputs still show positive annual pressure despite negative recent crude-oil momentum. Interval method = sample dispersion of recent annual-rate values, sigma = 3.49 percentage points, and 80% half-width = 1.28*sigma = 1.28*3.49 = 4.47 percentage points. Point = 4.9 + 0.2 = 5.1; interval = 5.1 +/- 4.5 = [0.6, 9.6] after one-decimal rounding."},{"kind":"text","text":"Counter-considerations: downside risk outside the interval would require another large August fall in crude oil or imported input prices plus weaker metals and chemicals, pushing the annual rate below 0.6%. Upside risk outside the interval would require a renewed energy or precious-metals shock that lifts August input prices sharply enough to land above 9.6%. The central case is a near-flat to modestly positive August index after two sharp monthly declines."},{"kind":"forecast","point":5.1,"ciLow":0.6,"ciHigh":9.6}]}

# Reviewer critique
{"summary":"The draft is publishable: resolver fields match the ledger target, the first-print rule and unit are clear, and the prior/update/interval logic is coherent.","requiredFixes":[],"optionalSuggestions":["Consider making the base-rate sentence appear before the current-evidence bullets in the final trace, even though the compact math step already separates prior and update clearly."]}

Emit the final JSON object only.
