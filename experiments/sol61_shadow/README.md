# Sol 6.1 shadow forecasts (October 2026)

An unpublished model comparison. GPT-6.1 Sol forecasts the open registered
targets that Thesis has already published primary forecasts for, using the
production `thesis.analyst` prompt (see Prompt below). Its runs are validated
by the production runner and scored against the same Chronicle first prints
once the targets resolve.

These are **not Thesis forecasts**. They never enter `records/**`, the docket,
the site or the Brier reward export. The publication gate
(`docs/forecast-publication-policy.md`) admits only CI or attested runs with
complete Codex execution receipts. The runner records these runs as saved
responses (`--response-file`), and the gate refuses that execution format by
design.

## Why it exists

Spare weekly quota on the ChatGPT-subscription Codex lanes (October 6–9,
2026) bought a few hundred GPT-6.1 Sol runs at no marginal cost. A shadow
comparison is the use of those runs that stays inside the repository's
publication rules: it measures a newer model on live targets without
creating a second forecast record.

## Design

**Targets.** `targets.json` freezes every target with a successful published
primary run whose registered release window opens on or after 2026-10-13:
71 targets, read from the committed batch manifests at checkout `17b62a1a`.
Strategy suites (ladder, median3) are excluded; they attach to a primary
rather than defining one. The window start comes from the registration's
nested `sourceBinding.expectedReleaseWindow`, falling back to the top-level
window and then `resolutionDate`.

**Prompt.** Each prompt is the runner's own `--print-prompt` output for the
target's committed batch context, in the arm's prompt mode, under a short
wrapper. It is the prompt for a run without the tool-evidence MCP server, the shape
every primary generated before 2026-09-20 received. CI runs since #260
(2026-09-20) add a "Captured tool evidence" section for an MCP server these
runs do not have; 6 of the 67 validatable targets have primaries from
after that change. The wrapper (`shadow.py:WRAPPER`) says there is no repository, forbids any
Thesis or Brier surface (site, API, GitHub, records), and asks for the bare
JSON object. `prompts/index.json` pins the SHA-256 of every prompt sent.

**Arms.** All three run `gpt-6.1-sol` at ultra reasoning effort through
Subfleet (`--task research|build --tier hard`). Each differs from `web` in
one respect.

| Arm | Prompt mode | Sandbox | Tools | Rollouts |
|---|---|---|---|---|
| `web` | fast | read-only | hosted web search (the CI default lane) | 3 |
| `net` | fast | workspace-write with outbound network | web search plus `curl`, with the runner's `--codex-network` fetch-honesty note | 3 |
| `full` | full | read-only | hosted web search | 3 |

Every rollout is an independent job, so each arm's median CDF
(`scripts/median_rollout_ensemble.py:median_distribution`) mirrors the
production median3 strategy. The design grew twice, each time before any
affected job ran. The `full` arm was added after the first pre-registration
commit, whose `web` and `net` prompts it left byte-identical. Rollouts 2 and 3
of `net` and `full` were added on 2026-10-07, after wave 1, when spare Codex
quota allowed a symmetric three-by-three design.

**Eligibility.** A run counts only if all four hold:

1. the production runner validates its response (`validation.ok`);
2. its Subfleet job finished before 00:00Z on the target's window-start day;
3. its trace shows no search, opened page or shell command touching a Thesis
   surface (`CONTAMINATION_RE`);
4. the attempt's recorded launch argv ran `-m gpt-6.1-sol`.

Ineligible runs stay in `results.json` with the reason; nothing is dropped
silently.

**Targets the runner cannot validate here.** The runner validates a
resolve-by-bound target only inside a generation ticket, so a saved response
for one always fails (`spawned_cells_to_ts.py`: "resolve-by-bound target
requires generation ticket context"). The pilot's SPM run showed this. Batches
after the pilot leave out the four such targets (the CRP and SPM conditional
pairs), leaving 67 targets. The pilot run stays in `results.json` as an
ineligible record.

**Network-arm validation.** The runner refuses `--codex-network` outside a
live Codex run, and the flag changes only the prompt text and the Codex
invocation. `net` responses are therefore validated without it, so the
`prompt.md` in their run directories is the non-network variant; the prompt
actually sent is the one pinned in `prompts/net/`.

## Comparisons (fixed before any run)

For each resolved target with an observation whose `source_record_id` equals
the target's `dataPointId` and whose unit equals the target unit:

- exact CRPS of each eligible run's materialized CDF, of the `web` median3,
  and of the published primary's CDF (`shadow.py:crps_numeric_cdf`, a
  line-for-line port of the site's `scoreNumericCdfDistribution`);
- PIT, 80% interval coverage and absolute error of the median;
- per-target CRPS ratio against the primary, summarized by geometric mean
  (the site's leaderboard statistic) and win share.

## Confounds to read the results with

- **Information time.** The primaries ran between June and early October
  2026; these runs are made October 6–9. Sol therefore sees more recent
  prints, so a CRPS advantage over the primary is not a pure model effect.
  `web` against `net` and rollout against rollout are same-time
  comparisons.
- **Single pass.** Production primaries ran draft, pre-submit review and
  revision. These runs are single-pass.
- **Prompt mode.** 55 primaries ran in fast mode and 16 in full mode; the
  `web` and `net` arms run fast mode on all 71, and `full` runs full mode on
  all 71.
- **Harness.** Codex CLI 0.159.0 on a subscription login through Subfleet,
  against CI's pinned Codex CLI 0.144.0 on an API key, where the batch runs
  the runner's default model (`gpt-5.5` today) unless dispatched with
  another. Any harness difference is confounded with the model difference.
- **Chronology evidence.** The finish time is Subfleet's local clock, and the
  outside witness is GitHub's record of when the branch was pushed. That is
  weaker than the RFC 3161 witness the records chain carries.
- **Contamination audit.** String matching on the event stream. It catches a
  search or command that names a Thesis surface; it cannot see what a web
  search result page contained.

## Running it

```bash
python3 experiments/sol61_shadow/shadow.py freeze --cutoff 2026-10-13
python3 experiments/sol61_shadow/shadow.py prompts
python3 experiments/sol61_shadow/shadow.py batch --arm web --rollout 1
python3 experiments/sol61_shadow/shadow.py submit --label sol61-shadow-web-r1
python3 experiments/sol61_shadow/shadow.py collect
python3 experiments/sol61_shadow/shadow.py score --ledger <chronicle official_observations.jsonl>
```

Batch manifests, Subfleet receipts and raw deliverables live outside the
repository in `~/ThesisInstitute/_sol61-shadow/` (override with
`SOL61_SHADOW_OPS`). `collect` copies each finished run's response, redacted
event stream (`scripts/tool_evidence.py` redaction, gzipped) and runner
validation directory into this folder and records it in `results.json`.
`submit` derives its request id from the batch label, so re-submitting a
manifest settles the same jobs rather than duplicating them.
