# Thesis analyst runner

`scripts/run_thesis_analyst.py` is the local Axiom-style runner for forecast
cells. It turns a target spec into a complete run directory, then feeds the
validated cell into the existing spawned-cell converter.

Before changing the runner, read [`docs/thesis-vision.md`](thesis-vision.md).
The runner exists to make agent-only public-data forecasts reproducible:
prompt, command, stdout/stderr, raw response, normalized forecast, validation,
manifest, and later score should remain linked.

Scheduled docket runs preregister their target contracts before invoking this
runner. `scripts/register_targets.py` fixes the data-point identity, unit,
value scale, source adapter, source series/field/table, transform, release
policy, and expected release window in a canonical-hashed
`records/targets/*.json` snapshot. The normalized cell must retain the bound
`dataPointId` and unit and use the bound source host; the analyst still writes
the precise first-print rule within that binding.

Scheduled rolls use `thesis_target_registration_v2`: a privileged workflow job
captures `registeredAtUtc`, commits and pushes the canonical snapshot before any
analyst code runs, then binds the target and run record to the snapshot's
introducing `registrationCommit`. The contract hash excludes the operational
timestamp; protected Git ancestry and the later RFC 3161 record witness provide
the timing evidence. Publication accepts only data artifacts and regenerates
all TypeScript with trusted checkout code.

Prospect proposals follow the same registration boundary even though the
proposals themselves are untrusted. The prospect workflow mines gaps and asks
Codex for candidates in a read-only job, then a separate privileged job
revalidates the proposal schema, denylist, registry/catalog uniqueness, and
resolver bindability before it creates and pushes any v2 registration. Analyst
generation checks out that exact registered SHA. Records and trusted generated
TypeScript land together only after full bundle, chain, custody, test, and build
validation.

## Strategy comparison workflow

Ladder and median-of-three comparison runs attach to existing published cells;
they never create target registrations or forecast wave modules. Dispatch them
through `.github/workflows/strategy-docket.yml`. Its trusted selector binds an
open published target set to an exact source SHA and a GitHub-server-witnessed
selection artifact. The unprivileged job runs a reviewed ladder and/or three
independent fast rollouts, then derives median3 without another model call. The
publisher accepts only the exact suite inventory, checks every claimed run time
inside the witnessed select-to-publish window, verifies custody, and regenerates
`site/src/data/thesis-strategy-comparisons.ts` from every indexed strategy
suite on disk.

New median3 records use timestamp-first run directories and custody inventory
v2. Their custody root commits the local derived distribution and cell plus
exactly three distinct, verified constituent custody roots. The July 8, 2026
median records predate this contract and remain narrowly classified as
legacy-incomplete; new publication bundles cannot use that legacy shape.

Never push locally generated strategy records or a partial strategy TypeScript
file to `main`. The CI selector and publisher are the publication authority,
and whole-corpus regeneration prevents a later suite from dropping an earlier
wave.

## Subscription-backed Codex run

Use the native Codex path for local GPT-family runs. It follows the same
pattern as Axiom Encode: prefer the Desktop-bundled Codex CLI, create a
temporary `CODEX_HOME` with subscription auth symlinked in, ignore user config,
run `codex exec --json`, capture the last assistant message, and persist the
full JSONL event stream as activity artifacts.

```bash
python3 scripts/run_thesis_analyst.py \
  --series ons.labour.unemployment_rate \
  --period 2026-Q4 \
  --codex-model gpt-5.5
```

Use `--no-codex-search` for reviewer-like runs that should not fetch new
evidence, `--codex-sandbox` to change the execution sandbox, and
`--codex-reasoning-effort` to change the Codex reasoning-effort config.

## API-key-backed Gemini CLI run

Use the native Gemini path to run the same Thesis prompt through Gemini CLI.
Set `GEMINI_API_KEY` in the runner's parent environment first; the runner reads
that variable but never invokes a secret manager itself. It resolves the binary
from `THESIS_GEMINI_BIN` when set, otherwise from `gemini` on `PATH`, and fails
closed when either the executable or API key is missing.

```bash
python3 scripts/run_thesis_analyst.py \
  --series ons.labour.unemployment_rate \
  --period 2026-Q4 \
  --gemini-model gemini-3.7-flash
```

The invocation is:

```text
gemini -m MODEL --approval-mode plan -o stream-json -p PROMPT
```

The full prompt is passed directly as the `-p` value rather than on stdin or
through a pointer file: `-p` is required for deterministic headless operation,
while stdin content would be prepended to it. `command.json` records `<prompt>`
in place of those bytes, and `prompt.md` remains the canonical prompt artifact.
`plan` is the only approval mode used: read-only tools such as web search and
fetch can run, while `yolo` and `auto_edit` are never enabled.

