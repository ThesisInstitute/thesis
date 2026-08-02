# Dispersion — the headline

Generated 2026-07-31T10:56:07-04:00. **N = 2520 scored runs, 12 units, 5 repeats per cell by design.** Sweep completion: 2520/2520 cells (100.0%).

> The pre-registered headline quantity is a **dispersion, not a best configuration**. No configuration is recommended anywhere in this file, and none will be.

## Construction

For each dimension, all OTHER dimensions are held at the reference configuration `{'policy_context': 'operative_only', 'elicitation': 'point_ci_json', 'pipeline': 'single_pass', 'model': 'claude-sonnet-5', 'magnitude': 'actual'}`; `policy_context=operative_only` is the reference for D2-D5 because it is the only policy_context the contamination arm (D5) was run at.

- **spread** — per unit, the range of the per-level MEDIAN forecast across that dimension's levels, as a percentage of that unit's unconditioned median (`policy_context=none` at reference). Reported as median and IQR across units.
- **noise_floor** — per unit, the range across the 5 REPEATS *within* a cell, averaged over that dimension's cells, same denominator.
- **ratio** — median(spread) / median(noise_floor) across units, with a 2000-draw bootstrap 95% CI resampling **units** with replacement (seed 20260731). `median_of_ratios` (the per-unit ratio, then the median) is reported alongside as a robustness check.
- **A dimension whose ratio CI includes 1 is reported as NULL.** This is pre-registered (PREREGISTRATION.md, "What counts as a null result"). A null is a robustness finding and is reported as prominently as a positive one.

### Two properties of this construction, stated up front

1. **The test is conservative by construction.** The numerator ranges over per-level *medians of 5 draws*; the denominator ranges over *5 single draws*. Under a true null the numerator is the range of a less noisy quantity, so the expected ratio is below 1. A NULL verdict is therefore weaker evidence of robustness than a symmetric test would give, and an EXCEEDS verdict is correspondingly stronger.
2. **Ratios are not comparable across dimensions with different level counts.** The range statistic grows with the number of levels: D1 has 5 levels, D2 4, D3 2, D4 4, D5 3. Each dimension's `n_levels` is printed in its row. Compare a dimension against 1, never against another dimension.

## Headline table

| dim | field | n_levels | n_units | spread % (median) | spread IQR | noise floor % (median) | noise IQR | ratio | 95% CI | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| D1 | `policy_context` | 5 | 12 | 3.54 | [2.86, 4.69] | 1.96 | [1.49, 2.85] | 1.81 | [1.11, 2.65] | **EXCEEDS NOISE FLOOR** |
| D2 | `elicitation` | 4 | 12 | 8.10 | [5.91, 10.77] | 4.67 | [2.60, 5.57] | 1.73 | [1.17, 2.92] | **EXCEEDS NOISE FLOOR** |
| D3 | `pipeline` | 2 | 12 | 1.04 | [0.52, 1.73] | 2.97 | [2.01, 4.42] | 0.35 | [0.10, 0.76] | **NULL** |
| D4 | `model` | 4 | 12 | 9.31 | [4.89, 12.69] | 2.00 | [1.87, 2.72] | 4.65 | [2.11, 6.46] | **EXCEEDS NOISE FLOOR** |
| D5 | `magnitude` | 3 | 11 | 2.13 | [1.06, 2.86] | 1.82 | [1.22, 3.03] | 1.17 | [0.34, 1.94] | **NULL** |

### Verdicts

**NULL (pre-registered):** D3 `pipeline`, D5 `magnitude`. The across-level spread is not distinguishable from sampling noise at fixed temperature. This is a robustness finding, reported as such.
**EXCEEDS NOISE FLOOR:** D1 `policy_context`, D2 `elicitation`, D4 `model`. Changing this dimension moves the forecast by more than run-to-run sampling noise.

## Per-dimension detail

### D1 — `policy_context`

