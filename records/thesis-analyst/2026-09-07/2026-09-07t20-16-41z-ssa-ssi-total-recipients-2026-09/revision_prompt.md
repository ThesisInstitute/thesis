# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: ssa.ssi.total_recipients
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "ssi-recipients-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "ssa.ssi.total_recipients.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-11-08", "start": "2026-10-31"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.ssa.gov"], "expectedReleaseWindow": {"end": "2026-11-08", "start": "2026-10-31"}, "field": "ssa.ssi.total_recipients", "releasePolicy": "first_print", "sourceSeriesId": "ssa.ssi.total_recipients", "sourceUrl": "https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2026-07/table02.html", "table": "Social Security Administration SSI Monthly Statistics", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-07-9509b1552284e3dcd59b3e1c6a6752efb3be2cf74e57824022343f3a837dde2f.json"
- targetContentHash: "9509b1552284e3dcd59b3e1c6a6752efb3be2cf74e57824022343f3a837dde2f"
- registrationCommit: "f1baea413714fe099f71118840f6363977fcdb5c"
- registeredAtUtc: "2026-09-07T20:04:45Z"

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
{"slug":"ssi-recipients-september-2026","country":"US","type":"data","title":"SSI recipients, September 2026","question":"Social Security Administration SSI Monthly Statistics Table 2, total number of recipients for all federally administered payments, September 2026, first print, converted to millions.","unit":"millions","pointEstimate":7.326,"ciLow":7.292,"ciHigh":7.36,"confidence":0.8,"resolutionDate":"2026-11-08","resolutionSource":"Social Security Administration SSI Monthly Statistics","resolutionSourceUrl":"https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2026-09/table02.html","resolutionRule":"Resolve to the first published September 2026 value in SSA SSI Monthly Statistics Table 2, row September 2026, column Total number of recipients for all federally administered payments. Use the whole-recipient first print from the Supplemental Security Record, 100 percent data, convert to millions by dividing by 1,000,000, and report to three decimals. Ignore later revisions or adjusted checks after the first September 2026 table is posted. The registered expected release window ends 2026-11-08; SSA's Publishing Schedule was checked this run and lists SSI Monthly Statistics as a monthly publication but did not expose a more specific September 2026 release day in the fetched text.","dataPointId":"ssa.ssi.total_recipients.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2025-07"},"label":"2025-07","value":7.394877},{"period":{"type":"month","value":"2025-08"},"label":"2025-08","value":7.405735},{"period":{"type":"month","value":"2025-09"},"label":"2025-09","value":7.436689},{"period":{"type":"month","value":"2025-10"},"label":"2025-10","value":7.393406},{"period":{"type":"month","value":"2025-11"},"label":"2025-11","value":7.391176},{"period":{"type":"month","value":"2025-12"},"label":"2025-12","value":7.392201},{"period":{"type":"month","value":"2026-01"},"label":"2026-01","value":7.36951},{"period":{"type":"month","value":"2026-02"},"label":"2026-02","value":7.358913},{"period":{"type":"month","value":"2026-03"},"label":"2026-03","value":7.351825},{"period":{"type":"month","value":"2026-04"},"label":"2026-04","value":7.338132},{"period":{"type":"month","value":"2026-05"},"label":"2026-05","value":7.322937},{"period":{"type":"month","value":"2026-06"},"label":"2026-06","value":7.323731},{"period":{"type":"month","value":"2026-07"},"label":"2026-07","value":7.300297}],"drivers":["July 2026 level fell to 7.300297 million","Recent monthly momentum is negative but not one-way","September has shown mixed but recently positive seasonal movement","No known 2026 SSI policy cliff large enough to dominate recipient counts","First-print whole-recipient SSA Table 2 value converted to millions"],"sourceContext":["https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2026-07/table02.html","https://www.ssa.gov/policy/pub_schedule.html","https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2025-09/table02.html","https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2024-09/table02.html","https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2023-09/table02.html","https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2022-09/table02.html"],"runAt":"2026-09-07T20:16:46Z","reasoning":[{"kind":"heading","text":"SSI total recipients September 2026"},{"kind":"text","text":"Exact resolver: SSA SSI Monthly Statistics Table 2, All Federally Administered Payments, Total number of recipients, September 2026 first print. The variant is unadjusted end-of-month recipients from the Supplemental Security Record, 100 percent data; all anchors below use the same Table 2 Total recipient variant."},{"kind":"tool","tool":"official.lookup","call":"Fetched SSA SSI Monthly Statistics, July 2026, Table 2 at the official ssa.gov table URL.","result":"Latest official Table 2 Total recipient prints fetched: 2026-02 7,358,913; 2026-03 7,351,825; 2026-04 7,338,132; 2026-05 7,322,937; 2026-06 7,323,731; 2026-07 7,300,297."},{"kind":"tool","tool":"official.lookup","call":"Fetched older official SSA September Table 2 pages for same-month and July-to-September reference class history.","result":"Official September Table 2 totals fetched: 2022-09 7,567,439; 2023-09 7,450,135; 2024-09 7,430,106; 2025-09 7,436,689. July-to-September changes were -22,869 in 2022, -24,600 in 2023, +20,432 in 2024, and +41,812 in 2025 recipients."},{"kind":"tool","tool":"official.lookup","call":"Checked SSA Publishing Schedule and the July 2026 SSI Monthly Statistics index for release-basis context.","result":"SSA Publishing Schedule fetched SSI Monthly Statistics as Monthly; the July 2026 SSI Monthly Statistics index says released August 2026, and its Table 2 July total is 7,300,297. The fetched schedule text did not expose a specific September 2026 release day, so I use the registered expectedReleaseWindow end 2026-11-08 as the resolutionDate bound."},{"kind":"text","text":"Base rate/reference class: the recent 13-print official Table 2 sample runs from 7.394877 million in 2025-07 to 7.300297 million in 2026-07, with average one-month change -0.007882 million. The four July-to-September same-variant moves average +0.003694 million but split between negative 2022-2023 and positive 2024-2025, so I avoid a strong seasonal lift."},{"kind":"math","text":"Prior/update/interval: Persistence prior starts from the latest same-variant SSA level, 7.300297 million in 2026-07. Historical sample is the 12 successive monthly changes in the 2025-07 through 2026-07 official Table 2 totals: mean change -0.007882 million and monthly sigma = 0.018722 million. Adjustment components: level +7.300297; momentum for two months -0.010 million, lighter than the raw recent average because September seasonality can reverse declines; seasonal/policy-mechanism add +0.036 million based on the 2024-2025 September lift and no major known eligibility-policy discontinuity. Point = 7.300297 - 0.010 + 0.036 = 7.326 million. For the two-month horizon, scaled sigma = 0.018722*sqrt(2) = 0.026477, so 1.28*sigma = 0.033891; rounded 80% bounds are 7.326 +/- 0.034 = 7.292 to 7.360 million."},{"kind":"text","text":"Counter-considerations: upside risk is another September processing jump like 2025, which would land above the interval if August and September together add more than about 60,000 recipients from July. Downside risk is continued administrative attrition like early 2026 plus weak new awards, which would land below the interval if the July level loses more than about 8,000 recipients by September. Outside the interval would require either a clear seasonal surge beyond the recent sample or another July-like monthly drop."},{"kind":"forecast","point":7.326,"ciLow":7.292,"ciHigh":7.36}]}

# Reviewer critique
{
  "summary": "Draft is broadly publishable but has a blocking resolver/source mismatch against the registered ledger contract.",
  "requiredFixes": [
    {
      "rubricItem": "resolver",
      "severity": "blocking",
      "summary": "The draft sets resolutionSourceUrl to the predicted September 2026 table URL, but the ledger sourceBinding sourceUrl is the registered SSA July 2026 Table 2 URL and the target is bounded by expectedReleaseWindow ending 2026-11-08.",
      "actionRequested": "Align the resolver/source text and URL with the registered target contract, or explicitly state any concrete ledger discrepancy while keeping the same target."
    },
    {
      "rubricItem": "resolver",
      "severity": "warning",
      "summary": "The resolutionRule says convert whole-recipient first print to millions by dividing by 1,000,000, while the registered sourceBinding transform is multiply by 0.001.",
      "actionRequested": "Clarify the source extraction unit so the stated conversion is consistent with the registered transform and final unit 'millions'."
    }
  ],
  "optionalSuggestions": [
    "The prior/update/interval step is strong; keep the explicit sigma and 80% bound arithmetic.",
    "The downside tail threshold could be restated relative to the final interval lower bound to make the tail math easier to audit."
  ]
}

Emit the final JSON object only.