Each Gemini stage runs with a fresh temporary `HOME` containing only
`.gemini/settings.json` with
`{"security":{"auth":{"selectedType":"gemini-api-key"}}}`. This prevents a
real user setting such as `oauth-personal` from opening a browser in a headless
run; the runner also detects the OAuth browser-prompt text and fails closed.
Gemini CLI merges workspace settings over user settings, so the stage also uses
a clean temporary working directory rather than a checkout that might contain
`.gemini/settings.json`. The v1 Gemini backend therefore cannot read repository
files. That isolation is intentional and does not prevent its plan-mode web
tools from gathering public evidence.

Plan mode is reinforced by an unconditional workspace guard around every
Gemini stage. The runner fingerprints the run directory and repository tree
before and after execution and fails the run closed on any mutation, recording
`workspaceMutations` in `command.json` and `workspaceHygiene` in
`manifest.json`.

For batches, pass `--gemini-model` to `scripts/run_thesis_batch.py` or set
`THESIS_GEMINI_MODEL`. Non-ticket batches refuse ambiguous command, Codex, and
Gemini backend selections; when none is selected they retain the existing
default Codex model. Generation tickets remain Codex-only.

## Network-enabled Codex runs

The default read-only sandbox denies ALL sockets: `curl` inside it exits 6
(could not resolve host) before any HTTP happens, and no config restores
network under read-only. The hosted `--search` web tool is not a substitute
for data APIs — it cannot fetch raw JSON from CDN-fronted agency endpoints
(for `data.census.gov/api/access/...` it fails with "Cache miss"), and
`api.census.gov` now requires an API key outright. The 2026-07-24 broadband
incident showed what happens when a run's contract demands fetched numbers
that its tools cannot fetch: four consecutive runs narrated live fetches
while inventing the values. The invented 65+ broadband series
(79.4/81.6/83.5/84.8 for 2021-2024) matches neither the ACS 1-year file
(83.1/84.8/86.5/88.2) nor the 5-year file (78.6/80.6/82.6/84.6), and its
"fetched" raw counts are wrong by up to 2.3 million — so this is
fabrication, not a vintage mix-up, and no vintage-only rule would have
caught it. The spawn-time history anchors did.

For targets whose official source is such an endpoint, run with:

```bash
python3 scripts/run_thesis_analyst.py \
  --series census.acs.broadband_subscription_65_plus.share \
  --period 2025 \
  --codex-model gpt-5.5 \
  --codex-sandbox workspace-write \
  --codex-network
```

`--codex-network` adds `sandbox_workspace_write.network_access=true` to the
Codex invocation (recorded in `command.json` with `networkAccess: true`) and
injects a fetch-honesty note into the fast/full prompt: fetch with
`curl -sS`, read values only from the echoed response, and fail honestly if
a fetch fails. Because workspace-write also makes the checkout writable, the
runner guards the workspace around every network-enabled agent stage: it
fingerprints the run directory and the git tree before the stage and fails
the run closed (`workspaceMutations` in `command.json`,
`workspaceHygiene` in `manifest.json`, `ok: false`) on any mutation beyond
the agent's own last-message file. Custody inventory v2 independently
rejects unreferenced files at promotion; the guard fails at run time and
covers the rest of the worktree. Ladder modes keep their sealed contracts
and do not gain the prompt note; the flag is for fast/full lanes only.
Codex runs default to the read-only sandbox and may inspect local repo context
when useful, including prior run manifests, activity artifacts, generated
comparison data, prediction packs, ledger targets, docs, and tests. The prompt
treats that context as optional: agents should use it when it improves an
update or resolver, but they are not required to inspect prior traces for every
target.

`--command` remains available for non-Codex agents or custom experiments. The
command may reference `{prompt_path}` and `{repo_root}` and receives the prompt
on stdin:

```bash
python3 scripts/run_thesis_analyst.py \
  --series ons.labour.unemployment_rate \
  --period 2026-Q4 \
  --command "codex exec -C {repo_root} -"
```

Agent commands default to a 600 second timeout. Use `--timeout-seconds` to make
smoke tests shorter or longer. A timeout writes `command.json`, `stdout.txt`,
`stderr.txt`, `raw_response.txt`, `error.json`, and `manifest.json` with
`ok: false`. Codex runs additionally write `codex_stdout.jsonl`,
`codex_stderr.log`, `codex_events.jsonl`, `codex_last_message.txt`, and
`codex_trace.json`. Gemini runs additionally write `gemini_stdout.jsonl`,
`gemini_events.jsonl`, `gemini_last_message.txt`, and `gemini_trace.json`.

