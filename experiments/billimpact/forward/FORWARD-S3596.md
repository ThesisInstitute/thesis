# S.3596 bill-conditional forward forecasts — ready to register

**Stronger Start for Working Families Act** (Hassan/Young; refundable-CTC
earned-income threshold $2,500 → $1, TY2026+). Produced 2026-07-31 with the
architecture the day's validation supports: mechanical leg from PolicyEngine
(exact household deltas, 14 verified cases), forecast leg elicited separately,
composition explicit. Models: opus-5 and fable-5; 3 repeats; medians below.
Raw runs with timestamps: `s3596_conditional_runs.jsonl`.

Both targets are **already registered** in the ledger with first-print
resolution rules; the S.3596 forecasts are conditional forecasts against them.

| Registered target | Resolves | Current law | S.3596 enacted | Δ |
|---|---|---|---|---|
| `census.spm.child_poverty_rate.2027` (%) | 2028-09-15 | opus 13.60 · fable 13.30 | 13.50 · 13.15 | **−0.10 · −0.15 pp** |
| `irs.soi.ctc.qualifying_children.ty2026` (M) | 2028-08-31 | opus 49.3 · fable 48.5 | 49.5 · 48.9 | **+0.2 · +0.3 M** |

Reading: the poverty delta is the bill's channel (refundable dollars reaching
families below the current phase-in floor). The qualifying-children delta is
NOT mechanical — a threshold change does not alter qualifying-child status —
so the models' +0.2–0.3M is a *behavioral uptake* claim (newly positive
credits inducing filing). The two rows therefore separate the operational
effect from the inferred behavioral effect, which is the product's own
three-output distinction, applied to its demo bill.

Also present from the earlier lane build (partial; its session was cancelled
mid-run): `targets_forward.json` (16 selected near-resolving program-level
targets), `runs_forward.jsonl` (T01–T04 across 4 lanes × 3 reps), and
`forward_harness.py`. These are per-config lanes on near-term targets
(resolving from August 2026), usable as-is for the live harness-sensitivity
experiment.

## To register (requires repo write access — one command after merge)

1. Merge the branch (cells and runs are committed with runAt timestamps —
   claimed-time chronology from git history).
2. Run the recorder: `gh workflow run record-forecasts.yml --ref main`.
   Chronology note, stated precisely: these JSONL runs carry no custody roots,
   so their ceiling under `classifyPublicationProof` is
   **claimed_time_verified** (git history attests the run time). Reaching the
   witness-verified tier requires re-emitting the two conditionals as recorded
   `thesis.analyst` runs through the runner before the 2028 resolutions —
   OPERATIONALISATION.md item 7 has the exact path.

Why this completes the backtest: every retrospective accuracy number in this
study sits inside model training windows and is recall-contaminated by
construction (demonstrated causally in `RESULTS.md` §3a). These targets have
no realized values. Whatever the harness comparisons show here, they show
cleanly — and the lab scores them mechanically as the months resolve.

## History-label caveat (SENSE_CHECK items)

The qualifying-children history supplied to the models carried labels inherited
from the repo's forecast cell that primary-source checking could not fully
verify as child counts: TY2019 "48" best matches ~48M *returns claiming the
CTC* (returns≠children); TY2021 "61" is Treasury/IRS advance-payment child
coverage (real, but not an SOI tabulation); TY2022 "49" was not verified
against any SOI product. The registered target's own resolution rule hedges to
"the closest directly comparable official count", so the forecasts stand, but
the fable delta convention is: Δ = median of within-run (enacted − current-law)
deltas, which is why fable's displayed levels (48.5 → 48.9) differ from its
stated +0.3M. Flagged upstream since the labels originate in
`site/src/data/forecast-cells.ts`.
