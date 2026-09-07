# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: fns.snap.total_persons
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "snap-participation-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "usda.fns.snap.persons.september_2026"
- expectedReleaseWindow: {"end": "2027-02-15", "start": "2027-02-07"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.fns.usda.gov"], "expectedReleaseWindow": {"end": "2027-02-15", "start": "2027-02-07"}, "field": "Persons", "releasePolicy": "first_print", "sourceSeriesId": "fns.snap.total_persons", "sourceUrl": "https://www.fns.usda.gov/pd/supplemental-nutrition-assistance-program-snap", "table": "FNS SNAP data tables, national monthly participation (thousands)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-07-c75aaa27f9ca01b95b9261fe1d397216de66021ff374c9ad807e6ca69dca9672.json"
- targetContentHash: "c75aaa27f9ca01b95b9261fe1d397216de66021ff374c9ad807e6ca69dca9672"
- registrationCommit: "f1baea413714fe099f71118840f6363977fcdb5c"
- registeredAtUtc: "2026-09-07T20:04:45Z"

# Source hints
- Use USDA FNS program-data pages, official data tables, and the FNS data release calendar.
- For SNAP, WIC, and QC targets, distinguish annual fiscal-year quality-control releases from monthly participation tables.
- If the catalog unit is millions, convert official person counts to millions in the emitted cell.

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
{"slug":"snap-participation-september-2026","country":"US","type":"data","title":"US SNAP participation, September 2026","question":"USDA FNS SNAP Data Tables national monthly Persons for September 2026, first print, converted to millions","unit":"millions","pointEstimate":34.422,"ciLow":33.819,"ciHigh":35.026,"confidence":0.8,"resolutionDate":"2027-02-15","resolutionSource":"FNS SNAP data tables, national monthly participation (thousands)","resolutionSourceUrl":"https://www.fns.usda.gov/pd/supplemental-nutrition-assistance-program-snap","resolutionRule":"Resolve to the first value published by USDA FNS for September 2026 in the SNAP Data Tables national monthly Persons field in the Persons, Households, Benefits, and Average Monthly Benefit per Person and Household table. Express the published Persons count in millions, rounded to three decimals for display. Use the first official print only and ignore later revisions, backfills, same-day corrections, or subsequent workbook/PDF updates.","dataPointId":"usda.fns.snap.persons.september_2026","historicalContext":[{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":41.09666},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":39.99989},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":39.207898},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":38.552133},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":37.947123},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":37.531152},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":37.078596},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":36.562128}],"drivers":["latest official May 2026 level was 36.562 million persons","recent monthly declines averaged about 0.498 million over January-May 2026","large FY2026 downtrend dominates short-horizon persistence","policy and administrative tightening risk further participation losses","first-print target uses unrevised FNS monthly national Persons table"],"sourceContext":["https://www.fna.usda.gov/pd/supplemental-nutrition-assistance-program-snap","https://fns-prod.azureedge.us/sites/default/files/resource-files/snap-4fymonthly-8.pdf","https://www.fna.usda.gov/data-research"],"runAt":"2026-09-07T20:14:23Z","reasoning":[{"kind":"heading","text":"September 2026 SNAP persons forecast"},{"kind":"text","text":"Framing and exact resolver: this targets the USDA FNS SNAP national monthly Persons field for September 2026, first print only, from the SNAP Data Tables. The current FNS PDF displays Persons as whole-person counts, for example 36,562,128 for May 2026; I convert those counts to millions for this cell while preserving the registered target unit and dataPointId."},{"kind":"tool","tool":"official.lookup","call":"Opened the current FNA SNAP Data Tables page for source identity and latest available monthly table.","result":"The official SNAP Data Tables page says the FY 23 through FY 26 National View Summary has Latest Available Month: May 2026, and the page was updated August 20, 2026."},{"kind":"tool","tool":"official.lookup","call":"Opened the August 2026 SNAP national monthly participation PDF and read FY2026 monthly Persons values.","result":"The PDF is Data as of August 14, 2026 and reports FY2026 Persons of 41,096,660 in Oct 2025, 39,999,890 in Nov 2025, 39,207,898 in Dec 2025, and 38,552,133 in Jan 2026."},{"kind":"tool","tool":"official.lookup","call":"Read the latest FY2026 monthly Persons values from the same SNAP national monthly participation PDF.","result":"The same PDF reports Persons of 37,947,123 in Feb 2026, 37,531,152 in Mar 2026, 37,078,596 in Apr 2026, and 36,562,128 in May 2026."},{"kind":"tool","tool":"official.calendar","call":"Checked official FNA data-and-research publication listings and the registered bounded target schedule for release timing.","result":"The official FNA listing shows May 2026 Keydata Report dated 08/10/2026, May 2026 Performance Report dated 08/12/2026, April 2026 Keydata Report dated 07/15/2026, and March 2026 reports dated 06/18/2026; the registered target window for September 2026 is 2027-02-07 to 2027-02-15, so this cell keeps the registered resolutionDate 2027-02-15."},{"kind":"text","text":"The outside-view base rate/reference class is a short monthly persistence model on the same official FNS national Persons variant. The latest level is 36.562128 million in May 2026, with seven observed month-to-month changes from October 2025 through May 2026: -1.096770, -0.791992, -0.655765, -0.605010, -0.415971, -0.452556, and -0.516468 million."},{"kind":"text","text":"Level effect starts at 36.562128 million. Momentum effect uses the more recent four-change average from Jan-May 2026, -0.497501 million per month, rather than the full seven-change mean of -0.647790 because the earliest FY2026 drops look unusually front-loaded. One-off/policy mechanism adds -0.150 million by September for continued eligibility and administrative tightening, but no separate disaster-assistance adjustment is added."},{"kind":"math","text":"Prior/update/interval: persistence prior = latest official May 2026 level of 36.562128 million; historical sample = Oct 2025-May 2026 same-table Persons values listed above. Successive changes are -1.096770, -0.791992, -0.655765, -0.605010, -0.415971, -0.452556, and -0.516468 million; their sample standard deviation gives sigma = 0.235716 million. Point = 36.562128 + 4*(-0.497501) - 0.150 = 34.422123 million, rounded to 34.422. The one-month 80% half-width is 1.28*sigma = 1.28*0.235716 = 0.301717 million; for a four-month horizon I scale by sqrt(4), giving 0.603434 million. Bounds are 34.422123 - 0.603434 = 33.818689 and 34.422123 + 0.603434 = 35.025557, rounded to 33.819 and 35.026."},{"kind":"text","text":"Upside risk is that the early FY2026 enrollment drop stabilizes quickly, state backlogs or recertifications raise the September count, or disaster-related reporting adds participants; that would land above the interval if September exceeds 35.026 million. Downside risk is faster eligibility loss, stronger work-requirement implementation, or administrative churn continuing near the Oct-Jan decline pace; that would land below the interval if September is under 33.819 million. The outside the interval cases are therefore a clear stabilization above 35.026 or an accelerated drop below 33.819."},{"kind":"forecast","point":34.422,"ciLow":33.819,"ciHigh":35.026}]}

