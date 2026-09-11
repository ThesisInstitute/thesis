# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.employed_people_by_occupation.healthcare_support
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-healthcare-support-employment-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.healthcare_support.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-10-08", "start": "2026-09-30"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-08", "start": "2026-09-30"}, "field": "Healthcare support occupations", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.employed_people_by_occupation.healthcare_support", "sourceUrl": "https://www.bls.gov/web/empsit/cpseea19.htm", "table": "CPS Employment Situation Table A-19, employed persons by occupation, not seasonally adjusted (thousands)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-b1aecf400204f8c11eab1e73433ad74b308fcd147b28e0f8727fdda9787cde9b.json"
- targetContentHash: "b1aecf400204f8c11eab1e73433ad74b308fcd147b28e0f8727fdda9787cde9b"
- registrationCommit: "f527f4e54f1df0156366f87eeb5dd630eeb66fe4"
- registeredAtUtc: "2026-09-11T19:13:41Z"

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
{"slug":"cps-healthcare-support-employment-september-2026","country":"US","type":"data","title":"US healthcare support employment, September 2026","question":"What will BLS first report for September 2026 employed people age 16 and over in Healthcare support occupations, not seasonally adjusted, in CPS Employment Situation Table A-19, converted from thousands to millions?","unit":"millions","pointEstimate":5.72,"ciLow":5.52,"ciHigh":5.92,"confidence":0.8,"resolutionDate":"2026-10-08","resolutionSource":"U.S. Bureau of Labor Statistics Employment Situation, CPS Table A-19","resolutionSourceUrl":"https://www.bls.gov/web/empsit/cpseea19.htm","resolutionRule":"Resolve to the first value published by BLS for September 2026 in CPS Employment Situation Table A-19, row 'Healthcare support occupations,' Total, 16 years and over, not seasonally adjusted, reported in thousands and multiplied by 0.001 to millions. Retain three decimals and ignore all later revisions or later corrections. The official BLS Employment Situation schedule fetched this run lists September 2026 for October 2, 2026 at 08:30 AM ET; the canonical ledger target fixes resolutionDate as 2026-10-08, so this cell remains tied to that registered date and states the discrepancy.","dataPointId":"bls.cps.employed_people_by_occupation.healthcare_support.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2025-06"},"label":"June 2025","value":5.95},{"period":{"type":"month","value":"2025-07"},"label":"July 2025","value":6.038},{"period":{"type":"month","value":"2025-08"},"label":"August 2025","value":5.923},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":5.691},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":5.797},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":5.709}],"drivers":["August 2026 Table A-19 level of 5.709 million","recent 2026 values remain below same-month 2025 values","CPS occupation-row sampling volatility","no discrete policy or classification mechanism identified"],"sourceContext":["https://www.bls.gov/web/empsit/cpseea19.htm","https://www.bls.gov/schedule/news_release/empsit.htm","https://www.bls.gov/cps/cpsaat09.htm","https://web.archive.org/web/20260710110509/https://www.bls.gov/web/empsit/cpseea19.htm"],"runAt":"2026-09-11T19:32:31Z","reasoning":[{"kind":"heading","text":"September 2026 CPS healthcare support employment forecast"},{"kind":"text","text":"The resolver is the first BLS CPS Employment Situation Table A-19 print for employed people age 16 and over in 'Healthcare support occupations,' not seasonally adjusted. Values are in thousands on the BLS table and are transformed to millions by multiplying by 0.001. All monthly anchors use that same CPS occupation-row, Total age 16 years and over, not seasonally adjusted variant."},{"kind":"tool","tool":"official.lookup","call":"Open https://www.bls.gov/web/empsit/cpseea19.htm and read the Healthcare support occupations row.","result":"BLS CPS Table A-19, Last Modified Date September 04, 2026, reports Healthcare support occupations Total 16 years and over: August 2025 = 5,923 thousand and August 2026 = 5,709 thousand, equal to 5.923 and 5.709 million."},{"kind":"tool","tool":"public_record.lookup","call":"Inspect the published Thesis public A-19 record generated from the August 07, 2026 BLS Table A-19 page for the same healthcare support row.","result":"The public record for bls.cps.employed_people_by_occupation.healthcare_support.august_2026.first_print records the fetched July 2026 BLS Table A-19 value as 5,797 thousand, equal to 5.797 million, and the same row's July 2025 value as 6,038 thousand."},{"kind":"tool","tool":"public_record.lookup","call":"Inspect the published Thesis public A-19 record and registered Wayback source for the July 02, 2026 BLS Table A-19 page.","result":"The Wayback-backed public record for the BLS Table A-19 source reports Healthcare support occupations: June 2025 = 5,950 thousand and June 2026 = 5,691 thousand, equal to 5.950 and 5.691 million."},{"kind":"tool","tool":"official.lookup","call":"Open https://www.bls.gov/cps/cpsaat09.htm for annual same-occupation context.","result":"BLS CPS annual Table 9 reports Healthcare support occupations Total 16 years and over: 2024 = 5,456 thousand and 2025 = 5,830 thousand; the 2025 annual estimate excludes October because October 2025 data were not collected."},{"kind":"tool","tool":"official.calendar","call":"Open https://www.bls.gov/schedule/news_release/empsit.htm to verify the Employment Situation release schedule.","result":"BLS schedule rows fetched this run list August 2026 with release date Sep. 04, 2026 at 08:30 AM, September 2026 with release date Oct. 02, 2026 at 08:30 AM, and October 2026 with release date Nov. 06, 2026 at 08:30 AM. This conflicts with the registered resolutionDate 2026-10-08, which I retain because the target contract supplies it."},{"kind":"text","text":"The outside-view base rate/reference class is latest same-table persistence: August 2026 first print was 5.709 million, after same-row monthly prints of 5.950, 6.038, 5.923, 5.691, 5.797, and 5.709 million across June-August 2025 and June-August 2026. The previous August 2026 forecast centered on 5.797 million, but the newly fetched first print was 5.709 million, so I update the level anchor down to the official August value."},{"kind":"text","text":"Level, momentum, one-off, and policy-mechanism effects: the level anchor is 5.709 million; the recent 2026 June-to-August path is choppy but nearly flat from June to August, so I add only +0.011 million for mild rebound/persistence toward 5.720; I add 0.000 million for one-off effects and 0.000 million for policy or classification mechanisms because I found no public evidence for a September break in the CPS occupation classification or healthcare-support labor market."},{"kind":"tool","tool":"model.candidates","call":"Compute simple persistence and drift candidates from fetched first-print monthly history.","result":"Using fetched same-row monthly values 5.950, 6.038, 5.923, 5.691, 5.797, and 5.709 million gives successive changes +0.088, -0.115, -0.232, +0.106, and -0.088 million, mean -0.048 million and sigma = 0.143 million. Persistence candidate point = 5.709 million; selected mild-drift candidate point = 5.720 million with 80% interval 5.520-5.920."},{"kind":"math","text":"Prior/update/interval: model prior = latest first-print persistence at 5.709 million; historical sample = fetched same-row monthly levels 5.950, 6.038, 5.923, 5.691, 5.797, and 5.709 million; adjustment components = +0.011 million for mild rebound/seasonal persistence, +0.000 million one-off, +0.000 million policy mechanism, so point = 5.709 + 0.011 = 5.720 million. Successive changes are +0.088, -0.115, -0.232, +0.106, and -0.088 million, giving sigma = 0.143 million. The mechanical 80% half-width is roughly 1.28*sigma = 1.28*0.143 = 0.183 million; I widen slightly to 0.200 million, about 1.09x the mechanical half-width, because the exact first-print monthly history is short and CPS occupation subgroup allocation is noisy. Final implied bounds are 5.720 - 0.200 = 5.520 and 5.720 + 0.200 = 5.920 million."},{"kind":"text","text":"Upside risk: a favorable September CPS sample, faster hiring for home health and care-support roles, or rebound from the August dip would land above the interval if the Table A-19 row exceeds 5.920 million. Downside risk: adverse CPS sampling, weaker healthcare support participation, or continued drift below the 2025 same-month level would land below the interval if the row is under 5.520 million. Either case would be outside the interval."},{"kind":"forecast","point":5.72,"ciLow":5.52,"ciHigh":5.92}]}

# Reviewer critique
{
  "summary": "The draft is mostly publishable, but its interval math overstates rigor because it treats a non-contiguous August 2025 to June 2026 gap as a one-month realized change.",
  "requiredFixes": [
    {
      "rubricItem": "interval",
      "severity": "warning",
      "summary": "The realized-volatility sample labels all successive differences as monthly changes even though the 2025-08 to 2026-06 step is a 10-month gap.",
      "actionRequested": "Revise the interval explanation to either compute volatility only from contiguous month-to-month pairs or explicitly describe the sample as sparse same-row changes and justify using it for the 80% width."
    },
    {
      "rubricItem": "prior_update_interval",
      "severity": "warning",
      "summary": "The compact Prior/update/interval step inherits the same non-contiguous-change issue in the historical sample and sigma derivation.",
      "actionRequested": "Update the compact step so the historical sample, change calculation, sigma, and implied bounds use a coherent interval method."
    }
  ],
  "optionalSuggestions": [
    "Keep the explicit note that the BLS calendar appears to say October 2, 2026 while the registered target fixes resolutionDate as 2026-10-08.",
    "Consider making the +0.011 million rebound adjustment less precise or tie it to a simple average of recent contiguous changes."
  ]
}

Emit the final JSON object only.
