# Agent Instructions

This repository contains Brier and the Thesis forecasting app. Future agents
should treat this file as the operating entrypoint.

## Read First

Before changing forecast-generation, pack, resolution, scoring, or agent-run
surfaces, read these in order:

1. `docs/thesis-vision.md` - mission, scope, non-goals, prioritization.
2. `docs/cell-contract.md` - forecast-cell schema and trace-depth bar.
3. `docs/thesis-analyst-runner.md` - how live agent runs become records.
4. `docs/brier-lab.md` - reward export, splits, and scoring loop.
5. `agents/thesis-analyst/system.md` - analyst method and honesty rules.

For UI work, also inspect the existing page/component before editing; preserve
the utilitarian forecast-lab feel.

## North Star

Thesis is an open-source, agent-only forecasting lab for automatically
resolvable public-data series. Brier is the forecast-accuracy agent trained and
evaluated on Thesis records.

Optimize for:

- more official-series forecasts that resolve mechanically;
- complete public activity traces;
- run comparison across agents, prompt modes, and pack sets;
- automatic resolution and proper scoring;
- reproducibility over hand-authored polish.

## Hard Constraints

- Do not turn Thesis into a human prediction market.
- Do not add forecasts that require subjective adjudication unless they are
  outside the core Brier training loop.
- Do not hand-edit generated forecast modules except to wire generated output
  into the catalog after review.
- Do not collapse full activity into a summary. Preserve prompt, command,
  stdout/stderr, raw response, parsed/normalized cells, validation, manifest,
  resolution event, and score where available.
- Do not infer `resolutionDate` from cadence. Verify it from an official
  calendar, schedule, release placeholder, or policy-state rule.
- Do not use FRED or news as the final resolution source when an official
  agency source exists. FRED can be a history mirror.
- Do not silently clean failed agent runs into successful ones. Failed traces
  are useful records.

### Choose a resolution date basis

Use the default `release-calendar` basis when an official calendar, schedule,
or release notice states a specific planned day. Use `resolve-by-bound` only
for a reviewed target whose Thesis registration commits a conservative
`expectedReleaseWindow` and outer deadline while an official announcement
authenticates the resolving methodology identity without providing an exact
day. The announcement is not evidence for the lab-committed window or
deadline. A bounded target must set `resolutionDate` to its window's end and
require the attested replay to contain a successful structured exact-URL fetch
event for the registered announcement; never infer a day from cadence.

## Common Tasks

### Work on the experiment core

`thesis_core/` is the new experiment backend. Read
`docs/thesis-core-architecture.md`, `docs/thesis-core-runbook.md` and
`docs/thesis-core-verification.md` before changing it. The Fable-approved build
contract is `docs/thesis-core-plan.md`; keep those reviewed bytes intact and
record later decisions separately.

Install `brier[core]` for the `thesis-core` CLI and read-only API; the existing
site displays it at `/core` through `THESIS_CORE_API_URL`. Use a separate
PostgreSQL schema and ignored `.thesis-core/` artifact storage for local work.
Run database acceptance tests with `THESIS_CORE_REQUIRE_POSTGRES=1`; a skipped
database suite is not acceptance. Regenerate shared contracts with
`python -m thesis_core.schema` and check drift with `--check`.

The core runs alongside the existing publishers. Do not rewrite `records/**`
to migrate it, promote historical replay to prospective evidence, or treat a
verified timestamp without a known accuracy bound as proof of strict ordering.
Production cutover requires a separate release decision.

### Add Or Run Forecasts

Use the thesis analyst runner:

```bash
uv run --extra dev python scripts/run_thesis_analyst.py \
  --series ons.labour.unemployment_rate \
  --period 2026-Q4 \
  --prompt-mode fast \
  --command "/Users/maxghenis/.bun/bin/codex --search exec --ignore-user-config -m gpt-5.5 -c 'service_tier=\"fast\"' --sandbox read-only -C {repo_root} -"
```

Use `--prompt-mode fast` for high-volume public-release batches. Use full
prompt mode when auditing or improving the agent method.

After a successful run:

