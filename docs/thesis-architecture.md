# Thesis Architecture Blueprint

This is the clean architecture target for Thesis. It describes the system we
would build from scratch, then migrate toward. Current repository
reconciliation belongs in [`docs/thesis-migration.md`](thesis-migration.md).

The core principle is simple: every prediction is an append-only agent run
against a registered ledger target. The ledger defines what can be forecast and
how it resolves; agents, packs, judges, and UI are downstream of that contract.

Related contracts:

- [`docs/thesis-vision.md`](thesis-vision.md) defines the strategic mission.
- [`docs/cell-contract.md`](cell-contract.md) defines the current forecast-cell
  JSON surface.
- [`docs/brier-lab.md`](brier-lab.md) defines the reward and judge exports.
- [`docs/thesis-migration.md`](thesis-migration.md) maps the current codebase
  and committed schema into this target architecture.

## Goals

Thesis should become an open-source, agent-only forecasting lab for official
public series that can resolve automatically. It should support many small,
checkable forecasts, publish the full activity trace for every run, resolve
from official sources, and use proper scores to improve Brier.

The architecture should optimize for:

- automatic resolution over subjective judging;
- immutable records over hand-edited catalog state;
- repeated target families over one-off questions;
- explicit baselines over unaudited agent intuition;
- public traces over hidden reasoning summaries;
- proper-score rewards over preference ratings.

## Non-Negotiables

1. **Ledger first.** No forecast run exists without a registered ledger target.
   The target owns `targetId`, `dataPointId`, unit, resolver, resolution
   policy, resolution date basis, source, and scoring unit.
2. **Append-only runs.** Forecasts, reviews, judges, resolutions, and scores are
   immutable events. New information creates a new run; it does not overwrite
   an old one.
3. **Agents only.** Humans improve schemas, adapters, prompts, code, and review
   policy. They do not enter the forecasts that become scored Thesis runs.
4. **Open trace.** The scientific record is prompt, command, source activity,
   raw output, normalized output, validation, review, resolution, and score.
5. **Proper reward.** Brier is trained and selected on resolved forecast
   accuracy. LLM judges are process diagnostics, never reward.

## System Boundary

Thesis has six primary layers:

1. target ledger;
2. source adapters and observation store;
3. baseline and model-candidate generator;
4. forecast strategy runners;
5. review, validation, resolution, and scoring;
6. UI and public exports.

The critical boundary is between target definition and forecasting. The ledger
is not a hint to the model. It is the contract the model must honor.

## Target Ledger

The ledger is the source of truth for automatically resolvable targets. It is
normalized and versioned, not inferred from static forecast cards.

Identifier model:

- `targetId` is the stable Thesis target identity used in URLs, runs, scores,
  and exports.
- `targetVersionId` identifies the exact version of the target contract a run
  used.
- `dataPointId` is the stable natural key for the official fact being resolved,
  such as a source-family, period, geography, and measure tuple.
- `observationId` identifies an observed official value for a `dataPointId`.
- `vintageId` identifies a specific publication vintage of an observation.

Each target version should include:

- `targetId`, `targetVersionId`, and `dataPointId`;
- country, agency, source family, and source URL;
- unit, scaling, and any scoring transform;
- period label and target period;
- `resolverKind`, such as `public_release`, `policy_state`,
  `conditional_gate`, or `formula_publication`;
- `resolutionPolicy`, such as `first_print`, `fixed_vintage`, or `final`;
- resolution date basis: scheduled release, official placeholder, policy
  deadline, expected first-post window, or unresolved until official post;
- exact resolution rule, including table, row, field, vintage, rounding, and
  conditional policy;
- allowed source adapters and expected source schema;
- source-series bindings for history, resolver evidence, and formula inputs;
- target-family tags for scheduling, packs, and evaluation slices.

The ledger should reject targets that cannot be resolved mechanically. A target
with an uncertain release date can still exist, but the uncertainty must be
typed. The agent should not silently replace it with a cadence guess.

