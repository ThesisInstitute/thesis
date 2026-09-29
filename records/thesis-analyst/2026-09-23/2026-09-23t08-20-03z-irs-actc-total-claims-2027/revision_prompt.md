# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: irs.actc.total_claims
- period: 2027
- conditionalOn: Legislation enacted by 2027-12-31 makes the IRC §24(d)(1)(B)(i) earned-income threshold no more than $1 for tax year 2027.
  Your cell's `conditionalOn` field must repeat this text byte-for-byte; the registry gates on the exact string.

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "additional-child-tax-credit-total-claims-ty2027-threshold-one-dollar"
- country: "US"
- targetUnit: "millions"
- dataPointId: "irs.actc.total_claims.2027.first_print.threshold_one_dollar"
- resolutionDate: "2029-12-31"
- publishedResolutionDate: "2029-12-31"
- resolutionDateBasis: "resolve-by-bound"
- expectedReleaseWindow: {"end": "2029-12-31", "start": "2029-01-01"}
- resolutionSource: "IRS Statistics of Income, Individual Income Tax Returns Complete Report (Publication 1304), Table 3.3"
- resolutionSourceUrl: "https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304"
- resolutionRule: "If the condition in conditionalOn is satisfied, resolve from the first IRS publication of tax-year 2027 Publication 1304 Table 3.3: the 'All returns, total' row and 'Number of returns' subcolumn under 'Refundable child tax credit or additional child tax credit.' The series is annual and not seasonally adjusted. The adapter returns the published whole-return count; multiply it by 0.000001 to express it in millions. Later revisions are irrelevant. The registered official-source release window is 2029-01-01 through 2029-12-31, with resolutionDate set to its verified by-date endpoint, 2029-12-31. If the stated legislative condition is not satisfied by 2027-12-31, mark this conditional forecast unresolved."
- resolutionPolicy: "first_print"
- sourceBinding: {"adapter": "irs-soi-pub1304", "allowedHosts": ["www.irs.gov"], "expectedReleaseWindow": {"end": "2029-12-31", "start": "2029-01-01"}, "field": "refundable_child_tax_credit_returns", "releasePolicy": "first_print", "sourceSeriesId": "irs.actc.total_claims", "sourceUrl": "https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304", "table": "IRS SOI Individual Income Tax Returns Complete Report (Publication 1304), Table 3.3, all returns total row, refundable child tax credit or additional child tax credit, number of returns", "transform": {"factor": 1e-06, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-08-03-6978365a2924b850a9516b49451ed3e07b2bb14321ea908344ce17744296f5e6.json"
- targetContentHash: "6978365a2924b850a9516b49451ed3e07b2bb14321ea908344ce17744296f5e6"
- registrationCommit: "a4f59c018641c8d772975263735424cb5d46bb25"
- registeredAtUtc: "2026-08-03T20:13:09Z"
- conditional: "Legislation enacted by 2027-12-31 makes the IRC \u00a724(d)(1)(B)(i) earned-income threshold no more than $1 for tax year 2027."

Reviewed anchors are cross-checks, not the full historical reference class or a history-floor waiver. Fetch at least six distinct canonical official prints when available, including earlier years if the recent table exposes fewer. Do not count an anchor as a fetched print without its official source.

# Comparison target contract (machine checked)
This run is a strategy comparison against an already published forecast. The sealed cell's resolutionDate, resolutionSource, resolutionSourceUrl and resolutionRule are pinned to that forecast's published resolver; publishedResolutionDate "2029-12-31" is its resolver date. Still verify the official release schedule this run and state any discrepancy in reasoning rather than changing the target.

# Resolve-by-bound target contract (machine checked)
- registeredResolveByBound: "2029-12-31"
- officialAnnouncementUrl: "https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304"
The bound and expected release window are Thesis lab commitments, not timing claims made by the announcement. The announcement authenticates methodology identity only; it does not establish the bound or expected release window. This is an outer bound, not a scheduled release day. resolutionDate must byte-echo the registered resolve-by bound; never infer a more specific day from cadence.
resolutionSourceUrl must byte-echo officialAnnouncementUrl. Call `thesis_announcement_fetch.fetch_official_announcement` with that exact URL. The publisher authenticates the structured draft/final tool event; a reasoning-token claim, search result, same-host page, or prose citation cannot substitute for it.
Base rate during a methodology transition: while NO official print under the announced revised methodology exists — including revised historical or backcast estimates — the CURRENT official series is the admissible base rate: fetch it from its official source, name its vintage explicitly, and state the announced transition as the regime consideration in the sigma step. Do not refuse for lack of the unpublished revised series, and do not fabricate or pre-apply revision adjustments. The moment any revised-methodology official print exists, revised prints are required and old-methodology history stops being admissible.

# Resolution-grade base-rate fetch (captured workbook extraction)
For each of the latest six published tax years, call fetch_source on https://www.irs.gov/pub/irs-soi/YYin33ar.xls (YY is the two-digit tax year), then use that returned call ID in:
  extract_irs_soi({"sourceCallId":"FETCH_CALL_ID","seriesId":"irs.actc.total_claims","year":"YYYY"})   # YYYY is that workbook's four-digit tax year
The tool replays the registered adapter against the complete captured bytes and returns rawValue plus value in the target unit. Use value directly; do not apply the transform twice. Use the extraction call IDs as calculate inputs for the base rate and interval arithmetic. Preserve the exact extracted values and year identities in historicalContext through review and revision. A binary fetch excerpt is not a parsed table. Do not guess a value from it or substitute a rounded bulletin number. Parser errors describe an extraction failure, not unavailability of that official year. Record the refusal and keep the run failed if canonical history cannot be extracted. Four verified anchors do not mean only four years exist. Fetch earlier official workbooks to retain at least six canonical prints; do not replace them with a history waiver.
Use these MCP calls in the native captured lane; shell network access and package installation are unavailable there.
This count is TOTAL ACTC claiming returns at the reviewed plain Additional child tax credit concept header. The separate refundable portion and used to offset other taxes columns are different subsets; never substitute them.

# Source hints
- Use IRS filing-season statistics, annual inflation-adjustment revenue procedures, and official IRS release pages.
- For threshold targets, resolve to the first official IRS value for the named tax year and parameter, not an inferred estimate once the official figure is available.
- Match the catalog unit, usually nominal dollars or billions of nominal dollars.

# Default promoted forecasting practices
- Resolve the exact first-print target before inside-view evidence.
- Fetch and state the recent official-source reference class: at least 6 distinct prints are MANDATORY whenever the official source exposes them.
- Anchor on the outside-view base rate before current-release adjustments.
- Separate level, momentum, one-off, and policy-mechanism effects before combining them.
- Include one public reasoning step beginning "Prior/update/interval:" that names the model or persistence prior, historical sample, adjustment components, interval method, and final implied bounds.
- For strict first-print or original-vintage targets, keep the ledger resolver in substance and do not add same-day correction or release-day grace exceptions unless the target rule includes them.
- Size the 80% interval from realized dispersion and SHOW the arithmetic in the Prior/update/interval step: compute sigma from the fetched history (successive changes for level/rate series; the values themselves for change/flow series), state it literally as "sigma = X", and derive the half-width as roughly 1.28*sigma. If you widen or narrow beyond about 0.75x-1.75x of that half-width, state the regime or mechanism reason in the same step. Never default to a round hedged band.
- When a release has variants (gross vs smoothed/synthetic, SA vs NSA, flash vs final), the resolution rule must name the variant and every anchor and historical value must come from that same variant; say so once in a text step.
- resolutionSourceUrl must byte-echo the registered official methodology-announcement URL shown in the bounded target context. Use the `thesis_announcement_fetch.fetch_official_announcement` tool on that exact URL; put any separately fetched resolving table or data-artifact URL in sourceContext.
- Name concrete upside, downside, and outside-the-interval scenarios, using the literal phrases "upside risk", "downside risk", and "outside the interval" (or "would land above/below the interval") so the falsification step is machine-checkable.

# Required JSON shape
{
  "slug": "kebab-case-unique-vs-catalog",
  "country": "US|UK|CA|AU|EA|JP",
  "type": "conditional",
  "conditionalOn": "the registered conditional text, byte-for-byte",
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
- resolutionDate must byte-echo the registered Thesis lab-committed resolve-by bound shown in the target context. It is an outer bound, not a scheduled release day; the official announcement does not establish it, and you must not infer a more specific date from cadence.
- Do not use existing local catalog point estimates or intervals as forecast evidence. If inspected, treat them only as non-authoritative prior strategy context and keep them out of tool-result evidence.
- runAt must be the actual UTC date command output from this run.
- Slug should be stable and descriptive; if the same target already exists, reuse the obvious canonical slug rather than inventing a near-duplicate.

Emit the final JSON object only. (agent thesis.analyst v2.5.11, prompt 87db344b803f, tools 024388e49298, promptMode fast)

# Threshold-ladder elicitation (promptMode ladder)
This run elicits the distribution as binary exceedance questions BEFORE stating any point estimate, then derives the published numbers from the ladder.
- After research, choose 11-15 strictly increasing thresholds t in the target's print units spanning your genuine uncertainty: the first rung's cumulative probability must be <= 0.10 and the last >= 0.90.
- For each rung independently answer the binary question 'What is the probability the first print is <= t?', as if pricing a binary market. Probabilities must be non-decreasing across rungs and within [0.01, 0.99].
- Add one math reasoning step that begins 'Ladder:' and lists every rung literally as 'P(X <= t) = p' pairs.
- Derive the published numbers FROM the ladder by linear interpolation between rungs: pointEstimate at cumulative 0.50, ciLow at 0.10, ciHigh at 0.90, each rounded to the print precision. The cell fields and the final forecast step must equal these derived values exactly.
- Keep every fast-mode requirement above (sigma arithmetic, base rate, upside/downside/outside-the-interval risks). In the Prior/update/interval step, also state how the ladder-implied 80% width compares to the 1.28*sigma width.
- Add this top-level field to the cell JSON, with your actual rungs as two equal-length numeric arrays:
{
  "thresholdLadder": {
    "thresholds": [
      "strictly increasing numeric rungs"
    ],
    "cumulativeProbabilities": [
      "non-decreasing, within [0.01, 0.99]"
    ]
  }
}


# Captured tool evidence
Use the thesis_tool_evidence MCP tools for source reads and calculations.
fetch_source saves the complete public HTTPS response and returns its call ID,
hash, and a bounded excerpt. extract_json selects a JSON Pointer from a prior
fetch_source response. extract_irs_soi replays the reviewed IRS Table 3.3
parser on a prior captured workbook, selecting the exact series and tax year;
its numeric value is already in the registered unit. calculate evaluates
bounded arithmetic, with named inputs
that can refer to earlier extraction/calculation results by {"callId":"call-0001"}.
Use these tools for the base rate and interval arithmetic, and cite the returned
call IDs in your trace. Keep supplied assumptions and judgment adjustments
explicit. An extraction or calculation replay verifies the operation on its
inputs; it does not independently verify those assumptions or the source's truth.
Tool calls outside this channel, including hosted web search and shell commands,
do not preserve full response receipts here. Say when evidence was not captured.
Never manufacture a tool receipt or describe model-authored text as captured
output. Failed calls remain in the record. Only public, unauthenticated HTTPS
sources are supported; do not send credentials or private URLs to these tools.


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
{"slug":"additional-child-tax-credit-total-claims-ty2027-threshold-one-dollar","country":"US","type":"conditional","conditionalOn":"Legislation enacted by 2027-12-31 makes the IRC §24(d)(1)(B)(i) earned-income threshold no more than $1 for tax year 2027.","title":"ACTC total claims, TY2027 threshold $1","question":"IRS SOI Publication 1304 Table 3.3 first-print total returns claiming the refundable child tax credit or additional child tax credit for tax year 2027, conditional on the IRC 24(d)(1)(B)(i) earned-income threshold being no more than $1.","unit":"millions","pointEstimate":22.142857,"ciLow":16.4,"ciHigh":32,"confidence":0.8,"resolutionDate":"2029-12-31","resolutionSource":"IRS Statistics of Income, Individual Income Tax Returns Complete Report (Publication 1304), Table 3.3","resolutionSourceUrl":"https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304","resolutionRule":"If the condition in conditionalOn is satisfied, resolve from the first IRS publication of tax-year 2027 Publication 1304 Table 3.3: the 'All returns, total' row and 'Number of returns' subcolumn under 'Refundable child tax credit or additional child tax credit.' The series is annual and not seasonally adjusted. The adapter returns the published whole-return count; multiply it by 0.000001 to express it in millions. Later revisions are irrelevant. The registered official-source release window is 2029-01-01 through 2029-12-31, with resolutionDate set to its verified by-date endpoint, 2029-12-31. If the stated legislative condition is not satisfied by 2027-12-31, mark this conditional forecast unresolved.","dataPointId":"irs.actc.total_claims.2027.first_print.threshold_one_dollar","historicalContext":[{"period":{"type":"year","value":"2018"},"label":"2018","value":20.450468},{"period":{"type":"year","value":"2019"},"label":"2019","value":19.867646},{"period":{"type":"year","value":"2020"},"label":"2020","value":19.119249},{"period":{"type":"year","value":"2021"},"label":"2021","value":37.771612},{"period":{"type":"year","value":"2022"},"label":"2022","value":18.076696},{"period":{"type":"year","value":"2023"},"label":"2023","value":17.626084}],"drivers":["Latest normal-law ACTC total-claims level is 17.626084 million in TY2023","TY2021 full-refundability outlier shows a high-participation ceiling of 37.771612 million","A $1 earned-income threshold should add very-low-earnings working families but not all zero-earnings families","Filing incentives and awareness determine whether small refundable amounts are claimed"],"sourceContext":["https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304","https://www.irs.gov/pub/irs-soi/18in33ar.xls","https://www.irs.gov/pub/irs-soi/19in33ar.xls","https://www.irs.gov/pub/irs-soi/20in33ar.xls","https://www.irs.gov/pub/irs-soi/21in33ar.xls","https://www.irs.gov/pub/irs-soi/22in33ar.xls","https://www.irs.gov/pub/irs-soi/23in33ar.xls","https://www.irs.gov/pub/irs-soi/24in33ar.xls"],"runAt":"2026-09-23T08:21:06Z","thresholdLadder":{"thresholds":[14,16,17,18,19,20,21,22,23,24,26,28,31,34],"cumulativeProbabilities":[0.03,0.08,0.13,0.19,0.26,0.34,0.42,0.49,0.56,0.63,0.73,0.81,0.88,0.94]},"reasoning":[{"kind":"heading","text":"ACTC total claims, TY2027 threshold $1"},{"kind":"text","text":"Framing and exact resolver: this conditional cell resolves only if legislation enacted by 2027-12-31 makes the IRC 24(d)(1)(B)(i) earned-income threshold no more than $1 for tax year 2027. The resolving variant is IRS SOI Publication 1304 Table 3.3, all returns total row, number of returns under refundable child tax credit or additional child tax credit, first print, annual NSA, expressed in millions. The registered resolve-by-bound is 2029-12-31; the official announcement page was fetched with the required exact URL and authenticates methodology identity, not a scheduled release day."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0003/call-0002/call-0005, then extract_irs_soi call-0012/call-0010/call-0011 for IRS Pub 1304 Table 3.3 TY2018-TY2020","result":"Fetched official workbook values: TY2018 rawValue 20450468 and value 20.450468 million; TY2019 rawValue 19867646 and value 19.867646 million; TY2020 rawValue 19119249 and value 19.119249 million."},{"kind":"tool","tool":"official.lookup","call":"fetch_source call-0004/call-0006/call-0001, then extract_irs_soi call-0009/call-0008/call-0007 for IRS Pub 1304 Table 3.3 TY2021-TY2023","result":"Fetched official workbook values: TY2021 rawValue 37771612 and value 37.771612 million; TY2022 rawValue 18076696 and value 18.076696 million; TY2023 rawValue 17626084 and value 17.626084 million."},{"kind":"text","text":"Reference class and base rate: the current official series, with no captured revised-methodology replacement print, gives a six-print base rate of 2018-2023 values: 20.450468, 19.867646, 19.119249, 37.771612, 18.076696, and 17.626084 million. The 2024 workbook URL returned 404 in captured call-0013, so I kept the latest six extractable official prints, TY2018-TY2023."},{"kind":"tool","tool":"official.calculate","call":"calculate call-0014/call-0015/call-0020/call-0022 over the six extracted IRS values and ladder outputs","result":"Fetched-history calculations: mean 22.151959166666664 million; sigma from stdev(values) 7.724964211235581; 1.28*sigma 9.887954190381544; ladder half-width from 16.4 to 32.0 is 7.800000000000001 million."},{"kind":"math","text":"Prior/update/interval: persistence prior is the official six-print IRS history centered near the current-law/post-ARPA level, with the 2021 fully refundable value retained as an observed regime outlier; historical sample is TY2018-TY2023, values 20.450468, 19.867646, 19.119249, 37.771612, 18.076696, 17.626084 million. Adjustment components: start from a roughly 18-20 million normal-law level, add several million claims for very-low-earnings families newly eligible when the threshold is $1, keep the upper tail below 2021 because a $1 earned-income threshold is not the same as full refundability for zero-earnings families. For this annual flow/count series, sigma = 7.724964 from the fetched values themselves, so 1.28*sigma = 9.887954. The ladder-implied 80% interval is 16.4 to 32.0, half-width 7.8, about 0.79x the 1.28*sigma half-width because the 2021 full-refundability spike is only a partial analog to the narrower threshold-only condition. Final implied bounds are 16.4 and 32.0 million."},{"kind":"math","text":"Ladder: P(X <= 14) = 0.03; P(X <= 16) = 0.08; P(X <= 17) = 0.13; P(X <= 18) = 0.19; P(X <= 19) = 0.26; P(X <= 20) = 0.34; P(X <= 21) = 0.42; P(X <= 22) = 0.49; P(X <= 23) = 0.56; P(X <= 24) = 0.63; P(X <= 26) = 0.73; P(X <= 28) = 0.81; P(X <= 31) = 0.88; P(X <= 34) = 0.94. Linear interpolation gives P10 = 16.4, P50 = 22.142857142857142, and P90 = 32.0 million; rounded forecast fields use 16.4, 22.142857, and 32.0."},{"kind":"text","text":"Counter-considerations: upside risk is a broader refundable-CTC design riding with the threshold change, aggressive outreach, or simplified claiming that pulls the result toward the 2021 37.771612 million outlier and would land above the interval. Downside risk is low take-up for tiny phase-in amounts, weak low-income labor-force attachment, or a restrictive final statute, which would keep claims near the TY2023 value of 17.626084 million or below. Outside the interval below 16.4 million would require the threshold change to produce little net take-up or be offset by eligibility tightening."},{"kind":"forecast","point":22.142857,"ciLow":16.4,"ciHigh":32}]}

# Reviewer critique
{
  "summary": "Draft is mostly coherent, but it needs a structured official-announcement fetch event and a clearer quantitative bridge from the persistence prior to the point estimate.",
  "requiredFixes": [
    {
      "rubricItem": "resolver",
      "severity": "blocking",
      "summary": "The reasoning says the official announcement page was fetched, but the draft does not show the required structured `thesis_announcement_fetch.fetch_official_announcement` event for the exact `resolutionSourceUrl`.",
      "actionRequested": "Add or preserve the structured announcement-fetch tool event using `https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304` exactly; do not rely on prose, sourceContext, or same-host workbook fetches."
    },
    {
      "rubricItem": "update",
      "severity": "warning",
      "summary": "The move from the latest normal-law value of 17.626084 million to a 22.142857 million point estimate is directionally explained but only loosely quantified.",
      "actionRequested": "State a compact numeric update bridge, for example current-law/post-ARPA baseline plus estimated low-earnings eligibility/take-up increment, and tie that bridge to the final median."
    }
  ],
  "optionalSuggestions": [
    "Keep the six exact extracted IRS values and year labels as written; they satisfy the canonical-history requirement if the extraction call IDs are preserved.",
    "Clarify that the 2024 workbook fetch failure was an official captured fetch failure, not evidence that no TY2024 publication exists."
  ]
}

Emit the final JSON object only.
