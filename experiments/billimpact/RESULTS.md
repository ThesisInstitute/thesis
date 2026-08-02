# RESULTS — Harness sensitivity of bill-conditioned forecasting

> **STATUS (12:20 EDT): §§1–5 final** — every number independently re-derived
> from raw records (`CHECK2.md`, incl. items 11–12 for §5's significance
> claims). Landing later today: quantile-CDF/calibration lab, two cross-type
> corpus waves (appropriations, program-creation, tariff, subsidy-parameter,
> administrative-sunset units), and the S.3596 envelope §9 integration.

**2026-07-31, Hacking the Think Tank II (FAI/IFP, Washington DC).** David Gringras.

Design frozen in [`PREREGISTRATION.md`](PREREGISTRATION.md), committed 09:59 EDT
(`f95c4b6c`) **before the first model call**. Extensions in
[`PREREG-AMENDMENT-1.md`](PREREG-AMENDMENT-1.md) and
[`PREREG-AMENDMENT-2.md`](PREREG-AMENDMENT-2.md), each committed before its own
first run. Adversarial audit of our own constructions:
[`RED_TEAM.md`](RED_TEAM.md) — its corrections are **applied here**, not hidden.
Scope: **Leg B (conditional forecast) plus the S.3596 mechanical arm**; the
team's extraction leg is out of scope and nothing here merges the two.

**Totals: ~7,400 usable scored runs** — 2,520 (corpus A grid) + 719
(amendment arms H/I/J/K) + 180 (arm P) + 180 (A3) + 240 (A4) + 1,380 (CTC) +
the A5/bake-off arms landing at time of writing — across **28 retrospective
units (5 enacted laws, 5 programs)** and **14 PolicyEngine-verified household
cases**. 171 failed cells were quarantined with recorded reasons and
re-executed; replacements are counted once, inside the arm totals, and 20 CTC
cells (all sonnet-5 without tools) remain unparseable after re-execution and
are reported as such in §4's denominators. All first prints frozen before any
model ran; zero API transport errors.

---

## 1 · The dispersion (corpus A: SNAP under Pub. L. 118-5 §§311–314)

12 units = 6 states × 2 target months; forecaster sees the series as published
2023-06 (pre-effect vintage), scored on first prints (zero revisions) with the
house CDF + exact CRPS + PIT; the Python scorer is pinned against
`site/src/data/prediction-distribution.ts` by an executable cross-artefact test.

| Dim | What varies | Spread | Naïve ratio | **Corrected inference** (RED_TEAM) |
|---|---|---|---|---|
| D4 | model tier | 9.3% | 4.65 [2.11, 6.46] | **12.4× its permutation null; survives Bonferroni + state clustering. The most defensible number in the study.** |
| D1 | policy context shown | 3.5% | 1.81 [1.11, 2.65] | 4.1× its permutation null (p<0.0003) — but the effect is **carried by the purpose-clause arm** (see §2); statutory-text-only levels alone are null |
| D2 | elicitation format | 8.1% | 1.73 [1.17, 2.92] | 4.8× its permutation null, but **fragile to state clustering** (clustered CI spans 1); report as suggestive |
| D3 | debate pipeline | 1.0% | 0.35 → "null" | **Wrong as originally stated**: no magnitude effect, but debate shifts forecasts *up* in 8/9 moving units (p=0.039) and inflates within-cell variance 5.4× |
| D5 | statutory magnitude | 2.1% | 1.17 → corrected **0.97** | Null (the 1.17 excluded the most insensitive unit because its noise floor was 0 — a denominator selection RED_TEAM caught) |

The original "ratio > 1" threshold was **wrong**: under a true null the
expected ratio is 0.12–0.52, not 1 (numerator ranges over medians-of-5,
denominator over single draws). The permutation-based restatement above is the
honest test — and it *strengthens* the headline. Both constructions are
reported; nothing was re-run to get there.

