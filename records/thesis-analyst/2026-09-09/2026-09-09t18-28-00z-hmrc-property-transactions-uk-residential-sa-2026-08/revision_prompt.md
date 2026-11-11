# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: hmrc.property_transactions.uk_residential_sa
- period: 2026-08
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "uk-residential-property-transactions-sa-august-2026"
- country: "UK"
- targetUnit: "count"
- dataPointId: "hmrc.property_transactions.uk_residential_sa.2026_08.first_print"
- expectedReleaseWindow: {"end": "2026-09-30", "start": "2026-09-30"}
- resolutionSourceUrl: "https://www.gov.uk/government/statistics/monthly-property-transactions-completed-in-the-uk-with-value-40000-or-above"
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.gov.uk"], "expectedReleaseWindow": {"end": "2026-09-30", "start": "2026-09-30"}, "field": "provisional seasonally adjusted estimate of the number of UK residential transactions", "releasePolicy": "first_print", "sourceSeriesId": "MPT_UK_RESIDENTIAL_SA", "sourceUrl": "https://www.gov.uk/government/statistics/monthly-property-transactions-completed-in-the-uk-with-value-40000-or-above", "table": "UK monthly property transactions tables", "transform": {"factor": 1, "operation": "identity"}}
- targetRegistrationPath: "records/targets/2026-09-09-4c090e13de6dd10b1a4aaadfee1f3e82662c6a2163e9ae9ce16f53d1950e740b.json"
- targetContentHash: "4c090e13de6dd10b1a4aaadfee1f3e82662c6a2163e9ae9ce16f53d1950e740b"
- registrationCommit: "178a51ccdef886b1402ac341feda74fc546c3091"
- registeredAtUtc: "2026-09-09T18:25:32Z"

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
{"slug":"uk-residential-property-transactions-sa-august-2026","country":"UK","type":"data","title":"UK Residential Transactions SA, August 2026","question":"HMRC Monthly Property Transactions provisional seasonally adjusted estimate of the number of UK residential transactions in August 2026, first print.","unit":"count","pointEstimate":95600,"ciLow":90500,"ciHigh":100700,"confidence":0.8,"resolutionDate":"2026-09-30","resolutionSource":"HMRC Monthly property transactions completed in the UK with value of GBP40,000 or above, UK monthly property transactions tables","resolutionSourceUrl":"https://www.gov.uk/government/statistics/monthly-property-transactions-completed-in-the-uk-with-value-40000-or-above","resolutionRule":"Resolve to the provisional seasonally adjusted estimate of the number of UK residential transactions for August 2026 in HMRC's first official Monthly property transactions completed in the UK with value of GBP40,000 or above release published on 2026-09-30, series code MPT_UK_RESIDENTIAL_SA, UK monthly property transactions tables. Use the count as published, rounded to the nearest ten; do not incorporate later revisions or replacement files after the first print.","dataPointId":"hmrc.property_transactions.uk_residential_sa.2026_08.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":94680},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":102410},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":103910},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":101030},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":98450},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":98700},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":96710}],"drivers":["July 2026 first print was 96,710 seasonally adjusted residential transactions","June 2026 was revised to 98,390 after an earlier provisional print near 98,700","August 2025 first print fell from July to 93,630","Mortgage approvals weakened in May and July 2026","Completions lag offers by roughly two to four months","April-to-July 2026 seasonally adjusted total stayed high at 393,800"],"sourceContext":["https://www.gov.uk/government/statistics/monthly-property-transactions-completed-in-the-uk-with-value-40000-or-above","https://www.gov.uk/government/statistics/monthly-property-transactions-completed-in-the-uk-with-value-40000-or-above/uk-monthly-property-transactions-commentary--2","https://www.gov.uk/government/statistics/announcements/monthly-property-transactions-completed-in-the-uk-with-the-value-of-40000-or-above--30","https://www.gov.uk/government/statistics/monthly-property-transactions-completed-in-the-uk-with-value-40000-or-above/uk-monthly-property-transactions-background-and-references","https://www.bankofengland.co.uk/statistics/money-and-credit/2026/april-2026","https://www.bankofengland.co.uk/statistics/money-and-credit/2026/may-2026","https://www.bankofengland.co.uk/statistics/money-and-credit/2026/july-2026"],"runAt":"2026-09-09T18:28:17Z","reasoning":[{"kind":"heading","text":"UK residential property transactions SA August 2026 forecast"},{"kind":"text","text":"Framing and exact resolver: the target is HMRC's provisional seasonally adjusted estimate of UK residential transactions for August 2026, first print only, in the Monthly property transactions tables. The variant is UK residential, seasonally adjusted, source series MPT_UK_RESIDENTIAL_SA; all transaction anchors here refer to that same variant."},{"kind":"tool","tool":"official.lookup","call":"Checked the GOV.UK statistics page and the GOV.UK official statistics announcement for the scheduled August 2026 property-transactions release.","result":"GOV.UK states the latest release was 09:30 on 28 August 2026 with July 2026 data, and the next release will be published at 09:30 on 30 September 2026 with August 2026 data; the announcement page lists release date 30 September 2026 9:30am provisional."},{"kind":"tool","tool":"official.lookup","call":"Fetched the latest HMRC GOV.UK commentary for the same seasonally adjusted UK residential series.","result":"HMRC's July 2026 provisional seasonally adjusted UK residential transactions estimate was 96,710, 1% lower than July 2025 and 2% lower than June 2026; the same page states June 2026 was 98,390 and July 2025 was 97,820."},{"kind":"tool","tool":"official.lookup","call":"Fetched HMRC recent-release history and same-month context from GOV.UK commentary and HMRC-cited public release reports.","result":"Recent provisional seasonally adjusted UK residential transaction prints used for the reference class were January 2026 94,680, February 2026 102,410, March 2026 103,910, April 2026 101,030, May 2026 98,450, June 2026 about 98,700 at first print before later revision to 98,390, and July 2026 96,710; August first prints were 87,010 in 2023, 90,210 in 2024, and 93,630 in 2025."},{"kind":"tool","tool":"official.lookup","call":"Fetched mortgage and pipeline indicators from Bank of England Money and Credit releases.","result":"Bank of England reported house-purchase mortgage approvals of 65,900 in April 2026, 56,200 in May 2026, 58,200 in June 2026, and 56,100 in July 2026; the newly drawn mortgage rate rose from 4.22% in May to 4.35% in June and 4.45% in July."},{"kind":"math","text":"Prior/update/interval: persistence prior is the July 2026 first-print level of 96,710, with a reference class/base rate from recent first-print-like monthly levels [94,680, 102,410, 103,910, 101,030, 98,450, 98,700, 96,710], mean 99,413. Adjustment components: level anchor 96,710; momentum -900 because July fell 2% from June and August 2025 also fell from July; one-off +300 because April-to-July 2026 seasonally adjusted transactions totalled 393,800 and August 2023-2025 same-month levels had been rising; policy/credit mechanism -500 because May-July mortgage approvals were around 56,100 to 58,200 after April's 65,900 and rates rose to 4.45%. Combined point is 96,710 - 900 + 300 - 500 = 95,610, rounded to 95,600. Interval method uses successive changes for this level series: changes are +7,730, +1,500, -2,880, -2,580, +250, -1,990, so sigma = 4007; 1.28*sigma = 5129. Point 95,600 +/- about 5,100 gives 90,500 to 100,700 after rounding to the nearest ten."},{"kind":"text","text":"Counter-considerations: upside risk is that high April approvals and resilient completed-sales pipelines carry more strongly into August than assumed, which would land above the interval if the first print exceeds 100,700. Downside risk is a sharper lagged response to May-July approval weakness, higher mortgage rates, or longer chains falling through, which would land outside the interval below 90,500. The main uncertainty is timing because HMRC notes these completions generally reflect offers made two to four months earlier."},{"kind":"forecast","point":95600,"ciLow":90500,"ciHigh":100700}]}

# Reviewer critique
{"summary":"The draft is publishable: resolver, prior/update/interval, tails, and JSON fields are coherent with the registered target.","requiredFixes":[],"optionalSuggestions":["Add the June 2026 Bank of England Money and Credit URL or avoid relying on exact June approval/rate figures if that source is not otherwise captured.","Note that the volatility estimate uses a short recent sample, so the 80% interval is mechanically derived but sample-limited."]}

Emit the final JSON object only.