## Observation Adapters

Source adapters are the main rebuild priority. Agents should consume typed
evidence before they browse or parse pages themselves.

An adapter should return observations with:

- source series identifier;
- period and publication timestamp;
- value, unit, and scaling;
- first-print or revision vintage;
- source URL and retrieval timestamp;
- numerator, denominator, and formula components when relevant;
- missing-period rows with explicit missing reasons;
- source-role labels such as resolver evidence, history, timing, formula input,
  or target registration only.

Initial adapters should cover recurring source families:

- BLS CES, CPS, CPI, JOLTS, OEWS, and Employment Projections;
- Census ASEC, SPM, income, poverty, health insurance, and PER releases;
- CMS Medicaid and CHIP enrollment plus Medicaid PI eligibility processing;
- USDA FNS SNAP, WIC, and QC payment-error releases;
- Treasury MTS and IRS filing-season statistics;
- ONS labor-market time series;
- statutory formula inputs such as CPI-U and C-CPI-U windows.

Adapters should be testable against historical first prints. If an adapter
cannot distinguish first print from later revisions, it should not feed a
first-print target without a warning.

This document uses **source adapter** to mean an official-data retrieval and
normalization layer. That is separate from model adapters such as statsmodels
or time-series wrappers, which forecast from already-normalized history.

## Baselines And Priors

Every numeric forecast should start with benchmark candidates before the agent
does inside-view reasoning.

Default candidates:

- last-print persistence;
- rolling mean or median;
- damped local trend;
- simple seasonal or same-month persistence when enough history exists;
- panel shrinkage for state, occupation, or category panels;
- official projection when the target is comparable to an agency forecast;
- formula nowcast for indexed statutory parameters.

Each candidate should emit:

- point estimate;
- p10, p50, p90;
- 80% and 90% intervals;
- interval method;
- training cutoff;
- calibration sample size;
- walk-forward score when possible;
- assumptions and failure modes.

The agent may override the best candidate, but the trace must say why and show
the signed update from the prior.

## Forecast Strategies

Thesis should model strategies explicitly, not just agents.

A strategy is a reproducible forecasting procedure:

- no-pack LLM;
- pack-informed LLM;
- persistence baseline;
- time-series baseline;
- official-projection anchor;
- formula-nowcast;
- reviewer-assisted LLM;
- meta-aggregator.

The same model can run many strategies. The same strategy can update over
time. The UI should default to the latest run per strategy while preserving
every historical run.

Every forecast run should record:

- `targetId` and `targetVersionId`;
- `strategyId` and `strategyVersionId`;
- model and runtime;
- prompt hash and tool-policy hash;
- packs used and pack versions;
- model candidates available to the agent;
- full activity artifacts;
- output distribution;
- validation result;
- reviewer artifacts when review is enabled.

## Packs

Packs should be typed forecasting modules, not generic advice files.

A pack should define:

- target families it applies to;
- required evidence fields;
- source adapter dependencies;
- prior construction;
- allowed updates;
- interval method;
- validation checks;
- examples and counterexamples;
- expected failure modes;
- ablation plan.

Pack pages should show what the pack changes through examples, target coverage,
and measured performance. They should not repeat a generic definition of packs
on every page.

Portable lessons from successful packs should be promoted into the default
Brier or thesis.analyst policy only after held-out proper-score evidence and a
leakage audit.

## Review And Judges

Pre-submit review is a workflow variant. It should be part of the public trace:
draft, review prompt, reviewer output, revision prompt, final answer, and
review disposition.

Reviewers should check:

- resolver and ledger alignment;
- base-rate and model-prior use;
- evidence for movement from the prior;
- interval calibration;
- tail scenarios;
- source and vintage correctness;
- leakage or catalog-copying risk.

LLM judges are separate from pre-submit reviewers. Judges should summarize
process weaknesses across many runs and recommend improvements to prompts,
validators, packs, adapters, scheduling, or UI. They are not reward signals.
Before judge-derived changes become policy, they should be checked against
held-out proper scores.