**Calibration, the sharpest accuracy statement in the study:** adding bill text
made intervals **narrower in 12/12 units (p=0.0005) while coverage fell**
(0.50 → 0.33 against a nominal 0.80). Bill context bought confidence, not
accuracy. No policy-context level improved CRPS over the unconditioned
baseline (all four point estimates worse; every CI spans 0).

## 2 · The purpose-clause effect is *named-statute recall*, not preamble sycophancy

FRA §313 is a real enacted purpose clause with zero mechanical content. Shown
*only* this clause (statute named in the header), forecasts fell in 10/12
units (two unmoved; sign test on the 10 nonzero units, p=0.002), median −2.65% — **more** than the operative sections
themselves (−0.69%). Amendment 2 decomposed the mechanism:

| Arm | Construction | Median shift | Sign test |
|---|---|---|---|
| `purpose_only` | clause + **statute named** | −2.65% | p=0.002 |
| `purpose_unnamed` | name redacted | −0.35% | p=0.29 |
| `purpose_complete` | + "this is the complete bill" | 0.00% | p=0.45 |
| `purpose_synthetic_expand` | pro-enrollment clause, complete framing | 0.00% (no sign flip) | p=0.45 |

**The name of the law does the work.** Strip it and the effect collapses;
assert completeness and it vanishes; an access-*expanding* clause fails to push
forecasts up. What looked like sycophancy is the model recognising
"Pub. L. 118-5" and pricing in what it remembers that law doing — direct,
mechanism-level evidence of backtest contamination, caught because the test
was built to be decomposable. (N=12 non-independent units; one reference
config.)

## 3 · Counterfactual statutory forecasting is recall-dominated — at every tier tested

Three escape routes for the "it's just the pipeline" objection were closed in
turn:

- **Not elicitation.** Decomposed elicitation (arm K) elicits the policy delta
  as its own number. Models produce a plausible-magnitude delta (−8k to −20k
  persons) — which then **fails to track the statute**: severe-vs-inert in the
  expected direction in only 3/12 units across a 40-year rewrite of the ABAWD
  age caps. The delta is a prior about "SNAP work-requirement bills", not a
  reading of this one.
- **Not effect size.** The FPUC arm (arm J) rewrites a $300/week supplement to
  $100 / $900 — a first-order, dollar-denominated effect on UI outlays.
  **Dose-response monotone in 0/6 (unit × model × elicitation) cells.**
- **Not the model tier.** Fable-5 fails it too, and diagnostically: its
  forecasts hug the *realised* Jan/Mar-2021 trajectory regardless of dose —
  recall-anchoring on a period deep inside training data.

Corpus A's version of the same finding: 6/12 units returned *identical*
forecasts under a 20-year-stricter and a 20-year-looser rewrite while being
displaced from the unmodified statute — the models react to the *existence* of
an amendment, not its *content*.

### 3a · The causal test (Amendment 3, as corrected by review): recall-anchoring is keyed by statutory identity

Same FPUC statute, same $100/$300/$900 doses, with the operative window moved
to Sept–Dec 2026 — a period with no realized trajectory to recall (the future
arm is never scored; the measurand is dose-response only):

| Period | Elicitation | Monotone in dose | Spread ÷ repeat noise |
|---|---|---|---|
| future 2026 | point+CI or derivation | **6/6 cells** | 2.3–47× |
| retro 2021 | point+CI | **0/3** | 0.2–2.0× |
| retro 2021 | directed derivation | **3/3** | 3.0–10.8× |

The models can derive: in the future arm, fable reads the rate, estimates ~2M
weekly claimants, computes the annualized contribution (9.9/31.2/84.2 for the
three doses — 1:3:9), and composes it onto the baseline. On the memorized
period the same models under default elicitation ignore the dose and return
the remembered trajectory. A decomposed derivation format restores
dose-sensitivity there too.