1. Inspect `manifest.json`, `validation.json`, and `normalized_cells.json`.
2. Keep failed runs in `records/thesis-analyst/...`.
3. Promote successful runs through a generator, not by hand-pasting JSON.
4. Verify the detail page, log page, and Brier reward export if the run is
   wired into the UI.

### Attested local generation lane

Use this lane for registered hard targets that the CI generation lane cannot
serve. A trusted workflow first mints an expiring, single-publication ticket
that seals the target set, nonce, and complete Codex policy. The runner binds
that ticket to its clean introducing checkout, and the operator uploads only a
data bundle; `publish-attested.yml` reconstructs and replays the run before CI
commits and attests any `records/**` changes. Never commit or push the locally
generated record files.

Ticket expiry is clamped to the targets' earliest answer-knowable UTC day
start: the minimum authenticated `sourceBinding.expectedReleaseWindow.start`
or any registered `conditionDeadline`. A ticket therefore dies before either
the conditioning outcome or resolving print can be known. A target without an
authenticated nested window refuses to mint by design: without that stated
boundary the clamp cannot hold, and such series belong to the scheduled CI
lane.

A transcript binding the nonce cannot predate mint, so the nonce proves the
published artifact set was assembled after mint; it does not prove the
forecasting work occurred then. A ticket permits one publication, not one
execution: parallel clean checkouts can run the ticket, select one result
offline, and discard the others without detection. The lane also cannot prove
model authorship or trust the operator's wall clock, and its git-status
cleanliness checks do not see gitignored local inputs. These residual risks are
why published cells carry `local_operator_attested`. The label is disclosure,
not a scoring adjustment; the cells score identically to CI cells.

Mint against exactly one registry series or an exact slug set:

```bash
gh workflow run mint-generation-ticket.yml --ref main \
  -f slugs=hard-target-slug \
  -f prompt_mode=fast \
  -f codex_model=gpt-5.5 \
  -f codex_reasoning_effort=high \
  -f codex_network=true \
  -f attempt=1
```

After the workflow commits the ticket to `main`, use a dedicated clean
worktree at the commit that introduced it. Set `TICKET_PATH` to the path shown
by the mint workflow:

```bash
set -euo pipefail
git fetch origin main
TICKET_PATH='records/tickets/YYYY-MM-DD/YYYY-MM-DD-LOWERCASE_HEX.json'
TICKET_COMMIT=$(git log --full-history --diff-filter=A --format=%H \
  origin/main -- "$TICKET_PATH")
RUN_ROOT=$(mktemp -d)
git worktree add --detach "$RUN_ROOT/checkout" "$TICKET_COMMIT"
cd "$RUN_ROOT/checkout"

WORK_DIR=$(mktemp -d)
uv run python scripts/run_thesis_batch.py --ticket "$TICKET_PATH" \
  | tee "$WORK_DIR/run.log"
BATCH_ABS=$(sed -n 's/^batch manifest: //p' "$WORK_DIR/run.log")
test -n "$BATCH_ABS" && test -f "$BATCH_ABS"
BATCH_PATH=$(BATCH_ABS="$BATCH_ABS" uv run python - <<'PY'
import os
import pathlib

root = pathlib.Path.cwd().resolve()
batch = pathlib.Path(os.environ["BATCH_ABS"]).resolve()
try:
    print(batch.relative_to(root).as_posix())
except ValueError as exc:
    raise SystemExit(f"batch manifest is outside checkout: {batch}") from exc
PY
)
jq '{targets: .targets}' "$TICKET_PATH" > "$WORK_DIR/trusted-targets.json"
uv run python scripts/docket_publication.py stage \
  --bundle-dir "$WORK_DIR/bundle" \
  --batch "$BATCH_PATH" \
  --trusted-targets "$WORK_DIR/trusted-targets.json"
```

Package the staged bundle, then create and push an orphan transport commit
whose root contains exactly `bundle.tar.zst` and `bundle.sha256`. Git plumbing
keeps the dirty local record files out of that commit:

