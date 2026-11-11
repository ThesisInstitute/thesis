# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.jolts.job_openings
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "jolts-openings-september-2026"
- country: "US"
- targetUnit: "millions"
- dataPointId: "bls.jolts.job_openings.september_2026.first_print"
- expectedReleaseWindow: {"end": "2026-11-09", "start": "2026-11-01"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-11-09", "start": "2026-11-01"}, "field": "bls.jolts.job_openings", "releasePolicy": "first_print", "sourceSeriesId": "bls.jolts.job_openings", "sourceUrl": "https://www.bls.gov/news.release/jolts.nr0.htm", "table": "U.S. Bureau of Labor Statistics Job Openings and Labor Turnover Survey first-print release", "transform": {"factor": 0.001, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-25f383726a59f3170ab6359a0393aae5291197c2654c5e5ad362fcc4e0fef3f9.json"
- targetContentHash: "25f383726a59f3170ab6359a0393aae5291197c2654c5e5ad362fcc4e0fef3f9"
- registrationCommit: "baad7107ac843adbbb7a8038e4138d5e24100521"
- registeredAtUtc: "2026-09-04T19:02:52Z"

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
{"slug":"jolts-openings-september-2026","country":"US","type":"data","title":"US JOLTS job openings, September 2026","question":"What will BLS first report for total nonfarm job openings, seasonally adjusted, for September 2026 in the Job Openings and Labor Turnover Survey release?","unit":"millions","pointEstimate":7.32,"ciLow":6.69,"ciHigh":7.95,"confidence":0.8,"resolutionDate":"2026-11-03","resolutionSource":"U.S. Bureau of Labor Statistics Job Openings and Labor Turnover Survey first-print release","resolutionSourceUrl":"https://www.bls.gov/news.release/jolts.nr0.htm","resolutionRule":"Resolve to the first-published preliminary BLS Job Openings and Labor Turnover Survey total nonfarm job openings level, seasonally adjusted, for September 2026, from Table A or Table 1 of the initial release. The printed level is in thousands and is multiplied by 0.001 to millions. Ignore later monthly revisions, annual benchmark revisions, corrections after the first official print, and database values revised after the release.","dataPointId":"bls.jolts.job_openings.september_2026.first_print","historicalContext":[{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":6.542},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":6.946},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":6.882},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":6.866},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":7.618},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":7.594},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":7.359},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":7.271}],"drivers":["July first-print openings were 7.271 million, close to the recent 7.3 million center","Recent first-print changes are volatile, with a 0.752 million April jump followed by smaller declines","August payroll growth of 162000 and 4.1 percent unemployment reduce near-term downside pressure","Low-hire, low-fire conditions argue against a sharp September breakout"],"sourceContext":["https://www.bls.gov/schedule/news_release/jolts.htm?stream=business","https://www.bls.gov/news.release/archives/jolts_02052026.htm","https://www.bls.gov/news.release/archives/jolts_03132026.htm","https://www.bls.gov/news.release/archives/jolts_03312026.htm","https://www.bls.gov/news.release/archives/jolts_05052026.htm","https://www.bls.gov/news.release/archives/jolts_06022026.htm","https://www.bls.gov/news.release/archives/jolts_06302026.htm","https://www.bls.gov/news.release/archives/jolts_08042026.htm","https://www.bls.gov/news.release/archives/jolts_09012026.htm","https://www.bls.gov/news.release/archives/empsit_09042026.htm","https://www.bls.gov/news.release/jolts.nr0.htm"],"runAt":"2026-09-04T19:12:19Z","reasoning":[{"kind":"heading","text":"September 2026 BLS JOLTS job openings forecast"},{"kind":"text","text":"The resolver is the BLS JOLTS first-print preliminary total nonfarm job openings level, seasonally adjusted, for September 2026. The BLS schedule page lists September 2026 JOLTS for release on November 3, 2026 at 10:00 AM ET, so resolutionDate is 2026-11-03."},{"kind":"text","text":"Variant discipline: all anchors use the seasonally adjusted total nonfarm job openings level from BLS JOLTS Table A or equivalent first-print release table. The printed unit is thousands; this cell reports millions using the registered 0.001 transform."},{"kind":"tool","tool":"official.lookup","call":"BLS JOLTS release calendar lookup for September 2026","result":"Fetched schedule rows: July 2026 release Sep. 01, 2026 at 10:00 AM; August 2026 release Sep. 29, 2026 at 10:00 AM; September 2026 release Nov. 03, 2026 at 10:00 AM."},{"kind":"tool","tool":"official.lookup","call":"BLS archived JOLTS Table A first-print total job openings for late 2025 and early 2026","result":"Fetched first-print total job openings, seasonally adjusted, in thousands: December 2025 6542, January 2026 6946, February 2026 6882, March 2026 6866."},{"kind":"tool","tool":"official.lookup","call":"BLS archived JOLTS Table A first-print total job openings for April through July 2026","result":"Fetched first-print total job openings, seasonally adjusted, in thousands: April 2026 7618, May 2026 7594, June 2026 7359, July 2026 7271."},{"kind":"tool","tool":"official.lookup","call":"BLS Employment Situation August 2026 labor-market cross-check","result":"Fetched August 2026 labor-market values: total nonfarm payroll employment increased 162000, unemployment rate was 4.1 percent, June payroll change was revised to +31000, and July payroll change was revised to +21000."},{"kind":"text","text":"The reference class and base rate are recent same-series first prints: December 2025 through July 2026 total openings ran from 6.542 million to 7.618 million, with the latest July print at 7.271 million. A persistence prior around 7.27 million is more relevant than a long-run average because JOLTS is a level series with strong local persistence."},{"kind":"math","text":"Prior/update/interval: persistence prior is July 2026 first print 7.271 million; historical sample is BLS first-print monthly openings from December 2025 through July 2026; adjustment components are +0.03 million for the August payroll rebound and stable 4.1 percent unemployment, +0.02 million for current openings still above early-2026 levels, and roughly 0.00 million for policy mechanism effects because no direct September hiring mandate applies. Successive changes were +0.404, -0.064, -0.016, +0.752, -0.024, -0.235, -0.088 million; one-month sample stdev is 0.347, so two-month horizon sigma = sqrt(2)*0.347 = 0.490. The 80 percent half-width is 1.28*sigma = 1.28*0.490 = 0.627 million. Point is 7.271 + 0.05 = 7.32; interval is 7.32 +/- 0.63 = [6.69, 7.95]."},{"kind":"text","text":"Upside risk would come from August and September openings rising alongside the 162000 August payroll gain, especially in food services, education, construction, or health care; a September first print near 8.0 million or above would land above the interval. Downside risk is renewed hiring freezes or a pullback in professional and business services; a broad demand drop below about 6.7 million would land outside the interval on the low side."},{"kind":"forecast","point":7.32,"ciLow":6.69,"ciHigh":7.95}]}

# Reviewer critique
{"summary":"Draft is publishable with only minor clarity issues; resolver, unit, first-print rule, prior/update math, interval, tails, and JSON fields are coherent.","requiredFixes":[],"optionalSuggestions":["State explicitly that the 2026-11-03 release date is inside the registered 2026-11-01 to 2026-11-09 expected release window.","Clarify that the persistence/random-walk prior is the chosen time-series model rather than leaving 'model prior' implicit."]}

Emit the final JSON object only.
