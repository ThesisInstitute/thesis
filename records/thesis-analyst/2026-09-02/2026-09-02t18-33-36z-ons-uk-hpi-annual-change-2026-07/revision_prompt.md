# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: ons.uk_hpi.annual_change
- period: 2026-07
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "uk-house-price-index-annual-rate-july-2026"
- country: "UK"
- targetUnit: "percent"
- dataPointId: "ons.uk_hpi.annual_change.2026_07.first_print"
- expectedReleaseWindow: {"end": "2026-09-16", "start": "2026-09-16"}
- resolutionSourceUrl: "https://www.gov.uk/government/collections/uk-house-price-index-reports"
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.gov.uk"], "expectedReleaseWindow": {"end": "2026-09-16", "start": "2026-09-16"}, "field": "Annual Change", "releasePolicy": "first_print", "sourceSeriesId": "UKHPI:K02000001:all-property-types:annual-change", "sourceUrl": "https://www.gov.uk/government/collections/uk-house-price-index-reports", "table": "UK House Price Index full file, United Kingdom row", "transform": {"factor": 1, "operation": "identity"}}
- targetRegistrationPath: "records/targets/2026-09-02-07be653389c2ef5984ed0ae11abda329a931f1585747e491ec5bbe0cc22d6670.json"
- targetContentHash: "07be653389c2ef5984ed0ae11abda329a931f1585747e491ec5bbe0cc22d6670"
- registrationCommit: "e915c43aeba83b903f1c01b7fd2df8ed8e2c8391"
- registeredAtUtc: "2026-09-02T18:31:06Z"

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
{"slug":"uk-house-price-index-annual-rate-july-2026","country":"UK","type":"data","title":"UK HPI Annual Change, July 2026","question":"First-print UK House Price Index full file Annual Change for the United Kingdom all-property-types series for July 2026, percent, not revised after first publication.","unit":"percent","pointEstimate":2.1,"ciLow":0.4,"ciHigh":3.8,"confidence":0.8,"resolutionDate":"2026-09-16","resolutionSource":"HM Land Registry UK House Price Index full file, United Kingdom row","resolutionSourceUrl":"https://www.gov.uk/government/collections/uk-house-price-index-reports","resolutionRule":"Resolve to the Annual Change value in the first official July 2026 UK House Price Index full file for sourceSeriesId UKHPI:K02000001:all-property-types:annual-change, United Kingdom row. Use the first print published on 2026-09-16 and do not incorporate later revisions, same-day corrections, or replacement files unless the original first print is withdrawn before a numeric value is available. Record the published percent value as reported.","dataPointId":"ons.uk_hpi.annual_change.2026_07.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":1.3},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":1.2},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":0.0},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":3.8},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":2.7},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":2.0}],"drivers":["June first-print persistence near 2.0 percent","July 2025 base month was a modest 0.3 percent monthly rise","Mortgage approvals softened in July","Transactions data mixed with seasonally adjusted decline but non-seasonally adjusted rise","April-to-June annual-rate volatility driven by SDLT base effects"],"sourceContext":["https://www.gov.uk/government/collections/uk-house-price-index-reports","https://www.gov.uk/government/publications/about-the-uk-house-price-index/about-the-uk-house-price-index","https://www.gov.uk/government/statistical-data-sets/uk-house-price-index-data-downloads-june-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-june-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-may-2026/uk-house-price-index-summary-may-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-april-2026/uk-house-price-index-summary-april-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-march-2026/uk-house-price-index-summary-march-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-february-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-january-2026/uk-house-price-index-summary-january-2026","https://www.gov.uk/government/statistics/uk-house-price-index-for-july-2025/uk-house-price-index-summary-july-2025","https://www.bankofengland.co.uk/statistics/money-and-credit/2026/july-2026","https://www.gov.uk/government/statistics/monthly-property-transactions-completed-in-the-uk-with-value-40000-or-above/uk-monthly-property-transactions-commentary--2"],"runAt":"2026-09-02T18:34:15Z","reasoning":[{"kind":"heading","text":"UK HPI July 2026 annual-change forecast"},{"kind":"text","text":"Framing and exact resolver: the target is the UK House Price Index full-file Annual Change field for sourceSeriesId UKHPI:K02000001:all-property-types:annual-change, United Kingdom row, July 2026, first print only. The registered ledger source URL is the GOV.UK UK HPI reports collection; the exact resolving artifact should be the July 2026 data-download full file linked from that collection."},{"kind":"tool","tool":"official.lookup","call":"Checked GOV.UK About the UK House Price Index calendar release dates and UK HPI reports collection.","result":"The official calendar lists July 2026 UK HPI publication at 9:30am on 16 September 2026; the reports collection also states the July 2026 UK HPI will be published at 9.30am on Wednesday 16 September 2026."},{"kind":"tool","tool":"official.lookup","call":"Fetched recent official UK HPI headline annual-change prints for the UK from GOV.UK UK HPI monthly summary/report pages.","result":"Recent UK annual price-change prints fetched: January 2026 1.3%, February 2026 1.2%, March 2026 0.0%, April 2026 3.8%, May 2026 2.7%, June 2026 2.0%; June also reported monthly change 0.1% and average price GBP272,000."},{"kind":"tool","tool":"official.lookup","call":"Fetched base-effect anchors from GOV.UK UK HPI July 2025 summary and June 2026 report.","result":"July 2025 UK HPI summary reported annual change 2.8%, monthly change 0.3%, and average price GBP270,000; June 2026 report reported annual change 2.0%, monthly change 0.1%, and noted the rate was down from a revised May 2026 estimate of 3.0%."},{"kind":"tool","tool":"official.lookup","call":"Fetched housing-demand and transactions indicators from Bank of England Money and Credit July 2026 and HMRC monthly property transactions commentary.","result":"Bank of England reported house-purchase mortgage approvals decreased to 56,100 in July 2026 from 58,200 in June, net mortgage borrowing decreased to GBP4.3bn from GBP7.7bn, and the newly drawn mortgage rate rose to 4.45% from 4.35%; HMRC reported July 2026 seasonally adjusted residential transactions of 96,710, 2% lower than June 2026, and non-seasonally adjusted residential transactions of 106,620, 3% higher than June 2026."},{"kind":"math","text":"Prior/update/interval: persistence prior is the June 2026 UK HPI annual change of 2.0%, with a reference class/base rate from the six recent first-print annual changes [1.3, 1.2, 0.0, 3.8, 2.7, 2.0], whose mean is 1.83%. For the level-to-annual update, June annual 2.0 plus forecast July 2026 monthly change 0.4 minus July 2025 monthly base 0.3 gives 2.1%. Components: level 2.0, momentum +0.1 from normal summer monthly gain versus the 0.3% base month, one-off SDLT base effect mostly fading after the April spike, policy/credit mechanism -0.1 from softer approvals and higher mortgage rates, offset by still-positive completions. Interval method uses the fetched annual-change values themselves because this is a change-rate series: sample sigma = 1.32, so 1.28*sigma = 1.69; point 2.1 +/- 1.7 gives an 80% interval of 0.4 to 3.8 after rounding."},{"kind":"text","text":"Counter-considerations: upside risk is a stronger-than-assumed July NSA price gain if late spring completions and Northern Ireland/Scotland strength lift the UK aggregate, which would land above the interval if the first-print annual change exceeds 3.8%. Downside risk is a sharper credit-led fall or weak London/southern England mix effect, which would land outside the interval below 0.4%. The most important falsifier is a large July 2026 monthly move rather than a revision, because resolution is first print only."},{"kind":"forecast","point":2.1,"ciLow":0.4,"ciHigh":3.8}]}

# Reviewer critique
{
  "summary": "Draft is publishable with no blocking issues; it states the resolver, prior, update, interval math, and JSON fields coherently.",
  "requiredFixes": [
    {
      "rubricItem": "interval",
      "severity": "warning",
      "summary": "The interval uses dispersion of recent annual-change levels, not realized forecast error or month-to-month annual-rate volatility.",
      "actionRequested": "Either relabel this as an explicit uncertainty choice or briefly justify why recent level dispersion is the intended proxy for 80% forecast uncertainty."
    }
  ],
  "optionalSuggestions": [
    "Clarify that the 0.4% July 2026 monthly assumption is a forecast assumption, not an observed value.",
    "Keep the first-print wording tightly aligned to the ledger rule if same-day corrections have a defined treatment elsewhere."
  ]
}

Emit the final JSON object only.