**Correction from the #61 review (arms deconfounded).** The original arms
differed in name-visibility as well as period; the reviewer's objection was
registered as a new arm and the second branch fired: with the statute name
redacted from the header (nothing else changed), the memorized-period doses go
monotone in 4/4 cells (point+CI: 8.1×/3.0× noise; derivation 7.4×/9.6×) —
where the named version was flat 0/3. The period claim is withdrawn. The
unified account, matching §2: recall is triggered by statutory identity; hide
the name and the model derives from the text even inside its training window;
decomposed elicitation overrides the trigger; reasoning effort does not. A
named-future cell was not run, so a residual period effect is not excluded.

### 3b · Compute does not substitute for structure (Amendment 4)

Reasoning effort (adaptive thinking, low → max; opus-5 and fable-5; 240 runs):
future-period dose-response is monotone at **every** effort level, including
low (~200 completion tokens). Retro-period dose-response stays flat at every
effort level — opus at max effort spends ~4,400 tokens arriving at the same
remembered number (at low effort its retro forecast is 570, the realized
first print to within rounding). **Raising effort does not break
recall-anchoring; restructuring the elicitation does.**

## 4 · The control: mechanical statutory analysis works — and tools close the tier gap

S.3596 (Stronger Start for Working Families Act; CTC phase-in threshold
$2,500 → $1) against 14 PolicyEngine-verified household cases (zero-delta and
partial-delta traps included). Exact-answer rates (±$1), **single-pass runs,
all runs in the denominator — unparseable responses count as wrong** (they are
concentrated in sonnet-without-tools; scoring them out would flatter exactly
the model that failed to answer). n = 70 per cell (14 cases × 5 reps); fable
ran only the full-bill conditions and is marked — elsewhere.

| Condition | haiku-4.5 | sonnet-5 | opus-5 | fable-5 |
|---|---|---|---|---|
| full bill, no tools | 4% | 66% | 100% | 100% |
| full bill + PolicyEngine tool | **100%** | 100% | 100% | 100% |
| §2(a) only (conforming amendment withheld), no tools | — | **50%** (30% on partial-delta, n=20) | 100% | — |
| §2(a) only + tool | — | 100% | 86% (85% partial-delta) | — |
| plain-English summary, no tools | — | 94% | 100% | — |

Multi-agent pipeline (extractor→analyst→critic→judge), full bill: opus 100%
with or without tools (n=70 each); sonnet 50% without tools, 100% with
(n=70 each) — the pipeline does not substitute for either capability or tools.

Three facts: **the tool converts every model to 100%** (haiku 4→100); the
**statutory trap works** — the verbatim-but-incomplete excerpt is *worse*
input than a plain description for sonnet (50% vs 94%); and **tools fix
arithmetic, not extraction** — opus with the tool but the incomplete excerpt
dips to 86%, feeding a mis-extracted threshold into a correct calculator.

Put §3 and §4 together and the architecture writes itself: **compute the
statutory leg mechanically (PolicyEngine, full text), never inside the
forecast — the LLM demonstrably substitutes memory for derivation exactly
there.** (PolicyEngine is used here as the reference implementation of the
statutory arithmetic; per house convention it remains a model input, never
ground truth for behaviour.)

## 5 · Out-of-sample accuracy (28 units, 5 laws; every arm on matched units)

Corpus B expanded to 28 units within the same four events (target months added,
first prints frozen before their runs). All arms scored with the house CRPS,
normalized by each unit's history dispersion; the Winkler interval score
(proper for the 80% interval — it charges for width and for misses, so neither
over-narrow nor over-wide intervals can win it) guards against single-metric
optimisation. Canonical batch pinned per `CHECK2.md`.

