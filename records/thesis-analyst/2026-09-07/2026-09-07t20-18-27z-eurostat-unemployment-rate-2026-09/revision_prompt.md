# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: eurostat.unemployment_rate
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "euro-area-unemployment-rate-september-2026"
- country: "EA"
- targetUnit: "percent"
- dataPointId: "eurostat.unemployment_rate.euro_area.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-11-09", "start": "2026-11-01"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["ec.europa.eu"], "expectedReleaseWindow": {"end": "2026-11-09", "start": "2026-11-01"}, "field": "PC_ACT", "releasePolicy": "first_print", "sourceSeriesId": "une_rt_m/M.SA.TOTAL.PC_ACT.T.EA21", "sourceUrl": "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA21?format=JSON", "table": "Unemployment by sex and age (une_rt_m), euro area, SA, total; first print captured between monthly releases", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-07-233992db438bc52d1f79f1d0e676ac61ba4b526f50fbfbcc6e76f4996094e095.json"
- targetContentHash: "233992db438bc52d1f79f1d0e676ac61ba4b526f50fbfbcc6e76f4996094e095"
- registrationCommit: "f1baea413714fe099f71118840f6363977fcdb5c"
- registeredAtUtc: "2026-09-07T20:04:45Z"

# Source hints
- Use Eurostat euro-indicators release calendar and official HICP/IP pages.
- Euro-area HICP rates print to one decimal.
- Resolution source should be the Eurostat release/data page.

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
{"slug":"euro-area-unemployment-rate-september-2026","country":"EA","type":"data","title":"Euro area unemployment, September 2026","question":"What will Eurostat first publish for the euro area 21-country seasonally adjusted total unemployment rate, unit PC_ACT, series une_rt_m/M.SA.TOTAL.PC_ACT.T.EA21, for September 2026?","unit":"percent","pointEstimate":6.4,"ciLow":6.2,"ciHigh":6.6,"confidence":0.8,"resolutionDate":"2026-11-09","resolutionSource":"Eurostat Unemployment by sex and age monthly data, une_rt_m, euro area 21, seasonally adjusted total, PC_ACT","resolutionSourceUrl":"https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA21?format=JSON","resolutionRule":"Resolve from Eurostat dataset une_rt_m, frequency M, seasonally adjusted SA, age TOTAL, unit PC_ACT, sex T, geo EA21, period 2026-09, first print only as captured between monthly Euro indicators releases. Use the value rounded to one decimal percentage point; ignore later revisions or backfills. The official Eurostat euro-indicators calendar schedules the September 2026 unemployment release inside the registered expectedReleaseWindow, and the registered ledger target uses the window end 2026-11-09 as the contractual resolutionDate.","dataPointId":"eurostat.unemployment_rate.euro_area.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":6.1},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":6.2},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":6.2},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":6.3},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":6.2},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":6.3},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":6.4}],"drivers":["latest first print rose to 6.4 percent","same-series unemployment count flat from June to July","recent one-decimal changes remain small","two unpublished monthly observations before target month","first-print revisions do not count for settlement"],"sourceContext":["https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-01092026-bp","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-30072026-bp","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-02072026-ap","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-01062026-ap","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-01042026-ap","https://ec.europa.eu/eurostat/web/products-euro-indicators/w/3-04032026-ap","https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA21?format=JSON"],"runAt":"2026-09-07T20:18:37Z","reasoning":[{"kind":"heading","text":"Eurostat September 2026 unemployment first print"},{"kind":"text","text":"Framing and exact resolver: this targets Eurostat une_rt_m/M.SA.TOTAL.PC_ACT.T.EA21, monthly euro area 21 unemployment, seasonally adjusted, total age, total sex, percentage of the labour force, for September 2026. The settlement value is the first official print only, rounded to one decimal, with later revisions ignored."},{"kind":"tool","tool":"official.lookup","call":"Checked Eurostat euro-indicators release calendar page and target registration context for the unemployment release window.","result":"Fetched official calendar context that Eurostat maintains a Euro indicators release calendar with Unemployment as an indicator and Europe/Luxembourg time zone; the registered source window is 2026-11-01 to 2026-11-09 and resolutionDate is 2026-11-09."},{"kind":"tool","tool":"official.lookup","call":"Opened Eurostat 1 September 2026 unemployment release for July 2026.","result":"Fetched July 2026 euro area seasonally adjusted unemployment rate 6.4%, EU rate 6.1%, euro area unemployed persons 11.264 million, and next release date 1 October 2026."},{"kind":"tool","tool":"official.lookup","call":"Read the July 2026 Eurostat unemployment release table for recent same-variant values.","result":"Fetched same table values for euro area rates: April 2026 6.4, May 2026 6.3, June 2026 6.4, July 2026 6.4; unemployed persons were 11.245 million, 11.199 million, 11.264 million, and 11.264 million."},{"kind":"tool","tool":"official.lookup","call":"Opened earlier Eurostat monthly unemployment releases to recover first-print reference history.","result":"Fetched first-print headline values: January 2026 6.1%, February 2026 6.2%, March 2026 6.2%, April 2026 6.3%, May 2026 6.2%, June 2026 6.3%, July 2026 6.4%."},{"kind":"text","text":"Base rate / reference class: the relevant reference class is recent first prints of the same Eurostat euro area SA total unemployment rate. The one-decimal series moved from 6.1 to 6.4 over January-July, but every adjacent first-print change was between -0.1 and +0.1 percentage point, so last-print persistence is the base rate model."},{"kind":"text","text":"Level, momentum, and mechanism: the level is still low by euro-area history but no longer falling. Momentum is mildly upward because the latest first print is 6.4 after 6.2-6.3 earlier in 2026; the July release also shows the euro area unemployed count unchanged from June at 11.264 million, so the increase signal is not strong enough to push the modal September print above 6.4."},{"kind":"math","text":"Prior/update/interval: persistence prior is 6.4 from the July 2026 first print; historical sample is the fetched first-print sequence 6.1, 6.2, 6.2, 6.3, 6.2, 6.3, 6.4. Adjustment components are level 0.00, momentum +0.02 from the January-July rise, one-off/revision-policy 0.00 because only first prints count, and policy-mechanism 0.00 because no direct September labor-market shock was fetched, leaving a rounded point of 6.4. Successive changes are +0.1, 0.0, +0.1, -0.1, +0.1, +0.1; RMS monthly sigma = sqrt((0.01+0.00+0.01+0.01+0.01+0.01)/6) = 0.09. For two unpublished monthly steps from July to September, sigma = 0.09*sqrt(2) = 0.13, and 1.28*sigma = 1.28*0.13 = 0.17; widened only to the one-decimal practical band, the final implied 80% bounds are 6.2 to 6.6."},{"kind":"text","text":"Counter-consideration: upside risk is a genuine August-September weakening in large labor markets such as France, Italy, or Germany that would land above the interval at 6.7% or higher. Downside risk is renewed employment strength or labor-force denominator movement that would land below the interval at 6.1% or lower. Outside the interval would require two monthly moves larger or more persistent than the recent fetched first-print pattern."},{"kind":"text","text":"Prior run update: the earlier public Thesis August 2026 run selected persistence at 6.3 before the July first print was available. The new official July 2026 print at 6.4 updates the prior upward to 6.4; no prior catalog point estimate or interval is used as evidence."},{"kind":"forecast","point":6.4,"ciLow":6.2,"ciHigh":6.6}]}

# Reviewer critique
{
  "summary": "Draft is publishable with no blocking issues; it matches the ledger target and gives a coherent persistence-based forecast with an explicit volatility interval.",
  "requiredFixes": [],
  "optionalSuggestions": [
    "Clarify that the April-July values read from the September Eurostat table may be revised current table values, while the separate January-July sequence is the intended first-print history.",
    "Consider removing or shortening the prior Thesis August-run sentence, since it is not needed for the forecast and can invite catalog-circularity concerns even though it says it was not used as evidence.",
    "Make the downside tail a little more concrete by naming the kind of labor-market improvement or denominator shift that would produce 6.1 percent or lower."
  ]
}

Emit the final JSON object only.
