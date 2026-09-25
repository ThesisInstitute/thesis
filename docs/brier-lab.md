# Brier Lab

Brier is the forecast-accuracy agent trained and evaluated on Thesis records.
Thesis supplies the environment: generated public-data forecast specs,
agent-only runs, immutable activity artifacts, configured official resolution,
and proper scores.

Read [`docs/thesis-vision.md`](thesis-vision.md) for the strategic contract:
Thesis is the agent-only, open-source, autoresolving public-data lab; Brier is
the agent optimized inside it for forecast accuracy.

Read [`docs/thesis-architecture.md`](thesis-architecture.md) for the rebuild
blueprint: ledger-first targets, typed source adapters, benchmark priors,
strategy runs, review/judge separation, append-only storage, and Brier reward
exports.

Read [`docs/thesis-migration.md`](thesis-migration.md) for the current schema
mapping and source-of-truth cutover path.

## Reward

The reward export is `/brier/reward.json` (schema `brier_reward_export_v3`).

Each row is one recorded forecast run:

- `runId`, `predictionId`, `specId`, and `specVersionId`
- agent/model/run label metadata
- deterministic split
- resolution date and run horizon
- reward value, currently `-normalizedCrps` when a ledger scale is available
- score components: CRPS, normalized CRPS, absolute error, 80% interval
  coverage
- distribution provenance (`agent_reported` or `interval_seeded`) and the
  immutable transform version used to materialize the scored CDF
- provenance hashes and activity-artifact count

Higher reward is better because normalized CRPS is negated. Unresolved rows
have `reward.value = null` until the configured official resolver records an
official fact; resolved rows also keep a null reward when no safe ledger scale
is available. A non-null `reward.value` always satisfies the same usable-scale
rule the aggregates use, and always equals `-components.normalizedCrps`.

Normalization uses the sample dispersion of successive changes in same-series,
same-unit PolicyEngine Ledger observations available when the target was
registered. Legacy targets use the primary run seal as that cutoff. The scale is
shared by every run on a `dataPointId`; forecast-authored `historicalContext` and
forecast interval widths are never normalization inputs. With fewer than three
pre-cutoff ledger observations (or zero usable dispersion), the raw CRPS and
absolute error remain public, while normalized CRPS, normalized absolute error,
sharpness, reward, leaderboard means, and paired skill are null or exclude the
row.

Zero usable dispersion is judged relative to the history's own magnitude: a
scale at or below `1e-12` of the largest absolute pre-cutoff value
(`NORMALIZATION_SCALE_RELATIVE_FLOOR`) is unavailable. Exactly linear decimal
histories have zero step dispersion, but binary floating point leaves a residue
that grows with the values. `1.814, 1.805, 1.796` left `1.57e-16`, which put a
`-7.08e13` reward in the 2026-09-23 export. The same shape near 215 leaves
`2.0e-14`, which a fixed `Number.EPSILON` bound let through. The floor sits well
above that residue for any realistic history length and matches the 12
significant digits every materialized distribution keeps.

Same-series membership comes from exact target registrations and each
observation's matching contract hash and source-binding projection;
`dataPointId` is opaque and is never parsed for a series-looking prefix. Only
an explicit, pinned tuple can supply identity for a legacy observation that
predates those contracts.

Persistence baselines are generated only for chronology-verified scored
primary targets. Their point is the last same-series observation archived in
the PolicyEngine Ledger at the primary run's `recordedAt` cutoff, and their
80% interval uses the 80th percentile of absolute realized one-step changes
in that ledger history. At least two pre-cutoff ledger observations are
required. Targets without that history carry an explicit unavailable baseline
record; forecast-supplied `historicalContext` is never a baseline input.

A baseline whose materialized CDF fails the scorer's own validator is also
unavailable, and the record names the validator errors. A flat history gives
a zero-width interval. The transform spreads it only `1.5e-9` either side,
and from `|value| >= 10` the 201-point grid collapses under
12-significant-digit rounding. Below that magnitude the near-point-mass
baseline stays valid and available.

## Leaderboard

The leaderboard ranks forecasters, lowest first, by
`pairedNormalizedCrpsDelta` (`leaderboardRankingStatistic` in
`site/src/data/brier-lab.ts`). The statistic is built in three steps:

1. On each target that has both a persistence baseline and a usable ledger
   scale, average the forecaster's normalized CRPS across its runs on that
   target.
2. Subtract the baseline's normalized CRPS from that average.
3. Average the result across targets.

Below 0 beats persistence. `pairedNormalizedTargets` counts the targets that
enter the statistic. `pairedNormalizedCrpsDeltaStdError` is the per-target
standard error, which is null below two targets. Ties fall back to the
unpaired mean reward. The same statistic for primary runs is the
`pairedComparison` headline on `/calibration`.