| Arm (all N=28 unless noted) | nCRPS | Winkler | cov80 | width % | vs naive same-model |
|---|---|---|---|---|---|
| **fable · bill · effort=max** | **0.208** | **1.30** | 0.75 | 7.4 | **−0.084 [−0.164, −0.008]** |
| opus · no-bill (naive) | 0.253 | 1.61 | 0.82 | 11.9 | — |
| opus · bill · effort=max | 0.247 | 1.48 | 0.79 | 10.9 | −0.006 [−0.046, +0.042] |
| opus · max-effort instruction variants (plain/premortem/ref-class/quantiles, n=26–27) | 0.24–0.26 | 1.5–1.6 | 0.68–0.90 | 9–12 | n.s. |
| structured scaffolds (scenario/auditor/persona, n=27–28) | 0.25–0.27 | 1.5–1.8 | 0.83–0.89 | 10–15 | n.s. |
| persistence | 0.326 | 2.20 | 0.64 | 6.9 | — |
| drift | 0.321 | 2.80 | 0.57 | 6.9 | — |
| fable · no-bill (naive) | 0.292 | 1.84 | 0.66 | 8.3 | — |
| fable · bill · default effort | 0.339 | 2.05 | 0.61 | 9.2 | +0.047 vs fable naive |

Three results, ranked by strength:

1. **One configuration significantly beats both its naive elicitation and
   persistence.** fable+bill+max-effort: −0.084 [−0.164, −0.008] vs naive
   (20/28 units) and **−0.118 [−0.211, −0.035] vs persistence** (22/28), while
   leading the Winkler interval score at 0.75 coverage — no metric traded
   away (narrower arms exist only at collapsed coverage; CHECK2.md item 12). Its wins
   spread across all four events (per-event nCRPS 0.12–0.28). The naive-
   comparison CI's upper bound is −0.008: significant at the nominal level,
   marginal under multiplicity correction; the persistence comparison is the
   robust one.
2. **The effort × bill-context interaction, with mechanism.** The same fable
   recipe at default effort is among the worst arms (+0.047 vs its naive
   baseline). Decomposition: the damage is point error (+0.082 SD; widths
   unchanged), concentrated on Medicaid-unwinding and WEP/GPO units, and the
   direction is overshoot — the bill pushes forecasts further along the
   statute's implied direction, past the truth (worst case: a near-correct
   baseline plus an aggressively sized one-time-payment adjustment that the
   series' SAAR convention multiplies by 12). At max effort the same
   adjustment is sized correctly and the recipe leads the board: effort
   disciplines the magnitude of bill-triggered adjustments rather than their
   direction.
3. **Ornate scaffolds bought nothing.** Instruction styles and multi-stage
   scaffolds (scenario mixture, variance auditor, persona pool) cluster at or
   below the plain arms on matched units. The gains all came from model tier,
   reasoning effort, and aggregation (median-of-k improves monotonically,
   0.243 → 0.231 for k=1→5); none came from architecture.

**Changing only the reasoning-effort parameter.** Identical model, prompt and
bill text; only the reasoning-effort setting changes (default → max). fable:
−0.131 [−0.205, −0.062] (39% lower mean nCRPS, 19/28 units), rising to 53%
and 10/10 on big-shock units (−0.335 [−0.439, −0.231]); largest single-unit
swings 0.98→0.36 and 0.85→0.30. opus: −0.014 [−0.038, +0.015] (5%, n.s.).

**Heterogeneity by realized shock size (objective stratifier: |first print −
last history value| > 1 history SD).** On the 17 big-shock units the leading
configuration beats persistence 17/17 (−1.016 [−1.606, −0.480]) and its naive
same-model configuration 16/17 (−0.225 [−0.342, −0.131]); on the 19 quiet
units both comparisons are null. The margin concentrates exactly where a
statute moves the series. The stratifier is ex-post (it uses the realized
move) and is reported as a description of where the skill lives, not a
selection rule.