```bash
set -euo pipefail
TICKET_ID=$(jq -r .ticketId "$TICKET_PATH")
tar -C "$WORK_DIR/bundle" -cf "$WORK_DIR/bundle.tar" bundle_manifest.json repo
zstd -q -f "$WORK_DIR/bundle.tar" -o "$WORK_DIR/bundle.tar.zst"
shasum -a 256 "$WORK_DIR/bundle.tar.zst" \
  | awk '{print $1 "  bundle.tar.zst"}' > "$WORK_DIR/bundle.sha256"

HASH_BLOB=$(git hash-object -w "$WORK_DIR/bundle.sha256")
TAR_BLOB=$(git hash-object -w "$WORK_DIR/bundle.tar.zst")
TREE_SHA=$(printf '100644 blob %s\tbundle.sha256\n100644 blob %s\tbundle.tar.zst\n' \
  "$HASH_BLOB" "$TAR_BLOB" | git mktree)
BUNDLE_SHA=$(printf 'Attested generation bundle %s\n' "$TICKET_ID" \
  | git commit-tree "$TREE_SHA")
git push origin "$BUNDLE_SHA:refs/heads/attested/$TICKET_ID"

gh workflow run publish-attested.yml --ref main \
  -f ticket_path="$TICKET_PATH" \
  -f bundle_sha="$BUNDLE_SHA"
```

A failed, expired, or abandoned attempt remains public evidence. Retry only by
minting the next attempt with `supersedes_ticket_id`, `superseded_outcome`, and
a nonempty `superseded_reason`; a consumed ticket cannot be superseded.

### Add comparison runs

Strategy comparisons are published only through the dispatch-only strategy
docket. The workflow selects open, already-published targets with trusted
checkout code, runs the requested ladder and/or median-of-three suite without a
write token, and lets a separate publisher validate the exact data bundle and
regenerate the complete comparison file:

```bash
gh workflow run strategy-docket.yml --ref main \
  -f catalog_slugs=australia-cpi-annual-rate-july-2026 \
  -f auto_select=false \
  -f max_targets=1 \
  -f suite=both
```

`suite=ladder` runs reviewed threshold-ladder elicitation. `suite=median3`
runs three independent fast rollouts and derives their deterministic median
CDF. `suite=both` runs both interventions. The selector rejects unknown,
unpublished, resolved, and release-day targets.

`ladder_prompt_mode` picks the ladder lane's elicitation contract and is
bound into the trusted selection (never a generate-job input). `ladder`
(default) is the v1 contract: identical ladder elicitation plus the
fast-mode sigma discipline — the math step must state "sigma = X" (or the
1.28 z-multiplier) and compare the ladder-implied 80% width against
1.28*sigma. `ladder_v2` (pre-registered 2026-07-10) is the quantile-native
contract: the same ladder elicitation and structural gates, but the
machine-checkable width derivation is the ladder itself — the math step
must list the "P(X <= t) = p" rungs and state the interpolated 10th and
90th percentiles literally, with no parametric sigma disclosure demanded.
Motivation: the 2026-07-10 model wave showed gpt-5.6-luna/-terra producing
complete quantile-inversion derivations while failing the sigma idiom
0/12, versus gpt-5.5's 6/6; running the same models under both contracts
separates capability from idiom compliance. Runs seal their promptMode
into the cell, land as a distinct agent (`thesis.analyst.ladder_v2`), and
are validated mode-aware in both `scripts/spawned_cells_to_ts.py` and
`site/src/__tests__/trace-depth.test.ts`.

Do not run strategy batches locally and push their records or generated
TypeScript to `main`. `scripts/strategy_comparisons.py` is a trusted publisher
generator over the complete indexed strategy corpus; it is not an authority
for bypassing the select → generate → publish boundary. If units differ
between a run and its catalog target, encode the conversion in the trusted
target or generator mapping so comparisons render in the catalog unit.

### Add Or Change Packs

Packs are forecasting interventions, not generic markdown skills. A pack page
should explain what the pack changes in the forecast process and show where it
is used. Do not repeat a meta-definition of packs on every individual pack
page.

Useful pack comparisons show at least:

- no-pack/control run;
- pack-enabled run;
- point and interval shift;
- trace or reasoning difference;
- eventual score difference when resolved.

