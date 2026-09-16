# System One lane

`scripts/run_system_one_forecast.py` forecasts one already-published Thesis
target with a System One model: a model that answers named typed questions
about a fixed state and returns probabilities without generating text. The
lane turns a target into 15 yes/no questions of the form "the first print
will be at or below t", records the request and the raw response verbatim,
monotonizes the answers into a CDF, and seals the run as a complete v2
custody inventory under run mode `system_one`.

Only the `typesafe` backend is a System One model. The `adapter` backend
emulates the same interface over a general LLM, and the emulation is not the
thing: it sends all 15 questions in one structured-output request and the
model may reason before it answers. Every backend therefore carries its own
hashed policy, its own cell heading, and its own method sentence, so no
record claims isolation it did not get.

This is a comparison lane, not a headline lane. It never creates a target
registration and never carries the headline forecast for a target. Custody
reports `headline_eligible: false` for every run in it, the same way it does
for `derived_ensemble`. Its CRPS is published beside `thesis.analyst` and the
persistence baseline on cell pages and in the log scoreboard at the
claimed-time tier; like the other comparison lanes it earns no reward, for
the reason [`docs/brier-lab.md`](brier-lab.md) records.

Read [`docs/cell-contract.md`](cell-contract.md) for the forecast-cell schema
and [`docs/thesis-analyst-runner.md`](thesis-analyst-runner.md) for the
analyst runner whose custody and cell shape this lane mirrors.

## Identity

| Field | Value |
| --- | --- |
| agent | `thesis.system_one` |
| agentVersion | `0.1.0` |
| promptMode | `system_one_noul_ladder` |
| manifest schemaVersion | `thesis_system_one_run_manifest_v1` |
| custody run mode | `system_one`, inventory version 2 |
| run directory | `records/thesis-analyst/<YYYY-MM-DD>/<stamp>-system-one-<catalogSlug>/` |

`agent.model` is the model that answered: `response.model` for the `typesafe`
backend, `"<provider>/<model>"` for `adapter`, and the backend name for
`mock` and `response_file`. A `typesafe` run that failed before the service
answered records `null`, not the backend name, so a failure is never tallied
against a model that never spoke. `agent.promptHash` is the canonical sha256
of the ladder policy (question template, rung count, span, dispersion
constants, monotonization version, bases). `agent.toolPolicyHash` is the
canonical sha256 of the backend policy, which is per backend: the shared part
is no tools, no web access, Noul questions only, pre-resolution state only,
and the redaction list below, and the per-backend part is how the answers
were elicited, whether the questions were isolated from one another, whether
the backend generates text, and whether a chain of thought is possible.
`typesafe` and `adapter` therefore hash differently, and so does the same
lane run through `mock` or `response_file`. Changing the wording or the
ladder constants changes `promptHash`, so runs under different contracts are
distinguishable in the record.

## Evidence boundary

`state.json` (`thesis_system_one_state_v1`) is everything the model sees. It
is assembled from an allowlist of public, pre-resolution material, never by
deleting fields from the published cell, so no forecast field is ever read in
the first place:

- `target`: `catalogSlug`, `title`, `question`, `unit`, `country`, `series`,
  `period`, `dataPointId`, `resolutionDate`, `resolutionRule`,
  `resolutionSource`, `resolutionSourceUrl`. The unit is the registered
  scoring unit, read from `targetUnit` on a trusted selection target or
  `unit` on a registration snapshot.
- `historicalContext`: `{label, value, period}` rows copied from the
  published primary cell, carrying `provenance: "agent_reported"` and a note
  saying they were reported by that run and are not re-fetched here.