**Cross-type confirmation (N=36; committed as an extension before its runs).**
Eight new units across four additional bill types (retro tax-parameter: ARPA
§9611 advance CTC; appropriations: IIJA div. J highways; business-side tax:
§301 tariffs → customs duties; administrative sunset: FRA §271 loan restart)
joined the corpus with independently verified first prints. On the pooled 36
units the headline arm beats its naive same-model configuration
**−0.094 [−0.174, −0.022]** (26/36) and persistence **−0.518 [−0.863, −0.228]**
(29/36); it is near-exact on the advance-CTC pulse (nCRPS 0.08 — the phase-in
window is written in §7527A and the model prices it) and best-or-tied on
tariffs and the loan restart. The pooled persistence margin is flattered by
the new units' catastrophic mechanical baselines; the per-family table is in
`results/final_multimetric.json`. New-type arms ran on a second API transport,
recorded per run.

**Amendment 7, falsified as registered.** A booking-profile elicitation (an
explicit series-convention step: SAAR scaling, lump-sum month, outlay lag)
targeted the leader's diagnosed residual error class. It lost overall
(+0.076 [+0.038, +0.117], 12/36 wins vs the leader) and lost on the very
class it targeted (+0.100 [+0.051, +0.151]), with coverage falling 0.77→0.59.
On the single worst prior unit it worked exactly as designed (named the SAAR
convention, booked 55 instead of the default-effort +125-class overshoot);
everywhere else, mandating an explicit booked contribution manufactured
adjustments the implicit max-effort path had correctly sized to about zero.
Structure that changes what must pass through the answer fixes validity;
structure that mandates a quantity the model would otherwise implicitly zero
injects error. The diagnosis (booking-timing residuals) stands; this cure is
ruled out.

Composition (baseline + mechanical delta) cannot be validated on backtests —
a recall-informed baseline already contains the enacted policy, so adding the
mechanical delta double-counts it. Composition is scored only in the forward
program (§6).

## 6 · Forward registration — making it a live experiment

Retrospective validation is the rehearsal; the lab's own machinery is the real
instrument. `forward/` (in progress at time of writing) registers per-config
lanes on already-registered, near-resolving Thesis targets, so harness
sensitivity resolves *mechanically, out of training distribution*, under the
lab's chronology verification, over the coming weeks and months.

## 7 · Instrumentation defects caught and corrected (all documented, none silent)

1. **max_tokens truncation** correlated with elicitation verbosity (a measured
   dimension) — 9 runs quarantined and re-run.
2. **The prose parser read calendar years as forecasts** — 214 runs, 70% of
   free-text; corrected *offline* from stored responses (`reparse.py`), v1
   parses preserved; caught by the scorer pin looking for something else.
3. **Thinking-budget exhaustion** produced empty responses on the CTC arm (157
   quarantined, re-run at raised caps).
4. **A backwards direction comment** on the perturbation arm and a wrong
   commit-time claim in an earlier draft of this file — both recorded in
   Amendment 1 §F.
5. RED_TEAM's corrections to our own statistics (§1).

Each of 1–3 was non-random with respect to a measured dimension — precisely
the class of artefact this study exists to detect, caught by its own
machinery.

## 8 · What none of this supports

N = 20 retrospective units across 5 laws; 12 of them are 6 states × 2 months
and not independent; every dimension is measured at one reference config;
retrospective accuracy on in-training-window targets is an upper bound;
D2 is clustering-fragile; the bake-off is N=8. No claim generalises beyond the
programs tested without further corpora. State N. Always.

---

## The three sentences

> We backtested the forecasting leg against five enacted laws with frozen
> first-print ground truth, pre-registered before the first run — then held
> the bills fixed and changed only the scaffolding nobody reports: model
> choice moves the forecast twelve times its sampling noise, and showing the
> model the bill made it *more confident and less calibrated* in twelve of
> twelve units.

> When we rewrote a statute's operative numbers — a forty-year swing in a
> work-requirement age cap, a tripled unemployment supplement — the forecasts
> didn't track the change at any model tier, while the same models computed a
> bill's household tax effect to the dollar once PolicyEngine was in the loop;
> the models derive mechanics but recall forecasts.

> So the architecture conclusion is: compute the statutory leg mechanically,
> never inside the forecast, report your harness with your number — and we've
> started registering per-config forward forecasts in the lab so this measures
> itself, contamination-free, from here on.