When the command names a model with `-m`, `--model`, or `--model=...`, the
runner records that runtime model in `manifest.json` and in generated cell
metadata. If it differs from the agent default in `agent.yaml`, the manifest
also keeps `configuredModel` for comparison. Gemini runtime metadata records
`backend: "gemini_cli"`, keeps `model` as the requested model, and adds
`runtimeModel` from the CLI's `stats.models` key when present.

## Credential hygiene

Incident 2026-07-21: during an aging-wave batch, the codex agent ran
`env | rg -i 'CENSUS|API|KEY'` while hunting for a Census API key, and 18
credential env vars inherited from the interactive shell landed verbatim in
recorded trace files; GitHub push protection was the only thing that kept
them out of the public repo. The runner now enforces two independent layers,
covering the draft, pre-submit review, and final stages of the native Codex,
native Gemini, and `--command` paths:

1. **Allowlisted subprocess environment.** Agent subprocesses receive only
   `PATH`, `HOME`, `TERM`, `SHELL`, `TMPDIR`, `LANG`, `LC_ALL`, `LC_CTYPE`,
   and `CODEX_HOME` (`AGENT_ENV_ALLOWLIST` in `run_thesis_analyst.py`) — an
   allowlist, never a denylist — so an env dump has nothing secret to print.
   Codex authenticates through `CODEX_HOME/auth.json` (subscription login or
   CI `codex login --with-api-key`), not env vars. The Gemini backend alone
   adds `GEMINI_API_KEY` and overrides `HOME` with its temporary directory.
   The key value is never placed in argv or any artifact; `command.json`
   records subprocess environment variable names only. A `--command` agent
   that genuinely needs another variable requires a deliberate, reviewed
   extension of the allowlist.
2. **Stream redaction before sealing.** Every captured agent stream —
   Codex stdout/stderr JSONL, Gemini stream JSONL and tool events, both native
   backends' last messages, `--command` stdout/stderr, recorded argv, and saved
   `--response-file` content — is redacted before any artifact is written.
   Redaction covers
   `NAME=value` lines and `"name": "value"` JSON fields with
   credential-shaped names (`KEY`/`TOKEN`/`SECRET`/`PASSWORD`), plus
   well-known token formats (`sk-ant-`, `sk-proj-`, `sk-or-`, legacy `sk-`,
   `ghp_`, `github_pat_`, `xoxb-`/`xoxp-`, `AIza`, `eyJhbGciOi` JWTs, and
   `AKIA`), replacing matches with `[REDACTED]`. JSON documents and JSONL
   event lines are redacted value-wise so they stay parseable, and clean
   content passes through byte-identical. Because redaction happens before
   sealing, custody roots commit to the already-clean bytes — a post-hoc
   scrub that breaks attestation is never needed again.

`tests/test_thesis_analyst_env_hygiene.py` replays the incident end to end
with planted secrets and asserts both layers, including that redacted runs
still validate and pass custody verification.

## Saved-response and dry-run modes

Use a saved response when a model run happened elsewhere:

```bash
python3 scripts/run_thesis_analyst.py \
  --series ons.labour.unemployment_rate \
  --period 2026-Q4 \
  --response-file /tmp/codex-output.txt
```

Use the deterministic mock mode to test plumbing without calling an agent:

```bash
python3 scripts/run_thesis_analyst.py \
  --series test.synthetic_rate \
  --period 2030-01 \
  --mock-cell
```

## Pre-submit review loop

Use `--pre-submit-review-codex-model` or `--pre-submit-review-command` to run a
reviewer subagent between the draft and final forecast:

```bash
python3 scripts/run_thesis_analyst.py \
  --series ons.labour.unemployment_rate \
  --period 2026-Q4 \
  --codex-model gpt-5.5 \
  --pre-submit-review-codex-model gpt-5.5
```

The runner first saves the draft response, then asks the reviewer to critique
resolver clarity, base-rate discipline, time-series/model prior use, update
justification, interval calibration, tail scenarios, coherence, and leakage.
The forecaster is then rerun with the draft and critique and must include a
public `Review disposition:` reasoning step in the final JSON. The draft,
review prompt, reviewer output, revision prompt, final response, parsed cells,
validation, and manifest are all activity artifacts. Only the final forecast is
scored; the review loop is a workflow variant that can be compared against
unreviewed runs later.

