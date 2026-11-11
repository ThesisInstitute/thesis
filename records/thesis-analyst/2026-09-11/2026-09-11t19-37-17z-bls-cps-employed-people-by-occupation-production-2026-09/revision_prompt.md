# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.cps.employed_people_by_occupation.production
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "cps-production-employment-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.cps.employed_people_by_occupation.production.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-10-14", "start": "2026-10-06"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-14", "start": "2026-10-06"}, "field": "Production occupations", "releasePolicy": "first_print", "sourceSeriesId": "bls.cps.employed_people_by_occupation.production", "sourceUrl": "https://www.bls.gov/web/empsit/cpseea19.htm", "table": "CPS Employment Situation Table A-19, employed persons by occupation, not seasonally adjusted (thousands)", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-509aaff9e5589d155465f734902b0c02b366eb09226d957107fa7091bf786808.json"
- targetContentHash: "509aaff9e5589d155465f734902b0c02b366eb09226d957107fa7091bf786808"
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
{"slug":"cps-production-employment-september-2026","country":"US","type":"data","title":"US CPS production occupations employment, September 2026","question":"What will BLS first report in CPS Employment Situation Table A-19 for September 2026 employed people age 16 and over in Production occupations, not seasonally adjusted, in millions?","unit":"millions","pointEstimate":7.556,"ciLow":7.264,"ciHigh":7.848,"confidence":0.8,"resolutionDate":"2026-10-02","resolutionSource":"U.S. Bureau of Labor Statistics Employment Situation, CPS Table A-19","resolutionSourceUrl":"https://www.bls.gov/web/empsit/cpseea19.htm","resolutionRule":"Resolve to the first official BLS value published for September 2026 in CPS Employment Situation Table A-19, row 'Production occupations,' Total, 16 years and over, not seasonally adjusted, reported in thousands. Multiply the published thousands value by 0.001 and report millions rounded to three decimals. Use the first official print only, with no later revisions or later correction exceptions. The official BLS Employment Situation calendar fetched this run lists September 2026 for October 2, 2026 at 08:30 AM ET; this conflicts with the registered target window ending 2026-10-14, but the slug and dataPointId remain tied to the registered target.","dataPointId":"bls.cps.employed_people_by_occupation.production.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":7.786},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":7.742},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":7.685},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":7.883},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":7.912},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":7.759},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":8.121},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":7.716}],"drivers":["August 2026 A-19 level","Recent CPS occupation volatility","Typical August-to-September NSA softening","No discrete policy mechanism"],"sourceContext":["https://www.bls.gov/web/empsit/cpseea19.htm","https://www.bls.gov/schedule/news_release/empsit.htm","https://fred.stlouisfed.org/series/LNU02032213","https://fred.stlouisfed.org/data/LNU02032213","https://alfred.stlouisfed.org/series?seid=LNU02032213"],"runAt":"2026-09-11T19:37:22Z","reasoning":[{"kind":"heading","text":"September 2026 CPS production occupations employment forecast"},{"kind":"text","text":"Framing and exact resolver: this is the CPS household-survey Production occupations row, not seasonally adjusted, Total age 16 years and over, reported by BLS in thousands in Employment Situation Table A-19 and converted to millions by multiplying by 0.001. The matching BLS/FRED source code for the same Production occupations employment level is LNU02032213; FRED/ALFRED are used only as public history mirrors, while resolution uses the BLS A-19 page."},{"kind":"tool","tool":"official.lookup","call":"Fetch current BLS CPS Employment Situation Table A-19 row for Production occupations from https://www.bls.gov/web/empsit/cpseea19.htm.","result":"BLS Table A-19 reports Production occupations at 7,716 thousand for August 2026 and 7,482 thousand for August 2025, equal to 7.716 million and 7.482 million after the 0.001 transform."},{"kind":"tool","tool":"history.lookup","call":"Fetch recent BLS-source LNU02032213 history from FRED/ALFRED history pages and current series page.","result":"The BLS-source LNU02032213 history gives January 2026 7,786 thousand, February 2026 7,742 thousand, March 2026 7,685 thousand, April 2026 7,883 thousand, May 2026 7,912 thousand, June 2026 7,759 thousand, July 2026 8,121 thousand, and August 2026 7,716 thousand."},{"kind":"tool","tool":"official.lookup","call":"Verify the Employment Situation release date from the BLS schedule page for September 2026.","result":"The BLS schedule lists Reference Month September 2026 with Release Date Oct. 02, 2026 and Release Time 08:30 AM; the registered sourceBinding window says 2026-10-06 to 2026-10-14, so the official calendar is earlier by 4 to 12 days."},{"kind":"text","text":"Base rate / reference class: the strongest simple prior is latest-level persistence from the same CPS production occupations series, anchored on August 2026 at 7.716 million. The recent reference class is January-August 2026 exact-series values of 7.786, 7.742, 7.685, 7.883, 7.912, 7.759, 8.121, and 7.716 million, with the year staying mostly in a 7.7-8.1 million band but noisy month-to-month movement."},{"kind":"text","text":"Level, momentum, one-off, and policy effects: level starts at the August 2026 first print of 7.716 million. Momentum is mixed because July's spike to 8.121 was followed by August's fall to 7.716. One-off CPS sampling noise is large for this occupation subgroup, so I do not extrapolate the full July-to-August drop. Policy mechanism is neutral; no discrete public policy event changes the September CPS occupation count."},{"kind":"math","text":"Prior/update/interval: persistence prior = 7.716 million from August 2026; historical sample = January-August 2026 values 7.786, 7.742, 7.685, 7.883, 7.912, 7.759, 8.121, and 7.716 million; adjustment components = -0.160 million for typical August-to-September NSA softening, +0.000 one-off, +0.000 policy, yielding point = 7.716 - 0.160 = 7.556 million. Interval method = RMS successive changes from the fetched 2026 history: changes are -0.044, -0.057, +0.198, +0.029, -0.153, +0.362, and -0.405 million, so sigma = sqrt((0.044^2 + 0.057^2 + 0.198^2 + 0.029^2 + 0.153^2 + 0.362^2 + 0.405^2)/7) = 0.228 million. The 80% half-width is roughly 1.28*sigma = 1.28*0.228 = 0.292 million; 7.556 - 0.292 = 7.264 and 7.556 + 0.292 = 7.848."},{"kind":"text","text":"Upside risk is a rebound in the September CPS sample, stronger goods-sector labor demand, or occupational reclassification back into production work, which would land above the interval at more than 7.848 million. Downside risk is another adverse CPS sample, deeper manufacturing weakness, or a larger seasonal September decline, which would land below 7.264 million and outside the interval."},{"kind":"forecast","point":7.556,"ciLow":7.264,"ciHigh":7.848}]}

