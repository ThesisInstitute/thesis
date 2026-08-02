# CHECK2 — independent re-derivation from raw run records

Recomputed from JSONL records + `ground_truth_B_all.json` + `baselines_B_all.json` only; CRPS via `scoring.py:score_forecast`; nCRPS normalizer = `statistics.pstdev` of each unit's `history` values; per-unit = mean CRPS over reps ÷ pstdev; arm mean = mean over units; coverage pooled over records. Snapshots of the still-filling files: **S1 = 11:45:28**, **S2 = 11:55:44** (all S2 unless marked). `runs_bakeoff.jsonl` contains two batches of the same design: **B1** = 6-field cell_keys (`BO|unit|ctx|elic|model|rep`, n=840, complete at 28×5/arm) and **B2** = 7-field keys (`…|default/max|rep`, n=1033 at S2, still filling). Bootstrap: resample the 28 unit-level diffs with replacement, 4000 draws, `random.Random(20260731)`, percentile CI; endpoints carry ~±0.003 seed noise (checked with alternate seeds).

## Item 1 — Bake-off arms (effort absent)

| Arm | Claimed nCRPS/cov | Recomputed B1 (n=140) | Recomputed full file S2 (n) | Verdict |
|---|---|---|---|---|
| opus none point_ci | 0.243 / 0.86 | 0.2429 / 0.8643 | 0.2477 / 0.8419 (272) | MATCH (on B1; full file has drifted) |
| opus operative_only | 0.268 / 0.79 | 0.2676 / 0.7929 | 0.2660 / 0.8118 (271) | MATCH (on B1) |
| fable none | 0.294 / 0.71 | 0.2939 / 0.7143 | 0.2933 / 0.6801 (272) | MATCH (on B1) |
| fable operative_only | 0.346 / 0.60 | 0.3458 / 0.6000 | 0.3428 / 0.5956 (272) | MATCH (on B1) |
| fable operative_only decomposed | 0.356 / 0.46 | 0.3564 / 0.4571 | 0.3692 / 0.4081 (272) | MATCH (on B1) — current-file coverage now 0.41; quote one batch state consistently |

Unlisted arm also present: opus operative_only decomposed — B1 0.2648 / 0.7357; full S2 0.2623 / 0.7296 (270).

## Item 2 — Paired tests (bootstrap on unit-level nCRPS diffs)

| Test | Claimed | Recomputed B1 | Recomputed full S2 | Verdict |
|---|---|---|---|---|
| opus none vs persistence | meanΔ −0.083 [−0.170, −0.008], 19/28 wins | −0.0830 [−0.1688, −0.0080], 19/28 | −0.0781 [−0.1641, −0.0014], 18/28 | MATCH (on B1; CI endpoints within bootstrap seed noise) |
| fable oper vs fable none | +0.052 [+0.012, +0.093] | +0.0519 [+0.0134, +0.0924], 10/28 | +0.0495 [+0.0097, +0.0909], 9/28 | MATCH (on B1) |

Persistence CRPS recomputed from `baselines_B_all.json` point/CI via `score_forecast`; recomputed values agree with the stored `crps` fields to machine precision (max |Δ| = 0.0).

## Item 3 — Effort cells (config.effort == "max")

| Cell | Claimed (partial, n=7) | Recomputed at current n (S2) | Verdict |
|---|---|---|---|
| opus operative_only max | 0.178 / cov 0.94 | **n=117, 25/28 units: nCRPS 0.2143 / cov 0.8291** (S1 n=73, 15 units: 0.1958 / 0.9178) | SUPERSEDED — n=7 read no longer holds; still filling, value moving |
| fable operative_only max | (not claimed) | n=127, 26/28 units: 0.2072 / 0.7480 | — |

## Item 4 — A3 (`runs_amend3.jsonl`, n=180, 1 record unparsed/excluded)

| Claim | Recomputed | Verdict |
|---|---|---|
| future2026 monotone (third<actual<tripled by median) 6/6 model×elicitation cells | 6/6 | MATCH |
| retro2021 point_ci_json 0/3 monotone | 0/3 | MATCH |
| retro2021 derivation_json 3/3 monotone | 3/3 | MATCH |

