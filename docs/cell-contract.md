# The spawned-cell contract

One JSON object per forecast, produced by a thesis.analyst run and converted
into the catalog by `scripts/spawned_cells_to_ts.py` (which validates all of
this; `site/src/__tests__/trace-depth.test.ts` re-enforces it in CI).

This contract serves the Thesis vision in
[`docs/thesis-vision.md`](thesis-vision.md): agent-only forecasts over
automatically resolvable public data, with full activity traces preserved for
later scoring and Brier training.

```json
{
  "slug": "kebab-case-unique-vs-catalog",
  "country": "US|UK|CA|AU|EA|JP",
  "type": "data|policy|conditional",
  "title": "Short display title",
  "question": "Resolution-grade: exact series, period, adjustment, first print",
  "unit": "for a registered target: the registered targetUnit, byte-for-byte; otherwise one of count|percent|usd|usd_millions|usd_billions|usd_monthly|thousands|millions|million_cubic_feet|ratio|percent_growth|gbp_billions|per_1000_live_births",
  "pointEstimate": 0,
  "ciLow": 0,
  "ciHigh": 0,
  "confidence": 0.8,
  "resolutionDate": "YYYY-MM-DD (official calendar date or registered resolve-by bound)",
  "resolutionSource": "Agency, release name",
  "resolutionSourceUrl": "https://... (the release/data page that resolves it)",
  "resolutionRule": "Exact series/table/line, first print, rounding, condition policy",
  "dataPointId": "agency.dataset.concept.period.first_print",
  "conditionalOn": "(conditionals only) checkable condition w/ provision ref",
  "historicalContext": [
    {
      "period": { "type": "month", "value": "2026-04" },
      "label": "April 2026",
      "value": 0
    }
  ],
  "drivers": ["3-5 short driver phrases"],
  "sourceContext": ["urls actually fetched this run (>=2)"],
  "runAt": "real `date -u +%Y-%m-%dT%H:%M:%SZ` at generation",
  "activityLog": [
    {
      "artifactType": "prompt|command|stdout|stderr|codex_stdout_jsonl|codex_stderr_log|codex_events_jsonl|codex_last_message|codex_trace|draft_forecast|review_prompt|pre_submit_review|review_disposition|revision_prompt|raw_response|parsed_cell|normalized_cell|run_distribution|cells_with_activity|validation_report|model_candidates|manifest",
      "path": "records/thesis-analyst/...",
      "sha256": "hex",
      "bytes": 0,
      "createdAt": "ISO timestamp"
    }
  ],
  "reasoning": [
    { "kind": "heading", "text": "…" },
    { "kind": "text", "text": "…" },
    {
      "kind": "tool",
      "tool": "fred.lookup",
      "call": "…",
      "result": "actual fetched numbers"
    },
    { "kind": "math", "text": "explicit point + CI derivation" },
    { "kind": "forecast", "point": 0, "ciLow": 0, "ciHigh": 0 }
  ]
}
```

Use `million_cubic_feet` for values reported in million cubic feet; the site
renders this canonical token as `MMcf`.