## Meta-Aggregation

The canonical displayed forecast can be a meta-aggregator run. It should see:

- all strategy runs for the target;
- prior runs of the same strategy;
- model candidates;
- source adapter observations;
- pack outputs;
- pre-submit reviews;
- relevant score history from resolved analogous targets.

The meta-aggregator should output a new forecast distribution and cite the
component runs it used. It should not erase component forecasts. When the same
strategy has multiple updates, the default input should be the latest run for
that strategy unless the meta-aggregator explicitly uses an older run for
comparison.

## Resolution And Scoring

Resolution should be automated from the same adapter system when possible.

A resolution event should record:

- `targetId`, `targetVersionId`, `dataPointId`, `observationId`, and
  `vintageId`;
- official observed value;
- resolution timestamp;
- source URL and retrieval artifact;
- policy-specific provenance, such as first-print vintage proof,
  fixed-vintage timestamp, final-release evidence, or policy-state citation;
- any unit conversion;
- resolver validation;
- scoreable status or failure reason.

Scores should be proper and stored per run:

- CRPS or normalized CRPS for numeric distributions;
- Brier score for binary or categorical targets;
- absolute error and interval coverage as diagnostics;
- calibration slices by agency, target family, horizon, strategy, model, and
  pack.

Unresolved runs carry no reward. The training split should be based on
resolution date and data availability, not run creation order.

Name collision note: **Brier** is both the forecast-accuracy agent/project name
and a proper score for binary events. Numeric public-series targets should use
CRPS-like scores; binary targets can use Brier score.

## Storage Model

Use normalized append-only tables for queryable state and an append-only
artifact store for raw evidence. Static TypeScript exports can remain as a site
delivery format, but they should be generated views, not the system of record.

Core tables:

- `targets`: one stable forecastable target. Primary key `targetId`; unique
  `slug`; stable `dataPointId`; country, agency, source family, tags, and
  creation metadata.
- `target_versions`: one immutable contract version for a target. Primary key
  `targetVersionId`; foreign key `targetId`; version label; question text;
  period; unit; scaling; `resolverKind`; `resolutionPolicy`;
  `resolutionDateBasis`; resolution rule; source URL; scoring transform;
  publication timestamp.
- `source_series`: one official source series or table slice that can provide
  history, resolver evidence, formula inputs, or target registration metadata.
  Primary key `sourceSeriesId`; adapter ID; agency series ID; source URL; unit;
  update cadence; default vintage policy.
- `observations`: one normalized observed value for a source series and period.
  Primary key `observationId`; foreign key `sourceSeriesId`; period; value;
  unit; numerator; denominator; source URL; retrieval metadata. Resolver
  observations, official source-adapter history, and generated historical
  context imports are all observations; only explicit resolution events make an
  observation scoreable for a target. Generated historical context rows may omit
  `dataPointId` rather than claiming the future target's natural key.
- `observation_vintages`: one published vintage of an observation. Primary key
  `vintageId`; foreign key `observationId`; vintage kind; publication time;
  retrieval time; source snapshot artifact; normalized payload hash.
- `target_observation_bindings`: joins target versions to the source series or
  observations they use. Primary key `bindingId`; foreign key
  `targetVersionId`; optional `sourceSeriesId`; optional `observationId`;
  role such as `history`, `resolver`, `formula_input`, `timing`, or
  `conditioning`; transform expression or adapter method.
- `baseline_candidates`: generated model-prior candidates for a target version.
  Primary key `candidateId`; foreign key `targetVersionId`; optional
  `sourceSeriesId`; model adapter; training cutoff; point estimate; intervals;
  walk-forward score; assumptions; artifact reference; provenance metadata.
  Every row must carry either an artifact reference or source-series
  provenance.