## Item 5 — A4 (`runs_amend4.jsonl`, n=240)

| Claim | Recomputed | Verdict |
|---|---|---|
| retro2021 opus non-monotone at all four efforts | non-monotone 4/4 (low/medium/high/max) | MATCH |
| future2026 monotone at all four efforts, both models | monotone 8/8 | MATCH |
| median completion_tokens ≈ {low ~208, medium ~369, high ~720, max ~4390} | {low 208.5, medium 369.0, high 720.5, max 4390.5} | MATCH |

Side observation (not claimed): fable retro2021 is monotone at effort=medium (520<530<550), non-monotone at the other three.

## Item 6 — A5 (`runs_amend5.jsonl`, n=300)

| Claim | Recomputed | Verdict |
|---|---|---|
| snap_agecaps median spread/noise: retro 0.44 | 0.4419 (median over 8 retro2023 cells) | MATCH |
| snap_agecaps median spread/noise: future 1.63 | 1.6265 (median over 8 future2027 cells) | MATCH |
| fpuc_window all 4 cells monotone none<half<full | 4/4 monotone | MATCH |

## Item 7 — Composed-system autopsy

| Claim | Recomputed | Verdict |
|---|---|---|
| opus-none baseline (median point/CI) + median decomposed policy_delta → mean nCRPS 0.403 | Construction reproduces with **opus** decomposed deltas, CI shifted by delta: 0.4033 (S1 full), 0.4054 (S2 full), 0.4059 (B1 only) | MATCH (value is batch-state-dependent, 0.403–0.406) |
| ensemble-with-fable loses to opus-none parent, meanΔ +0.203 [+0.137, +0.274] | Not reproduced under 19 candidate constructions. Closest: B1 pooled-reps base (opus∪fable none) + fable delta **+0.2040 [+0.1202, +0.2907]**; B1 mean-of-bases + fable delta +0.2196 [+0.1317, +0.3128]; S2 opus base + fable delta +0.1810 [+0.1085, +0.2582]. Direction and CI-excludes-zero hold in every variant (+0.16 to +0.27). | CANNOT-DERIVE exactly — construction underdetermined; qualitative claim (loses, significantly) verified |

## Item 8 — Instruction arm (`runs_instr.jsonl`) — first read, S2 (n=179, 16 units, still filling)

| Style | n records | parse failures | mean nCRPS | coverage |
|---|---|---|---|---|
| plain | 48 | 0 | 0.1862 | 0.9583 |
| premortem | 43 | 0 | 0.1827 | 0.9535 |
| quantiles | 45 | 0 | 0.1778 | 0.9111 |
| reference_class | 43 | 0 | 0.2003 | 0.8837 |

No prior claim — first read. Unit set grew 8→16 during this pass; treat as interim.

## Item 9 — MAS arms (`runs_mas.jsonl`) — first read, S2 (n=120, 14 units, still filling)

| Arm | n records | parse failures | mean nCRPS | coverage |
|---|---|---|---|---|
| persona_pool | 41 | 0 | 0.2975 | 0.9024 |
| scenario_mixture | 41 | 0 | 0.2188 | 0.9756 |
| variance_auditor | 38 | 1 (medicaid.us.2024-01 rep 2, truncated JSON) | 0.2092 | 1.0000 |

No prior claim — first read.

## Item 10 — S.3596 conditionals (`forward/s3596_conditional_runs.jsonl`, n=3 per cell)

| Cell | Claimed (current-law → enacted medians) | Recomputed | Verdict |
|---|---|---|---|
| poverty 2027, opus | 13.60 → 13.50 | 13.60 → 13.50 | MATCH |
| poverty 2027, fable | 13.30 → 13.15 | 13.30 → 13.15 | MATCH |
| qualifying children, opus | 49.3 → 49.5 | 49.3 → 49.5 | MATCH |
| qualifying children, fable | 48.5 → 48.9 | 48.5 → 48.9 | MATCH |

## Duplicates + denominators (`runs_bakeoff.jsonl`)

