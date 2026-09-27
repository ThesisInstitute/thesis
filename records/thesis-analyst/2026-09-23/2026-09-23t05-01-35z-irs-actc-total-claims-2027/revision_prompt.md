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

# Resolution-grade base-rate fetch (run this — do not substitute)
The registered adapter's own parser is runnable in this workspace, and its output IS the series this target resolves against: history fetched any other way (summaries, bulletins, line-item estimates, adjacent products) fails anchored validation even when it is a real official series. For each of the most recent published periods (fetch at least the latest six), run:
  pip install --user xlrd==2.0.1 >/dev/null 2>&1; python3 -c "import sys; sys.path.insert(0, 'scripts'); import resolve_pending as r; print(r.irs_soi_pub1304_fetch_normalized_year(r.IRS_SOI_PUB1304_ADAPTERS['irs.actc.total_claims'], 'PERIOD')[0])"   # PERIOD = a tax year like 2023

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
fetch_source response. calculate evaluates bounded arithmetic, with named inputs
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
{"slug":"additional-child-tax-credit-total-claims-ty2027-threshold-one-dollar","country":"US","type":"conditional","conditionalOn":"Legislation enacted by 2027-12-31 makes the IRC §24(d)(1)(B)(i) earned-income threshold no more than $1 for tax year 2027.","title":"ACTC total claims TY2027 with $1 threshold","question":"What will IRS SOI Publication 1304 Table 3.3 first print report for tax year 2027, all returns total row, number of returns under refundable child tax credit or additional child tax credit, if the earned-income threshold is no more than $1?","unit":"millions","pointEstimate":21.611111,"ciLow":16.3,"ciHigh":32.125,"confidence":0.8,"resolutionDate":"2029-12-31","resolutionSource":"IRS Statistics of Income, Individual Income Tax Returns Complete Report (Publication 1304), Table 3.3","resolutionSourceUrl":"https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304","resolutionRule":"If the condition in conditionalOn is satisfied, resolve from the first IRS publication of tax-year 2027 Publication 1304 Table 3.3: the 'All returns, total' row and 'Number of returns' subcolumn under 'Refundable child tax credit or additional child tax credit.' The series is annual and not seasonally adjusted. The adapter returns the published whole-return count; multiply it by 0.000001 to express it in millions. Later revisions are irrelevant. The registered official-source release window is 2029-01-01 through 2029-12-31, with resolutionDate set to its verified by-date endpoint, 2029-12-31. If the stated legislative condition is not satisfied by 2027-12-31, mark this conditional forecast unresolved.","dataPointId":"irs.actc.total_claims.2027.first_print.threshold_one_dollar","historicalContext":[{"period":{"type":"year","value":"2018"},"label":"2018","value":18.52836},{"period":{"type":"year","value":"2019"},"label":"2019","value":19.011027},{"period":{"type":"year","value":"2020"},"label":"2020","value":19.119249},{"period":{"type":"year","value":"2021"},"label":"2021","value":37.771612},{"period":{"type":"year","value":"2022"},"label":"2022","value":18.076696},{"period":{"type":"year","value":"2023"},"label":"2023","value":17.626084}],"drivers":["Recent current-law ACTC claimant counts cluster around 17.6 to 19.1 million","TY2021 ARPA full-refundability regime shows an upper reference point at 37.771612 million","A $1 earned-income threshold mechanically helps very-low-earnings families but is weaker than full refundability","Population and filing growth by TY2027 modestly lift the current-law base","Interval is derived from the threshold ladder and checked against realized dispersion"],"sourceContext":["https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304","https://www.irs.gov/pub/irs-soi/18in33ar.xls","https://www.irs.gov/pub/irs-soi/19in33ar.xls","https://www.irs.gov/pub/irs-soi/20in33ar.xls","https://www.irs.gov/pub/irs-soi/21in33ar.xls","https://www.irs.gov/pub/irs-soi/22in33ar.xls","https://www.irs.gov/pub/irs-soi/23in33ar.xls","https://www.irs.gov/pub/irs-prior/p1304--2020.pdf","https://www.irs.gov/pub/irs-prior/p1304--2021.pdf"],"runAt":"2026-09-23T05:01:51Z","thresholdLadder":{"thresholds":[14,16,17.5,18.5,19.5,20.5,21.5,22.5,24,26,28.5,31.5,34,38],"cumulativeProbabilities":[0.04,0.09,0.14,0.22,0.31,0.4,0.49,0.58,0.67,0.76,0.84,0.89,0.93,0.98]},"reasoning":[{"kind":"heading","text":"ACTC total claims TY2027 with $1 threshold"},{"kind":"text","text":"Framing and exact resolver: this conditional cell keeps the registered resolve-by-bound date 2029-12-31 and the IRS Publication 1304 Table 3.3 first-print rule. The target variant is annual, not seasonally adjusted, all returns total row, number of returns under refundable child tax credit or additional child tax credit, transformed from whole returns to millions."},{"kind":"text","text":"Official announcement and schedule check: thesis_announcement_fetch fetched the exact registered URL with status 200, 153837 response bytes, and sha256 1177f06ca6188df3562231a0de84faeceb79a0c1ec7664b31c3204a5eb314656. The page authenticates the Publication 1304 methodology/product identity, not a specific TY2027 release day, so I do not infer a date from cadence and keep the Thesis lab-committed outer bound of 2029-12-31."},{"kind":"tool","tool":"official.lookup","call":"Fetched IRS Publication 1304 Table 3.3 official workbooks for TY2018 and TY2019 with thesis_tool_evidence receipts call-0002 and call-0003; cross-checked the exact Table 3.3 rows in IRS prior Publication 1304 PDFs for tax years 2018 and 2019.","result":"Fetched official values: TY2018 additional child credit refundable portion all-returns total was 18,528,360 returns, or 18.528360 million; TY2019 additional child tax credit refundable portion all-returns total was 19,011,027 returns, or 19.011027 million."},{"kind":"tool","tool":"official.lookup","call":"Fetched IRS Publication 1304 Table 3.3 workbooks for TY2020 and TY2021 with evidence receipts call-0004 and call-0007, matching the reviewed adapter anchor hashes and parser identity for irs.actc.total_claims.","result":"Fetched official adapter values: TY2020 was 19,119,249 returns, or 19.119249 million; TY2021 was 37,771,612 returns, or 37.771612 million."},{"kind":"tool","tool":"official.lookup","call":"Fetched IRS Publication 1304 Table 3.3 workbooks for TY2022 and TY2023 with evidence receipts call-0005 and call-0006, matching the same all-returns total row and same subcolumn variant.","result":"Fetched official adapter values: TY2022 was 18,076,696 returns, or 18.076696 million; TY2023 was 17,626,084 returns, or 17.626084 million."},{"kind":"text","text":"Base rate / reference class: the admissible current official series history is TY2018-TY2023 on the same Publication 1304 Table 3.3 variant. The non-ARPA years sit tightly around 17.6 to 19.1 million, while TY2021 under ARPA full refundability reached 37.771612 million. The announced conditional is a $1 earned-income threshold, not automatic full refundability, so TY2021 is an upper regime reference rather than the central base rate."},{"kind":"math","text":"Ladder: P(X <= 14) = 0.04; P(X <= 16) = 0.09; P(X <= 17.5) = 0.14; P(X <= 18.5) = 0.22; P(X <= 19.5) = 0.31; P(X <= 20.5) = 0.40; P(X <= 21.5) = 0.49; P(X <= 22.5) = 0.58; P(X <= 24) = 0.67; P(X <= 26) = 0.76; P(X <= 28.5) = 0.84; P(X <= 31.5) = 0.89; P(X <= 34) = 0.93; P(X <= 38) = 0.98. Linear interpolation gives the 10th percentile 16.300000 from call-0011, median 21.611111 from call-0012, and 90th percentile 32.125000 from call-0013."},{"kind":"math","text":"Prior/update/interval: persistence prior = recent non-ARPA level near 18.0 million; historical sample = 18.528360, 19.011027, 19.119249, 37.771612, 18.076696, 17.626084; adjustment components = +1.0 million for population and filing growth by TY2027, +2.5 million for families with very low earnings newly crossing the refundability threshold, and asymmetric upside for broader child-credit legislation bundled with the threshold. For the annual flow series I used the values themselves: sigma = 7.899 from call-0009, so 80% half-width check = 1.28*sigma = 10.111 from call-0010. The ladder-implied 80% width is 15.825 from call-0014, a 7.913 half-width, about 0.78x the 1.28*sigma check because TY2021 full refundability is more generous than the stated $1-threshold mechanism."},{"kind":"text","text":"Policy mechanism: lowering IRC §24(d)(1)(B)(i)'s earned-income threshold from the current-law threshold to no more than $1 mainly adds families with positive but very low earnings and increases marginal ACTC eligibility for some low earners. It does not by itself imply the TY2021 ARPA combination of full refundability, larger maximum credit, age-17 eligibility, and advance payment administration."},{"kind":"text","text":"Counter-considerations: upside risk is that enacted legislation paired with the $1 threshold also expands the refundable amount or child eligibility, which would land above the interval toward the TY2021 ARPA print. Downside risk is that take-up, qualifying-child counts, or very-low-earnings filing behavior remain close to current law, which would land near or below the lower interval. A materially different IRS Table 3.3 concept label or unresolved condition would be outside the interval as a scoring-state issue rather than a numeric miss."},{"kind":"forecast","point":21.611111,"ciLow":16.3,"ciHigh":32.125}]}

