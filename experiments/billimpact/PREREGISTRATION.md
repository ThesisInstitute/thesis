# Preregistration — Harness sensitivity of bill-conditioned forecasts

**Frozen:** 2026-07-31, drafted 09:47–11:10 EDT, committed before the first scored run.
**Author:** David Gringras (Hacking the Think Tank II — FAI/IFP, Washington DC).
**Repo:** Thesis / Brier. **Status:** pre-data-collection.

## Scope note

This preregistration covers **Leg B only — the conditional forecast**. The
extraction / first-order leg (Leg A: did the tool read the bill correctly,
scored against PolicyEngine's computed statutory effect) is owned by other team
members and is deliberately out of scope here. Nothing in this document should
be read as a claim about extraction accuracy, and the two legs are never merged
into a single accuracy number.

## Research question

Given a real enacted statutory change and a real program indicator, **how much
does a bill-conditioned forecast move when you change scaffolding that nobody
reports changing?** Accuracy against realised outcomes is secondary and is
reported with its N stated loudly.

The headline quantity is a **dispersion**, not a best configuration.

## Corpus

12 units = 6 states × 2 target months. One policy event, held fixed.

**Policy event.** Fiscal Responsibility Act of 2023, Pub. L. 118-5, Title III
[SNAP provisions], §§311–314, enacted 2023-06-03. Text pulled verbatim from
govinfo `PLAW-118publ5` and stored at `bills/FRA-2023-118publ5.txt`; the four
provisions are sliced into `provisions.json` with SHA-256 prefixes:

| Provision | Role | sha256[:12] |
|---|---|---|
| §311 Modification of work requirement exemptions (ABAWD age caps: FY2023 over 51, FY2024 over 53, FY2025+ over 55; new exemptions for homeless individuals, veterans, and foster-youth aged ≤24) | operative | `e592c97a52b6` |
| §312 Modification of general exemptions (state discretionary exemption pool reduced to 8% of covered individuals from FY2024) | operative | `e682bed8d04c` |
| §313 SNAP under the Food and Nutrition Act of 2008 (adds an employment-and-earnings **purpose** clause to 7 U.S.C. 2011) | stated purpose | `2f03831291fb` |
| §314 Waiver transparency | operative (ancillary) | `d7de1b83b56b` |

§313 is a pure statement-of-purpose amendment enacted in the same title as the
operative eligibility restriction. It is therefore a *real* stated-purpose
treatment, not a synthetic preamble we wrote ourselves.

**Indicator.** State-level monthly SNAP recipients, Census/USDA-FNS series
`BR<ST><FIPS>M647NCEN`, for CA, FL, NY, TX, PA, OH.

**Target months.** 2023-12-01 and 2024-03-01 — 3 and 6 months after the §311
phase-in, which applies to applications for initial certification or
recertification received starting 90 days after enactment (≈ 2023-09-01).

**Forecast origin.** History supplied to the forecaster is read at the
**2023-06-01 ALFRED vintage** — the series as it stood published *before* the
Act took effect — and truncated at 2023-05-01. Verified: no history row is at
or after any unit's target month.

**Horizon is long, and this is a property of the data, not a design choice.**
This Census/FNS state series publishes with a ~2-year lag in annual bulk
updates: at the 2023-06-01 vintage it carried observations only through
**2021-06**. The forecaster therefore sees 60 months ending 2021-06 and must
forecast 30 months (2023-12) or 33 months (2024-03) ahead. That is exactly what
an analyst reading this official series at the forecast origin would have had.
It also means the policy signal is a small share of total forecast error, which
biases the accuracy leg toward pessimism and the D1 dispersion test toward the
null. Both are stated wherever the numbers are reported.

**Realised first prints** (all 12 units resolved; discovered vintage
2026-02-01; revision from first print to today's vintage is 0.0 for every
unit) are frozen in `ground_truth.json` before any model is called.

Units are enumerated in `corpus_spec.json`. A unit whose first print cannot be
established is **dropped and reported as dropped** in `RESULTS.md`; it is not
back-filled with a revised value.

## Ground truth and scoring

**First prints only.** The realised value for each unit is discovered
empirically: vintages are walked forward month by month from the observation
month and the earliest vintage carrying a non-missing value is taken as the
first print. The vintage date is recorded alongside every value, together with
today's revised value so the revision size is visible. ALFRED is used strictly
as a **history mirror** (AGENTS.md permits this; it is not the resolution
source of record).

**Scoring rule — matched to the house rule, not invented.** Forecasts are
elicited as point + 80% interval, converted to a 201-point piecewise-linear
`numeric_cdf_v1` CDF by the existing repo transform
(`interval_anchor_v1`; `scripts/run_thesis_analyst.py:interval_distribution`,
port of `site/src/data/prediction-distribution.ts:buildNumericCdfFromInterval`),
and scored with **CRPS** plus the **probability integral transform** for
calibration, as a line-by-line Python port of
`scoreNumericCdfDistribution`. The port is pinned against the TypeScript
original by a cross-artefact agreement test; no existing scoring code is
modified.

## Ablation grid

Dimensions and levels:

- **D1 `policy_context`** (5) — `none` (history + base rate only; the
  *unconditioned baseline*), `summary` (neutral one-paragraph operational
  description, no statutory text), `operative_only` (§311+§312+§314 verbatim),
  `purpose_only` (§313 verbatim), `operative_plus_purpose` (all four).
- **D2 `elicitation`** (4) — `point_ci_json`, `free_text`, `cot_then_json`,
  `forced_choice_bins`.
- **D3 `pipeline`** (2) — `single_pass`, `debate` (Skeptic → Verifier → Judge).
- **D4 `model`** (3) — `anthropic/claude-opus-5`, `anthropic/claude-sonnet-5`,
  `anthropic/claude-haiku-4.5`.
- **D5 `magnitude`** (3) — `actual`, `severe` (age caps rewritten to *over 33*),
  `inert` (age caps rewritten to *over 73*). Contamination arm.

**Repeats: 5 per cell.** No per-config difference is reported without its
per-config variance across repeats.

Full cross-product is not run. The pre-registered fractional design is:

| Arm | D1 | D2 | D3 | D4 | D5 | runs |
|---|---|---|---|---|---|---|
| **A — primary** | all 5 | all 4 | single | sonnet-5 | actual | 5×4×12×5 = 1200 |
| **B — model** | all 5 | point_ci_json | single | all 3 | actual | 5×3×12×5 = 900 (300 shared with A) |
| **C — pipeline** | all 5 | point_ci_json | debate | sonnet-5 | actual | 5×12×5 = 300 runs (×3 calls) |
| **D — contamination** | operative_only | point_ci_json | single | sonnet-5 | all 3 | 3×12×5 = 180 |

Temperature is fixed at 1.0 (the repo's experiment default) for all arms;
run-to-run variance at fixed temperature is exactly the noise floor we need.

## Metrics

1. **`spread_pp`** — for a given unit and dimension, the range of the median
   forecast across that dimension's levels, expressed in percent of the
   unconditioned (`none`) median. Primary dispersion metric.
2. **`noise_floor`** — the same range computed across the 5 repeats *within* a
   cell. Any dimension effect is reported as a ratio to this floor; a
   dimension whose spread does not exceed its noise floor is reported as null.
3. **CRPS** against the first print, per cell, mean and SD across repeats.
4. **PIT** per cell, for calibration (are the 80% intervals 80% intervals?).
5. **`skill_vs_unconditioned`** — CRPS(conditioned) − CRPS(`none`). Negative is
   improvement.
6. **`magnitude_elasticity`** — (median under `severe` − median under `inert`) /
   median under `actual`. A tool that *derives* from the statute must move when
   the age cap moves by 40 years; a tool that *recalls* the realised caseload
   will not. Near-zero elasticity is evidence of memorisation.

## Primary analysis (declared in advance)

**P1 (headline).** Dispersion of the median forecast across **D1
`policy_context`**, relative to the within-cell noise floor, pooled over units.

**P2.** Dispersion across **D2 `elicitation`**, same construction.

**P3 (the sycophancy test).** Does `purpose_only` move the forecast in the
*same direction* as `operative_only` relative to `none`? The operative
provisions restrict eligibility and should push participation **down**. §313's
purpose clause is nominally about employment and earnings and carries no
eligibility change. If `purpose_only` produces a comparable downward shift, the
model is reading the preamble as if it were the statute.

**P4.** `magnitude_elasticity` under D5 — memorisation check.

Everything else — D3 debate, D4 model tier, CRPS accuracy levels, PIT
calibration, per-state heterogeneity — is **exploratory** and will be labelled
as such.

## What counts as a null result

- **P1/P2 null:** the across-level spread does not exceed the within-cell noise
  floor (ratio ≤ 1, or the 95% bootstrap CI of the ratio includes 1). This
  would be a *robustness* finding and will be reported as prominently as a
  positive one.
- **P3 null:** `purpose_only` is statistically indistinguishable from `none`.
- **P4 null (and a bad sign for the tool):** elasticity ≈ 0, i.e. the forecast
  does not respond to a 40-year change in the statutory age cap.
- **Skill null:** `skill_vs_unconditioned` ≥ 0 — conditioning on the bill does
  not improve the forecast. **This will be reported if it occurs.**

## Constraints binding this analysis

- N = 12 units, one policy event, one program. Confidence intervals go on the
  accuracy estimates and N is stated on every table. No claim generalises
  beyond SNAP participation without further corpora.
- The corpus is not contamination-free by construction; D5 measures the
  contamination rather than assuming it away.
- Reporting the best configuration is forbidden. The deliverable is the
  distribution.