- Levels declared: ['none', 'summary', 'operative_only', 'purpose_only', 'operative_plus_purpose']
- Levels present in data: ['none', 'summary', 'operative_only', 'purpose_only', 'operative_plus_purpose']
- Held fixed: `{'elicitation': 'point_ci_json', 'pipeline': 'single_pass', 'model': 'claude-sonnet-5', 'magnitude': 'actual'}`
- Units contributing: **12**
- spread: median **3.54%**, IQR [2.86%, 4.69%]
- noise_floor: median **1.96%**, IQR [1.49%, 2.85%]
- **ratio (median spread / median noise) = 1.806**, 95% CI [1.107, 2.652] (2000/2000 valid draws)
- median_of_ratios = 2.100, 95% CI [0.935, 2.812]
- **Verdict: EXCEEDS NOISE FLOOR** — point ratio 1.81, 95% bootstrap CI [1.11, 2.65] excludes 1 from below

  Per-unit values:

  | unit | spread % | noise floor % | ratio | levels present | reps per level |
  |---|---|---|---|---|---|
  | snap.ca.2023-12 | 4.04 | 1.62 | 2.50 | 5 | 25 |
  | snap.ca.2024-03 | 14.55 | 3.72 | 3.91 | 5 | 25 |
  | snap.fl.2023-12 | 3.57 | 2.86 | 1.25 | 5 | 25 |
  | snap.fl.2024-03 | 3.51 | 1.40 | 2.50 | 5 | 25 |
  | snap.ny.2023-12 | 5.17 | 1.24 | 4.17 | 5 | 25 |
  | snap.ny.2024-03 | 3.39 | 1.08 | 3.12 | 5 | 25 |
  | snap.oh.2023-12 | 1.39 | 1.67 | 0.83 | 5 | 25 |
  | snap.oh.2024-03 | 1.38 | 1.52 | 0.91 | 5 | 25 |
  | snap.pa.2023-12 | 4.53 | 2.67 | 1.70 | 5 | 25 |
  | snap.pa.2024-03 | 2.73 | 2.84 | 0.96 | 5 | 25 |
  | snap.tx.2023-12 | 5.63 | 2.25 | 2.50 | 5 | 25 |
  | snap.tx.2024-03 | 2.90 | 4.35 | 0.67 | 5 | 25 |

  Per-unit level medians, normalised to each unit's unconditioned median (1.000 = identical to the unconditioned forecast):

  | unit | none | summary | operative_only | purpose_only | operative_plus_purpose |
  |---|---|---|---|---|---|
  | snap.ca.2023-12 | 1.000 | 1.000 | 1.000 | 0.960 | 1.000 |
  | snap.ca.2024-03 | 1.000 | 1.000 | 1.000 | 1.000 | 0.855 |
  | snap.fl.2023-12 | 1.000 | 1.018 | 1.007 | 0.982 | 0.982 |
  | snap.fl.2024-03 | 1.000 | 1.000 | 1.000 | 0.965 | 0.965 |
  | snap.ny.2023-12 | 1.000 | 0.990 | 0.983 | 0.948 | 0.976 |
  | snap.ny.2024-03 | 1.000 | 0.973 | 0.973 | 0.966 | 0.973 |
  | snap.oh.2023-12 | 1.000 | 0.993 | 0.993 | 0.993 | 1.007 |
  | snap.oh.2024-03 | 1.000 | 1.000 | 0.993 | 0.986 | 1.000 |
  | snap.pa.2023-12 | 1.000 | 0.955 | 0.976 | 0.976 | 0.955 |
  | snap.pa.2024-03 | 1.000 | 0.978 | 0.973 | 1.000 | 1.000 |
  | snap.tx.2023-12 | 1.000 | 0.944 | 0.972 | 0.944 | 0.944 |
  | snap.tx.2024-03 | 1.000 | 1.000 | 1.000 | 0.971 | 0.971 |

### D2 — `elicitation`