- `forecast_strategies`: stable strategy identities such as no-pack LLM,
  pack-informed LLM, time-series baseline, official-projection anchor, and
  meta-aggregator. Primary key `strategyId`.
- `strategy_versions`: immutable versions of strategy procedure. Primary key
  `strategyVersionId`; foreign key `strategyId`; prompt policy; tool policy;
  required inputs; model family constraints; created timestamp.
- `packs`: stable pack identities. Primary key `packId`; target-family tags and
  owner metadata.
- `pack_versions`: immutable pack content. Primary key `packVersionId`;
  foreign key `packId`; evidence requirements; validator rules; prompt content
  hash; examples; ablation plan.
- `forecast_runs`: one agent or deterministic run against one target version
  and one strategy version. Primary key `runId`; foreign keys
  `targetVersionId` and `strategyVersionId`; agent ID; model; runtime; prompt
  hash; tool-policy hash; input-bundle hash; status; idempotency key; run time.
- `run_artifact_refs`: join table from forecast runs to raw activity artifacts.
  Primary key `runArtifactRefId`; foreign keys `runId` and `artifactRefId`;
  artifact role; sequence index.
- `run_pack_versions`: join table from forecast runs to pack versions. Primary
  key `runPackVersionId`; foreign keys `runId` and `packVersionId`; role such
  as required, optional, ablation, or comparison.
- `forecast_distributions`: the scored output distribution. Composite primary
  key `runId, pointIndex`; exactly 201 CDF points unless a future schema
  deliberately replaces that contract; value; probability; unit; interval mass;
  validation status.
- `reasoning_events`: public reasoning and activity timeline. Primary key
  `reasoningEventId`; foreign key `runId`; sequence; event kind; public text;
  artifact reference; redaction status.
- `tool_calls`: structured tool activity. Primary key `toolCallId`; foreign key
  `runId`; sequence; tool name; request hash; response hash; source role;
  status; timing; artifact references.
- `review_runs`: pre-submit review workflow records. Primary key
  `reviewRunId`; foreign key `runId`; reviewer agent; draft artifact; findings;
  revision artifact; disposition.
- `judge_runs`: batch or run-level judge diagnostics. Primary key `judgeRunId`;
  optional foreign key `runId`; optional batch ID; optional structured pairwise
  subject fields `leftRunId` and `rightRunId`; judge model; prompt version;
  findings; recommendations; reward eligibility fixed to false.
- `resolution_events`: official resolution records. Primary key
  `resolutionEventId`; foreign key `targetVersionId`; foreign keys
  `observationId` and `vintageId`; resolved value; source URL; resolver proof;
  scoreable status; event timestamp.
- `scores`: proper-score rows. Primary key `scoreId`; foreign keys `runId` and
  `resolutionEventId`; scoring rule; CRPS or Brier score; normalized score;
  absolute error; PIT; interval coverage; created timestamp.
- `quality_gate_results`: deterministic validation results. Primary key
  `qualityGateResultId`; optional `runId`, `targetVersionId`, `packVersionId`,
  or `judgeRunId`; gate ID; pass/fail status; findings; artifact reference.
- `audit_events`: hash-chained append-only audit log for every mutation and
  derived export. A locked singleton head allocates a monotonically increasing
  sequence before each insert, so bulk rows cannot fork the chain when their
  transaction-stable timestamps match. Primary key `auditEventId`; chain
  sequence; subject type; subject ID; event kind; actor; parent hash; payload
  hash; artifact reference; timestamp.
- `artifact_refs`: content-addressed references to prompts, command logs, model
  event streams, source snapshots, normalized JSON, validation reports, review
  outputs, judge outputs, and resolution proofs. Primary key `artifactRefId`;
  content hash; media type; storage URI; public visibility.

### Canonical hashing and content identity

Build-time projections serialize hash payloads as canonical JSON: object keys
are sorted lexicographically by UTF-16 code units, arrays retain their order,
numbers use JSON's stable ECMAScript representation, and non-finite numbers are
rejected. SHA-256 is the only projection hash. Payload-hash columns retain the
full 64-character lowercase digest; content-derived public IDs use at least the
first 16 hexadecimal characters while preserving their existing namespace
shape.