# Reviewer critique
{
  "summary": "The forecast is mostly coherent, but it needs source URL cleanup and better support for the policy-tightening adjustment before publication.",
  "requiredFixes": [
    {
      "rubricItem": "resolver",
      "severity": "warning",
      "summary": "The main resolutionSourceUrl is correct, but sourceContext and reasoning repeatedly cite `fna.usda.gov` instead of the registered FNS host `www.fns.usda.gov`.",
      "actionRequested": "Replace the typo URLs and text references with the registered USDA FNS SNAP page URL and host."
    },
    {
      "rubricItem": "update",
      "severity": "warning",
      "summary": "The -0.150 million policy/administrative tightening adjustment is not tied to a concrete cited policy, administrative change, or observed evidence beyond the recent trend.",
      "actionRequested": "Either cite and describe the specific current evidence supporting the additional -0.150 million adjustment, or remove/reduce it and leave the point driven by the stated persistence model."
    }
  ],
  "optionalSuggestions": [
    "State explicitly that 2027-02-15 is the registered resolve-by-bound date at the end of the expected release window, not an official FNS announced release date.",
    "Clarify whether the interval only reflects monthly residual volatility, since it does not separately widen for uncertainty in the trend choice or policy adjustment."
  ]
}

Emit the final JSON object only.