- `ledgerObservations`: same-series official observations pinned from the
  ledger JSONL passed with `--ledger-jsonl`, carrying
  `provenance: "official_ledger"`, the match rule that selected them, a count
  of the rows the rule rejected, and the `source_record_id` of each row. The
  match rule is: `measure.concept` or `measure.source_concept` equals the
  target's `sourceBinding.sourceSeriesId` or `series`; `measure.unit` equals
  the registered unit; the row's geography is the target country's national
  geography, using the same country ids
  `scripts/stamp_docket_ledger_refs.py` binds docket series with; the
  observation's period precedes the target period at the same granularity,
  with a numeric ledger period (`{"type": "fiscal_year", "value": 2025}`)
  read as its decimal string and a docket `FY2026` period read as that
  fiscal year; and `observed_at` strictly precedes the instant this run
  started. Geography is part of the key because the ledger holds one row per
  state as well as the national row for the same concept, and pooling them
  would silently average a country. When the surviving rows disagree about
  `entity`, only the lineage of the most recent observation is kept and the
  rest are counted in `rejectedRows`, so a fallback to the history basis is
  never silent. Without `--ledger-jsonl` this list is empty.
- `sourceContext`: the primary cell's URLs as plain strings. No URL is
  fetched by this lane, and the state says so.
- `redaction`: the list of primary-cell fields that are withheld.
- `primaryCellProvenance`: the primary cell's path and sha256, plus its
  run manifest path and sha256, so the evidence the model saw is bound to an
  existing custody root.

### Redacted primary-cell fields

`pointEstimate`, `ciLow`, `ciHigh`, `confidence`, `drivers`, `reasoning`,
`predictionDistribution`, `thresholdLadder`, `preSubmitReview`,
`activityLog`, `model`, `runAt`.

The runner scans the serialized state and questions before it sends anything
and fails closed in phase `state` if a redacted key appears anywhere, or if
distinctive redacted prose (at least 24 characters and containing a space:
driver phrases, reasoning steps, review findings) appears verbatim. One
exemption: text that is also contained in an allowed primary-cell string is
not a leak, because a reasoning heading that repeats the target's own title
carries no forecast information. The same scan runs again as a validation
check, and `tests/test_run_system_one_forecast.py` asserts that neither the
redacted keys nor their values reach the state or questions.

The boundary is about what the model reads. It is not a claim that the model
knows nothing else: a general model may have seen the series, or the
resolving print, in its training data. Nothing in this lane can rule that
out.

## Ladder construction

Fifteen strictly increasing thresholds, on one of two bases:

- `ledger_dispersion` when at least 3 same-series ledger observations
  matched. This is the basis to prefer: the rows are official observations,
  not agent-reported history.
- `history_dispersion` when the ledger yields fewer than 3 rows and the
  primary cell's `historicalContext` resolves to at least 3 dated rows of one
  series.
- Neither: the run fails closed in phase `state`, and the sealed failure
  keeps `state.json` and `error.json`. The reason is `insufficient_history`
  when there are too few rows, `history_period_kinds_differ` or
  `history_periods_repeat` when the reported history is not one series.

Agent-reported history is not a series just because it is a list. Published
cells mix a four-week average in with the weekly prints, a CPI row in with
the real-earnings rows it explains, or a second program in with the target
program, and read in the reported order those look like successive
observations. So the history basis dates every row before it uses it: from
the row's own `period` when it has one, otherwise from its label (month
names, `YYYY-MM`, quarters, `FY2026`, ISO dates), and rows that name no
period are dropped rather than reordered into the series. If the dated rows
disagree about granularity, or if any period repeats, the list is two
lineages rather than one series and the run refuses the history basis
outright.

From the chosen rows in period order:

- `center` is the last observation's value.
- `scale` is the 80th percentile of absolute successive changes, floored at
  1e-9. This is the persistence-baseline dispersion convention in
  [`docs/brier-lab.md`](brier-lab.md).
- `sigma` is `scale / 1.2816`: the 80th-percentile absolute change is treated
  as an 80% half-width and converted to a standard deviation with the normal
  80% quantile.
- The rungs are 15 evenly spaced values from `center - 3*sigma` to
  `center + 3*sigma`, rounded to the largest decimal precision present in the
  input values, using the `decimal_places` helper the runner shares with
  `run_thesis_analyst.py`, then deduplicated. If fewer than 5 distinct rungs
  survive rounding, the run fails closed in phase `state` with reason
  `ladder_collapsed_under_rounding`.

