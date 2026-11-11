# The open challenge: external forecasters on the registered docket

*Design, 2026-07-19. **Status (2026-08-23): WITHDRAWN from the public
surface** — operator decision: v1 shipped ahead of its dependencies (intake
was a human-discretion PR merge, signing optional, no scoring ingestion of
`records/challenge/`, no headline-tier path) while the grading loop it
showcases still carries resolver debt. The complete v1 implementation and
the v2 target design (API intake, **required** Sigstore signing, attested
records-path writes) live on branch `challenge-lane-v2`
(`docs/challenge-v2-api-design.md` there); the lane returns when it wins a
roadmap slot and can be operated to its own standard. The two accepted v1
submissions (PavelMakarchuk, khs — both 2026-07-31, grandfathered as
GitHub-identity-attributed, claimed-time tier, reward-excluded) remain
published on their cells and in the witnessed records chain: withdrawal
closed the door, it did not unpublish anyone. The rules and mechanism below
are kept as design history.*

## Why

Accuracy is commodifying — every lab now ships a forecaster, and their
performance claims reduce to "trust the founder." The durable layer is
canonicity: the place where competing systems' claims become comparable
and checkable. Thesis's registered docket, mechanical resolution, and
witnessed chronology are exactly that machinery, so instead of entering
news-question tournaments off-design, we host: any external system may
forecast any open registered target, and its claims inherit the same
custody, the same scoring, and the same chronology tiers as our own
agents. A challenger who shows up validates the venue; a challenger who
wins earns a claim nobody can dispute — including us.

## Rules (v1)

1. **Question set.** The open registered docket, nothing else. Every
   target auto-resolves from a registered official source; no question is
   ever resolved by human judgment.
2. **Who may enter.** Any system. Participants self-declare
   `systemType` (`ai` | `human` | `hybrid`); the headline challenge is
   AI-vs-AI. (Current build: external leaderboard rows are labeled with
   the declaration; grouped segmentation ships with `records/challenge/`
   scoring ingestion.) Identity = the GitHub account that submits; one
   account is one challenger.
3. **One shot per target.** A challenger's first valid submission for a
   dataPointId is final; later submissions for the same pair are
   rejected. This matches our own agents' one-registered-run-per-lane
   discipline and blocks last-minute-information advantage. (Horizon-
   matched multi-update scoring is a possible v2; it must never change
   v1 scores retroactively.)
4. **Chronology is inherited, not negotiated.** A submission enters the
   records chain through the attested intake path and is externally
   witnessed like any records commit. The v5 tiers then apply verbatim:
   witnessed before the observation → headline-eligible;
   claimed-time-only → published below the fold; on or after the
   observation → violated. No special cases. (Current build: the merged
   inbox path yields claimed-time chronology — honestly labeled, reward-
   excluded; headline eligibility requires the records-path intake.)
5. **Distributions, not vibes.** The v1 intake requires all three:
   point estimate, 80% central interval, and the full seven-rung
   quantile grid (p = 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, strictly
   increasing values), scored as a piecewise-linear CDF exactly like
   agent-native distributions. External scores are labeled by the
   `externalSubmission { challenger, systemType }` field carried on
   every run entry and reward row; `distributionProvenance` keeps
   describing the distribution's own construction (`agent_reported`
   for a submitted grid), exactly as for agent runs.
6. **No trace requirement — visibly.** Our agents publish full reasoning
   traces; challengers may not want to. External cells are exempt from
   the trace-depth rubric and the site renders their submission record
   under a "submission record (no reasoning trace required)" label. The
   transparency gap stays legible instead of being papered over.
7. **Scoring.** Identical to agents: exact CRPS on the materialized CDF,
   normalization only by pre-registered ledger dispersion, paired
   persistence comparison where a baseline exists. No challenger-specific
   scoring code paths.
8. **No prizes (v1).** Recognition is the leaderboard and the custody of
   the claim. Money changes the abuse calculus; it can come later with
   its own design pass.