Run IDs commit to the forecast point, interval, and distribution. Resolution
payload hashes commit to the observed value and unit. Score IDs commit to the
forecast payload, outcome payload, and versioned scoring rule. A repeated ID is
accepted only when its payload digest is identical; a truncated-ID collision
between different digests is a build failure.

Python integrity tools use `scripts/canonical_json.py`, which mirrors the
TypeScript serializer. In particular, keys are sorted by UTF-16 code units,
not Python's Unicode-code-point order. This distinction matters for
astral-plane keys. Custody records retain both the raw-byte SHA-256 (proof of
the exact stored file) and, for JSON files, the canonical-JSON SHA-256
(cross-language content identity).

### Verifiable projection replica

`/targets.json` is the root manifest for the target-architecture projection.
It commits the builder version, `VERCEL_GIT_COMMIT_SHA`, and every per-table
manifest. Each table manifest commits the canonical-JSON SHA-256 of every row
chunk. Every chunk names the same projection root, preventing a deployment
change during download from producing a mixed-generation input. To avoid a
circular commitment, the chunk digest covers the complete canonical chunk
except its `projectionRootSha256` reference; the manifest declares this hash
semantic explicitly.

The Supabase copy is a replica, not a second source of truth. The ingest first
downloads and verifies the root and every chunk, then loads a fresh staging
schema in one database transaction. It compares canonical per-row digest
multisets and each typed database value with the downloaded logical rows before
atomically renaming the staged schema to `thesis_projection_active`. The
active tables retain the committed logical payload, digest, and projected key
set in `_projection_*` verification columns alongside the typed replica row.
The `thesis_projection_active_generation` singleton exposes the root currently
served by that schema, while `thesis_projection_generations` retains an
append-only history of root hash, source commit, builder version, row counts,
and ingest time.

A third party can therefore corroborate the site's state independently:

1. Fetch `/targets.json` and all referenced chunks.
2. Recompute every canonical chunk hash, table-manifest hash, and the root.
3. Read the replica's active-generation singleton and require the same root.
4. Run `scripts/ingest_target_architecture.py --verify` with read access to
   recompute the live replica's row digests and typed values against those
   downloaded chunks.

Matching roots prove that the replica claims the exact site generation;
`--verify` additionally detects row insertion, deletion, or mutation behind
that pointer. The existing forecast-snapshot recorder already archives
`/targets.json`, so its `targets` surface now preserves this root manifest
without adding another URL to the fetch list.

### Forecast-record chain and independent witness

`records/CHAIN_GENESIS.json` is the explicit integrity cutover. It names the
first `digest-<runId>.json` snapshot and the canonical
`records/GENESIS_RECORDS.json` enumeration. That enumeration fixes every file
in the pre-chain Git tree by path, SHA-256, and size. A later chained bootstrap
digest commits the enumeration, `CHAIN_GENESIS.json`, and the TSA trust-anchor
bundle. The verifier independently code-pins the audited enumeration hash,
cutoff commit, immutable trust-bundle hash, root SPKI, and signer SPKI. It also
compares the enumeration to the cutoff Git tree when `.git` is available. No
unlisted file is accepted as implicitly "pre-chain," and a second genesis
cutover is invalid.
`records/CHAIN_HEAD.json` commits the current tail so simply deleting the
newest snapshot also fails local verification.

Every recorder invocation creates a never-overwritten
`records/<YYYY-MM-DD>/digest-<runId>.json`. Its `chain.prevDigestPath` and
`chain.prevDigestSha256` name the immediately preceding invocation, including
across date boundaries. The compressed response bodies, build canary, current
repository commit, and ledger-branch API response/commit are retained with the
snapshot. `scripts/verify_record_chain.py` rejects missing blocks, missing
predecessors, forks, orphans, hash changes, unenumerated legacy digests, and
head drift.