`questions.json` records `ladderBasis`, `center`, `scale`, `scaleMethod`,
`sigma`, `precision`, `observationCount`, `thresholds`, the matched
`ledgerSourceRecordIds`, and the questions as sent.

The ladder is a fixed rule over public history. It is not a forecast: it only
decides where the model is asked, and a ladder whose span misses the outcome
shows up as the off-ladder failure below rather than as a quietly bad
forecast.

## Elicitation

One `system_one` call carries 15 Noul questions named `rung_01` through
`rung_15`, each with instructions of the form:

```
The official first print of {title} for {period} will be at or below {value}.
```

`{value}` is the rung at the ladder's precision followed by the registered
unit when the target has one. A title that ends with the period is trimmed so
the sentence does not repeat it, and a `week_YYYY-MM-DD` period renders as
"week ending YYYY-MM-DD". A real question from a run on
`us-natural-gas-vented-flared-2025`:

```
The official first print of U.S. natural gas vented and flared for 2025 will
be at or below 335163 million_cubic_feet.
```

On the `typesafe` backend every question is answered independently and in
isolation, which TypeSafe states and this repository records as a vendor
statement rather than a verified mechanism. On the `adapter` backend it is
not true at all: `system-one-adapter==0.1.3` serializes the state once and
sends all 15 questions in a single provider request (read from
`_client.py` `_prepare_evaluation` and `providers/openai.py`
`_responses_request_kwargs` on 2026-09-16), so the answers are drawn
together and the provider's default reasoning applies. Either way the raw
answers are a set of point probabilities rather than a distribution, which is
why the monotonization step below exists. `Noul` is the only question type in
v1: no `Choice`, no `Score`.

`request.json` records the state, the questions as sent, and the backend,
provider, and model. `response.json` is the `SystemOneResponse` serialized
with `msgspec.to_builtins`, verbatim, including its `model` and `usage`.
Before the `typesafe` and `adapter` backends send anything, the runner
re-encodes the SDK question objects and refuses the run if they differ from
the recorded payloads, so `request.json` is what was actually sent. API keys
are never written to any artifact, and a backend exception is recorded as its
class name only, never its message.

## Monotonization and the forecast

The raw per-rung probabilities are an unordered set of independent answers,
so they can violate `P(X <= t)` being non-decreasing in `t`. The runner
applies pool adjacent violators (the least-squares non-decreasing fit),
clamps to [0, 1], and stores both vectors on the cell's `thresholdLadder`:

```json
{
  "thresholds": [143071.0, "..."],
  "cumulativeProbabilities": [0.0032714501, "..."],
  "rawCumulativeProbabilities": [0.0032714501, "..."],
  "monotonization": "pav_v1",
  "ladderBasis": "history_dispersion"
}
```

`thresholds` and `cumulativeProbabilities` are the existing contract read by
`ladder_distribution`; the other three keys are additions this lane makes.
The point estimate is the monotone ladder interpolated at cumulative 0.50 and
`ciLow` / `ciHigh` at 0.10 and 0.90, by linear interpolation between rungs.
`ladder_distribution` then materializes a `numeric_cdf_v1` distribution with
provenance `agent_reported`, which is what the CRPS pipeline scores.

If the monotone ladder does not reach 0.10 at the first rung or 0.90 at the
last, the 80% interval is off the ladder and the run fails closed in phase
`ladder` with reason `off_ladder_mass`, recording the raw and monotone
probabilities in `error.json`. The lane never extrapolates past its own
rungs.

## Backends

| Backend | Needs | Notes |
| --- | --- | --- |
| `typesafe` | `TYPESAFE_API_KEY`, the `system-one` extra | The real System One model through `typesafe-sdk==0.6.0`. `--model` is optional; `agent.model` comes back from the response. |
| `adapter` | `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` for the chosen `--provider`, the `system-one` extra | The interface emulated over an LLM by `system-one-adapter==0.1.3` with structured outputs and probability answers: one request carries the state and all 15 questions, and the model may reason before it answers. Defaults: provider `openai`, model `gpt-5.5`. |
| `response_file` | `--response-file` | Replays a saved `SystemOneResponse` JSON deterministically. `command.json` records the file's name and sha256. |
| `mock` | nothing | A deterministic offline ladder for tests and smoke runs: a normal CDF at the ladder's own center and sigma, with a small per-rung tilt derived from the question name. It exercises the pipeline and says nothing about any model. |

