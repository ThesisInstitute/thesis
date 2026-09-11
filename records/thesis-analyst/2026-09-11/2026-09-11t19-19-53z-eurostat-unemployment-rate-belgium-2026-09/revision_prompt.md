# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: eurostat.unemployment_rate.belgium
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "belgium-unemployment-rate-september-2026"
- country: "BE"
- targetUnit: "percent"
- dataPointId: "eurostat.une_rt_m.unemployment_rate.belgium.2026_09.first_print"
- expectedReleaseWindow: {"end": "2026-11-09", "start": "2026-11-01"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["ec.europa.eu"], "expectedReleaseWindow": {"end": "2026-11-09", "start": "2026-11-01"}, "field": "eurostat.unemployment_rate.belgium", "releasePolicy": "first_print", "sourceSeriesId": "eurostat.unemployment_rate.belgium", "sourceUrl": "https://ec.europa.eu/eurostat/databrowser/view/une_rt_m/default/table?lang=en", "table": "Eurostat monthly unemployment euro-indicators release / une_rt_m data page", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-2a2e910a9190e434ae3320828c92ff9333ea94033678800a7900d94687de0d26.json"
- targetContentHash: "2a2e910a9190e434ae3320828c92ff9333ea94033678800a7900d94687de0d26"
- registrationCommit: "f527f4e54f1df0156366f87eeb5dd630eeb66fe4"
- registeredAtUtc: "2026-09-11T19:13:41Z"

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
{"slug":"belgium-unemployment-rate-september-2026","country":"BE","type":"data","title":"Belgium unemployment rate, September 2026","question":"What will Eurostat first print for Belgium's seasonally adjusted total unemployment rate, age 15-74, unit PC_ACT, in une_rt_m for September 2026?","unit":"percent","pointEstimate":6.1,"ciLow":5.9,"ciHigh":6.3,"confidence":0.8,"resolutionDate":"2026-11-09","resolutionSource":"Eurostat monthly unemployment euro-indicators release / une_rt_m data page","resolutionSourceUrl":"https://ec.europa.eu/eurostat/databrowser/view/une_rt_m/default/table?lang=en","resolutionRule":"Resolve to the first Eurostat print in table une_rt_m for geo=BE, s_adj=SA, sex=T, age=Y15-74, unit=PC_ACT, time=2026-09, reported in percent to one decimal. Use the first official value published for that monthly observation; do not substitute later revisions. The registered ledger target expectedReleaseWindow is 2026-11-01 to 2026-11-09, and this cell uses the target's 2026-11-09 contractual resolutionDate.","dataPointId":"eurostat.une_rt_m.unemployment_rate.belgium.2026_09.first_print","historicalContext":[{"period":{"type":"month","value":"2026-02"},"label":"2026-02","value":6.4},{"period":{"type":"month","value":"2026-03"},"label":"2026-03","value":6.3},{"period":{"type":"month","value":"2026-04"},"label":"2026-04","value":6.2},{"period":{"type":"month","value":"2026-05"},"label":"2026-05","value":6.3},{"period":{"type":"month","value":"2026-06"},"label":"2026-06","value":6.3},{"period":{"type":"month","value":"2026-07"},"label":"2026-07","value":6.0}],"drivers":["Latest first-print Belgium unemployment rate was 6.0 percent for July 2026 after several months near 6.2 to 6.4 percent.","Belgium monthly unemployment in Eurostat's seasonally adjusted total age 15-74 series is persistent, but recent first prints include a 0.3 percentage point July drop.","Two unreleased months remain before the September target, so I partly mean-revert the July low rather than fully carry it forward.","Euro area and EU unemployment rates were stable around 6.4 percent and 6.1 percent in the latest Eurostat release, limiting the case for a sharp Belgian break."],"sourceContext":["https://ec.europa.eu/eurostat/web/products-euro-indicators/w/3-01092026-bp","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-30072026-bp","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-01042026-ap","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-30042026-cp","https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar","https://ec.europa.eu/eurostat/databrowser/view/une_rt_m/default/table?lang=en"],"runAt":"2026-09-11T19:20:13Z","reasoning":[{"kind":"heading","text":"Belgium unemployment rate, September 2026"},{"kind":"text","text":"Framing and exact resolver: this is Eurostat table une_rt_m, Belgium geo=BE, seasonally adjusted s_adj=SA, total sex sex=T, age 15-74, unit PC_ACT, for period 2026-09. The settlement value is the first official print only, rounded to one decimal percentage point, with later revisions ignored."},{"kind":"tool","tool":"official.lookup","call":"Checked Eurostat's euro-indicators release calendar page and the registered target timing for the September 2026 unemployment release.","result":"Eurostat's release-calendar page is the official schedule source; the registered public target window is 2026-11-01 to 2026-11-09, and the ledger resolutionDate is 2026-11-09. The same Eurostat unemployment sequence showed the July 2026 release on 2026-09-01 and the prior June 2026 release on 2026-07-30."},{"kind":"tool","tool":"official.lookup","call":"Fetched the latest Eurostat euro-indicators unemployment release for July 2026, seasonally adjusted unemployment totals.","result":"Eurostat's 2026-09-01 July 2026 release printed Belgium rates of 6.1 for Jul-25, 6.3 for Apr-26, 6.3 for May-26, 6.3 for Jun-26, and 6.0 for Jul-26; the same table printed euro area 6.4 and EU 6.1 for Jul-26."},{"kind":"tool","tool":"official.lookup","call":"Fetched prior Eurostat unemployment releases to build the recent same-variant first-print reference class.","result":"Eurostat releases printed Belgium total unemployment rates of 6.4 for Feb-26 in the 2026-04-01 release, 6.3 for Mar-26 in the 2026-04-30 release, 6.2 for Apr-26 in the 2026-06-01 release, 6.3 for May-26 in the 2026-07-02 release, and 6.3 for Jun-26 in the 2026-07-30 release."},{"kind":"tool","tool":"official.lookup","call":"Checked Eurostat release notes and methodology fields for variant control.","result":"Eurostat states the unemployment rate is unemployed persons as a percentage of the labour force and that rates in the news release cover persons aged 15 to 74; the July 2026 Belgium total table also printed 329 thousand unemployed persons and 6.0 percent for Jul-26."},{"kind":"text","text":"Base rate / reference class: the recent same-variant first-print reference class is 6.4, 6.3, 6.2, 6.3, 6.3, and 6.0 percent for February through July 2026. That centers near 6.25 percent but ends at 6.0 percent, so persistence alone points around 6.0 to 6.1 while the broader six-month base rate argues against treating July as a permanent collapse."},{"kind":"text","text":"Variant control: all anchors use Eurostat seasonally adjusted unemployment totals for Belgium, age 15-74, percent of active population, matching une_rt_m and the target's first-print variant; I am not mixing youth, sex-specific, unadjusted, national-register, or revised settlement definitions."},{"kind":"math","text":"Prior/update/interval: persistence prior = latest same-series first print, July 2026 at 6.0; historical sample = Feb-Jul 2026 first prints 6.4, 6.3, 6.2, 6.3, 6.3, 6.0; adjustment components = +0.05 for mean reversion from the isolated July drop, +0.03 for stable euro area/EU labor-market backdrop, +0.02 for two-month horizon rounding uncertainty, giving point 6.1 after one-decimal rounding. For the level/rate interval I used successive changes -0.1, -0.1, +0.1, 0.0, -0.3; sigma = 0.15, so 80% half-width = 1.28*sigma = 1.28*0.15 = 0.19; rounded one-decimal bounds around 6.1 are 5.9 to 6.3."},{"kind":"text","text":"Counter-considerations: upside risk is a reversal of the July drop, weaker employment survey inputs, or upward first-print seasonal adjustment that would land above the interval; downside risk is continued labor-force absorption or another unemployment-count fall that would land below the interval. A sudden Belgium-specific survey rebenchmark or data-processing revision would be outside the interval risk in either direction."},{"kind":"forecast","point":6.1,"ciLow":5.9,"ciHigh":6.3}]}

# Reviewer critique
{"summary":"The draft is publication-ready on the rubric, with resolver, unit, prior, update logic, interval math, tails, and JSON fields aligned to the registered target.","requiredFixes":[],"optionalSuggestions":["Add the specific prior-release URLs for the 2026-06-01 and 2026-07-02 evidence if the trace validator expects every historical anchor to appear in sourceContext.","Consider noting that the 5.9-6.3 interval is an 80% interval after one-decimal rounding."]}

Emit the final JSON object only.