The reviewer Codex path does not enable web search by default; add
`--pre-submit-review-codex-search` only when the review should fetch additional
public context. The normal review mode should judge the draft, cited evidence,
and target spec. The native reviewer backend remains Codex-only in v1, but a
Gemini forecaster may use it: draft and final stages run through Gemini while
the prefixed pre-submit-review stage runs through Codex, with both trace
families preserved.

## Time-series model-candidate preflight

For repeated numeric public series, run model candidates before asking the
agent to make an inside-view update. The shared schema is
`thesis_model_candidate_v1`: every candidate carries point, p10/p50/p90, 80%
and 90% intervals, interval method, train cutoff, calibration_n, history, and
walk-forward score metadata when enough history exists.

```bash
python3 scripts/run_time_series_models.py \
  --target-id fns.snap.overpayment_payment_error_rate.us.fy2026 \
  --target-period FY2026 \
  --history-json '[{"period":"2024","value":9.26},{"period":"2025","value":9.28}]' \
  --models persistence \
  --round-increment 0.1
```

With enough history and the Python `experiments` extra installed, include the
first open-source adapter:

```bash
uv run --extra experiments python scripts/run_time_series_models.py \
  --target-id example.series.2026 \
  --target-period 2026 \
  --history-file /tmp/history.json \
  --models persistence,statsmodels-local-level
```

`statsmodels-local-level` uses statsmodels SARIMAX(0,1,0) with drift and
native state-space prediction intervals. If a future adapter cannot produce
native intervals, it must wrap the point forecast with conformal, residual,
panel, or fallback-prior intervals and label `intervalMethod` accordingly.

## Activity artifacts

Every run writes a directory under `records/thesis-analyst/YYYY-MM-DD/` with:

- `prompt.md`
- `command.json`
- `stdout.txt` and `stderr.txt` when a command is used
- `codex_stdout.jsonl`, `codex_stderr.log`, `codex_events.jsonl`,
  `codex_last_message.txt`, and `codex_trace.json` when `--codex-model` or
  `--pre-submit-review-codex-model` is used
- `gemini_stdout.jsonl`, `gemini_events.jsonl`, `gemini_last_message.txt`, and
  `gemini_trace.json` when `--gemini-model` is used
- `raw_response.txt`
- `draft_stdout.txt`, `pre_submit_review_stdout.txt`, and `revision_prompt.md`
  when pre-submit review is enabled
- `parsed_cells.json`
- `normalized_cells.json`
- `distribution.json` (the materialized 201-point scored CDF)
- `validation.json`
- model-candidate JSON from `scripts/run_time_series_models.py` when a
  repeated numeric series preflight is run
- `cells.with_activity.json`
- `custody_root.json`
- `manifest.json`

`cells.with_activity.json` carries `activityLog` refs for the prompt, raw
response, parsed/normalized cells, materialized run distribution, and
validation report. When that file is
converted with `scripts/spawned_cells_to_ts.py`, the refs land in
`predictionRun.activityLog`, then in Thesis Log run records. As of
`thesis_log_v3`, `/log.json` is a manifest and full run records are reachable
through its canonical-hashed `/log/runs/{index}.json` chunks.

`custody_root.json` is written after all activity artifacts. It contains both
raw-byte and canonical-JSON SHA-256 commitments, including a commitment to the
manifest before its root reference. The runner then performs the only final
manifest write, adding `custodyRootSha256`. Verify a run before promotion with
`python3 scripts/verify_custody.py <run-dir>`; custody-era converter inputs are
rejected if this verification fails.

New roots use custody inventory v2. Successful analyst runs always preserve
`command.json`, `stdout.txt`, and `stderr.txt`, including saved-response and
mock modes. Codex stages always preserve all five Codex trace files, even when
an individual stream is empty; Gemini stages likewise preserve all four Gemini
trace files. The verifier selects the required family from each stage's
`command.json`, so mixed Gemini-forecaster/Codex-review runs remain complete.
It rejects missing required files and any regular file in the run directory
that is not referenced by the manifest. Roots without an inventory version
remain verifiable only as `legacy-incomplete` records.

## Convert to a generated catalog module

```bash
python3 scripts/run_thesis_analyst.py \
  --series ons.labour.unemployment_rate \
  --period 2026-Q4 \
  --codex-model gpt-5.5 \
  --write-ts site/src/data/forecast-examples/generated-thesis-agent.ts \
  --const-name GENERATED_THESIS_AGENT_CELLS
```

Generated modules should be imported into `site/src/data/forecast-cells.ts`
only after review. Do not hand-edit generated modules; rerun the agent or
replace the source artifact.
