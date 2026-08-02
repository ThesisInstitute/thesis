# Skill — does conditioning on the bill improve the forecast?

Generated 2026-07-31T10:56:07-04:00. **N = 2520 scored runs, 12 units.** Sweep completion: 2520/2520 cells (100.0%).

`skill_vs_unconditioned` = CRPS(conditioned) - CRPS(`none`), per `policy_context` level, at the reference configuration for the other four dimensions (`{'elicitation': 'point_ci_json', 'pipeline': 'single_pass', 'model': 'claude-sonnet-5', 'magnitude': 'actual'}`). **Negative = improvement.** CRPS is normalised by the SD of each unit's own supplied 60-month history, frozen in `ground_truth.json` at pre-registration; it is never normalised by the model's own interval width.

## Headline

**Conditioning on the bill does not improve the forecast.** No `policy_context` level has a 95% bootstrap CI for `skill_vs_unconditioned` lying entirely below zero. This is the pre-registered **skill null** and it is reported, not buried. It does not mean the statutory text is irrelevant to SNAP participation; it means that at this horizon (30-33 months, forced by the ~2-year publication lag of this Census/FNS series) the policy signal is a small share of total forecast error, exactly as the pre-registration warned.

## skill_vs_unconditioned by policy_context level

| level | n_units | mean skill (normalised CRPS) | 95% CI | median skill | 95% CI | mean skill (persons) | units improved | sign-test p | verdict |
|---|---|---|---|---|---|---|---|---|---|
| `summary` | 12 | 0.3063 | [-0.0907, 0.7405] | 0.0351 | [-0.1278, 0.6507] | 23218 | 5/12 | 0.7744 | **NO DETECTABLE SKILL (CI includes 0)** |
| `operative_only` | 12 | 0.2209 | [-0.0702, 0.5973] | -0.0303 | [-0.0752, 0.1690] | 9096 | 7/12 | 0.7744 | **NO DETECTABLE SKILL (CI includes 0)** |
| `purpose_only` | 12 | 0.1989 | [-0.1166, 0.5389] | 0.1826 | [-0.2737, 0.5110] | 16341 | 4/12 | 0.3877 | **NO DETECTABLE SKILL (CI includes 0)** |
| `operative_plus_purpose` | 12 | 0.4630 | [-0.0868, 1.1082] | 0.1172 | [-0.1328, 0.6058] | 64620 | 4/12 | 0.3877 | **NO DETECTABLE SKILL (CI includes 0)** |

## Accuracy and calibration by level (context for the numbers above)

| level | n_units | n_runs | mean CRPS (persons) | mean CRPS (normalised) | mean SD of CRPS across the 5 repeats | 80% coverage | mean PIT | mean width (persons) | mean width (normalised) |
|---|---|---|---|---|---|---|---|---|---|
| `none` | 12 | 60 | 131,963 | 0.873 | 45017 | 0.500 | 0.545 | 309,000 | 2.202 |
| `summary` | 12 | 60 | 155,182 | 1.180 | 39737 | 0.417 | 0.595 | 267,000 | 1.875 |
| `operative_only` | 12 | 60 | 141,059 | 1.094 | 17972 | 0.317 | 0.613 | 233,833 | 1.549 |
| `purpose_only` | 12 | 60 | 148,304 | 1.072 | 21487 | 0.283 | 0.676 | 289,500 | 2.082 |
| `operative_plus_purpose` | 12 | 60 | 196,583 | 1.336 | 18274 | 0.283 | 0.636 | 242,833 | 1.632 |

Calibration reading (EXPLORATORY, per the pre-registration): nominal 80% coverage is 0.80 and a calibrated mean PIT is 0.50. A mean PIT near 0 or 1 means the intervals sit systematically on one side of the realised value.

**Every level is badly over-confident.** Observed 80% coverage ranges 0.283-0.500 against a nominal 0.80: these are not 80% intervals at this horizon. This is EXPLORATORY (PIT calibration was declared exploratory in advance), and it is the same story the skill table tells — the dominant error at a 30-33 month horizon is not the policy signal.

Run-level coverage vs the unconditioned baseline (EXPLORATORY; two-proportion z-test from `brier/experiments/analyze.py`, whose p-values are **bucketed**, not exact):

| level | n_runs | coverage | coverage(`none`) | difference | p (bucketed) |
|---|---|---|---|---|---|
| `summary` | 60 | 0.417 | 0.500 | -0.083 | 0.200 |
| `operative_only` | 60 | 0.317 | 0.500 | -0.183 | 0.050 |
| `purpose_only` | 60 | 0.283 | 0.500 | -0.217 | 0.050 |
| `operative_plus_purpose` | 60 | 0.283 | 0.500 | -0.217 | 0.050 |

## Per-unit skill (normalised CRPS difference vs `none`)

| unit | `summary` | `operative_only` | `purpose_only` | `operative_plus_purpose` |
|---|---|---|---|---|
| snap.ca.2023-12 | 0.2033 | 0.1828 | 0.7466 | 0.1691 |
| snap.ca.2024-03 | 1.0981 | 0.1552 | 0.1485 | 3.0816 |
| snap.fl.2023-12 | -0.2058 | -0.0511 | 0.0801 | 0.0209 |
| snap.fl.2024-03 | 0.0038 | -0.0095 | 0.2167 | 0.1906 |
| snap.ny.2023-12 | -0.0249 | -0.0755 | 0.2753 | -0.0074 |
| snap.ny.2024-03 | 0.1400 | 0.1458 | 0.2582 | 0.2002 |
| snap.oh.2023-12 | -0.0499 | -0.0748 | -0.1553 | 0.0654 |
| snap.oh.2024-03 | -0.2638 | -0.2935 | -0.4333 | -0.2583 |
| snap.pa.2023-12 | 1.8106 | 1.3569 | 1.2886 | 2.2118 |
| snap.pa.2024-03 | 1.5244 | 1.6421 | 1.0341 | 1.0114 |
| snap.tx.2023-12 | -0.6267 | -0.2616 | -0.6799 | -0.6891 |
| snap.tx.2024-03 | 0.0664 | -0.0658 | -0.3921 | -0.4401 |