- Levels declared: ['point_ci_json', 'free_text', 'cot_then_json', 'forced_choice_bins']
- Levels present in data: ['point_ci_json', 'free_text', 'cot_then_json', 'forced_choice_bins']
- Held fixed: `{'policy_context': 'operative_only', 'pipeline': 'single_pass', 'model': 'claude-sonnet-5', 'magnitude': 'actual'}`
- Units contributing: **12**
- spread: median **8.10%**, IQR [5.91%, 10.77%]
- noise_floor: median **4.67%**, IQR [2.60%, 5.57%]
- **ratio (median spread / median noise) = 1.734**, 95% CI [1.174, 2.919] (2000/2000 valid draws)
- median_of_ratios = 1.799, 95% CI [1.282, 2.708]
- **Verdict: EXCEEDS NOISE FLOOR** — point ratio 1.73, 95% bootstrap CI [1.17, 2.92] excludes 1 from below
- *Robustness (EXPLORATORY), pooling over all 5 `policy_context` levels instead of holding it at `operative_only`:* ratio 1.431, 95% CI [1.039, 2.058], verdict EXCEEDS NOISE FLOOR (n_units 12).

  Per-unit values:

  | unit | spread % | noise floor % | ratio | levels present | reps per level |
  |---|---|---|---|---|---|
  | snap.ca.2023-12 | 22.22 | 8.33 | 2.67 | 4 | 20 |
  | snap.ca.2024-03 | 11.52 | 5.96 | 1.93 | 4 | 20 |
  | snap.fl.2023-12 | 11.79 | 4.29 | 2.75 | 4 | 20 |
  | snap.fl.2024-03 | 10.53 | 6.32 | 1.67 | 4 | 20 |
  | snap.ny.2023-12 | 2.76 | 2.24 | 1.23 | 4 | 20 |
  | snap.ny.2024-03 | 2.37 | 2.42 | 0.98 | 4 | 20 |
  | snap.oh.2023-12 | 6.94 | 2.34 | 2.96 | 4 | 20 |
  | snap.oh.2024-03 | 8.28 | 3.28 | 2.53 | 4 | 20 |
  | snap.pa.2023-12 | 8.53 | 2.67 | 3.20 | 4 | 20 |
  | snap.pa.2024-03 | 7.92 | 5.05 | 1.57 | 4 | 20 |
  | snap.tx.2023-12 | 2.82 | 5.28 | 0.53 | 4 | 20 |
  | snap.tx.2024-03 | 7.25 | 5.43 | 1.33 | 4 | 20 |

  Per-unit level medians, normalised to each unit's unconditioned median (1.000 = identical to the unconditioned forecast):

  | unit | point_ci_json | free_text | cot_then_json | forced_choice_bins |
  |---|---|---|---|---|
  | snap.ca.2023-12 | 1.000 | 0.838 | 1.061 | 0.883 |
  | snap.ca.2024-03 | 1.000 | 1.000 | 1.000 | 0.885 |
  | snap.fl.2023-12 | 1.007 | 1.018 | 1.036 | 1.125 |
  | snap.fl.2024-03 | 1.000 | 1.000 | 1.018 | 1.105 |
  | snap.ny.2023-12 | 0.983 | 0.983 | 0.983 | 1.010 |
  | snap.ny.2024-03 | 0.973 | 0.966 | 0.983 | 0.990 |
  | snap.oh.2023-12 | 0.993 | 0.993 | 0.972 | 1.042 |
  | snap.oh.2024-03 | 0.993 | 0.993 | 0.993 | 1.076 |
  | snap.pa.2023-12 | 0.976 | 1.003 | 1.013 | 0.928 |
  | snap.pa.2024-03 | 0.973 | 1.027 | 1.000 | 0.948 |
  | snap.tx.2023-12 | 0.972 | 0.958 | 0.972 | 0.944 |
  | snap.tx.2024-03 | 1.000 | 0.986 | 1.014 | 1.058 |

### D3 — `pipeline`

- Levels declared: ['single_pass', 'debate']
- Levels present in data: ['single_pass', 'debate']
- Held fixed: `{'policy_context': 'operative_only', 'elicitation': 'point_ci_json', 'model': 'claude-sonnet-5', 'magnitude': 'actual'}`
- Units contributing: **12**
- spread: median **1.04%**, IQR [0.52%, 1.73%]
- noise_floor: median **2.97%**, IQR [2.01%, 4.42%]
- **ratio (median spread / median noise) = 0.351**, 95% CI [0.098, 0.763] (2000/2000 valid draws)
- median_of_ratios = 0.292, 95% CI [0.091, 0.774]
- **Verdict: NULL** — point ratio 0.35 <= 1 — the across-level spread does not exceed the within-cell noise floor
- *Robustness (EXPLORATORY), pooling over all 5 `policy_context` levels instead of holding it at `operative_only`:* ratio 0.707, 95% CI [0.292, 1.156], verdict NULL (n_units 12).

  Per-unit values:

  | unit | spread % | noise floor % | ratio | levels present | reps per level |
  |---|---|---|---|---|---|
  | snap.ca.2023-12 | 0.00 | 5.56 | 0.00 | 2 | 10 |
  | snap.ca.2024-03 | 1.01 | 4.04 | 0.25 | 2 | 10 |
  | snap.fl.2023-12 | 1.07 | 3.21 | 0.33 | 2 | 10 |
  | snap.fl.2024-03 | 1.75 | 2.11 | 0.83 | 2 | 10 |
  | snap.ny.2023-12 | 1.72 | 2.41 | 0.71 | 2 | 10 |
  | snap.ny.2024-03 | 1.02 | 1.69 | 0.60 | 2 | 10 |
  | snap.oh.2023-12 | 0.00 | 1.74 | 0.00 | 2 | 10 |
  | snap.oh.2024-03 | 0.69 | 3.79 | 0.18 | 2 | 10 |
  | snap.pa.2023-12 | 6.40 | 1.33 | 4.80 | 2 | 10 |
  | snap.pa.2024-03 | 9.29 | 2.73 | 3.40 | 2 | 10 |
  | snap.tx.2023-12 | 0.00 | 5.63 | 0.00 | 2 | 10 |
  | snap.tx.2024-03 | 1.45 | 5.80 | 0.25 | 2 | 10 |

  Per-unit level medians, normalised to each unit's unconditioned median (1.000 = identical to the unconditioned forecast):

  | unit | single_pass | debate |
  |---|---|---|
  | snap.ca.2023-12 | 1.000 | 1.000 |
  | snap.ca.2024-03 | 1.000 | 1.010 |
  | snap.fl.2023-12 | 1.007 | 1.018 |
  | snap.fl.2024-03 | 1.000 | 1.018 |
  | snap.ny.2023-12 | 0.983 | 1.000 |
  | snap.ny.2024-03 | 0.973 | 0.983 |
  | snap.oh.2023-12 | 0.993 | 0.993 |
  | snap.oh.2024-03 | 0.993 | 0.986 |
  | snap.pa.2023-12 | 0.976 | 1.040 |
  | snap.pa.2024-03 | 0.973 | 1.066 |
  | snap.tx.2023-12 | 0.972 | 0.972 |
  | snap.tx.2024-03 | 1.000 | 1.014 |