A missing or blank key is refused before any run directory exists (exit code
2), and so is an unreadable or misshapen `--response-file`, so an input
mistake never leaves a half-written record. Anything a phase did not
anticipate is sealed as that phase's failure when the artifacts written so
far are exactly one phase inventory; when they are not, the partial run
directory is removed and the runner exits 2 with nothing recorded, which is
what the suite runner documents exit 2 to mean. Only `typesafe` and
`adapter` import the optional extra, and they import it lazily, so `mock` and
`response_file` run against the repository's base environment. Install the
extra with `uv sync --extra system-one` or run with
`uv run --locked --extra system-one`.

Exit codes: 0 sealed and valid, 1 sealed failure (the run directory keeps a
phase inventory and is custody-verifiable), 2 refused input.

## Run one target locally

The runner takes one trusted selection target object or one entry from a
registration snapshot. Pull one out with `python3` and point the runner at a
records root outside `records/`, so a local experiment can never be mistaken
for a published record:

```bash
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); json.dump(d['targets'][0], open('/tmp/target.json','w'), indent=2)" \
  records/targets/2026-08-14-e4f85c5b0ed9e1799c3a66733a53c5bf9772398e09a015a29bd6a3753df02e91.json

uv run python scripts/run_system_one_forecast.py \
  --target-json /tmp/target.json \
  --backend mock \
  --records-root /tmp/system-one-smoke

python3 scripts/verify_custody.py /tmp/system-one-smoke/thesis-analyst/*/*-system-one-*
```

The runner prints the manifest JSON. `--out-manifest PATH` also writes the
manifest's repository-relative path to a file.

With no `--primary-cell`, the runner resolves the primary cell the way the
site does: it reads the published catalog under
`site/src/data/forecast-examples`, finds the cell whose `slug` is the
target's `catalogSlug`, and takes the run directory its `predictionRun`
activity log cites. That is the run the catalog publishes, which is the
point: comparison-lane runs for the same target (ladder, ladder_v2, fast
rollouts) live in the same records tree and are not this target's published
evidence. A slug the catalog does not bind to a recorded run is refused, with
`--primary-cell` named as the way to pin one by hand. An explicit
`--primary-cell` must be that same file whenever the catalog does bind the
slug, so a local override can add a primary cell the catalog lacks but can
never quietly swap the one it has. `--run-at` fixes the run start and exists
for tests.

Add `--ledger-jsonl` to get the `ledger_dispersion` basis. The file is
`ledger/official_observations.jsonl` from the ledger repository the docket
workflow pins (`PolicyEngine/chronicle`, branch
`codex/thesis-ledger-facts`); fetch it the way the workflow does rather than
hand-editing a copy.

The adapter is the control arm: it runs without a TypeSafe key, and it spends
real provider credit, a few cents for one target.

```bash
OPENAI_API_KEY=... uv run --locked --extra system-one \
  python scripts/run_system_one_forecast.py \
  --target-json /tmp/target.json \
  --ledger-jsonl /tmp/official-observations.jsonl \
  --backend adapter --provider openai --model gpt-5.5 \
  --records-root /tmp/system-one-smoke
```

Never write a local run into `records/` and never push one. Records belong to
the allowlisted workflows, and the pre-push guard in `AGENTS.md` blocks any
local push that touches them.

## Dispatch the workflow

Published system_one runs come from the dispatch-only strategy docket, the
same select then generate then publish boundary the ladder and median3 lanes
use:

```bash
gh workflow run strategy-docket.yml --ref main \
  -f catalog_slugs=us-natural-gas-vented-flared-2025 \
  -f auto_select=false \
  -f max_targets=1 \
  -f suite=system_one \
  -f system_one_backend=adapter \
  -f system_one_model=
```

