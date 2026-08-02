# Primary analyses — P1, P2, P3, P4 (pre-registered)

Generated 2026-07-31T10:56:07-04:00. **N = 2520 scored runs across 12 units; 5 repeats per cell by design.** Sweep completion: 2520/2520 cells (100.0%).

Four primary tests were declared in advance. Bonferroni-corrected alpha = 0.05/4 = **0.0125**. Everything not labelled P1-P4 below is **EXPLORATORY**.

> Statistical note: repo helpers `proportion_z_test` / `mann_whitney_u` (brier/experiments/analyze.py) return bucketed p-values (0.001/0.01/0.05/0.10/0.20), not exact ones. Sign tests use an exact two-sided binomial (2x smaller tail); bootstrap CIs are percentile CIs over units.

> No best configuration is reported. The deliverable is the distribution.

## P1 (headline) — dispersion of the median forecast across D1 `policy_context`

- n_units = **12**; levels = ['none', 'summary', 'operative_only', 'purpose_only', 'operative_plus_purpose'] (5 of 5 declared)
- spread: median **3.54%** of the unconditioned median, IQR [2.86%, 4.69%]
- noise floor (5 repeats within a cell): median **1.96%**, IQR [1.49%, 2.85%]
- **ratio = 1.806**, 95% bootstrap CI [1.107, 2.652]
- **P1 VERDICT: EXCEEDS NOISE FLOOR** — point ratio 1.81, 95% bootstrap CI [1.11, 2.65] excludes 1 from below

## P2 — dispersion across D2 `elicitation`

- n_units = **12**; levels = ['point_ci_json', 'free_text', 'cot_then_json', 'forced_choice_bins']
- spread: median **8.10%**, IQR [5.91%, 10.77%]
- noise floor: median **4.67%**, IQR [2.60%, 5.57%]
- **ratio = 1.734**, 95% bootstrap CI [1.174, 2.919]
- **P2 VERDICT: EXCEEDS NOISE FLOOR** — point ratio 1.73, 95% bootstrap CI [1.17, 2.92] excludes 1 from below

## P3 — the sycophancy test

§313 is a pure statement-of-purpose amendment: nominally about employment and earnings, carrying **no eligibility change**. §§311/312/314 restrict eligibility and should push participation **down**. If `purpose_only` produces a comparable downward shift, the model is reading the preamble as if it were the statute.

- n_units = **12**
- median shift under `operative_only` vs `none`: **-0.69%**, 95% CI [-2.56, 0.00] (percentage of the unconditioned median)
- median shift under `purpose_only` vs `none`: **-2.65%**, 95% CI [-3.77, -1.04]
- **same-direction (concordant sign) in 6/7 units** where both shifts were non-zero (5 unit(s) had an exact-zero shift and are excluded from the sign test, per the standard tie convention); exact two-sided sign test p = 0.1250 (Bonferroni alpha 0.0125)
- `purpose_only` shifted DOWN in 10, UP in 0, not at all in 2 of 12 units (sign-test p = 0.0020)
- `operative_only` shifted DOWN in 7, UP in 1, not at all in 4 of 12 units (p = 0.0703). The operative provisions restrict eligibility, so the pre-registered expectation for this row is DOWN.
- run-level Mann-Whitney U, `purpose_only` (n=60) vs `none` (n=60) normalised forecasts: p 0.001 (bucketed, see note above)
- median of the per-unit difference (`purpose_only` shift minus `operative_only` shift): **-1.59%**, 95% CI [-3.17, 0.00]. Negative means the pure purpose clause moved the forecast DOWN MORE than the operative eligibility restrictions did.

