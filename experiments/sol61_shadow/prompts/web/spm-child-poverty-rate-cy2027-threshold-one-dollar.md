# Run instructions (read before the task prompt)

You are producing ONE forecast for an unpublished research comparison inside
the Thesis forecasting lab. The task prompt between the markers below is the
exact production prompt the Thesis CI analyst (thesis.analyst, prompt mode
fast) receives for this registered target. Follow it exactly, with these
overrides:

1. No repository. This workspace intentionally holds no Thesis checkout.
   Skip the local-file suggestions in the prompt's "Context access" section.
   Do not read, list or search any file outside this workspace directory.
   Shell use is limited to `date -u +%Y-%m-%dT%H:%M:%SZ`, short arithmetic
   (python3 -c, awk, bc).
2. Independence. Do not visit, search for or use thesisinstitute.org,
   app.thesisinstitute.org, github.com/ThesisInstitute, or any Thesis or
   Brier forecast, trace or record. This run is compared against Thesis's own
   published forecast for the same target, so it must not see it.
3. Evidence. Take every number from official public sources fetched in this
   run with your web search tool. Never present remembered values as fetched evidence.
   If you cannot fetch the history, say so in a text step instead of
   inventing numbers.
4. Do not create or modify files.
5. Output. Your final message must be exactly the one JSON object the prompt
   specifies: no Markdown, no code fence, no text before or after it.

----- BEGIN PRODUCTION PROMPT -----
# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: census.spm.child_poverty_rate
- period: 2027
- conditionalOn: For the CY2027 Census Supplemental Poverty Measure child-poverty outcome, legislation enacted by 2027-12-31 makes the IRC §24(d)(1)(B)(i) earned-income threshold no more than $1 for tax year 2027.
  Your cell's `conditionalOn` field must repeat this text byte-for-byte; the registry gates on the exact string.

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "spm-child-poverty-rate-cy2027-threshold-one-dollar"
- country: "US"
- targetUnit: "percent"
- dataPointId: "census.spm.child_poverty_rate.2027.first_print.threshold_one_dollar"
- resolutionDate: "2028-12-31"
- resolutionDateBasis: "resolve-by-bound"
- expectedReleaseWindow: {"end": "2028-12-31", "start": "2028-08-01"}
- resolutionSource: "U.S. Census Bureau revised-SPM methodology announcement (identity) and Poverty in the United States: 2027, Supplemental Poverty Measure Table B-2 (resolving artifact)"
- resolutionSourceUrl: "https://www.census.gov/newsroom/press-releases/2026/statement-on-supplemental-poverty-measure.html"
- resolutionRule: "Resolve to the first Census annual income-and-poverty release artifact for CY2027 using the revised SPM methodology whose identity is authenticated by the registered 2026-07-17 Census announcement: Poverty in the United States: 2027, Supplemental Poverty Measure Table B-2, ALL RACES 2027 row, Under 18 years / Below Poverty / Percent column. The 2028-08-01 through 2028-12-31 expected release window and 2028-12-31 resolve-by deadline are Thesis lab commitments; the announcement does not establish either timing value. Record the published percent without scaling or rounding and ignore later revisions."
- sourceBinding: {"adapter": "census-spm-annual-report", "allowedHosts": ["www.census.gov", "www2.census.gov"], "expectedReleaseWindow": {"end": "2028-12-31", "start": "2028-08-01"}, "field": "under_18_percent_in_poverty", "releasePolicy": "first_print", "sourceSeriesId": "census.spm.child_poverty_rate", "sourceUrl": "https://www.census.gov/newsroom/press-releases/2026/statement-on-supplemental-poverty-measure.html", "table": "Poverty in the United States annual income-and-poverty release, revised-methodology Supplemental Poverty Measure Table B-2, ALL RACES year row, Under 18 years / Below Poverty / Percent column", "transform": {"factor": 1, "operation": "identity"}}
- targetRegistrationPath: "records/targets/2026-08-05-1da9aeb900cf33a57a256b6c550ab8da7f7e286ae81153fc60b9ec57aefb1b27.json"
- targetContentHash: "1da9aeb900cf33a57a256b6c550ab8da7f7e286ae81153fc60b9ec57aefb1b27"
- registrationCommit: "8b58fab29b2593537430443eb9dc9ca69dff7e2e"
- registeredAtUtc: "2026-08-05T23:10:13Z"
- conditional: "For the CY2027 Census Supplemental Poverty Measure child-poverty outcome, legislation enacted by 2027-12-31 makes the IRC \u00a724(d)(1)(B)(i) earned-income threshold no more than $1 for tax year 2027."

# Resolve-by-bound target contract (machine checked)
- registeredResolveByBound: "2028-12-31"
- officialAnnouncementUrl: "https://www.census.gov/newsroom/press-releases/2026/statement-on-supplemental-poverty-measure.html"
The bound and expected release window are Thesis lab commitments, not timing claims made by the announcement. The announcement authenticates methodology identity only; it does not establish the bound or expected release window. This is an outer bound, not a scheduled release day. resolutionDate must byte-echo the registered resolve-by bound; never infer a more specific day from cadence.
resolutionSourceUrl must byte-echo officialAnnouncementUrl. Call `thesis_announcement_fetch.fetch_official_announcement` with that exact URL. The publisher authenticates the structured draft/final tool event; a reasoning-token claim, search result, same-host page, or prose citation cannot substitute for it.
Base rate during a methodology transition: while NO official print under the announced revised methodology exists — including revised historical or backcast estimates — the CURRENT official series is the admissible base rate: fetch it from its official source, name its vintage explicitly, and state the announced transition as the regime consideration in the sigma step. Do not refuse for lack of the unpublished revised series, and do not fabricate or pre-apply revision adjustments. The moment any revised-methodology official print exists, revised prints are required and old-methodology history stops being admissible.

# Source hints
- Use Census income, poverty, SPM, and health-insurance release pages, CPS ASEC historical tables, and the Census release calendar.
- For official-poverty targets, distinguish the official poverty measure from SPM and cite the exact Census table or report.
- For SPM targets, name the population group, calendar year, and whether taxes, credits, transfers, medical expenses, or housing adjustments matter for the forecast.
- For ACS table targets, fetch each history year's values from the keyless JSON endpoint https://data.census.gov/api/access/data/table?id=<PRODUCT><YEAR>.<TABLE>&g=010XX00US (for example ACSDT1Y2024.B28005) and read the cited variable columns from the returned JSON.
- api.census.gov requires an API key (keyless requests redirect to missing_key.html); never rely on it in keyless runs, and never present remembered values as fetched ones.
- ACS vintage discipline: never mix 5-year estimates into a 1-year series — the 5-year file is a five-year average, so its level trails the 1-year series; the product id in the fetch URL (ACSDT1Y vs ACSDT5Y) is the vintage authority.

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
----- END PRODUCTION PROMPT -----