`system_one_backend` is `adapter` (default) or `typesafe`.
`system_one_model` empty means the backend default: `gpt-5.5` for the
OpenAI adapter, and the model TypeSafe serves by default for `typesafe`.
Both are bound into the trusted selection request as `systemOneBackend` and
`systemOneModel`, the way `ladder_prompt_mode` is bound, so they are never a
generate-job input the unprivileged job can change. The docket accepts only
`typesafe` and `adapter`: `mock` and `response_file` exist for tests and local
smoke runs and cannot produce a published record.

The lane writes a batch manifest at
`records/thesis-analyst/batches/<day>/strategy-<run>-a<attempt>-system-one.json`
and the suite manifest carries
`lanes.systemOne: {batchManifest, backend, model}`, null on suites that do
not run it.

Publication verifies custody with run mode `system_one`, checks the resolver
and registration fields against the trusted target, and checks the claimed
run window against the witnessed select-to-publish window. It also rebuilds
the run rather than reading it:

- the backend, the requested model and the provider must equal the trusted
  request. A null `systemOneModel` means the runner default for that backend
  (`gpt-5.5` for the adapter), not any model, and an adapter run must name
  the runner's default provider, `openai`, since a dispatched run never
  chooses one.
- the primary cell is the one the published catalog binds to the slug, read
  from the publisher's own checkout, never the path the run cites.
- `state.json` is rebuilt from the trusted target, that primary cell and the
  pinned ledger, and compared byte for byte, so a forged history value,
  source URL, ledger row or provenance digest fails here. Validation
  therefore requires the pinned ledger: `stage` and `validate` take
  `--ledger-jsonl`, and a system one suite without it is refused.
- the ladder geometry and `questions.json` are rebuilt from that state, so
  the thresholds, center, scale and precision are recomputed rather than
  trusted, and then the response is re-monotonized, the forecast
  re-interpolated, the distribution rebuilt, and the lane's rubric re-run.

`scripts/strategy_comparisons.py` then projects the lane into
`site/src/data/thesis-strategy-comparisons.ts` with
`predictionRun.agent = "thesis.system_one"`, labeled "System One threshold
ladder" for a typesafe run and "System One emulation (adapter:
`<provider>/<model>`)" for an adapter run, with the same method sentence the
cell carries. `/models` grows a System One column as soon as a suite lands,
tallied per run rather than per batch, so a batch whose runs answered under
different models is not filed under one. What the site publishes is the
monotonized ladder; the raw per-rung answers stay in the cell as
`rawCumulativeProbabilities` and verbatim in `response.json`.

