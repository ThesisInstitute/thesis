# Amendment 1 — corpus extension, decomposed elicitation, dollar-perturbation, bake-off

**Written 2026-07-31 ~10:50 EDT, committed before any amendment run.** This is a
**post-hoc amendment** to [`PREREGISTRATION.md`](PREREGISTRATION.md): the
original 2520-run grid and its analyses are complete and committed (`e16ddf5c`);
everything below is new data collection designed *after* seeing those results,
and every analysis it feeds is labelled amendment-registered, not original-prereg.
Within the amendment, rules are frozen here before its first run.

## A. Corpus B — 8 units, 4 events, 4 programs (from `corpus_extra.json`)

| Event | Series (verified id) | Units | Horizon |
|---|---|---|---|
| Veterans' COLA Act 2023, Pub. L. 118-6 §2 | `W826RC1` veterans' benefits | 2 | 8, 11 mo |
| Social Security Fairness Act, Pub. L. 118-273 §§2–4 (WEP/GPO repeal) | `W823RC1` social security | 2 | 5, 8 mo |
| CAA 2021, Pub. L. 116-260 div. N §203 (FPUC $300) | `W825RC1` unemployment insurance | 2 | 3, 5 mo |
| CAA 2023, Pub. L. 117-328 div. FF §5131 (Medicaid unwinding) | `W729RC1` Medicaid | 2 | 8, 14 mo |

First prints frozen in `ground_truth_extra.json` before any amendment run.
These BEA-family series revise heavily (up to +40 on a 175 first print), so
first-print scoring is substantive here, not ceremonial. Series titles were
verified against FRED (`og:title` for W826RC1/W825RC1/W729RC1; search-title +
component-sum check for W823RC1); **units/seasonal-adjustment are deliberately
not asserted** — prompts say "in the units shown in the history".

D1 for Corpus B has levels `none / summary / operative_only` only: none of the
four Acts contains a findings/purpose section (verified by full-text scan; we
did not invent one). The purpose-clause test remains anchored on FRA §313.

## B. New elicitation level: `decomposed_json`

The original grid found forecasts quantized at ~0.10% of level, which can mask
a small policy delta inside baseline rounding. `decomposed_json` elicits
`{baseline_no_policy, policy_delta, point, ci_low, ci_high}` — the delta is its
own number and cannot hide under the baseline's rounding. **Registered
predictions:** (i) if the near-zero SNAP elasticity was granularity masking,
decomposed deltas will track the age-cap perturbation; (ii) if it was
recall/insensitivity, deltas will stay ≈0 or fail to track. Either outcome is
reportable.

## C. Dollar perturbation (FPUC) — the clean derivation-vs-recall test

SNAP's perturbation was confounded: the true caseload elasticity to the ABAWD
age cap is plausibly small, so "no response" ≠ "no derivation". FPUC has no such
confound: the $300/week supplement mechanically dominates `W825RC1` in the
target months. Substitutions: `$300` → `$900` (tripled) / `$100` (third) in the §203
operative text. (Not $600: the provision is an amendment that itself strikes
the prior `$600` rate, so inserting $600 would read as a no-op statute; $900
keeps the amendment coherent and widens the spread.) **Registered expectation for a deriving model:** the
UI-outlay forecast under tripled ≈ substantially above actual; under third ≈
substantially below; monotone ordering third < actual < tripled in every unit.
Failure of monotonicity, or no spread, is the recall signal.

## D. Frozen selection + out-of-sample bake-off

Selection was computed on Corpus A (SNAP, reparsed canonical file) **before any
Corpus B model run**: minimize mean normalized CRPS (history-SD normalizer, the
same one used throughout) over all 18 original-grid configs.

> **Selected: `policy_context=operative_only · elicitation=point_ci_json ·
> single_pass · claude-fable-5`** (mean nCRPS 0.5539, n=60).

Bake-off on Corpus B (never used for selection), same scoring:
1. Selected config (bill-conditioned).
2. Same model/elicitation with `policy_context=none` (ablates the bill).
3. **Persistence**: point = last pre-origin observation; 80% interval from the
   empirical 10th/90th percentiles of h-step changes in the unit's own history.
4. **Drift**: persistence point + h × mean 1-step change, same interval method.
Baselines are computed mechanically (no LLM). Primary bake-off metric: mean
normalized CRPS across the 8 units, with a paired bootstrap CI on each
difference. Win/loss counts reported per unit. N=8 stated everywhere.

## E. Amendment run plan

| Arm | Corpus | Grid | Runs |
|---|---|---|---|
| H | B | ctx{none,summary,operative_only} × elic{point_ci_json,decomposed_json} × sonnet-5 | 240 |
| I | B | ctx{none,operative_only} × point_ci_json × {opus-5, fable-5, haiku-4.5} | 240 |
| J | B/FPUC | 2 units × mag{actual,tripled,third} × elic{point_ci_json,decomposed_json} × sonnet-5, + fable-5 at point_ci_json | 90 |
| K | A/SNAP | 12 units × mag{actual,severe,inert} × decomposed_json × sonnet-5 | 180 |

5 repeats per cell throughout; overlapping cells run once (cell-key union).
Temperature 1.0. Failed runs are quarantined, never silently cleaned.

## F. Corrections to the original report, recorded here

1. `RESULTS.md` said the preregistration was committed at 11:38 EDT; git says
   **09:59 EDT** (`f95c4b6c`). Wrong by transcription; corrected.
2. The `severe`/`inert` direction comment in `harness.py` was backwards
   (§6(o)(3) is an *exemption* list; low caps ⇒ more exempt ⇒ higher
   participation). Labels retained for grid continuity; read severe=low_caps,
   inert=high_caps. Expected sign of (severe−inert) is positive.
3. P4's original wording ("recalling, not deriving") overstated. Corrected
   claim: 6/12 unit medians did not move at all across the 40-year swing; of
   the 6 that moved, 4 moved in the correct direction and 2 wrongly; movers'
   median |elasticity| ≈ 1.8%, near the output-granularity floor (median
   distinct-step ≈ 0.10% of level). Arms B and K above exist to separate
   granularity masking from genuine insensitivity.

---

## Amendment 6 (appended 2026-07-31 ~12:00 EDT, committed before its runs) — S.3596 envelope

The registered S.3596 conditional deltas were produced under 2 configs. This
arm measures their harness-sensitivity envelope: 4 context levels (full_bill /
summary / parameter_only / named_only) × 2 elicitations (paired-scenario JSON /
decomposed) × 2 models (opus-5, fable-5) × 3 reps on both registered targets.
Measurand: the SPREAD of the conditional delta across configs. Registered
predictions: (1) the poverty-delta's sign survives all 16 configs; (2) the
uptake delta loses its sign under parameter_only; (3) tier moves the delta
more than context. Nothing here is scored against outcomes.