Depth bar (rejected otherwise): >=7 reasoning steps; >=3 tool steps whose
results carry numbers fetched this run; one explicit base-rate/reference-class
step; one math derivation; one disconfirming consideration ("outside the
interval if…"); final forecast step exactly matching the cell numbers;
historicalContext >=3 real points; ciLow < point < ciHigh.

New thesis.analyst generations require at least 6 distinct numeric
`historicalContext` prints whenever the official source exposes them. Each
entry carries a canonical `period` identity independent of its display label:
`month` uses `YYYY-MM`, `quarter` uses `YYYY-Q1` through `YYYY-Q4`, `year` and
`fiscal_year` use `YYYY`, and `week_ending` uses `YYYY-MM-DD`. Validation counts
unique `(type, value)` identities, so alternate labels for one period never
become additional prints. The display label must unambiguously identify that
same canonical period. For floor-enforcing cells, the whole trimmed label must
match one closed printable-ASCII form: `YYYY-MM`, `Month YYYY`, `YYYY Month`,
`YYYY-QN`, `YYYY QN`, `QN YYYY`, `YYYY`, `calendar year YYYY`, `FY2026`,
`fiscal year YYYY`, `YYYY-MM-DD`, or `week ending YYYY-MM-DD`. Extra source or
revision prose, relative labels such as `t-1`, contradictory or multi-period
labels, ranges, and non-ASCII text refuse.

If the official source exposes fewer than 6 prints, fetch every available
print. A floor exception exists only when the exact series and target period
have a reviewed authorization in the sealed checkout's
`scripts/docket_series.json`. Like every docket change, that authorization is
committed and reviewed before the run. It records the canonical inventory:

```json
{
  "extras": {
    "historyFloorAuthorization": {
      "targetPeriod": "2026-06",
      "status": "official_source_exposes_fewer_than_six_prints",
      "availablePrintCount": 5,
      "availablePeriods": [
        { "type": "month", "value": "2026-01" },
        { "type": "month", "value": "2026-02" },
        { "type": "month", "value": "2026-03" },
        { "type": "month", "value": "2026-04" },
        { "type": "month", "value": "2026-05" }
      ]
    }
  }
}
```

The runner reads that registry from the manifest's sealed `checkoutSha` and
requires the run's canonical period set to match it exactly. A copied registry
fragment, target-context field, or cell field has no authority.

The agent may also add this top-level audit commentary alongside
`historicalContext` (with the actual count and a nonempty detail):

```json
{
  "historyAvailability": {
    "status": "official_source_exposes_fewer_than_six_prints",
    "availablePrintCount": 5,
    "detail": "Series began recently; the official source exposes only these five prints."
  }
}
```

The runner checks the exact status, canonical-count agreement, and nonempty
detail when this commentary is present. It remains in the run artifacts and
is omitted from the generated catalog cell. It is model-authored commentary,
not authorization: even a syntactically valid declaration can never waive the
floor without the matching reviewed docket entry from the sealed checkout.

`resolutionDate` has two target-context branches:

- `resolutionDateBasis` absent or `release-calendar` (the default): verify the
  literal date from an official release calendar or announcement during this
  run. This is the existing rule.
- `resolutionDateBasis: resolve-by-bound`: byte-echo the registered
  `resolutionDate`, which is a Thesis lab-committed outer deadline and not a
  claimed release day. The registered announcement authenticates methodology
  identity; it does not establish the deadline or expected release window.
  The cell must repeat its exact `sourceBinding.sourceUrl` as
  `resolutionSourceUrl`. In the required attested ticket lane, the publisher
  separately verifies an exact-URL, successful structured MCP fetch event in
  replayed draft/final stdout. A reasoning token, same-host substitute, search
  result, prose citation, or `sourceContext` entry is not fetch evidence.
  Never derive a more specific day from cadence.

For fast and full conditional runs, one reasoning step beginning exactly
`Policy chain:` must decompose the touched population (with a fetched count),
propagation to the measured quantity, offsetting responses, and timing/lag.
The pre-submit reviewer checks those four components and whether the policy
effect's direction and size are consistent with its cited precedent. The
runner's literal evidence gate is specified below.

Machine-checked requirements (CI-validated literally, not approximately;
a trace missing any is rejected):

- the base-rate step must use explicit reference-class wording — literally
  say "base rate" or "reference class", or a trailing-N range/
  distribution statement;
- the falsification step must use one of the literal phrasings
  "upside risk", "downside risk", "outside the interval", or
  "would land above/below the interval";
- fast and full conditional cells must include a reasoning step whose text
  begins exactly `Policy chain:` and either cites at least one fetched
  precedent URL that also appears exactly in `sourceContext`, or contains the
  exact phrase `no fetched precedent`, states a numeric policy-term bound, and
  labels that term `low-confidence`. The runner applies this gate only to
  fast/full runs; the dispatch-only `ladder` and `ladder_v2` contracts and
  validators remain sealed;
- one math step must begin "Prior/update/interval:" and SHOW the interval
  arithmetic: compute sigma from the fetched history (successive changes
  for level/rate series; the values themselves for change/flow series),
  state it literally as "sigma = X", and derive the half-width as roughly
  1.28*sigma — stating a regime or mechanism reason in the same step if
  you widen or narrow beyond about 0.75x–1.75x of that;
- confidence is 0.8 exactly; ciLow < pointEstimate < ciHigh;
- every tool step's result string includes at least one fetched numeric
  value; resolutionDate follows the applicable calendar/default or bounded
  branch above and is never inferred from cadence; runAt is the actual UTC
  date command output from this run.

Base-rate provenance: fetch `historicalContext` from the exact official
artifact the resolution rule names — for workbook or file sources, the
per-period files behind `sourceBinding.sourceUrl`, parsed at the exact
table/row/column the rule cites — never a secondary summary, bulletin
article, or adjacent series. Anchored targets fail validation whenever the
fetched history contradicts the pinned official first-print values, so a
near-miss series is a wasted run. The repository's resolver adapters in
`scripts/resolve_pending.py` are runnable public references for exactly
this parse (e.g. `irs_soi_pub1304_fetch_year` downloads and reads the
official Table 3.3 workbook cell); with workspace access you may run them
— installing a pinned parser like `xlrd==2.0.1` first if needed — and a
base rate fetched through the resolution parser is, by construction, the
series the target resolves against.

Resolve-by-bound targets during a methodology transition: while NO
official print under the announced revised methodology exists —
including revised historical or backcast estimates, not merely the
outcome print the resolution rule names — the CURRENT official series
is the admissible base rate: fetch it from its official source, name
its vintage explicitly in the trace, and state the announced
methodology transition as the regime consideration in the sigma step.
Refusing for lack of the unpublished revised series is wrong;
fabricating or adjusting values to "pre-apply" the revision is equally
wrong. The moment any revised-methodology official print exists, those
prints are required exactly as this section demands for every other
target, and old-methodology history stops being admissible.

`activityLog` is added by `scripts/run_thesis_analyst.py`, not by the model.
It preserves the full run envelope behind the curated public trace: prompt,
command metadata, stdout/stderr, raw response, parsed/normalized cells,
model-candidate JSON, and validation report. When pre-submit review is enabled,
the draft forecast, review prompt, reviewer output, revision prompt, and final
response are also artifacts. Codex CLI runs additionally preserve the raw
stdout JSONL, raw stderr log, normalized event JSONL, last assistant message,
and trace summary. The allowed artifact types include `model_candidates` for
outputs from `scripts/run_time_series_models.py`.

Ticketed local runs add this deterministic block immediately after the target
context in every prompt mode:

<pre><code>&#35; Generation ticket
ticket: &lt;ticketId&gt;
nonce: &lt;64-character lowercase-hex nonce&gt;</code></pre>

The runner and attested-bundle verifier both render the block through
`format_generation_ticket`; its exact bytes are covered by the prompt artifact
hash. Run and batch manifests bind the ticket id and path plus the nonce's
SHA-256 digest rather than repeating the nonce. A transcript binding the nonce
cannot predate mint, so this proves that the published artifact set was
assembled after mint. It does not prove that the forecasting work occurred
after mint.

A ticket permits one publication, not one execution. Parallel clean checkouts
can execute the same ticket, select one result offline, and discard the other
runs without detection. The lane also cannot prove model authorship or trust
the operator's wall clock, and its git-status cleanliness checks do not see
gitignored local inputs. These residual risks are why the published cells carry
`local_operator_attested`. The label is disclosure, not a scoring adjustment;
these cells score identically to CI cells.

The converter stamps `predictionRun` from `agents/thesis-analyst/`:
`{kind: "recorded-agent-run", runAt, agent: "thesis.analyst", model,
agentVersion, promptHash, toolPolicyHash, sourceContext, activityLog,
provenance}` — promptHash = sha256(system.md), toolPolicyHash =
sha256(skills/\*.md sorted by filename), version from agent.yaml. The recorded
model is the actual runtime model when the command names one with `-m`,
`--model`, or `--model=...`; otherwise it falls back to the agent.yaml default.
Bump the version when any agent file changes.

New ordinary workflow output has `predictionRun.provenance = "ci"`. A run
whose manifest carries a verified generation ticket instead has
`provenance = "local_operator_attested"` and
`generationTicket: {ticketId, ticketPath}`. The label is granted only by the
trusted publish workflow after attested-bundle verification; a cell cannot
claim it itself. It identifies this internally consistent, single-publication
path rather than proving the underlying execution's authorship or uniqueness.

New runs also stamp `predictionRun.custodyRootSha256`. The converter verifies
the sibling `custody_root.json` before carrying that root into the catalog,
Thesis Log, and Brier reward provenance.

`sourceContext`, reasoning, drivers, tool calls, and activity summaries must
not cite or rely on private meeting notes, call transcripts, email/chat
content, pasted attachments, personal notes, or other non-public local files.
Local repo context is admissible only when it is a public repository artifact,
a published Thesis record, or a generated file derived from public official
sources.

If a run uses pre-submit review, `predictionRun.preSubmitReview` carries compact
public metadata: review status, reviewer attribution, artifact paths, findings,
and the forecaster's public disposition. The full review text stays in the
artifact files so the review is auditable without replacing the scored final
forecast.