The generate job runs this lane under `uv run --locked --extra system-one`,
so the SDKs are the versions the lock names, and it installs no codex
toolchain: the sandbox, install, and login steps are all skipped when the
TRUSTED selection names `system_one`. The job exposes `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, and `TYPESAFE_API_KEY`, but the trusted request binds
only the backend and the model, so a dispatched `adapter` run always uses the
runner's own default provider, `openai`. Reaching the anthropic provider from
a dispatch would take a `systemOneProvider` request field in
`scripts/strategy_targets.py` and a matching workflow input; today
`--provider anthropic` is a local-run option only.

## What the cell's reasoning steps mean

The model writes no text, so every reasoning step is written by the runner
from what actually happened. Nothing in it is a paraphrase of model
reasoning, because there is none to paraphrase:

- **heading**: names the method and the backend. "System One threshold
  ladder" only for a typesafe run; otherwise "System One emulation" and the
  backend that produced the answers, for example "System One emulation
  (adapter: openai/gpt-5.5)".
- **text**: the method disclosure, per backend. A typesafe run says the model
  answered the rungs independently and in isolation with no tools, no search
  and no chain of thought. An adapter run says it emulates the interface, that
  one structured-output request carried the state and all 15 questions, that
  the answers are therefore not isolated from one another, and that the model
  may reason internally so its output tokens can include reasoning tokens. A
  mock run says it is a deterministic offline stand-in and not a model, and a
  response_file run says it replays a recorded response. Each then says what
  the state contained.
- **tool** `system_one.noul_ladder`: the call carries the backend, provider,
  model, and question count; the result carries the latency and the token
  usage the backend reported.
- **math** beginning `Ladder:`: every rung as `P(X <= t) = p` at the monotone
  values, then the interpolated 10th percentile, median, and 90th percentile.
  This is the complete derivation of the forecast from the answers, so a
  reader can recompute the point and interval from the listed rungs.
- **forecast**: the point, `ciLow`, and `ciHigh` that were scored.

There are no drivers (`drivers` is empty), no base rates, and no
reference-class prose. The lane will not write evidence reasoning the model
did not do.

## Validation and custody

`validation.json` uses its own rubric, `thesis_system_one_validation_v1`, not
the analyst trace-depth rubric, because there is no trace to judge. It
checks: resolver fields equal the trusted target; unit equals the registered
unit; registration fields equal the trusted target; `runAt` strictly before
`resolutionDate` and not before `runStartedAt`; thresholds strictly
increasing; cumulative probabilities non-decreasing; ladder arrays of equal
length; question count equal to the threshold count; raw probabilities inside
[0, 1]; the 80% interval on the ladder; `ciLow < pointEstimate < ciHigh`; a
materialized `numeric_cdf_v1` distribution; and no redacted content in the
state or questions.

A successful run seals nine artifacts plus `manifest.json` and
`custody_root.json`: `state.json`, `questions.json`, `request.json`,
`response.json`, `command.json`, `normalized_cells.json`,
`distribution.json`, `validation.json`, `cells.with_activity.json`. A failed
run seals the inventory its phase reached, always with `error.json`:
`state` keeps the state; `backend` adds questions, request, and command;
`ladder` adds the response; `validate` adds the normalized cell and
distribution. `scripts/verify_custody.py` knows every one of these
inventories exactly, re-checks the resolver fields, the cell metadata against
the manifest, the ladder's monotonicity and declared monotonization version,
and the distribution summary against the cell, and reports `run_succeeded`
from the manifest's `ok`. A tampered artifact, an extra file, or a
phase inventory that does not match the declared phase is a `CustodyError`.

Failed runs stay in the record. They are evidence about the lane.

## Honest limits

- No backend of this lane uses tools or performs a search. On the typesafe
  backend each question is answered in isolation and returns a probability
  and nothing else; on the adapter backend the questions travel together in
  one request and the provider model may reason first. Either way there is no
  reasoning trace to audit, which is a real loss against the analyst lane:
  the only auditable objects are the state, the questions, the raw
  probabilities, and the fixed rule that turns them into a CDF.
- TypeSafe describes its training as reinforcement learning for calibrated
  decisions; the reward and the data are undisclosed. That sentence is the
  limit of what this repository says about how the model was built, and it is
  a vendor description recorded when the lane was built (2026-09-15), not
  something the lab verified.
- The vendor's calibration claim, from the same 2026-09-15 reading, is about
  present-state tasks: questions about a state the model is given. A forecast
  is not a present-state task.
  Nothing published by the vendor establishes that this model is calibrated
  on questions whose answers do not exist yet, and this record is how we find
  out. Scored runs against `thesis.analyst` and the persistence baseline are
  the evidence; the claim is not.
- The `mock` and `response_file` backends produce no evidence about any
  model. `mock` answers from a normal CDF built out of the same history the
  ladder came from, and `response_file` replays bytes.
- The `typesafe` backend had never been run when the lane was built
  (2026-09-16): the model was in early access and the lab had no key.
  `records/thesis-analyst/*/*-system-one-*` is the authority on what has
  actually run, and each run's `command.json` and `manifest.json` name the
  backend and the model that answered.
- The adapter is an emulation of the interface, not the model. An adapter run
  measures an LLM answering ladder questions under structured output, which
  is a useful control arm and is not a System One result. The manifest keeps
  them apart by `agent.backend`, `agent.model` and `agent.toolPolicyHash`,
  and so do the cell heading, the method sentence and the comparison label.
- One run is one draw. The lane makes no claim from a single target, and its
  standing is whatever the paired CRPS difference against persistence says
  once enough targets resolve.
