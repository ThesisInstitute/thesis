# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: bls.ces.nonfarm_payrolls.change
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "nonfarm-payrolls-september-2026"
- country: "US"
- targetUnit: "thousands"
- dataPointId: "bls.ces.total_nonfarm.payroll_employment.change.sa.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-10-08", "start": "2026-09-30"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.bls.gov"], "expectedReleaseWindow": {"end": "2026-10-08", "start": "2026-09-30"}, "field": "bls.ces.nonfarm_payrolls.change", "releasePolicy": "first_print", "sourceSeriesId": "bls.ces.nonfarm_payrolls.change", "sourceUrl": "https://www.bls.gov/news.release/empsit.nr0.htm", "table": "Official agency release", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-04-588ebf8cdde209f7bb4aa76660059207951e0786ee12bfecf197ab6d18af34f6.json"
- targetContentHash: "588ebf8cdde209f7bb4aa76660059207951e0786ee12bfecf197ab6d18af34f6"
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
{"slug":"nonfarm-payrolls-september-2026","country":"US","type":"data","title":"US Nonfarm Payrolls Change, September 2026","question":"What will the BLS first-print seasonally adjusted change in total nonfarm payroll employment be for September 2026?","unit":"thousands","pointEstimate":75,"ciLow":-52,"ciHigh":202,"confidence":0.8,"resolutionDate":"2026-10-02","resolutionSource":"Official agency release","resolutionSourceUrl":"https://www.bls.gov/news.release/empsit.nr0.htm","resolutionRule":"Resolve to the first-print over-the-month change, in thousands, for seasonally adjusted total nonfarm payroll employment in the BLS Employment Situation release for September 2026, table B-1 / summary table B. Use the value as first published on October 2, 2026, without later revisions or same-day correction grace unless BLS replaces the official release before publication is complete.","dataPointId":"bls.ces.total_nonfarm.payroll_employment.change.sa.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":130},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":-92},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":178},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":115},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":172},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":57},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":-23},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":162}],"drivers":["2026 first-print payroll base rate averages about 87 thousand","last three first prints average 65 thousand despite August rebound","August strength was partly concentrated in food services and local government education","health care trend remains positive but slower than its prior 12-month pace","July and June were revised up but remain soft on a revised basis"],"sourceContext":["https://www.bls.gov/schedule/news_release/empsit.htm","https://www.bls.gov/news.release/empsit.nr0.htm","https://www.bls.gov/news.release/archives/empsit_09042026.htm","https://www.bls.gov/news.release/archives/empsit_08072026.htm","https://www.bls.gov/news.release/archives/empsit_07022026.htm","https://www.bls.gov/news.release/archives/empsit_06052026.htm","https://www.bls.gov/news.release/archives/empsit_05082026.htm","https://www.bls.gov/news.release/archives/empsit_04032026.htm","https://www.bls.gov/news.release/archives/empsit_03062026.htm","https://www.bls.gov/news.release/archives/empsit_02112026.htm"],"runAt":"2026-09-04T19:09:02Z","reasoning":[{"kind":"heading","text":"September 2026 first-print nonfarm payrolls forecast"},{"kind":"text","text":"The target is the BLS Current Employment Statistics total nonfarm payroll employment over-the-month change, seasonally adjusted, first print for September 2026, in thousands. The resolver is the BLS Employment Situation release page and table B-1 / summary table B; the series variant is the seasonally adjusted total nonfarm establishment payroll change, not household employment, not not-seasonally-adjusted employment, and not a later revised CES level."},{"kind":"tool","tool":"official.lookup","call":"Checked BLS Employment Situation schedule and current release page for the September 2026 publication date and latest labor-market print.","result":"BLS schedule lists September 2026 Employment Situation release on Oct. 02, 2026 at 08:30 AM; the Aug. 2026 release reports total nonfarm payroll employment +162 thousand, unemployment rate 4.1 percent, prior-12-month payroll average +31 thousand, June revised from +20 to +31 thousand, and July revised from -23 to +21 thousand."},{"kind":"tool","tool":"official.lookup","call":"Read BLS archived Employment Situation releases for early-2026 first-print total nonfarm payroll changes.","result":"First-print seasonally adjusted total nonfarm payroll changes fetched from BLS archives: January 2026 +130 thousand, February 2026 -92 thousand, March 2026 +178 thousand, April 2026 +115 thousand; associated unemployment rates were 4.3 percent, 4.4 percent, 4.3 percent, and 4.3 percent."},{"kind":"tool","tool":"official.lookup","call":"Read BLS archived Employment Situation releases for recent first-print total nonfarm payroll changes.","result":"First-print seasonally adjusted total nonfarm payroll changes fetched from BLS archives: May 2026 +172 thousand, June 2026 +57 thousand, July 2026 -23 thousand, August 2026 +162 thousand; August details included food services +59 thousand, local government education +42 thousand, manufacturing +16 thousand, health care +13 thousand, and information -23 thousand."},{"kind":"text","text":"Reference class/base rate: the same-variant 2026 first prints from January through August are 130, -92, 178, 115, 172, 57, -23, and 162 thousand. Their mean is 87.4 thousand, while the last three first prints average 65.3 thousand. I put more weight on the recent slower hiring regime than on the full-year mean."},{"kind":"text","text":"Level, momentum, one-off, and policy-mechanism effects are mixed. Level: unemployment at 4.1 percent is not recessionary. Momentum: June and July were weak even after revision, while August rebounded. One-off: August's +162 thousand had a visible local-government-education rebound and food-services surge that I do not fully extrapolate. Policy-mechanism: no resolver-relevant policy level changes the first-print rule; federal and information-sector weakness keep the forecast below the full 2026 mean."},{"kind":"math","text":"Prior/update/interval: persistence prior is the 2026 first-print reference class mean of 87.4 thousand from the 8 official BLS prints listed above; adjustment components are -15 thousand for recent three-month softness versus the full sample, -10 thousand for likely August one-off education/food-services payback, and +12 thousand for unemployment still near 4.1 percent and June/July upward revisions, giving about 74.4 thousand rounded to 75. For interval sizing, using the values themselves for this change/flow series, sample sigma = 99.1 thousand; 1.28*sigma = 126.9 thousand, so the 80% interval is 75 +/- 127 = [-52, 202] thousand."},{"kind":"text","text":"Upside risk is a second month of education normalization plus broad private services hiring that would land above the interval if September prints above +202 thousand. Downside risk is renewed information/professional-services contraction or a weak seasonal-adjustment print that would land below the interval if payrolls fall by more than 52 thousand. Outside the interval would likely require a broad shock rather than ordinary month-to-month noise."},{"kind":"forecast","point":75,"ciLow":-52,"ciHigh":202}]} }

# Reviewer critique
{
  "summary": "Draft is mostly publication-ready, but its resolutionDate conflicts with the canonical ledger target contract.",
  "requiredFixes": [
    {
      "rubricItem": "resolver",
      "severity": "blocking",
      "summary": "The draft sets resolutionDate to 2026-10-02, while the canonical target context binds the target to the ledger registration and expectedReleaseWindow ending 2026-10-08.",
      "actionRequested": "Set the cell resolutionDate to the ledger-bound date 2026-10-08, while keeping the reasoning explicit that the BLS scheduled first-print release is expected on 2026-10-02 if that remains the cited public schedule."
    }
  ],
  "optionalSuggestions": [
    "In the interval sentence, note that sigma is estimated from only eight 2026 first prints, so the 80% interval reflects high sampling uncertainty.",
    "Clarify that June and July revisions are current evidence available before the September target resolves, not target outcomes."
  ]
}

Emit the final JSON object only.
