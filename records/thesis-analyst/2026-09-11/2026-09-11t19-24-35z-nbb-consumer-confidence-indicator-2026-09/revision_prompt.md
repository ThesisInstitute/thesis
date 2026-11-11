# Thesis analyst fast public-release run

Return exactly one JSON object and no Markdown. Do not wrap it in a code fence.

# Context access
You may inspect the local repository/workspace when useful. This is optional, not required. Useful read-only context can include docs/cell-contract.md, site/src/data/forecast-cells.ts, site/src/data/ledger-targets.ts, prediction packs, generated comparison data, records/thesis-analyst run manifests, full activity artifacts, prior reasoning traces, and model-candidate files. You may run read-only commands such as rg, sed, cat, find, git log/status/show, `date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. Local context is admissible only when it is a public repository artifact, a published Thesis record, or a generated file derived from public official sources. Do not use private meeting notes, call transcripts, email/chat content, pasted attachments, personal notes, or other non-public local files as forecast evidence, source context, or tool-call provenance. If such material is present on disk, ignore it; if a prior run cites it, treat that run as tainted for evidence purposes. Do not modify files. Treat prior forecasts as historical forecasts or strategy context, not as ground-truth outcomes. If prior runs affect your forecast, briefly state the update from the previous run; if they do not matter, ignore them. Existing catalog pointEstimate, ciLow, and ciHigh values are not official evidence for a new forecast; use local catalog context to verify target identity/resolver fields only unless explicitly auditing an existing forecast.

Goal: produce one auditable forecast for an automatically resolvable government/public statistical release. Resolve on the first official print unless the series itself is a policy decision level after an announcement.

# Question spec
- series: nbb.consumer_confidence.indicator
- period: 2026-09
- conditionalOn: null

# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "belgium-consumer-confidence-september-2026"
- country: "BE"
- targetUnit: "index_points"
- dataPointId: "nbb.consumer_confidence.indicator.2026-09.first_print"
- expectedReleaseWindow: {"end": "2026-09-25", "start": "2026-09-17"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.nbb.be"], "expectedReleaseWindow": {"end": "2026-09-25", "start": "2026-09-17"}, "field": "nbb.consumer_confidence.indicator", "releasePolicy": "first_print", "sourceSeriesId": "nbb.consumer_confidence.indicator", "sourceUrl": "https://www.nbb.be/en/statistics/business-surveys/consumer-survey", "table": "National Bank of Belgium consumer survey release", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-d72d5551351863417bcb647e8da9f7cf61102d3bdb991fe8e9bbe6bd96367113.json"
- targetContentHash: "d72d5551351863417bcb647e8da9f7cf61102d3bdb991fe8e9bbe6bd96367113"
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
{"slug":"belgium-consumer-confidence-september-2026","country":"BE","type":"data","title":"Belgium consumer confidence, September 2026","question":"National Bank of Belgium consumer confidence indicator for September 2026, seasonally adjusted, first official print","unit":"index_points","pointEstimate":-8.0,"ciLow":-12.5,"ciHigh":-3.5,"confidence":0.8,"resolutionDate":"2026-09-25","resolutionSource":"National Bank of Belgium consumer survey release","resolutionSourceUrl":"https://www.nbb.be/en/statistics/topics/belgian-economy/firms-and-short-term-business-statitistics/consumer-confidence","resolutionRule":"Resolve to the first National Bank of Belgium published consumer confidence indicator for 2026-09, seasonally adjusted, reported in signed index points using the agency's published table precision. Use the first official NBB print only; ignore later NBB.Stat revisions, later corrections, FRED, and third-party mirrors. The official NBB latest-figures calendar fetched this run lists the 2026M9 Consumer confidence indicator publication and the 2026-09 press release for 22 Sep 2026; the registered Thesis target contract sets resolutionDate to 2026-09-25, so this cell preserves the registered resolutionDate and records that discrepancy.","dataPointId":"nbb.consumer_confidence.indicator.2026-09.first_print","historicalContext":[{"period":{"type":"month","value":"2025-09"},"label":"September 2025","value":-1},{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":0},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":2},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":-1},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":4},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":1},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":-6},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":-9},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":-10},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":-7},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":-5},{"period":{"type":"month","value":"2026-08"},"label":"August 2026","value":-7}],"drivers":["August first print fell to -7 after July -5","August deterioration came from macro and unemployment expectations","recent six-month level remains materially negative","the September survey is collected during the first half of the month","one-month NBB consumer survey moves have recently had sigma near 3.5 index points"],"sourceContext":["https://www.nbb.be/en/statistics/topics/belgian-economy/firms-and-short-term-business-statitistics/consumer-confidence","https://www.nbb.be/en/statistical-updates?calendar_timestamp=660006000&current=1456786800&date_format=custom&date_pattern=F&display_reset=0&next=1459461600&page=0&pager_type=calendar_month&previous=660006000&scope=2&theme%5B5067%5D=5067&use_previous_next=1","https://www.nbb.be/en/statistics/methodology/topics/firms-and-short-term-business-statistics/consumer-confidence","https://dataexplorer.nbb.be/vis?av=true&df%5Bag%5D=BE2&df%5Bds%5D=disseminate&df%5Bid%5D=DF_CONSN&df%5Bvs%5D=1.0&dq=M..BE&lc=nl&lo=13&lom=LASTNPERIODS&pg=0&to%5BTIME_PERIOD%5D=false","https://tradingeconomics.com/belgium/consumer-confidence"],"runAt":"2026-09-11T19:24:49Z","reasoning":[{"kind":"heading","text":"Belgium September 2026 NBB Consumer Confidence Forecast"},{"kind":"text","text":"Framing and exact resolver: the target is the National Bank of Belgium consumer confidence indicator for September 2026, seasonally adjusted, first official print, in signed index_points. The target contract binds slug belgium-consumer-confidence-september-2026, country BE, dataPointId nbb.consumer_confidence.indicator.2026-09.first_print, and registered resolutionDate 2026-09-25."},{"kind":"tool","tool":"official.lookup","call":"Checked the official NBB latest-figures calendar for the September 2026 consumer confidence release.","result":"Fetched official schedule numbers: Consumer confidence period 2026M9, Consumer confidence indicator Publication, release date 22 Sep 2026; the same official calendar also lists period 2026-09, Press release - Consumer confidence indicator, release date 22 Sep 2026."},{"kind":"tool","tool":"official.lookup","call":"Fetched the official NBB July 2026 consumer confidence indicator release table for same-variant history.","result":"Fetched NBB table values for the consumer confidence indicator: 2025 Sep -1, Oct 0, Nov 2, Dec -1, 2026 Jan 4, Feb 1, Mar -6, Apr -9, May -10, Jun -7, Jul -5 index points."},{"kind":"tool","tool":"official.lookup","call":"Fetched the current official NBB consumer-confidence topic page and the NBB.Stat/DataExplorer series context for the latest period and exact series identity.","result":"Fetched NBB same-series context: the latest official topic page shows Firms and short-term business statistics period 2026M8, Consumer confidence indicator, publication 21 Aug 2026 11:00; the NBB.Stat DataExplorer query identifies dataflow DF_CONSN with query M..BE and last 13 periods for Belgium."},{"kind":"tool","tool":"history.mirror","call":"Checked a public mirror of the NBB-sourced August release because the official indexed snippet exposed the August period and release date but not the August table value.","result":"Fetched NBB-sourced August history values from the mirror: consumer confidence decreased to -7 in August 2026 from -5 in July 2026; component values were economic situation -32 from -27, unemployment expectations 16 from 14, household financial situation -2 unchanged, and saving intentions 22 from 23."},{"kind":"tool","tool":"official.lookup","call":"Fetched the official NBB methodology page for variant, construction, and survey timing.","result":"Fetched methodology numbers: the National Bank's consumer confidence indicator is the arithmetic mean of 4 seasonally adjusted key question balances; the survey covers approximately 1850 households; interviews are conducted between the 1st and 15th days of each month; balances are bounded from -100 to +100."},{"kind":"text","text":"Base rate/reference class: the reference class is recent same-variant monthly NBB consumer confidence first prints. Using September 2025 through August 2026 values [-1, 0, 2, -1, 4, 1, -6, -9, -10, -7, -5, -7], the 12-print mean is -3.25, the latest six-print mean is -7.33, the latest three-print mean is -6.33, and persistence from August is -7.0. Because the recent regime since March has stayed negative, the base rate is closer to last-six persistence than to the full 12-print mean."},{"kind":"text","text":"Level, momentum, one-off, and policy mechanisms: level is negative but not at the May trough; momentum worsened in August after the July improvement; the main one-off September risk is another swing in unemployment and macro expectations during interviews from the 1st to 15th; the policy/income mechanism is mixed, with lower past confidence partly offset by household saving intentions that remained positive."},{"kind":"math","text":"Prior/update/interval: persistence prior = -7.0 from the August 2026 first print; historical sample = same-variant monthly values from 2025-09 through 2026-08; adjustment components = -0.6 for August's deterioration in economic expectations, -0.4 for unemployment expectations rising to 16, and +0.0 for household financial situation holding at -2, giving point = -8.0. Interval method uses realized dispersion of successive level changes [1, 2, -3, 5, -3, -7, -3, -1, 3, 2, -2]; sigma = 3.47, so 1.28*sigma = 4.45. I use a 4.5-point half-width, giving -8.0 - 4.5 = -12.5 and -8.0 + 4.5 = -3.5."},{"kind":"text","text":"Counter-consideration and falsification: upside risk is that August's decline reverses quickly because saving intentions stay high and financial-situation expectations remain stable, which would land above the interval if September prints -3.4 or higher. Downside risk is another jump in unemployment fears or macro pessimism during the September survey window, which would land below the interval if the first print is -12.6 or lower. Outside the interval would indicate a larger one-month sentiment shock than the recent NBB reference class implies."},{"kind":"forecast","point":-8.0,"ciLow":-12.5,"ciHigh":-3.5}]}

# Reviewer critique
{
  "summary": "Draft is mostly coherent, but the resolver URL should be tied to the canonical ledger source rather than the alternate topic URL.",
  "requiredFixes": [
    {
      "rubricItem": "resolver",
      "severity": "blocking",
      "summary": "resolutionSourceUrl does not match the ledger sourceBinding sourceUrl, and the draft uses an alternate NBB topic URL with a misspelled path segment.",
      "actionRequested": "Set resolutionSourceUrl to https://www.nbb.be/en/statistics/business-surveys/consumer-survey, or explicitly justify why the registered canonical source URL is wrong while keeping the same target."
    }
  ],
  "optionalSuggestions": [
    "Prefer citing the official NBB/DataExplorer source for the August value if available, with Trading Economics only as a mirror fallback.",
    "Keep the 22 Sep 2026 official calendar discrepancy in reasoning, while preserving the registered 2026-09-25 resolutionDate as drafted."
  ]
}

Emit the final JSON object only.