After the digest is final, `scripts/witness_snapshot.py` asks every TSA in the
newest active trust bundle for an RFC 3161 token over the same digest bytes.
New tokens use anchor-qualified paths such as
`digest-<runId>.freetsa-root-2016.tsr` and
`digest-<runId>.digicert-trusted-root-g4.tsr`. The v2 witness marker records
exactly one available-or-unavailable outcome per active-bundle anchor. Either
verified token makes the snapshot witnessed; both are preferred. If both
requests fail, the record remains in the chain with an explicit top-level
`status: unavailable`, per-anchor reasons, and no claimed token evidence.

A third party verifies every claimed token against its immutable,
code-approved bundle and independently pinned CA, never against a CA supplied
beside the token. The complete verifier is the authoritative check:

```bash
sha256sum records/YYYY-MM-DD/digest-RUN.json
jq '{status,trustBundleId,anchorOutcomes,supplementalOutcomes}' \
  records/YYYY-MM-DD/digest-RUN.witness.json
python3 scripts/verify_record_chain.py records
```

The first command's value must equal `digestSha256` in the witness JSON.
`scripts/verify_record_chain.py` requires a SHA-256 message imprint, verifies
every listed token rather than accepting the first valid one, pins each TSA's
root and signer identities and policy OID, extracts each signed `genTime`,
rejects any time after now or impossibly before a creation claim, and validates
each certificate chain at its own `genTime`. One invalid claimed token rejects
the complete marker even when another token verifies. Downloaded certificate
sidecars, if retained for archival context, are never trust input.

When a TSA replaces its responder certificate, follow
[`docs/tsa-signer-rotation.md`](tsa-signer-rotation.md): it covers the ledger
release chain's pinned signer set and this record-chain bundle.

A future TSA bundle must first be approved in verifier code and then introduced
by a snapshot witnessed under an already active bundle. During a transition,
new-authority attempts are recorded as non-authorizing supplemental outcomes;
the old-bundle token must make the transition available before replay activates
the new bundle. Subsequent snapshots must use the highest active bundle.
A bundle that only re-pins an anchor already in the active bundle, as when a
TSA replaces its responder certificate, has no supplemental outcomes. The
pull request that approves a bundle cannot write `records/trust/`, so it stages
the exact bytes under `scripts/staged_trust_bundles/`, and the recorder workflow
publishes them with `scripts/publish_trust_bundles.py` only when they equal the
code pin. One available anchor keeps a snapshot witnessed, so the recorder
reports any unavailable anchor in an issue (`scripts/witness_health.py`) rather
than failing. `docs/tsa-trust-bundle-rotation.md` is the full procedure.
`scripts/witnessed_timeline.py` publishes only run roots and registrations
reached by an available pinned witness; an unavailable witness never becomes
a claimed publication time. Root rows also expose custody inventory version,
status, and verifier-side headline eligibility.

### Per-run custody root

Every new thesis.analyst run ends with `custody_root.json`, followed by one
final write of `manifest.json`. The root commits the exact bytes and canonical
JSON of every activity artifact, including prompt/review bundles, commands and
outputs, normalized cells, `cells.with_activity.json`, and a distribution
artifact when present. It also commits the canonical manifest before the
`custodyRootSha256` reference is added.

The manifest's self artifact has one canonical exclusion: remove all
`artifactType: manifest` entries and `custodyRootSha256`, then hash the
canonical JSON. The `manifestHashSemantics` and self entry `hashMode` state
this rule. `scripts/verify_custody.py <run-dir>` recomputes the raw digests,
canonical digests, manifest exclusion, and custody-root hash. Generated-cell
conversion verifies custody before accepting runs at or after the enforcement
date.