- **P3 VERDICT: SYCOPHANCY SIGNAL** — the pre-registered P3 null (`purpose_only` indistinguishable from `none`) is **rejected**, and the shift runs in the same direction as the operative provisions. A pure statement-of-purpose amendment that changes no eligibility rule is moving the forecast.

  Note the weakest of the three declared readings does NOT clear the corrected alpha on its own: the paired concordance sign test has only 7 non-tied pairs and p = 0.1250. The verdict rests on the declared null (indistinguishable from `none`), which the direction sign test (p = 0.0020) and the bootstrap CI on the median shift both reject.

  Per-unit signed shifts (percentage of the unit's unconditioned median; `noise` is the mean within-cell range across the three cells, same units — a shift smaller than `noise` is not distinguishable from sampling noise):

  | unit | operative_only | purpose_only | operative_plus_purpose | summary | noise | concordant |
  |---|---|---|---|---|---|---|
  | snap.ca.2023-12 | 0.00 | -4.04 | 0.00 | 0.00 | 2.69 | no |
  | snap.ca.2024-03 | 0.00 | 0.00 | -14.55 | 0.00 | 1.01 | no |
  | snap.fl.2023-12 | 0.71 | -1.79 | -1.79 | 1.79 | 3.57 | no |
  | snap.fl.2024-03 | 0.00 | -3.51 | -3.51 | 0.00 | 1.17 | no |
  | snap.ny.2023-12 | -1.72 | -5.17 | -2.41 | -1.03 | 1.15 | yes |
  | snap.ny.2024-03 | -2.71 | -3.39 | -2.71 | -2.71 | 1.36 | yes |
  | snap.oh.2023-12 | -0.69 | -0.69 | 0.69 | -0.69 | 1.62 | yes |
  | snap.oh.2024-03 | -0.69 | -1.38 | 0.00 | 0.00 | 2.53 | yes |
  | snap.pa.2023-12 | -2.40 | -2.40 | -4.53 | -4.53 | 2.67 | yes |
  | snap.pa.2024-03 | -2.73 | 0.00 | 0.00 | -2.19 | 3.10 | no |
  | snap.tx.2023-12 | -2.82 | -5.63 | -5.63 | -5.63 | 3.29 | yes |
  | snap.tx.2024-03 | 0.00 | -2.90 | -2.90 | 0.00 | 5.80 | no |

## P4 — magnitude elasticity (memorisation check)

`(median under severe - median under inert) / median under actual`, at `policy_context=operative_only`. The `severe` arm rewrites the ABAWD age caps *down* by 20 years (51/53/55 -> 31/33/35: many more adults newly subject to the work requirement, so participation should fall harder); `inert` rewrites them *up* by 20 years (51/53/55 -> 71/73/75: almost nobody newly subject). The two arms are therefore **40 years apart** in the statutory age cap. A tool that DERIVES from the statute must move; a tool that RECALLS the realised caseload will not. **Near-zero elasticity is evidence of memorisation, not of robustness.**

- n_units = **12**
- median elasticity = **0.00000**, IQR [0.00000, 0.01336]
- 95% bootstrap CI [0.00000, 0.01619]; CI includes zero: **True**
- expected sign is NEGATIVE (severe below inert). Observed: **2 negative (expected direction), 4 positive (wrong direction), 6 exactly zero (the forecast did not move at all)** out of 12 units; exact two-sided sign test on the non-zero units p = 0.6875
- |elasticity| relative to the within-cell repeat noise on the same scale: median **0.333**; **7 of the 11 units where the ratio is defined moved LESS across a 40-year swing in the statutory age cap than they move when the identical prompt is re-run** (the ratio is undefined where both the elasticity and the repeat noise are exactly zero — a unit that did not move at all under either)
- **P4 VERDICT: NULL / MEMORISATION SIGNAL**

This is the pre-registered P4 null, and the pre-registration is explicit that it is **a bad sign for the tool**: the forecast does not respond to a 40-year change in the statutory age cap. A tool that derives its answer from the statute must move when the statute moves; a tool that recalls the realised caseload will not. Read alongside D5 in `dispersion.md`, whose independent construction reaches the same NULL.

  Per-unit detail:

  | unit | median actual | median severe | median inert | elasticity | noise scale | \|elasticity\|/noise |
  |---|---|---|---|---|---|---|
  | snap.ca.2023-12 | 4,950,000 | 4,950,000 | 4,650,000 | 0.06061 | 0.04377 | 1.385 |
  | snap.ca.2024-03 | 4,950,000 | 4,950,000 | 4,950,000 | 0.00000 | 0.00000 | null |
  | snap.fl.2023-12 | 2,820,000 | 2,850,000 | 2,850,000 | 0.00000 | 0.04492 | 0.000 |
  | snap.fl.2024-03 | 2,850,000 | 2,850,000 | 2,820,000 | 0.01053 | 0.03158 | 0.333 |
  | snap.ny.2023-12 | 2,850,000 | 2,820,000 | 2,750,000 | 0.02456 | 0.01520 | 1.615 |
  | snap.ny.2024-03 | 2,870,000 | 2,830,000 | 2,850,000 | -0.00697 | 0.00697 | 1.000 |
  | snap.oh.2023-12 | 1,430,000 | 1,440,000 | 1,440,000 | 0.00000 | 0.00932 | 0.000 |
  | snap.oh.2024-03 | 1,440,000 | 1,450,000 | 1,450,000 | 0.00000 | 0.02083 | 0.000 |
  | snap.pa.2023-12 | 1,830,000 | 1,830,000 | 1,790,000 | 0.02186 | 0.01821 | 1.200 |
  | snap.pa.2024-03 | 1,780,000 | 1,830,000 | 1,830,000 | 0.00000 | 0.01873 | 0.000 |
  | snap.tx.2023-12 | 3,450,000 | 3,350,000 | 3,350,000 | 0.00000 | 0.00966 | 0.000 |
  | snap.tx.2024-03 | 3,450,000 | 3,350,000 | 3,400,000 | -0.01449 | 0.02899 | 0.500 |

## EXPLORATORY — everything below is not a primary analysis

Declared exploratory in advance (PREREGISTRATION.md): D3 `pipeline` (debate), D4 `model` tier, CRPS accuracy levels, PIT calibration, per-state heterogeneity, and the pooled-over-policy_context robustness variants in `dispersion.md`. The D4 level `claude-fable-5` was added to the sweep on 2026-07-31 after the pre-registration was frozen; it is strictly additive (no level was dropped) and model tier was already exploratory, but it is flagged here so the amendment is visible.

- **D3 `pipeline` (EXPLORATORY)** — n_units 12, 2 levels, spread median 1.04%, noise floor median 2.97%, ratio 0.351 95% CI [0.098, 0.763], verdict NULL.
- **D4 `model` (EXPLORATORY)** — n_units 12, 4 levels, spread median 9.31%, noise floor median 2.00%, ratio 4.647 95% CI [2.107, 6.464], verdict EXCEEDS NOISE FLOOR.