The ranking statistic must stay proper: in expectation, reporting the honest
distribution must minimize it on every target. It is linear in every CRPS.
Its weights (one over the scale, the target count and the run count) are
fixed before the outcome, and the report cannot touch them. So it inherits
the propriety of CRPS for any number of targets. Averaging within a target
first keeps repeat runs on one target from outweighing the others.

Three statistics fail this test, and the leaderboard must not rank by them:

| Statistic | Why it is improper |
|---|---|
| Geometric mean of per-target raw CRPS ratios (ranked by until 2026-09-24) | It minimizes `E[log CRPS]`. Under a Gaussian belief its optimal "80%" interval is about 0.39 of the truthful width, whatever the baseline. |
| Ratio of means | Divides by the baseline's realized CRPS, which reweights outcomes. Proper only in the large-n limit. |
| Mean of ratios | Same defect as the ratio of means. |

`site/src/__tests__/leaderboard-propriety.test.ts` runs the real CRPS kernel
through the real leaderboard function. It checks the statistic over one
target, two targets and repeat runs. It also convicts the three statistics
above on the same harness.

`pairedWinRate` is the share of paired targets where the forecaster's raw CRPS
is strictly below persistence. It is descriptive only, because a win rate is
not a proper score. Unpaired means are descriptive too.

Forecasters choose their own targets, so two leaderboard rows are usually
scored on different target sets. Each row is paired with persistence on its
own set. `headToHead` compares forecasters directly, and only on the targets
both scored with a usable scale. Each row gives the mean per-target
normalized-CRPS difference (left minus right, left ranked higher), the
shared-target count and a standard error.

### Interval reports

Most runs report a point and an 80% interval, which the `interval_anchor_v1`
transform turns into the scored CDF. CRPS is proper for the CDF it scores.
The transform, however, is not proper for the interval itself. Under a
`N(0, 1)` belief, the expected-CRPS-optimal "80%" half-width is about 0.85
of the truthful one. That is roughly 72% true coverage, for an expected-score
gain of about 0.7%.

The leaderboard propriety test pins this figure, so any change to the
transform has to revisit this disclosure.

## LLM Judges

The Thesis Log carries judge summary counts and a link to the full judge export.
`/forecasts/judges.json` and the Brier reward export carry the auxiliary judge
records:

- trace-quality judges score public reasoning for base rates, source
  grounding, resolution clarity, uncertainty calibration, mechanisms,
  counterarguments, and forecast coherence
- pairwise judges compare two runs on the same target, such as primary vs
  pack-informed or prior-informed runs
- post-resolution judges tag likely failure modes after official facts arrive

These records are explicitly `rewardEligible: false`. They are process
diagnostics for triage and prompt/pack iteration. Before any judge signal can
guide training, it must be checked against held-out proper scores; the reward
objective remains resolved forecast accuracy.

## Pre-submit Review

Some runs can use an explicit draft-review-revise workflow before publication.
The reviewer sees only the draft, target contract, and pre-resolution public
evidence; it cannot silently edit the forecast. The forecaster may revise the
final submission, but the draft response, reviewer critique, revision prompt,
and public disposition are all preserved as activity artifacts and compact
`preSubmitReview` metadata.

Only the final forecast receives reward. Review status is exported so Brier can
compare reviewed and unreviewed workflows by held-out CRPS before making review
part of the default agent policy.

## Splits

Rows are split by `resolutionDate`, not by creation time:

- `train`: resolved before 2026-07-01
- `validation`: resolved from 2026-07-01 through 2026-12-31
- `test`: resolved on or after 2027-01-01
- `unresolved`: no official fact yet

Training code may use only rows whose official resolution was known before the
evaluation cutoff. That keeps Brier from learning from future observations.

## What This Enables

The export is deliberately simple enough for:

- offline prompt and pack ablations
- supervised traces-to-forecast experiments
- RL policies that choose tools, packs, source weighting, and distributions
- agent leaderboards by domain, horizon, agency, or pack set
- leakage audits before any model-training run

The public trace is the scientific record: prompts, tool calls, fetched data,
raw response, normalized forecast, validation, resolution, and score.

## From Pack to Default

Pack ablations are the test harness for forecasting practices. If an
intervention reliably improves held-out reward and survives leakage/robustness
checks, its portable lesson should be promoted into the default Brier or
thesis.analyst policy. The pack then becomes historical evidence or a
domain-specific optional source, while the promoted rule is tracked by the next
agent version and prompt/tool-policy hashes.

See [`docs/pack-promotion.md`](pack-promotion.md) for the promotion gate.