Custody inventory v2 declares `custodyInventoryVersion: 2` and a `runMode` in
both the manifest and root. The verifier enforces the exact required filenames
for that mode, one-to-one ordered manifest/root references, and the absence of
unreferenced files. Pre-cutover roots still verify under their original rules
but are labeled `legacy-incomplete` and are not complete-inventory evidence.
For analyst runs, verifier-side `headlineEligible` additionally requires a
successful validation-complete run; the site must also require external
witness coverage. Resolver runs seal their exact archived source responses,
and recorder v2 seals and self-verifies the exact surface, log-chunk, and live
forecast body inventory.

Join model:

- one `target` has many `target_versions`;
- one `target_version` points to one `dataPointId`, but can bind many
  `source_series` through `target_observation_bindings`;
- one `source_series` has many `observations`, and each observation has many
  `observation_vintages`;
- one `target_version` can have many `baseline_candidates` and many
  `forecast_runs`;
- one `forecast_run` uses one `strategy_version`, zero or more `pack_versions`,
  zero or more raw `artifact_refs`, one 201-point `forecast_distributions` set,
  many `reasoning_events`, and many `tool_calls`;
- one draft run can have many `review_runs`, but only the final run is scored;
- judge runs can attach to one run or to a batch with structured compared-run
  subjects, but never to reward rows;
- one `resolution_event` binds a target version to the official observation
  vintage used for scoring;
- one resolution event can score many forecast runs for that target version;
- all tables that change public state emit `audit_events`.

The source of truth is the append-only database plus artifact store. Static
site files, notebooks, and TypeScript data are generated projections. They must
not become independent editable copies of forecast state.

## UI

Forecast pages should expose the experiment structure.

Suggested tabs:

- **Current:** latest canonical or meta-aggregated forecast.
- **Strategies:** latest run by strategy, model, and pack set.
- **Updates:** historical runs over time for the same target and strategy.
- **Evidence:** source-adapter history, missing months, vintage labels, and
  source roles.
- **Trace:** full public reasoning and activity artifacts.
- **Review:** pre-submit review and LLM judge findings.
- **Scoring:** proper scores once resolved, with comparison to baselines.

Ledger pages should show target coverage, upcoming resolutions, source-family
coverage, and missing forecasts. Pack pages should show where the pack was
used, what it changed, and whether it improved held-out scores.

## Scheduler

The scheduler should choose both targets and infrastructure work.

Forecast priority:

1. nearest resolvable target with no recorded run;
2. target families with many related ledger entries;
3. targets with new official observations since the last run;
4. high policy relevance;
5. targets that improve strategy or pack comparisons;
6. targets that will resolve soon enough to score the loop.

Infrastructure priority:

1. adapter needed by many upcoming targets;
2. validator that prevents repeated review findings;
3. baseline generator that covers many target families;
4. UI that makes strategy comparison or trace audit easier;
5. scoring and export improvements that reduce training leakage.

The scheduler should be allowed to pause forecasting when a missing adapter or
validator would otherwise cause many low-quality repetitive traces.

## Rebuild Sequence

This is the idealized build order for the clean architecture, not a status
report on the current repository.

1. Define ledger schema, target versioning, source-series bindings, and
   resolver validation.
2. Create the append-only database and artifact store.
3. Build adapters for the highest-volume source families.
4. Generate model candidates before LLM forecasting.
5. Run strategy-specific forecast runners with full trace logging.
6. Add pre-submit review as a recorded workflow variant.
7. Add deterministic validators for recurring review findings.
8. Build strategy comparison, update history, and evidence tables in the UI.
9. Automate resolution and proper scoring.
10. Export Brier reward datasets with leakage-safe splits.
11. Add meta-aggregation.
12. Use resolved scores to train and select Brier policies.

## What To Avoid

- forecasts that bypass the ledger;
- agents inferring resolution dates from cadence;
- catalog point estimates used as evidence for new runs;
- packs that only restate generic prompt advice;
- overwriting old runs;
- rewarding LLM judge opinions;
- static app data as the only record of a forecast;
- UI that hides strategy variation behind a single polished trace.