### D4 — `model`

- Levels declared: ['claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5-20251001', 'claude-fable-5']
- Levels present in data: ['claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5-20251001', 'claude-fable-5']
- Held fixed: `{'policy_context': 'operative_only', 'elicitation': 'point_ci_json', 'pipeline': 'single_pass', 'magnitude': 'actual'}`
- Units contributing: **12**
- spread: median **9.31%**, IQR [4.89%, 12.69%]
- noise_floor: median **2.00%**, IQR [1.87%, 2.72%]
- **ratio (median spread / median noise) = 4.647**, 95% CI [2.107, 6.464] (2000/2000 valid draws)
- median_of_ratios = 4.873, 95% CI [1.875, 7.860]
- **Verdict: EXCEEDS NOISE FLOOR** — point ratio 4.65, 95% bootstrap CI [2.11, 6.46] excludes 1 from below
- *Robustness (EXPLORATORY), pooling over all 5 `policy_context` levels instead of holding it at `operative_only`:* ratio 4.242, 95% CI [2.541, 6.696], verdict EXCEEDS NOISE FLOOR (n_units 12).

  Per-unit values:

  | unit | spread % | noise floor % | ratio | levels present | reps per level |
  |---|---|---|---|---|---|
  | snap.ca.2023-12 | 18.59 | 2.27 | 8.18 | 4 | 20 |
  | snap.ca.2024-03 | 22.63 | 1.94 | 11.64 | 4 | 20 |
  | snap.fl.2023-12 | 13.04 | 2.01 | 6.49 | 4 | 20 |
  | snap.fl.2024-03 | 11.58 | 1.54 | 7.54 | 4 | 20 |
  | snap.ny.2023-12 | 6.90 | 4.74 | 1.45 | 4 | 20 |
  | snap.ny.2024-03 | 7.69 | 0.66 | 11.64 | 4 | 20 |
  | snap.oh.2023-12 | 3.82 | 2.00 | 1.91 | 4 | 20 |
  | snap.oh.2024-03 | 3.45 | 1.64 | 2.11 | 4 | 20 |
  | snap.pa.2023-12 | 10.93 | 2.00 | 5.47 | 4 | 20 |
  | snap.pa.2024-03 | 12.57 | 2.94 | 4.28 | 4 | 20 |
  | snap.tx.2023-12 | 4.79 | 2.82 | 1.70 | 4 | 20 |
  | snap.tx.2024-03 | 4.93 | 2.68 | 1.84 | 4 | 20 |

  Per-unit level medians, normalised to each unit's unconditioned median (1.000 = identical to the unconditioned forecast):

  | unit | claude-opus-5 | claude-sonnet-5 | claude-haiku-4-5-20251001 | claude-fable-5 |
  |---|---|---|---|---|
  | snap.ca.2023-12 | 1.030 | 1.000 | 0.844 | 1.030 |
  | snap.ca.2024-03 | 1.051 | 1.000 | 0.844 | 1.071 |
  | snap.fl.2023-12 | 1.054 | 1.007 | 1.137 | 1.054 |
  | snap.fl.2024-03 | 1.018 | 1.000 | 1.116 | 1.035 |
  | snap.ny.2023-12 | 1.009 | 0.983 | 1.052 | 1.017 |
  | snap.ny.2024-03 | 0.990 | 0.973 | 0.932 | 1.008 |
  | snap.oh.2023-12 | 0.993 | 0.993 | 1.031 | 1.000 |
  | snap.oh.2024-03 | 0.990 | 0.993 | 1.024 | 1.000 |
  | snap.pa.2023-12 | 1.040 | 0.976 | 0.931 | 1.029 |
  | snap.pa.2024-03 | 1.057 | 0.973 | 0.954 | 1.079 |
  | snap.tx.2023-12 | 0.972 | 0.972 | 0.924 | 0.972 |
  | snap.tx.2024-03 | 0.991 | 1.000 | 0.951 | 1.000 |