| Check | Result | Verdict |
|---|---|---|
| Duplicate cell_key strings | 0 (S1 and S2) | MATCH — but see next row |
| Logical duplicates | Two cell_key formats coexist (B1 6-field × 840; B2 7-field `…|default/max|rep` × 1033 at S2). **789 logical (arm, unit, rep) cells appear under both formats** — the string-level check passes only because the key format changed between batches. Every no-effort arm mixes both batches. | FLAG |
| Records per arm (S2) | opus none 272 · opus oper 271 · opus decomp 270 · fable none 272 · fable oper 272 · fable decomp 272 · opus max 117 · fable max 127 (total 1873) | — |
| Truth consistency | record `truth` == baselines `truth` == ground-truth `first_print_value` for all 28 units | MATCH |

---

# Final re-pass (files complete) — snapshot S3 = 12:17:52, `runs_bakeoff.jsonl` n=1960, both batches complete at 28×5/arm, 0 duplicate cell_key strings. Items 11-12 computed on the 7-field-key batch (B2) per instruction; bootstrap = resample the 28 unit diffs, 6000 draws, `random.Random(20260731)`, percentile CI.

## Item 11 — fable operative_only point_ci max, paired tests (B2, n=140/arm, 28 units)

| Test | Claimed | Recomputed | Verdict |
|---|---|---|---|
| fable max vs fable none (effort absent, B2) | meanΔ −0.084 [−0.164, −0.008], 20/28 wins | meanΔ −0.0844 [−0.1644, −0.0083], 20/28 | MATCH |
| fable max vs persistence | meanΔ −0.118 [−0.211, −0.035], 22/28 wins | meanΔ −0.1180 [−0.2094, −0.0317], 22/28 | MATCH — meanΔ and wins exact; CI endpoints differ ≤0.004, within bootstrap stream noise (alt-seed endpoints spanned −0.208…−0.030/−0.035) |

Sensitivity: against fable-none from B1 (−0.0860 [−0.1697, −0.0092], 20/28) or B1+B2 pooled (−0.0852 [−0.1660, −0.0089], 20/28) — conclusion unchanged.

## Item 12 — matched-unit leaderboard (B2, 28 units, n=140/arm; Winkler α=.2 = width + 10×outside-distance; per-unit mean over reps ÷ pstdev, arm mean over units; raw = un-normalized sensitivity)

| Arm | mean nCRPS | nWinkler | nWidth | raw Winkler | raw width | coverage |
|---|---|---|---|---|---|---|
| **fable oper MAX** | **0.2079** | **1.2951** | 0.8473 | **135.48** | 93.02 | 0.7500 |
| opus oper MAX | 0.2470 | 1.4807 | 1.1280 | 150.38 | 107.99 | 0.7857 |
| opus none | 0.2533 | 1.6116 | 1.1925 | 171.13 | 120.22 | 0.8214 |
| opus oper | 0.2606 | 1.5881 | 1.2653 | 171.21 | 130.36 | 0.8286 |
| opus decomp | 0.2612 | 1.5484 | 1.0225 | 169.22 | 110.01 | 0.7214 |
| fable none | 0.2923 | 1.8404 | 1.0152 | 206.55 | 117.84 | 0.6643 |
| fable oper | 0.3390 | 2.0506 | 1.0258 | 210.49 | 112.74 | 0.6143 |
| fable decomp | 0.3804 | 2.6566 | **0.8115** | 286.50 | **86.25** | 0.3929 |

| Claim leg | Recomputed | Verdict |
|---|---|---|
| fable+bill+max best on mean nCRPS | Yes — 0.2079 vs next 0.2470 | MATCH |
| best on Winkler (α=.2, ×10 penalties) | Yes — 1.2951 normalized (135.48 raw) vs next 1.4807 (150.38) | MATCH |
| best on width | **No — fable decomposed is narrower on every aggregation tried**: normalized mean 0.8115 vs 0.8473; raw mean 86.25 vs 93.02; per-unit-median and arm-median variants agree (and on median raw width fable none 61.30 beats both). fable+bill+max is best on width only if decomposed arms are excluded from the leaderboard — but fable decomp is complete (n=140) and buys its narrow width with 0.39 coverage | MISMATCH |
| coverage 0.75 | 0.7500 exactly (105/140) | MATCH |