### Verify Challenge Submissions

External forecasts arrive as PRs adding
`challenge/inbox/<github-login>/<cell>.json`, optionally signed with
Sigstore keyless (a `<cell>.json.sigstore.json` sidecar; see
`docs/challenge-signing.md`). Before publishing any of them, sweep the
inbox:

```bash
uv run --extra challenge python scripts/verify_challenge_signatures.py
```

Unsigned submissions stay valid (schema-checked only; full intake
validation happens at publication) — signing is optional. A
present-but-invalid bundle, a bundle without a Signed Entry Timestamp,
an orphan bundle, a symlink, or any file not shaped `<login>/<cell>.json`
must fail the sweep and must never be published. The sweep always covers
the whole inbox; in `--json` mode stdout is exactly one JSON document of
`thesis_challenge_signature_v1` blocks, which the publish adapter stores
alongside the merge SHA it already records. The signature never
authenticates the `challenger` account — the adapter must separately
require `challenger == github:<PR opener>` (and the matching inbox
directory) and persist PR number, opener, and merge SHA. Submitter
signing distributes proof, never signing authority: publish-side signing
stays CI-only and challenger PRs never touch `records/**`.

### Work On Resolution Or Scoring

Resolution and scoring code should preserve these invariants:

- splits are by `resolutionDate`, not run order;
- unresolved rows have null reward;
- resolved rows link to official observations;
- training cannot see future official outcomes;
- reward rows include provenance hashes and activity-artifact count.

### Bills end to end — series ingestion is part of the pipeline

Founder rule (2026-08-03): a bill metric whose official series is not yet
admitted is a **worklist item, never a stopping point**. "End to end" for
the bills lane means: extraction → metrics → series mapping → **if no
admitted series, ingest it** — Ledger observation history with witnessed
first prints, a resolvable adapter path in `resolve_pending.py`,
integrator-verified anchors per `docs/anchor-verifications.md`, and docket
admission — then preregister the pair and forecast. Never close a bills
lane with "metric lacks an admitted series" as the end state.

The division of labor is fixed:

- `scripts/map_bill_metrics.py` (proposal-only) annotates bill artifacts
  against the docket and the Ledger series catalog and writes ingestion
  requests to `drafts/ledger-ingestion/`. It never changes the docket,
  the catalog, or any record artifact.
- Admission is a reviewed change: adapter (or reuse of an existing
  family), anchors verified from official prints, docket entry, tests —
  the same bar every existing adapter cleared. Requests without a
  passable adapter stay open requests, visibly, not silent drops.

## Verification

For Python runner changes:

```bash
uv run --extra dev ruff check scripts/run_thesis_analyst.py scripts/thesis_records_to_comparisons.py tests/test_thesis_analyst_runner.py tests/test_thesis_analyst_env_hygiene.py
uv run --extra dev pytest tests/test_thesis_analyst_runner.py tests/test_thesis_analyst_env_hygiene.py
```

For site changes:

```bash
cd site
bun run test
bun run build
```

After meaningful frontend changes, verify the affected localhost pages in the
in-app browser.

For docs-only changes, at minimum run:

```bash
git diff --check
```

## Definition Of Done

A change is not done until:

- the relevant docs or generated artifacts are updated;
- validation catches bad cells rather than allowing weak traces through;
- the UI shows the new run/comparison/resolution where appropriate;
- the Brier reward export still builds;
- tests or a clear reason for not running tests are reported.

When in doubt, choose the path that increases the number of automatically
resolvable, fully traced, scored public-data forecasts.

### Records provenance (workflow attestations)

### The records-path guard (run this in every clone)

`records/**` belongs to the allowlisted workflows: they attest every push,
and the provenance audit fails main for any records commit that lacks one.
GitHub cannot enforce this server-side — public source repositories cannot
carry push rulesets at all (verified 2026-07-25: the API refuses with
"Source public repos cannot have push rules"), so the preventive half is a
committed pre-push hook. Activate it once per clone:

```bash
git config core.hooksPath .githooks
```

