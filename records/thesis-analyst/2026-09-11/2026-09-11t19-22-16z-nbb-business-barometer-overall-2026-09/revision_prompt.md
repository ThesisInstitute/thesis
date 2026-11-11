# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: nbb.business_barometer.overall
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "belgium-nbb-business-barometer-september-2026"
- country: "BE"
- targetUnit: "index_points"
- dataPointId: "nbb.business_barometer.overall.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-10-02", "start": "2026-09-24"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.nbb.be"], "expectedReleaseWindow": {"end": "2026-10-02", "start": "2026-09-24"}, "field": "nbb.business_barometer.overall", "releasePolicy": "first_print", "sourceSeriesId": "nbb.business_barometer.overall", "sourceUrl": "https://www.nbb.be/en/statistics/business-surveys/business-survey", "table": "National Bank of Belgium business survey release", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-5b1c21497b8b7b76398409ef924ba2fadc48fff653b2e6ce4d9d50821db0aeec.json"
- targetContentHash: "5b1c21497b8b7b76398409ef924ba2fadc48fff653b2e6ce4d9d50821db0aeec"
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
{"slug":"belgium-nbb-business-barometer-september-2026","country":"BE","type":"data","title":"Belgium NBB business barometer, September 2026","question":"National Bank of Belgium monthly business surveys, overall gross synthetic curve for Belgium, total sector, seasonally adjusted, September 2026, first official print","unit":"index_points","pointEstimate":-13.1,"ciLow":-15.9,"ciHigh":-10.3,"confidence":0.8,"resolutionDate":"2026-09-24","resolutionSource":"National Bank of Belgium business survey release","resolutionSourceUrl":"https://nsidisseminate-stat.nbb.be/rest/data/DF_BUSSURVM/M.SYNC.BE.A999.S?startPeriod=2026-09&endPeriod=2026-09&dimensionAtObservation=TIME_PERIOD","resolutionRule":"Resolve to the first National Bank of Belgium published monthly business surveys overall gross synthetic curve for Belgium, total sector, seasonally adjusted, period 2026-09, reported in index points and rounded to one decimal. SDMX identity: DF_BUSSURVM key M.SYNC.BE.A999.S (FREQ monthly, BUSSURVM_INDICATOR synthetic curve, BE_AREA Belgium, BUSSURV_SECTOR Total, BUSSURVM_ADJ seasonally adjusted). Use the first official print only; ignore later NBB.Stat revisions, corrections after the first release, and third-party mirrors.","dataPointId":"nbb.business_barometer.overall.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2026-08"},"label":"2026-08","value":-13.2},{"period":{"type":"month","value":"2026-07"},"label":"2026-07","value":-11.9},{"period":{"type":"month","value":"2026-06"},"label":"2026-06","value":-12.4},{"period":{"type":"month","value":"2026-05"},"label":"2026-05","value":-13.3},{"period":{"type":"month","value":"2026-04"},"label":"2026-04","value":-14.2},{"period":{"type":"month","value":"2026-03"},"label":"2026-03","value":-13.7},{"period":{"type":"month","value":"2026-02"},"label":"2026-02","value":-13.7},{"period":{"type":"month","value":"2026-01"},"label":"2026-01","value":-8.8},{"period":{"type":"month","value":"2025-12"},"label":"2025-12","value":-11.9},{"period":{"type":"month","value":"2025-11"},"label":"2025-11","value":-8.2},{"period":{"type":"month","value":"2025-10"},"label":"2025-10","value":-9.1},{"period":{"type":"month","value":"2025-09"},"label":"2025-09","value":-7.9}],"drivers":["August first print fell to -13.2 from -11.9 in July","recent six-print average is -13.1","manufacturing worsened in August while services and trade improved","September release is scheduled by NBB for 2026-09-24 at 15:00","monthly changes imply about 2.8 index points of 80% half-width"],"sourceContext":["https://www.nbb.be/en/statistical-updates?calendar_timestamp=1961708400&current=1964383200&date_format=custom&date_pattern=F&display_reset=0&next=1966975200&page=0&pager_type=calendar_month&previous=1961708400&scope=2&theme%5B5069%5D=5069&use_previous_next=1","https://www.nbb.be/en/statistics/latest-figures/business-confidence-indicator-2026m7","https://www.nbb.be/en/statistics/topics/general/online-statistical-database","https://nsidisseminate-stat.nbb.be/rest/data/DF_BUSSURVM/M.SYNC.BE.A999.S?startPeriod=2025-08&endPeriod=2026-08&dimensionAtObservation=TIME_PERIOD","https://tradingeconomics.com/belgium/business-confidence"],"runAt":"2026-09-11T19:22:44Z","reasoning":[{"kind":"heading","text":"Belgium September 2026 NBB Business Barometer Forecast"},{"kind":"text","text":"Framing and resolver: the target is nbb.business_barometer.overall for 2026-09, country BE, unit index_points, dataPointId nbb.business_barometer.overall.2026-09.first_print. The exact resolving variant is the National Bank of Belgium monthly business surveys overall gross synthetic curve, Belgium total sector, seasonally adjusted, first print. The registered expectedReleaseWindow ends 2026-10-02, but the official NBB calendar fetched this run gives the concrete September 2026 business confidence release day as 2026-09-24, so I use 2026-09-24 as the release-calendar resolutionDate while keeping the same target identity."},{"kind":"tool","tool":"official.lookup","call":"Search/open NBB statistical updates calendar for business confidence September 2026.","result":"Fetched official NBB calendar entries: Business confidence Period 2026M9 Monthly business surveys Data release date 24 Sep 2026, and Business confidence Period 2026-09 Press release - Business confidence indicator release date 24 Sep 2026; calendar note says business confidence press releases are scheduled at 3 p.m."},{"kind":"tool","tool":"official.lookup","call":"Use public prior-run NBB SDMX query artifact for official same-variant history through July 2026, DF_BUSSURVM/M.SYNC.BE.A999.S.","result":"Fetched official NBB overall seasonally adjusted synthetic curve values from that public artifact: 2025-09 -7.9, 2025-10 -9.1, 2025-11 -8.2, 2025-12 -11.9, 2026-01 -8.8, 2026-02 -13.7, 2026-03 -13.7, 2026-04 -14.2, 2026-05 -13.3, 2026-06 -12.4, 2026-07 -11.9 index points."},{"kind":"tool","tool":"official.lookup","call":"Search NBB July 2026 business confidence press-release page for table identity and sector values.","result":"Fetched NBB July table: Overall synthetic curve 2026-06 -12.4 and 2026-07 -11.9, change 0.5; manufacturing 2026-07 -15.5, business-related services -3.8, building -5.0, trade -10.8 index points."},{"kind":"tool","tool":"public.mirror.lookup","call":"Search public data mirrors carrying the NBB August 2026 first print while NBB SDMX network access was unavailable in the shell.","result":"Fetched August history from public pages attributing source to National Bank of Belgium: August 2026 business confidence -13.2, July 2026 -11.9, manufacturing August -17.8 versus July -15.5, business-related services August -1.4 versus July -3.8, trade August -5.2 versus July -10.8."},{"kind":"text","text":"Base rate/reference class: the recent official-source reference class is the same gross overall seasonally adjusted synthetic curve. The last twelve closed prints are -7.9, -9.1, -8.2, -11.9, -8.8, -13.7, -13.7, -14.2, -13.3, -12.4, -11.9, and -13.2; their average is about -11.9, the latest six average -13.1, the latest three average -12.5, and the latest print is -13.2. A persistence prior around -13.2 is therefore the starting point, with only a small pull toward the six-print mean."},{"kind":"text","text":"Inside-view update: level remains weak and August interrupted the May-July recovery. Momentum is mildly negative at the aggregate level because August fell 1.3 points, but the sector composition is mixed: manufacturing and construction weakened, while services and trade improved. There is no September survey signal before the print, so the update from the previous August run is only to replace the old July endpoint of -11.9 with the August first print of -13.2."},{"kind":"math","text":"Prior/update/interval: persistence prior = -13.2 from the August 2026 first print; historical sample = NBB total synthetic curve 2025-08 through 2026-08 with monthly changes +1.0,-1.2,+0.9,-3.7,+3.1,-4.9,+0.0,-0.5,+0.9,+0.9,+0.5,-1.3. Adjustment components: -0.2 for the August aggregate setback, +0.2 for the latest six-print mean of -13.1 and improving services/trade, +0.1 for mild mean reversion from the April trough, net +0.1, so point = -13.1. For the interval, sigma = 2.18 from successive fetched monthly changes; 1.28*sigma = 2.79, rounded to half-width 2.8. Final 80% bounds: -13.1 - 2.8 = -15.9 and -13.1 + 2.8 = -10.3."},{"kind":"text","text":"Counter-consideration and falsification: upside risk is a broad September rebound in manufacturing and construction alongside continued services and trade gains, which would land above the interval if the first print is -10.2 or higher. Downside risk is renewed export/order-book weakness spreading from manufacturing into trade and services, which would land below the interval if the first print is -16.0 or lower. Either outside the interval would be a larger move than the recent-change sigma expects."},{"kind":"forecast","point":-13.1,"ciLow":-15.9,"ciHigh":-10.3}]}

# Reviewer critique
{"summary":"Draft is mostly forecast-complete, but the resolver URL conflicts with the registered source binding host/source and should be fixed before publication.","requiredFixes":[{"rubricItem":"resolver","severity":"blocking","summary":"The draft resolutionSourceUrl uses nsidisseminate-stat.nbb.be, while the registered sourceBinding allows only www.nbb.be and names https://www.nbb.be/en/statistics/business-surveys/business-survey as the sourceUrl.","actionRequested":"Change resolutionSourceUrl to the registered NBB sourceBinding URL, or update the registered target through the proper reviewed ledger path if the SDMX endpoint is intended to be the resolver."}],"optionalSuggestions":["The use of Trading Economics/public mirrors for the August print should be framed as contextual evidence only; keep the final resolver explicitly official NBB first print.","Consider noting that 2026-09-24 comes from the official NBB release calendar even though the registered expected window ends 2026-10-02."]}

Emit the final JSON object only.
