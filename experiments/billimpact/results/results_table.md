# Results table — one row per configuration cell

Generated 2026-07-31T10:56:07-04:00 from `/Users/davidgringras26-27/career/thesis/experiments/billimpact/runs_api.jsonl`.

**N = 2520 runs read, 2520 scored, 42 configuration cells, 12 units.** Sweep completion: 2520/2520 cells (100.0%).

Every row states its own N. Reps per (cell, unit) = 5 by pre-registration; a partial sweep will show fewer.

**Column definitions.**

- `n_runs` — runs in this configuration cell, pooled over units and repeats. `n_units` — distinct units contributing. `n_scored` — runs with a parsed forecast.
- `median_persons` — median across units of the per-unit median forecast, in persons. Units differ in scale by ~4x (CA ~4.4M vs OH ~1.4M), so this column is **not** comparable across units; it is here for face-validity only. Use `median_norm`.
- `median_norm` — median of (forecast / that unit's unconditioned median), where the unconditioned median is the unit's median forecast at `policy_context=none` with the other four dimensions at reference (elicitation=point_ci_json, pipeline=single_pass, model=claude-sonnet-5, magnitude=actual). 1.000 means identical to the unconditioned forecast.
- `sd_reps_%` — mean across units of (SD of the forecast across repeats within this cell / mean forecast) x 100. This is the per-config variance that the pre-registration forbids omitting. `sd_reps_persons` is the same in persons.
- `mean_crps` / `sd_crps` — CRPS against the first print, persons, across all runs in the cell. `crps_norm` — CRPS divided by the SD of that unit's own supplied 60-month history (frozen in ground_truth.json at pre-registration). **Never normalised by the model's own interval width.**
- `cov80` — fraction of runs whose 80% interval contains the first print (nominal 0.80). `mean_pit` — mean probability integral transform (calibrated = 0.50, uniform). `width` — mean 80% interval width, persons; `width_norm` — the same divided by the unit's history SD.
- `n_implaus` — runs flagged `implausible_extraction`. A parsed forecast is flagged `implausible_extraction` when its point OR either interval endpoint falls outside [0.1x, 10x] the unit's last observed history value. This band is deliberately loose (a state SNAP caseload cannot move 10-fold in 30 months). It exists to separate an extraction artefact from a forecast, not to filter forecasts by quality. **Flagged runs are retained in every number in this table**; the sensitivity analysis that excludes them is reported separately in `dispersion.md` and `primary_analyses.md`.


## DATA-QUALITY FINDING (CORRECTED) — free-text extraction returned calendar years as forecasts

**Status: found, fixed, and re-derived offline. No run was dropped.** The numbers in every table in this report come from the corrected parse (parser versions observed on the run records: `{'parse_forecast_v2': 2520}`).

### What went wrong

The v1 prose fallback in `harness.parse_forecast` matched any number, filtered candidates with `n > 1000`, and returned the FIRST 3-wide window satisfying an ordering test. `2021`, `2023` and `2024` all clear 1000, and a prose forecast discusses the series history before it states an answer, so the first matching window was routinely a run of calendar years: "the last available data point in June 2021" yielded `{point: 2023, ci_low: 2021, ci_high: 2023}` for a series whose true level is ~4.2 million persons.

This was not noise. It fired only on prose, which is one LEVEL of a measured dimension (D2 `elicitation`), so it manufactured a difference between `free_text` and JSON that had nothing to do with elicitation format — the exact class of artefact this experiment exists to detect. A quieter second case hit `cot_then_json`: a trailing JSON object truncated at `max_tokens` or broken by a stray quote never reached the JSON path, so the prose heuristic mined the reasoning instead of reading the answer.

### Measured extent, before and after

Derived from the `forecast_v1` field preserved on **2515** re-derived records (`reparse.py`), not from narrative. Cells that were quarantined and re-executed no longer carry a v1 parse in this file, so their pre-fix parses are counted separately below: **4** further calendar-year points sit in the sibling quarantine file(s), for a complete pre-fix total of **214**.

| quantity | before fix | after fix |
|---|---|---|
| points that were a calendar year (1900-2100) | 214 (210 here + 4 quarantined) | 0 |
| forecasts with no interval at all (`ci_low == ci_high`) | 9 | 0 |
| runs outside [0.1x, 10x] the unit's last observed caseload | (all of the above) | 0 |
| point estimates changed by the re-derivation | — | 263 |

v1 parse modes across those records: `{'json': 2212, 'prose_triple': 201, 'prose_ordered': 102}`. Calendar-year points by elicitation level: `{'free_text': 209, 'cot_then_json': 1}`.

### How it was corrected

1. `harness.parse_forecast` v2 rejects year-shaped tokens, restricts prose candidates to within [0.2x, 5x] the unit's own last OBSERVED history value, locates the interval from explicit interval language taking the LAST such statement, and takes the point from the cue-marked candidate nearest that interval. The band is a SCALE filter, not an accuracy filter — a forecast of a 3x collapse still parses and is then scored badly on merit — and it is applied to the prose path ONLY, never to the JSON path, so D5 `magnitude_elasticity` (which runs entirely at `point_ci_json`) cannot be muted by it.
2. The parser is strictly EXTRACTIVE. A response stating an interval but no point, or truncated before it answers, FAILS the parse and is counted; it is never repaired by imputing a midpoint the model did not write.
3. Every stored response was re-derived OFFLINE — no model was re-called for the correction, so the re-parse is deterministic and introduces no new sampling. The alternative, re-eliciting `free_text`, would have drawn a fresh sample at a later date on one level of a measured dimension, which is a worse cure than the disease.
4. All **2212 of 2212** runs that had parsed via strict JSON re-derived to identical values, confirming the fix is confined to the prose and malformed-JSON paths.
5. Runs that remained unparseable were QUARANTINED with a recorded reason and re-executed under the raised `max_tokens` caps (see the quarantine table below); they were all truncations at the older caps, not model refusals.

| elicitation / parse_mode | scored | flagged implausible | rate |
|---|---|---|---|
| `cot_then_json/json` | 298 | 0 | 0.0% |
| `cot_then_json/json_keyscan` | 2 | 0 | 0.0% |
| `forced_choice_bins/json` | 299 | 0 | 0.0% |
| `forced_choice_bins/json_keyscan` | 1 | 0 | 0.0% |
| `free_text/prose_cued` | 300 | 0 | 0.0% |
| `point_ci_json/json` | 1619 | 0 | 0.0% |
| `point_ci_json/json_keyscan` | 1 | 0 | 0.0% |

Consequence for the analysis: D2 `elicitation` is the only pre-registered dimension containing a non-JSON elicitation level, so **P2 was the only primary result this defect could reach**. D1, D3, D4, D5 and the whole of `skill.md` run at `elicitation=point_ci_json` and were never affected. After the correction **no run is flagged implausible**, so the sensitivity view excludes nothing and is identical to the primary by construction; P2 is still reported both ways for continuity, and the primary P2 now measures elicitation format rather than the parser.

| policy_context | elicitation | pipeline | model | magnitude | n_runs | n_units | n_scored | n_parse_fail | n_api_err | n_implaus | median_persons | median_norm | sd_reps_% | sd_reps_persons | mean_crps | sd_crps | mean_crps_norm | cov80 | mean_pit | width | width_norm |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| none | cot_then_json | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,900,000 | 1.007 | 1.97 | 66017 | 100,750 | 100,675 | 0.654 | 0.700 | 0.500 | 364,333 | 2.570 |
| none | forced_choice_bins | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,950,000 | 1.017 | 3.42 | 129,335 | 173,472 | 250,288 | 0.994 | 0.500 | 0.424 | 250,383 | 1.722 |
| none | free_text | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,925,000 | 1.010 | 2.58 | 83200 | 115,448 | 120,662 | 0.739 | 0.667 | 0.513 | 363,333 | 2.541 |
| none | point_ci_json | debate | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,900,000 | 1.011 | 1.79 | 58705 | 109,440 | 97846 | 0.711 | 0.850 | 0.493 | 503,833 | 3.693 |
| none | point_ci_json | single_pass | claude-fable-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,955,000 | 1.021 | 0.70 | 26360 | 99020 | 75689 | 0.618 | 0.867 | 0.423 | 543,000 | 3.565 |
| none | point_ci_json | single_pass | claude-haiku-4-5-20251001 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 3,048,500 | 0.964 | 1.01 | 26492 | 307,269 | 371,916 | 2.168 | 0.167 | 0.486 | 159,050 | 1.006 |
| none | point_ci_json | single_pass | claude-opus-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,900,000 | 1.007 | 0.99 | 32872 | 88788 | 56368 | 0.584 | 0.983 | 0.479 | 599,083 | 3.977 |
| none | point_ci_json | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,875,000 | 1.000 | 1.91 | 54524 | 131,963 | 119,532 | 0.873 | 0.500 | 0.545 | 309,000 | 2.202 |
| operative_only | cot_then_json | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,900,000 | 1.000 | 3.14 | 100,418 | 128,725 | 138,668 | 0.918 | 0.583 | 0.530 | 327,167 | 2.350 |
| operative_only | forced_choice_bins | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 3,040,000 | 0.990 | 1.47 | 48973 | 298,206 | 330,998 | 2.134 | 0.183 | 0.450 | 177,167 | 1.204 |
| operative_only | free_text | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,850,000 | 1.000 | 2.31 | 77021 | 166,957 | 250,256 | 0.998 | 0.433 | 0.588 | 284,167 | 2.036 |
| operative_only | point_ci_json | debate | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,900,000 | 1.010 | 2.15 | 72129 | 130,620 | 147,132 | 0.732 | 0.683 | 0.521 | 376,000 | 2.692 |
| operative_only | point_ci_json | single_pass | claude-fable-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,950,000 | 1.017 | 0.98 | 34881 | 89209 | 73773 | 0.549 | 0.833 | 0.411 | 462,167 | 3.061 |
| operative_only | point_ci_json | single_pass | claude-haiku-4-5-20251001 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 3,115,000 | 0.951 | 1.22 | 28910 | 311,665 | 368,152 | 2.208 | 0.017 | 0.468 | 141,267 | 0.879 |
| operative_only | point_ci_json | single_pass | claude-opus-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,922,500 | 1.010 | 1.01 | 31440 | 85999 | 58474 | 0.555 | 1.000 | 0.472 | 556,333 | 3.776 |
| operative_only | point_ci_json | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,850,000 | 0.993 | 0.69 | 19234 | 141,059 | 110,957 | 1.094 | 0.317 | 0.613 | 233,833 | 1.549 |
| operative_only | point_ci_json | single_pass | claude-sonnet-5 | inert | 60 | 12 | 60 | 0 | 0 | 0 | 2,835,000 | 0.981 | 1.57 | 49192 | 169,748 | 187,724 | 1.238 | 0.250 | 0.649 | 242,333 | 1.617 |
| operative_only | point_ci_json | single_pass | claude-sonnet-5 | severe | 60 | 12 | 60 | 0 | 0 | 0 | 2,840,000 | 1.000 | 0.47 | 10908 | 127,762 | 95106 | 1.034 | 0.233 | 0.627 | 248,167 | 1.645 |
| operative_plus_purpose | cot_then_json | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,900,000 | 1.000 | 3.21 | 111,274 | 117,919 | 172,202 | 0.764 | 0.667 | 0.529 | 333,833 | 2.381 |
| operative_plus_purpose | forced_choice_bins | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,900,000 | 0.993 | 1.63 | 54139 | 320,459 | 374,346 | 2.197 | 0.167 | 0.508 | 176,500 | 1.140 |
| operative_plus_purpose | free_text | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,875,000 | 0.993 | 3.60 | 126,910 | 154,075 | 214,598 | 1.105 | 0.450 | 0.572 | 295,167 | 2.069 |
| operative_plus_purpose | point_ci_json | debate | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,900,000 | 1.000 | 1.74 | 59092 | 111,641 | 99421 | 0.759 | 0.667 | 0.537 | 376,667 | 2.629 |
| operative_plus_purpose | point_ci_json | single_pass | claude-fable-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,955,000 | 1.019 | 0.91 | 39372 | 93002 | 80782 | 0.573 | 0.817 | 0.417 | 469,500 | 3.077 |
| operative_plus_purpose | point_ci_json | single_pass | claude-haiku-4-5-20251001 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,967,500 | 0.951 | 1.11 | 29796 | 303,530 | 380,359 | 2.092 | 0.117 | 0.515 | 150,233 | 0.944 |
| operative_plus_purpose | point_ci_json | single_pass | claude-opus-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,905,000 | 1.008 | 0.76 | 27021 | 84731 | 55570 | 0.551 | 1.000 | 0.475 | 556,250 | 3.764 |
| operative_plus_purpose | point_ci_json | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,790,000 | 0.976 | 0.71 | 18705 | 196,583 | 279,278 | 1.336 | 0.283 | 0.636 | 242,833 | 1.632 |
| purpose_only | cot_then_json | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,825,000 | 0.988 | 2.88 | 92723 | 117,833 | 108,545 | 0.835 | 0.600 | 0.585 | 341,500 | 2.448 |
| purpose_only | forced_choice_bins | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,875,000 | 1.000 | 3.07 | 108,553 | 165,482 | 153,878 | 1.567 | 0.367 | 0.539 | 234,083 | 1.463 |
| purpose_only | free_text | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,825,000 | 0.993 | 2.29 | 60750 | 126,101 | 106,980 | 0.842 | 0.500 | 0.621 | 280,333 | 2.027 |
| purpose_only | point_ci_json | debate | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,885,000 | 1.007 | 2.32 | 82246 | 125,463 | 131,836 | 0.784 | 0.800 | 0.534 | 474,667 | 3.317 |
| purpose_only | point_ci_json | single_pass | claude-fable-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,955,000 | 1.021 | 0.62 | 20965 | 91034 | 73558 | 0.577 | 0.833 | 0.426 | 471,000 | 3.202 |
| purpose_only | point_ci_json | single_pass | claude-haiku-4-5-20251001 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,965,000 | 0.947 | 0.85 | 20218 | 311,812 | 367,349 | 2.245 | 0.083 | 0.534 | 172,400 | 1.134 |
| purpose_only | point_ci_json | single_pass | claude-opus-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,930,000 | 1.014 | 0.96 | 31615 | 90566 | 61017 | 0.582 | 1.000 | 0.470 | 577,333 | 3.862 |
| purpose_only | point_ci_json | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,750,000 | 0.973 | 0.79 | 24326 | 148,304 | 121,836 | 1.072 | 0.283 | 0.676 | 289,500 | 2.082 |
| summary | cot_then_json | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,865,000 | 1.000 | 2.85 | 93680 | 126,092 | 151,048 | 0.862 | 0.633 | 0.558 | 338,667 | 2.400 |
| summary | forced_choice_bins | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,850,000 | 1.021 | 2.73 | 89845 | 250,164 | 279,056 | 1.642 | 0.317 | 0.544 | 201,583 | 1.406 |
| summary | free_text | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,875,000 | 1.000 | 2.49 | 83891 | 166,672 | 241,100 | 0.941 | 0.567 | 0.561 | 298,667 | 2.234 |
| summary | point_ci_json | debate | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,900,000 | 1.013 | 2.26 | 82109 | 116,610 | 137,492 | 0.717 | 0.783 | 0.497 | 442,500 | 3.120 |
| summary | point_ci_json | single_pass | claude-fable-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,950,000 | 1.020 | 0.51 | 18069 | 96164 | 73084 | 0.600 | 0.867 | 0.417 | 521,333 | 3.425 |
| summary | point_ci_json | single_pass | claude-haiku-4-5-20251001 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,915,000 | 0.952 | 0.97 | 22199 | 291,324 | 377,340 | 2.077 | 0.200 | 0.573 | 167,617 | 1.061 |
| summary | point_ci_json | single_pass | claude-opus-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,915,000 | 1.010 | 1.14 | 37385 | 93599 | 68153 | 0.600 | 0.967 | 0.468 | 574,417 | 3.795 |
| summary | point_ci_json | single_pass | claude-sonnet-5 | actual | 60 | 12 | 60 | 0 | 0 | 0 | 2,860,000 | 0.997 | 1.13 | 41169 | 155,182 | 179,353 | 1.180 | 0.417 | 0.595 | 267,000 | 1.875 |

## Data quality

- Lines in file: **2520** (blank 0, malformed JSON 0, missing required field 0).
- Records read (one per `cell_key`): **2520**; duplicate `cell_key` seen: **0**, of which 0 were resolved in favour of a later record that parsed (the rest kept the first occurrence); unknown unit_id: **0**.
- **Records removed from the runs file by another process** (found in sibling quarantine files beside it — reported, not analysed, because a dropped-run count computed only from `--runs` would silently understate):
    - `runs_api.quarantined.jsonl`: 14 record(s); 14 of those cells were subsequently re-run and ARE present in the runs file, 0 are not; reasons {'max_tokens truncation; re-run with raised cap': 9, 'single_value_no_interval; completion_tokens=3000; queued for re-execution': 2, 'no_interval_structure; completion_tokens=3000; queued for re-execution': 1, 'no_scale_candidates; completion_tokens=3000; queued for re-execution': 1, 'single_value_no_interval; completion_tokens=2000; queued for re-execution': 1}
- API errors: **0**.
- Parse failures: **0** (0.00% of records read)
- Parse failures attributable to output truncation at the harness `max_tokens` cap: **0** of 0.
- Parse modes: {'json': 2216, 'json_keyscan': 4, 'prose_cued': 300}. `json` is the intended path. `json_keyscan` reads point/ci_low/ci_high by key out of a trailing object that will not `json.loads` (truncated or malformed) — extraction, not repair, and all three keys are required. `prose_cued` is the free-text path: the interval comes from explicit interval language and the point from the cue-marked candidate nearest it. `prose_bracketed` / `prose_ordered` are tail-scanned fallbacks used only when no interval language is present and carry more extraction risk. See the corrected-defect section above.
- Runs scored: **2520**; scoring exceptions: 0.
- Forecasts flagged `implausible_extraction` (retained, **not dropped**): **0** — see the section above.
- `truth` disagreements between run records and ground_truth.json: **0**.
- Pre-registered grid: **2520** (unit, config, rep) cells; observed **2520**; **missing 0** (2520/2520 cells (100.0%)). Observed cells not in the planned grid: 0.