## Mechanism

Challengers never touch trust surfaces:

- A challenger opens a PR adding one JSON file under
  `challenge-inbox/` (schema below; template in that directory). The
  inbox is data-only staging — nothing reads it at build or score time.
- The **intake workflow** (privileged, to be reviewed before landing)
  validates the file with `scripts/validate_challenge_submission.py`
  against trusted-HEAD code: schema, target exists and is an open
  registered target, no prior submission for the (challenger, target)
  pair, finite numbers, coherent interval/quantiles.
- On pass, the workflow writes the canonical submission record under
  `records/challenge/YYYY-MM-DD/…` via the same commit → attested push →
  recorder-witness path every records writer uses, and closes the PR
  with a receipt (record path + commit). On fail, it comments the
  precise refusal and closes. Challenger PRs are never merged; the
  privileged copy is the record.
- The site build reads `records/challenge/` only: external cells join
  scoring with `agent: <challengerId>` and `participation: external`.

Sybil note: many-accounts entry is visible by construction (every
submission names its account) and buys nothing under one-shot-per-target
plus no prizes; revisit with any prize design.

## Submission schema (`thesis_challenge_submission_v1`)

```json
{
  "schemaVersion": "thesis_challenge_submission_v1",
  "challenger": "github:preseen-team",
  "systemType": "ai",
  "systemName": "Preseen Chestnut",
  "dataPointId": "us.dol.initial_claims.sa.week_2026-07-25",
  "pointEstimate": 214.0,
  "ciLow": 200.0,
  "ciHigh": 229.0,
  "quantiles": [
    {"p": 0.05, "value": 196.0},
    {"p": 0.1, "value": 200.0},
    {"p": 0.25, "value": 207.0},
    {"p": 0.5, "value": 214.0},
    {"p": 0.75, "value": 221.0},
    {"p": 0.9, "value": 229.0},
    {"p": 0.95, "value": 233.0}
  ],
  "generatedAtUtc": "2026-07-20T14:00:00Z",
  "notes": "optional, ≤500 chars, rendered verbatim with the cell"
}
```

`quantiles` is required: exactly the seven rungs above
(p = 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95) with strictly increasing
values — the intake (`scripts/ingest_challenge_submissions.py`) rejects
anything else. One shot per (challenger, dataPointId): the first
content accepted onto the mainline (first-parent order, so merge-borne
files count at their merge) is canonical forever, keyed
case-insensitively across the whole inbox history (GitHub logins are
case-insensitive). Edits, renamed rewrites, delete-and-readd
replacements, and surplus divergent copies all reject while the
canonical forecast survives; a byte-identical rename carries the
forecast unchanged. `generatedAtUtc` is the challenger's
claim; under the current inbox intake the score carries claimed-time
chronology (labeled, reward-excluded). The records-path intake will
bind chronology to a witnessed commit instead.

## Build plan

| Piece | Status |
|---|---|
| Design (this doc) | done |
| `scripts/validate_challenge_submission.py` + tests | retired — deleted with the 2026-07-20 hold; the shipped inbox path validates via `scripts/ingest_challenge_submissions.py` |
| Intake workflow (`challenge-intake.yml`) | staged — cross-model review first (privileged writer + PR-triggered = the risky pair) |
| Attestation allowlist entry for the intake workflow | with the workflow |
| Site: external flag on scored rows + leaderboards (`externalSubmission` through run entries → reward rows → agent leaderboard) | done 2026-08-07 — accepted inbox submissions already score through `getForecastRunEntries`, so the flag rides the identical pipeline |
| Site: scoring ingestion of `records/challenge/` (replaces the hand-wired augment map + `site/src/data/challenge.ts` registry with generated output) | open — follows the intake workflow |
| `/challenge` page: rules, how to enter, live submissions + records digests | done 2026-08-07 — scores surface on `/calibration` once targets resolve |
| Outreach (Preseen, Mantic, FutureSearch, Metaculus bot authors) | after the lane is live-fired end to end |