# Reviewer critique
{"summary":"The draft is mostly coherent, but it has a blocking target-contract mismatch on resolution date and an unsupported August-to-September adjustment.","requiredFixes":[{"rubricItem":"resolver","severity":"blocking","summary":"The draft sets resolutionDate to 2026-10-02, while the registered ledger target requires the publication cell to stay tied to the target contract whose expectedReleaseWindow ends 2026-10-14.","actionRequested":"Change the JSON resolutionDate to 2026-10-14 and keep the reasoning note that the BLS calendar appears to list October 2, 2026 as a discrepancy rather than silently changing the registered target."},{"rubricItem":"update","severity":"warning","summary":"The -0.160 million 'typical August-to-September NSA softening' adjustment is material but not supported by the cited January-August 2026 sample, which contains no August-to-September transitions.","actionRequested":"Add cited historical August-to-September evidence from the same series, or reduce/remove the seasonal adjustment and state that persistence is being used because same-month seasonal evidence was not applied."},{"rubricItem":"interval","severity":"warning","summary":"The 80% interval is computed from only seven 2026 month-to-month changes, which is an explicit method but a thin volatility sample for a noisy CPS occupation subgroup.","actionRequested":"Either use a longer same-series realized-volatility sample, preferably including prior Aug-Sep transitions, or explicitly state why the short 2026 sample is the intended uncertainty basis."}],"optionalSuggestions":["Clarify whether the August 2026 value is itself a first print or current table value if that matters for trace wording.","Keep FRED/ALFRED framed only as history mirrors, as the draft already does, because BLS is the resolver."]}

Emit the final JSON object only.
