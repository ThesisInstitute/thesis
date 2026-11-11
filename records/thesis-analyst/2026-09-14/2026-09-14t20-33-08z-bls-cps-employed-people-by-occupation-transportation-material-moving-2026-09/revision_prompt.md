# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.employed_people_by_occupation.transportation_material_moving
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-transport-material-moving-employment-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.transportation_material_moving.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-10-14", "start": "2026-10-06"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-14", "start": "2026-10-06"}, "field": "Transportation and material moving occupations", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.employed_people_by_occupation.transportation_material_moving", "sourceUrl": "https://www.bls.gov/web/empsit/cpseea19.htm", "table": "CPS Employment Situation Table A-19, employed persons by occupation, not seasonally adjusted (thousands)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-14-d6e9c92086ea70e8b59790dcc9ac070c7eb079e22a59c17d88d559ebccc62072.json"
- targetContentHash: "d6e9c92086ea70e8b59790dcc9ac070c7eb079e22a59c17d88d559ebccc62072"
- registrationCommit: "0f2c009b27e9b65c2aeb9b253934fd8b301b787e"
- registeredAtUtc: "2026-09-14T20:23:15Z"

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
{"slug":"cps-transport-material-moving-employment-september-2026","country":"US","type":"data","title":"CPS transportation/material moving employment, Sep 2026","question":"What will the first official BLS CPS Employment Situation Table A-19 not-seasonally-adjusted employed people count be for Transportation and material moving occupations, total 16 years and over, in September 2026?","unit":"millions","pointEstimate":12.096,"ciLow":11.891,"ciHigh":12.301,"confidence":0.8,"resolutionDate":"2026-10-14","resolutionSource":"BLS Employment Situation Table A-19","resolutionSourceUrl":"https://www.bls.gov/web/empsit/cpseea19.htm","resolutionRule":"Resolve to the first official BLS CPS Employment Situation Table A-19, employed people by occupation, sex, and age, not seasonally adjusted, row Transportation and material moving occupations, Total 16 years and over column for September 2026, reported in thousands; multiply by 0.001 to convert to millions and round to three decimals. Use the first print only, with no later revisions or same-day correction grace unless the registered target is updated.","dataPointId":"bls.cps.employed_people_by_occupation.transportation_material_moving.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":12.214},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":12.127},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":12.12},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":12.01},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":12.223},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":12.011}],"drivers":["CPS household-survey occupation series is noisy month to month","not-seasonally-adjusted September level usually near late-summer level","August 2026 latest official table value was 12.011 million","recent six-print level centered near 12.118 million","transportation and warehousing payrolls showed little change in the latest Employment Situation narrative"],"sourceContext":["https://www.bls.gov/web/empsit/cpseea19.htm","https://www.bls.gov/schedule/news_release/empsit.htm","https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032214","https://fred.stlouisfed.org/series/LNU02032214","https://www.bls.gov/news.release/archives/empsit_11202025.htm","https://www.bls.gov/news.release/archives/empsit_10042024.htm","https://www.bls.gov/news.release/archives/empsit_10062023.htm","https://www.bls.gov/news.release/archives/empsit_10072022.htm"],"runAt":"2026-09-14T20:33:28Z","reasoning":[{"kind":"heading","text":"Forecast for September 2026 CPS transportation and material moving employment"},{"kind":"text","text":"The target is the BLS CPS household-survey occupation line, not seasonally adjusted, Table A-19 row Transportation and material moving occupations, total 16 years and over. The resolving public series corresponds to source code LNU02032214, reported in thousands and converted to millions by multiplying by 0.001."},{"kind":"tool","tool":"official.lookup","call":"Fetched the current BLS Table A-19 page at https://www.bls.gov/web/empsit/cpseea19.htm and read the Transportation and material moving occupations row.","result":"Current Table A-19 shows Transportation and material moving occupations total 16 years and over at Aug. 2025 = 11,647 thousand and Aug. 2026 = 12,011 thousand; the broader Production, transportation, and material moving occupations row is Aug. 2026 = 19,727 thousand."},{"kind":"tool","tool":"official.lookup","call":"Checked the BLS Employment Situation release calendar for the September 2026 reference month.","result":"The BLS schedule lists September 2026 Employment Situation release date Oct. 02, 2026 at 08:30 AM. The registered Thesis target has resolutionDate 2026-10-14 and expectedReleaseWindow 2026-10-06 to 2026-10-14, which appears inconsistent with the official calendar; I keep the registered resolutionDate because the prompt instructs using the ledger target contract."},{"kind":"tool","tool":"official.lookup","call":"Used the BLS public API series endpoint for LNU02032214 and the FRED mirror of that BLS source to assemble recent monthly official-source history.","result":"Recent LNU02032214 values are Mar 2026 = 12,214 thousand, Apr 2026 = 12,127 thousand, May 2026 = 12,120 thousand, Jun 2026 = 12,010 thousand, Jul 2026 = 12,223 thousand, and Aug 2026 = 12,011 thousand."},{"kind":"tool","tool":"official.lookup","call":"Fetched archived BLS Employment Situation releases to check same-month September reference values for the occupation line.","result":"Archived BLS releases show Transportation and material moving occupations employment at Sep 2022 = 11,866 thousand, Sep 2023 = 11,761 thousand, Sep 2024 = 12,217 thousand, and Sep 2025 = 11,910 thousand."},{"kind":"text","text":"For the base rate and reference class, I anchor on a persistence prior from the latest same-variant NSA CPS occupation level plus the recent six-print distribution. The six recent values average about 12.118 million, while the latest August 2026 level is 12.011 million. September 2025 was 0.263 million above August 2025, but this line has high sampling noise and the current August-to-July move was negative, so I only partially apply a September seasonal lift."},{"kind":"math","text":"Prior/update/interval: persistence prior = Aug 2026 value 12.011 million; historical sample = Mar-Aug 2026 official-source values 12.214, 12.127, 12.120, 12.010, 12.223, 12.011. Adjustment components: +0.054 million toward the recent six-print mean, +0.031 million for September seasonal risk from 2025 Sep-Aug behavior but damped for noise and weak latest momentum, for point 12.096 million. Successive changes are -0.087, -0.007, -0.110, +0.213, -0.212 million, so sigma = 0.160 million; 1.28*sigma = 0.205 million. Applying that half-width gives 12.096 +/- 0.205 = [11.891, 12.301]."},{"kind":"text","text":"Upside risk would be a normal September pickup in logistics, warehousing, and school-related transport categories plus household-survey rotation noise, which would land above the interval if the first print exceeds 12.301 million. Downside risk would be another large CPS occupation-allocation reversal or softer goods-movement employment, which would land below the interval if the first print is under 11.891 million."},{"kind":"forecast","point":12.096,"ciLow":11.891,"ciHigh":12.301}]}

# Reviewer critique
{
  "summary": "The draft is broadly publishable, with one resolver-text warning because the official BLS September 2026 Employment Situation date conflicts with the registered ledger date/window.",
  "requiredFixes": [
    {
      "rubricItem": "resolver",
      "severity": "warning",
      "summary": "The reasoning discloses that BLS schedules the September 2026 Employment Situation for 2026-10-02 while the registered target uses resolutionDate 2026-10-14 and window 2026-10-06 to 2026-10-14, but the resolver fields themselves do not carry that discrepancy.",
      "actionRequested": "Keep the ledger-bound resolutionDate 2026-10-14, but add a compact note in the resolutionRule or publication reasoning that the official calendar appears inconsistent and the cell intentionally follows the registered target contract."
    }
  ],
  "optionalSuggestions": [
    "Clarify that the +0.031 September lift is a damped seasonal/occupation-noise adjustment rather than strong current evidence.",
    "Consider naming the interval as an approximate 80% normal interval from recent month-to-month realized volatility."
  ]
}

Emit the final JSON object only.
