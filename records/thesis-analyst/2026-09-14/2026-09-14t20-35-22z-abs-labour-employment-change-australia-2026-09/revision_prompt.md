# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: abs.labour.employment_change.australia
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "abs-labour-employment-change-australia-september-2026"
- country: "AU"
- targetUnit: "thousands"
- dataPointId: "abs.labour.employment_change.australia.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-10-28", "start": "2026-10-20"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["data.api.abs.gov.au"], "expectedReleaseWindow": {"end": "2026-10-28", "start": "2026-10-20"}, "field": "LF/M3.3.1599.20.AUS.M", "releasePolicy": "first_print", "sourceSeriesId": "LF/M3.3.1599.20.AUS.M", "sourceUrl": "https://data.api.abs.gov.au/rest/data/LF/M3.3.1599.20.AUS.M?lastNObservations=30&format=jsondata", "table": "Labour Force, Australia (dataflow LF: employed persons, seasonally adjusted, Australia; month-over-month change)", "transform": {"factor": 1, "operation": "identity"}}
- targetRegistrationPath: "records/targets/2026-09-14-cb50e4f977134dd7052ae03768ee9c2e2d2606387498938baded80a6d1baf32b.json"
- targetContentHash: "cb50e4f977134dd7052ae03768ee9c2e2d2606387498938baded80a6d1baf32b"
- registrationCommit: "0f2c009b27e9b65c2aeb9b253934fd8b301b787e"
- registeredAtUtc: "2026-09-14T20:23:15Z"

