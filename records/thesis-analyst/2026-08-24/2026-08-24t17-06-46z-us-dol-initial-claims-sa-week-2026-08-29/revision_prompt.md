# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: us.dol.initial_claims.sa
- period: week_2026-08-29
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "initial-claims-week-2026-08-29"
- country: "US"
- targetUnit: "thousands"
- dataPointId: "us.dol.initial_claims.sa.week_2026-08-29"
- expectedReleaseWindow: {"end": "2026-09-11", "start": "2026-09-07"}
- sourceBinding: {"adapter": "alfred-fred", "allowedHosts": ["alfred.stlouisfed.org"], "expectedReleaseWindow": {"end": "2026-09-11", "start": "2026-09-07"}, "field": "ICSA", "releasePolicy": "advance_vintage", "sourceSeriesId": "ICSA", "sourceUrl": "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA", "table": "ALFRED graph CSV", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-08-24-b49b4c8de44e5d0f9f33d84f31bfef810666ef10c691abffc487cc41c48bbdbc.json"
- targetContentHash: "b49b4c8de44e5d0f9f33d84f31bfef810666ef10c691abffc487cc41c48bbdbc"
- registrationCommit: "14257c0253ea587a0c39c70f56ea7dbacb6dd3f1"
- registeredAtUtc: "2026-08-24T17:04:52Z"

# Source hints
- Use the official agency release calendar, not inferred cadence.
- FRED may be used as a history mirror, but resolution cites the agency.
- For FOMC targets, resolve to the target range upper bound after the announcement.
- For DOL claims, name the week-ending date and cite the release date.

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
{"slug":"initial-claims-week-2026-08-29","country":"US","type":"data","title":"US initial claims, week ending 2026-08-29","question":"What will the U.S. Department of Labor advance seasonally adjusted initial unemployment insurance claims, series ICSA, be for the week ending 2026-08-29 on the first official print?","unit":"thousands","pointEstimate":205,"ciLow":186,"ciHigh":224,"confidence":0.8,"resolutionDate":"2026-09-11","resolutionSource":"ALFRED graph CSV registered ICSA adapter, mirroring the U.S. Department of Labor Unemployment Insurance Weekly Claims Report first print","resolutionSourceUrl":"https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA","resolutionRule":"Resolve through the registered ALFRED graph CSV source binding for ICSA to the advance-vintage value corresponding to the first official U.S. Department of Labor Employment and Training Administration Unemployment Insurance Weekly Claims Report figure for seasonally adjusted initial claims for week ending 2026-08-29, in persons multiplied by 0.001 and rounded to the nearest 1 thousand. Later revisions do not change resolution. DOL is the official agency source; ALFRED is the registered mechanical mirror.","dataPointId":"us.dol.initial_claims.sa.week_2026-08-29","historicalContext":[{"period":{"type":"week_ending","value":"2026-06-27"},"label":"week ending 2026-06-27","value":215},{"period":{"type":"week_ending","value":"2026-07-04"},"label":"week ending 2026-07-04","value":215},{"period":{"type":"week_ending","value":"2026-07-11"},"label":"week ending 2026-07-11","value":208},{"period":{"type":"week_ending","value":"2026-07-18"},"label":"week ending 2026-07-18","value":187},{"period":{"type":"week_ending","value":"2026-07-25"},"label":"week ending 2026-07-25","value":197},{"period":{"type":"week_ending","value":"2026-08-01"},"label":"week ending 2026-08-01","value":199},{"period":{"type":"week_ending","value":"2026-08-08"},"label":"week ending 2026-08-08","value":209},{"period":{"type":"week_ending","value":"2026-08-15"},"label":"week ending 2026-08-15","value":206}],"drivers":["Latest official first print was 206 thousand for week ending 2026-08-15","Recent first-print reference class is centered near 205 to 207 thousand","Two unreleased weekly transitions remain before the target week","No visible policy mechanism points to a large displacement","Late-summer seasonal adjustment can still create weekly noise"],"sourceContext":["https://www.dol.gov/ui/data.pdf","https://oui.doleta.gov/unemploy/archive.asp","https://oui.doleta.gov/press/2026/081326.pdf","https://oui.doleta.gov/press/2026/080626.pdf","https://oui.doleta.gov/press/2026/073026.pdf","https://oui.doleta.gov/press/2026/072326.pdf","https://oui.doleta.gov/press/2026/071626.pdf","https://oui.doleta.gov/press/2026/070926.pdf","https://oui.doleta.gov/press/2026/070226.pdf","https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA"],"runAt":"2026-08-24T17:07:19Z","reasoning":[{"kind":"heading","text":"US initial claims forecast for week ending 2026-08-29"},{"kind":"text","text":"Framing and exact resolver: the target is U.S. Department of Labor Employment and Training Administration initial unemployment insurance claims, seasonally adjusted, advance first print, series ICSA, for week ending 2026-08-29, in thousands. The registered target uses ALFRED ICSA as the mechanical advance-vintage adapter while DOL remains the official agency source. The DOL archive says the weekly claims news release is published each Thursday at 8:30 a.m. Eastern except listed holiday exceptions; for this target week that points to the 2026-09-03 DOL release, while the registered sourceBinding window is 2026-09-07 to 2026-09-11, so I keep the top-level resolutionDate tied to the registered bound and state the calendar discrepancy rather than changing the target."},{"kind":"tool","tool":"official.lookup","call":"Fetched the current DOL UI Weekly Claims PDF at https://www.dol.gov/ui/data.pdf.","result":"The 2026-08-20 DOL release reported that for week ending 2026-08-15 the advance seasonally adjusted initial claims figure was 206,000, down 6,000 from the previous week's revised 212,000; the same release table listed 2026-08-08 at 212,000 revised and 2026-08-01 at 200,000 revised."},{"kind":"tool","tool":"official.lookup","call":"Fetched archived DOL releases for 2026-08-13, 2026-08-06, and 2026-07-30.","result":"The 2026-08-13 release first printed week ending 2026-08-08 at 209,000; the 2026-08-06 release first printed week ending 2026-08-01 at 199,000; the 2026-07-30 release first printed week ending 2026-07-25 at 197,000."},{"kind":"tool","tool":"official.lookup","call":"Fetched archived DOL releases for 2026-07-23, 2026-07-16, 2026-07-09, and 2026-07-02.","result":"The 2026-07-23 release first printed week ending 2026-07-18 at 187,000; the 2026-07-16 release first printed week ending 2026-07-11 at 208,000; the 2026-07-09 release first printed week ending 2026-07-04 at 215,000; the 2026-07-02 release first printed week ending 2026-06-27 at 215,000."},{"kind":"text","text":"Base rate / reference class: the recent official-source reference class is eight advance seasonally adjusted initial-claims first prints from 2026-06-27 through 2026-08-15: 215, 215, 208, 187, 197, 199, 209, and 206 thousand. The base rate center is about 205 thousand by mean and 207 thousand by median, with the latest first print at 206 thousand."},{"kind":"text","text":"Level, momentum, one-off, and policy effects: level anchors near 206 thousand; momentum is mixed after 187 to 197 to 199 to 209 to 206; mean reversion points only slightly toward the 205 to 207 center; no public policy mechanism in the claims release suggests a discrete jump. The series variant is advance seasonally adjusted initial claims, not NSA claims, continued claims, the insured unemployment rate, or the four-week moving average."},{"kind":"math","text":"Prior/update/interval: prior = recent first-print persistence/reference-class model using the fetched official DOL ICSA prints from 2026-06-27 through 2026-08-15; adjustment components = 206 latest level, -1 thousand mild pull toward the eight-print mean of 204.5, and 0 thousand for policy mechanism, giving point = 205. Interval method = realized dispersion of successive changes in the same first-print history. Changes were 0, -7, -21, +10, +2, +10, -3 thousand; sample sigma = 10.73 thousand; one-week 80% half-width = 1.28*sigma = 13.73 thousand. Because the target week is two unreleased weekly transitions after the latest print, widen by sqrt(2): 13.73*1.414 = 19.42 thousand. Final implied bounds = 205 +/- 19.42 = [185.58, 224.42], rounded to [186, 224]."},{"kind":"text","text":"Counter-considerations: upside risk is a renewed layoff pulse or another adverse seasonal-adjustment surprise after the 187 thousand July trough, which would land above the interval if the first print exceeds 224 thousand. Downside risk is continued very low late-summer layoffs with favorable seasonal factors, which would land below the interval if the first print is under 186 thousand. Outside the interval would require a move larger than the recent two-week noise without a currently observed mechanism."},{"kind":"forecast","point":205,"ciLow":186,"ciHigh":224}]}

# Reviewer critique
{"summary":"The draft is publication-ready with no blocking issues; it follows the registered target contract and clearly flags the DOL-calendar versus ledger resolution-date discrepancy.","requiredFixes":[],"optionalSuggestions":["Consider noting that the volatility estimate is based on only seven week-to-week changes, so the interval method is transparent but sample-limited.","The resolver text could avoid saying 'rounded' unless the registered adapter itself performs rounding, but this is not material given the integer-thousands forecast fields."]}

Emit the final JSON object only.