### D5 — `magnitude`

- Levels declared: ['actual', 'severe', 'inert']
- Levels present in data: ['actual', 'severe', 'inert']
- Held fixed: `{'policy_context': 'operative_only', 'elicitation': 'point_ci_json', 'pipeline': 'single_pass', 'model': 'claude-sonnet-5'}`
- Units contributing: **11**; excluded (no usable spread or noise floor): ['snap.ca.2024-03']
- spread: median **2.13%**, IQR [1.06%, 2.86%]
- noise_floor: median **1.82%**, IQR [1.22%, 3.03%]
- **ratio (median spread / median noise) = 1.171**, 95% CI [0.339, 1.940] (2000/2000 valid draws)
- median_of_ratios = 1.200, 95% CI [0.333, 2.000]
- **Verdict: NULL** — 95% bootstrap CI [0.34, 1.94] includes 1 — the across-level spread is not distinguishable from the within-cell noise floor
- *Robustness (EXPLORATORY), pooling over all 5 `policy_context` levels instead of holding it at `operative_only`:* ratio 0.573, 95% CI [0.000, 1.166], verdict NULL (n_units 12).

  Per-unit values:

  | unit | spread % | noise floor % | ratio | levels present | reps per level |
  |---|---|---|---|---|---|
  | snap.ca.2023-12 | 6.06 | 4.38 | 1.38 | 3 | 15 |
  | snap.fl.2023-12 | 1.07 | 4.52 | 0.24 | 3 | 15 |
  | snap.fl.2024-03 | 1.05 | 3.16 | 0.33 | 3 | 15 |
  | snap.ny.2023-12 | 3.45 | 1.49 | 2.31 | 3 | 15 |
  | snap.ny.2024-03 | 1.36 | 0.68 | 2.00 | 3 | 15 |
  | snap.oh.2023-12 | 0.69 | 0.93 | 0.75 | 3 | 15 |
  | snap.oh.2024-03 | 0.69 | 2.07 | 0.33 | 3 | 15 |
  | snap.pa.2023-12 | 2.13 | 1.78 | 1.20 | 3 | 15 |
  | snap.pa.2024-03 | 2.73 | 1.82 | 1.50 | 3 | 15 |
  | snap.tx.2023-12 | 2.82 | 0.94 | 3.00 | 3 | 15 |
  | snap.tx.2024-03 | 2.90 | 2.90 | 1.00 | 3 | 15 |

  Per-unit level medians, normalised to each unit's unconditioned median (1.000 = identical to the unconditioned forecast):

  | unit | actual | severe | inert |
  |---|---|---|---|
  | snap.ca.2023-12 | 1.000 | 1.000 | 0.939 |
  | snap.fl.2023-12 | 1.007 | 1.018 | 1.018 |
  | snap.fl.2024-03 | 1.000 | 1.000 | 0.989 |
  | snap.ny.2023-12 | 0.983 | 0.972 | 0.948 |
  | snap.ny.2024-03 | 0.973 | 0.959 | 0.966 |
  | snap.oh.2023-12 | 0.993 | 1.000 | 1.000 |
  | snap.oh.2024-03 | 0.993 | 1.000 | 1.000 |
  | snap.pa.2023-12 | 0.976 | 0.976 | 0.955 |
  | snap.pa.2024-03 | 0.973 | 1.000 | 1.000 |
  | snap.tx.2023-12 | 0.972 | 0.944 | 0.944 |
  | snap.tx.2024-03 | 1.000 | 0.971 | 0.986 |