# Source hints
- Use ABS release calendar and official monthly CPI indicator pages.
- Australia CPI indicator rates print to one decimal.
- Resolution source should be the ABS release page.

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
{"slug":"abs-labour-employment-change-australia-september-2026","country":"AU","type":"data","title":"Australia Employment Change, September 2026","question":"What will the Australian Bureau of Statistics first print for Labour Force, Australia series LF/M3.3.1599.20.AUS.M, seasonally adjusted employed persons month-over-month change, Australia, for September 2026, in thousands?","unit":"thousands","pointEstimate":18,"ciLow":-28.7,"ciHigh":64.7,"confidence":0.8,"resolutionDate":"2026-10-28","resolutionSource":"Australian Bureau of Statistics Data API, Labour Force LF/M3.3.1599.20.AUS.M","resolutionSourceUrl":"https://data.api.abs.gov.au/rest/data/LF/M3.3.1599.20.AUS.M?lastNObservations=30&format=jsondata","resolutionRule":"Resolve to the first observed September 2026 API observation for ABS Labour Force series LF/M3.3.1599.20.AUS.M: seasonally adjusted employed persons, Australia, month-over-month change, in thousands. Use the first official ABS Labour Force, Australia release/API print for the September 2026 reference period; ignore all later revisions or corrections. The official ABS release page currently schedules that first print for 15 October 2026, while the registered target contract sets resolutionDate to 2026-10-28, so this cell keeps the registered date and records the discrepancy.","dataPointId":"abs.labour.employment_change.australia.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2025-06"},"label":"2025-06","value":-25.2},{"period":{"type":"month","value":"2025-07"},"label":"2025-07","value":46},{"period":{"type":"month","value":"2025-08"},"label":"2025-08","value":-14.6},{"period":{"type":"month","value":"2025-09"},"label":"2025-09","value":9.3},{"period":{"type":"month","value":"2025-10"},"label":"2025-10","value":33.2},{"period":{"type":"month","value":"2025-11"},"label":"2025-11","value":-39.2},{"period":{"type":"month","value":"2025-12"},"label":"2025-12","value":57.3},{"period":{"type":"month","value":"2026-01"},"label":"2026-01","value":36.1},{"period":{"type":"month","value":"2026-02"},"label":"2026-02","value":22.1},{"period":{"type":"month","value":"2026-03"},"label":"2026-03","value":20},{"period":{"type":"month","value":"2026-04"},"label":"2026-04","value":-34.9},{"period":{"type":"month","value":"2026-05"},"label":"2026-05","value":38.1},{"period":{"type":"month","value":"2026-06"},"label":"2026-06","value":80.3},{"period":{"type":"month","value":"2026-07"},"label":"2026-07","value":-15.8}],"drivers":["Recent same-series mean remains positive but volatile","July first print was negative after a strong June gain","Trend employment still rose in July","No August 2026 official print was available at run time","Official ABS schedule differs from the registered outer-bound resolution date"],"sourceContext":["https://data.api.abs.gov.au/rest/data/LF/M3.3.1599.20.AUS.M?lastNObservations=30&format=jsondata","https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia","https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/jul-2026","https://www.abs.gov.au/articles/update-labour-force-modernisation-and-future-release-plans"],"runAt":"2026-09-14T20:35:38Z","reasoning":[{"kind":"heading","text":"Australia September 2026 employment change first-print forecast"},{"kind":"text","text":"Framing and exact resolver: this is the ABS Labour Force, Australia first print for September 2026, series LF/M3.3.1599.20.AUS.M, seasonally adjusted employed persons, Australia, month-over-month change in thousands. Anchors use the same seasonally adjusted employed-person variant, not trend, original, hours, unemployment, or participation."},{"kind":"tool","tool":"official.lookup","call":"Inspect ABS Labour Force, Australia current release page future-release section and Labour Force Modernisation schedule article.","result":"Fetched official schedule numbers: Labour Force, Australia, August 2026 release date 24/09/2026 11:30am AEST; September 2026 release date 15/10/2026 11:30am AEDT; October 2026 release date 19/11/2026 11:30am AEDT. The registered target contract instead lists resolutionDate 2026-10-28."},{"kind":"tool","tool":"official.lookup","call":"Inspect ABS Labour Force, Australia July 2026 release key statistics and employment table.","result":"Fetched latest official print numbers: June 2026 seasonally adjusted employed people 14,823,100; July 2026 seasonally adjusted employed people 14,807,200; July monthly change -15,800, i.e. -15.8 thousand; July unemployment rate 4.5 percent; July trend employment monthly change +29,300, i.e. +29.3 thousand."},{"kind":"tool","tool":"official.lookup","call":"Read ABS July 2026 release employment table for same-variant recent seasonally adjusted employed-person levels.","result":"Fetched recent seasonally adjusted levels in thousands: 2025-05 14594.6, 2025-06 14569.4, 2025-07 14615.4, 2025-08 14600.8, 2025-09 14610.1, 2025-10 14643.3, 2025-11 14604.1, 2025-12 14661.4, 2026-01 14697.5, 2026-02 14719.6, 2026-03 14739.6, 2026-04 14704.7, 2026-05 14742.8, 2026-06 14823.1, 2026-07 14807.2."},{"kind":"tool","tool":"python.compute","call":"Compute month-over-month changes and dispersion from the fetched ABS seasonally adjusted levels, using the ABS headline July change where available.","result":"Computed same-variant employment changes in thousands: 2025-06 -25.2, 2025-07 +46.0, 2025-08 -14.6, 2025-09 +9.3, 2025-10 +33.2, 2025-11 -39.2, 2025-12 +57.3, 2026-01 +36.1, 2026-02 +22.1, 2026-03 +20.0, 2026-04 -34.9, 2026-05 +38.1, 2026-06 +80.3, 2026-07 -15.8; mean +15.19, median +21.05, sample sigma 36.48."},{"kind":"text","text":"Base rate / reference class: the recent official-source reference class is the 14 same-series seasonally adjusted monthly employment changes from 2025-06 through 2026-07. The base rate is a positive but noisy monthly gain: mean +15.2 thousand, median +21.1 thousand, with swings from -39.2 to +80.3 thousand."},{"kind":"text","text":"Level, momentum, one-off, and policy-mechanism effects: the level remains high at 14,807.2 thousand employed people in July, while momentum is mixed because the +80.3 thousand June surge was followed by -15.8 thousand in July. One-off survey and rotation effects are material in this series, especially around large adjacent moves. No policy mechanism suggests a discrete September employment break, and the July unemployment rate at 4.5 percent argues against a large positive demand surprise."},{"kind":"math","text":"Prior/update/interval: prior = persistence toward the recent official-source mean/median reference class, with historical sample 2025-06 through 2026-07 changes. Adjustment components = +15.2 thousand base-rate mean, +4.8 thousand for the +21.1 thousand median and +29.3 thousand July trend gain, -2.0 thousand for the July negative SA print and 4.5 percent unemployment, giving point = 15.2 + 4.8 - 2.0 = 18.0 thousand. Interval method uses the values themselves for this change/flow series; sigma = 36.48 thousand, and 80% half-width = 1.28*sigma = 1.28*36.48 = 46.69 thousand. Final implied bounds = 18.0 - 46.69 = -28.69 and 18.0 + 46.69 = 64.69, rounded to [-28.7, 64.7]."},{"kind":"text","text":"Counter-considerations: upside risk is another broad hiring rebound or favourable rotation-group draw after July, which would land above the interval if September employment change exceeds +64.7 thousand. Downside risk is a sharper labour-demand cooling or payback from June and July volatility, which would land below the interval if the first print is less than -28.7 thousand. An outside the interval outcome would most likely require a survey shock comparable to the largest recent positive or negative months."},{"kind":"text","text":"Prior-run update: the public August target run used a recent-mean strategy through June 2026 and centered near +21 thousand; adding the official July -15.8 thousand print and the current ABS release table lowers the center modestly to +18.0 thousand and leaves realized dispersion near the prior run's broad interval scale."},{"kind":"forecast","point":18,"ciLow":-28.7,"ciHigh":64.7}]}

# Reviewer critique
{
  "summary": "Draft is publication-ready on forecast substance, but the resolver date discrepancy needs a blocking fix because it conflicts with the canonical ledger contract.",
  "requiredFixes": [
    {
      "rubricItem": "resolver",
      "severity": "blocking",
      "summary": "The resolutionRule says the official ABS page currently schedules the September 2026 first print for 15 October 2026 while the registered contract sets resolutionDate to 2026-10-28; this creates an unresolved contract discrepancy inside the cell.",
      "actionRequested": "Either remove the asserted 15 October schedule claim unless it is formally accepted as a ledger discrepancy, or keep the registered resolutionDate 2026-10-28 and state more narrowly that the cell follows the ledger's resolve-by-bound contract despite observed schedule evidence."
    }
  ],
  "optionalSuggestions": [
    "The prior/update/interval step is strong; consider making the historical sample label explicitly say 14 monthly changes from 2025-06 through 2026-07.",
    "The tail scenarios are adequate, but could name concrete labor-market mechanisms such as survey rotation, hiring slowdown, or rebound from prior-month volatility."
  ]
}

Emit the final JSON object only.