# Reviewer critique
{"summary":"The forecast is mostly coherent on the resolver, unit, history, point, and interval, but publication should wait for a structured official-announcement fetch event rather than a prose claim.","requiredFixes":[{"rubricItem":"resolver","severity":"blocking","summary":"The draft says thesis_announcement_fetch fetched the exact registered URL, but the submitted reasoning only records this as text; the target contract requires a structured thesis_announcement_fetch.fetch_official_announcement event for the exact officialAnnouncementUrl.","actionRequested":"Add or preserve the structured tool event from thesis_announcement_fetch.fetch_official_announcement for https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304, and keep resolutionDate as 2029-12-31."},{"rubricItem":"model_prior","severity":"warning","summary":"The draft uses a persistence prior but does not explicitly rule out a formal time-series model despite a short, policy-broken sample with TY2021 as an outlier.","actionRequested":"Add one compact sentence stating that a formal trend/ARIMA-style prior is ruled out because the six-print history is dominated by statutory regime changes, so the operative prior is non-ARPA persistence plus stated policy adjustments."},{"rubricItem":"update","severity":"warning","summary":"The +1.0 million filing/population and +2.5 million low-earnings-threshold adjustments are plausible but read as asserted inputs rather than evidence-tied updates.","actionRequested":"Clarify that these are judgmental adjustment components from the policy mechanism, or cite any public estimate used to size them."}],"optionalSuggestions":["Keep the existing byte-for-byte unit, resolver text, source URL, dataPointId, and resolve-by-bound date.","The tail scenarios are useful; consider tying the upside tail more explicitly to bundled refundable-credit expansion versus the threshold-only condition."]}

Emit the final JSON object only.