It refuses any local push that would publish a commit touching
`records/**` — the same commit-level walk the provenance audit runs, so
the guard blocks exactly the pushes the audit would redden main for.
Pushes to `main` are judged on every commit they publish; any other ref
is judged on the branch's own contribution against the main of the
destination that push is actually landing in — fetched at push time and
pinned to an immutable id, so no remote name, URL spelling, or stale
local ref decides it — and a branch rebased over main's attested
recorder commits therefore does not trip it. Pushes the guard cannot
verify (no comparator at the destination, unwalkable history, a shallow
clone) fail closed.
It prints the offending commits and can be overridden deliberately with
`THESIS_ALLOW_RECORDS_PUSH=1` — an override that still lands unattested and
still costs a permanent public waiver. Nine such waivers already exist
(`WAIVED_UNATTESTED_COMMITS`); each one is an admission, not an exemption.
`scripts/test_pre_push_guard.sh` is the guard's regression suite, run by
CI on every push and PR.

Every workflow that pushes `records/**` to `main` attests a canonical
subject naming the pushed commit (`scripts/attest_subject.py`, via the
composite action `.github/actions/attest-records-push`, Sigstore/GitHub
artifact attestations). `scripts/verify_records_attestations.py` — run by
`.github/workflows/records-provenance.yml` on every push and on a daily
audit — fails when any records commit after the enforcement epoch lacks a
valid attestation from an allowlisted publishing workflow on
`refs/heads/main`. The epoch is self-anchoring: the commit that introduced
the verifier script. Under the PR-only regime, a merge commit that leaves
`records/**` byte-identical to at least one post-epoch parent is an exempt
no-op (printed as `NOOP-MERGE`) — that covers both PR merges whose branch
lags the workflows' records pushes and the update-branch merges those PRs
carry. A merge whose records content differs from every in-scope parent,
or whose only TREESAME parents predate the epoch, is a records push like
any other, and a push range whose endpoints disagree about records content
with nothing attestable in between fails closed. Records content itself
never lands through PRs.

This binds each records commit to an allowlisted workflow run that
asserted the push (Sigstore proves the run attested the subject; push
causality follows from the workflow logic, which attests only after its
own ref advancement). It complements the RFC 3161 witness chain (when)
with workflow identity (who/how), and makes the "never push records from
a local checkout" rule mechanical: a local push turns `records-provenance`
red on its next run.

Honest limits: this is a detective control. The verifier, subject builder,
composite action, and workflows live in the same mutable `main` they
guard — an actor with direct write access could alter the control files
before pushing unsigned records, and force-pushes could remove an unsigned
commit before the daily audit sees it. Branch rulesets (no force pushes;
required review or CODEOWNERS on `.github/workflows/**` and the
provenance scripts) are the containment for that class and are a
repository-settings decision. Repository administration remains outside
the control's reach entirely.

Third parties should check records commits by running
`scripts/verify_records_attestations.py` itself — it is era-aware.
Commits signed before the 2026-07-22 transfer (MaxGhenis/brier →
ThesisInstitute/thesis) carry the old slug in their subject bytes and
certificate, and their attestations live in GitHub's OWNER-keyed store
under `--owner MaxGhenis`, not under the current repo; every acceptance
additionally requires the certificate to name the immutable repository
id 1113415529. A manual `gh attestation verify --repo
ThesisInstitute/thesis` therefore works only for post-transfer commits,
and nine 2026-07-2x commits are permanently waived as unattested local
pushes (`WAIVED_UNATTESTED_COMMITS` in the verifier — a public admission
list, separate by design from `waivers.json`'s grandfather sets, which
cover data-shape grandfathering rather than provenance misses).

### Waiver ratchet

`waivers.json` enumerates every grandfather set — pre-cutover v1/v2
registration snapshots, docket series without a committed sourceBinding
template, legacy-incomplete custody roots — and
`tests/test_waiver_ratchet.py` recomputes each population from live state on
every CI run. A population that exceeds its manifest fails the build:
exceptions shrink over time or grow only through a deliberate, reviewable
edit to `waivers.json`, never silently. (Pattern adapted from Axiom's
validation-waiver ratchet.)
