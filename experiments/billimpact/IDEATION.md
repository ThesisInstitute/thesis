# IDEATION — generalisability audit, demo steelman, and the one missed experiment

**2026-07-31 ~15:40 EDT, written against what EXISTS on disk** (RESULTS.md, amendments 1–3,
RED_TEAM.md, A5 = `runs_amend5.jsonl` [complete, 300/300 rows, verified by direct
recomputation for this doc], `forward/FORWARD-S3596.md`). Nothing below cites a pending
result. In-flight arms (scenario-mixture, variance-auditor, persona-pool in `runs_mas.jsonl`;
instruction variants in `runs_instr.jsonl`; effort scaling) are treated as unavailable and
un-duplicated. Bill/section/series identifiers proposed in §1 are marked **(verify)** where
this session could not confirm them against a fetched source — per house rules they are
candidates to check on govinfo, not asserted facts.

---

## 1 · Generalisability audit

### 1.1 What the corpus actually is

One sentence that should appear, verbatim or near it, in any honest scope statement: **every
covered event is a transfer to persons, read through a persons-side series.** Corpus A is
FNS/Census state SNAP *recipient counts*; corpus B is four BEA personal-current-transfer
components (UI, Social Security, Medicaid, veterans' benefits); S.3596 is household tax
arithmetic plus two persons-side forward targets (SPM child poverty, CTC qualifying
children). No covered bill's primary effect lands on production, prices, private compliance
behaviour, agency operations, or federal outlay pacing. The corpus is deep on one column of
the bill-type matrix and empty on the rest.

### 1.2 Type-by-type classification

| Bill type | Covered by | Depth |
|---|---|---|
| Eligibility restriction (conditions on receipt) | SNAP ABAWD, FRA §§311–314 | **Dense**: 2,520-run grid + arm K + A5 future-move replication |
| Flat dollar supplement (temporary) | FPUC, CAA-2021 div. N §203 | **Dense**: arms J/A3/A4 + A5 window-dose; the causal workhorse |
| Eligibility-protection sunset (coverage floor removal) | Medicaid unwinding, CAA-2023 §5131 | Thin: 2 bake-off units (+12 in `corpus_extra2`), no dose evidence |
| Indexed increase (COLA) | Vet COLA, PL 118-6 §2 | Thin: bake-off only |
| Benefit-formula repeal (+ retroactive lump sums) | SSFA, PL 118-273 §§2–4 | Thin: bake-off only; the lump-sum surge is in the 2025 units but never isolated |
| Tax-parameter change, household/refundable credit | S.3596 §2 | **Split**: mechanical leg saturated (100% with tool); forecast leg = 2 configs of unresolved forward deltas, zero retrospective evidence |
| Appropriations (agency-paced discretionary outlays) | — | **Uncovered** |
| Program creation (no prior series) | — | **Uncovered** |
| Program sunset as benefit-dollar cliff | provision verified (EA sunset §503(b)), dropped on indicator | **Uncovered** (indicator gap, not provision gap — CORPUS_EXTRA_NOTES §6b) |
| Regulatory mandate on private actors | — | **Uncovered** |
| Agency reporting / administrative duty | — | **Uncovered** (and mostly *unindicatable* — see below) |
| Business-side tax parameter | — | **Uncovered** |
| Funding-formula change (e.g. FMAP phase-down) | present *inside* §5131, never isolated as its own dose | **Unmeasured** |

### 1.3 Which findings transfer, per type — falsifiable bets, not vibes

- **D4 (model tier dominates)** — *bet: transfers everywhere.* Already replicated
  out-of-corpus (bake-off: sonnet+bill loses to persistence while fable beats it). The one
  finding I would defend on any bill type unseen.
- **Recall-anchoring** — *transfers as a function of (statute fame × period
  distinctiveness), not of bill type.* A5 already shows the gradient: FPUC (famous statute,
  unmistakable period) future/retro dose-spread ratios 2.3–47×; SNAP age caps (same period
  logic, second-order channel) 1.63× vs 0.44×. Prediction: maximal on ARPA-CTC (below),
  attenuated-to-absent on obscure reporting mandates — where the failure regime flips from
  recall to derivation-failure, a *different* product risk that the current evidence does
  not measure.
- **Bill-in-prompt hurts calibration** — *weakest transfer bet.* Demonstrated on 12
  non-independent SNAP units at one config; mechanism plausibly = contamination (named
  statute prices the remembered outcome), which predicts it *reverses* on genuinely novel
  bills. This is exactly what the forward lanes exist to settle; do not claim it as a
  general law on stage.
- **Tools → 100%** — *transfers only inside PolicyEngine's schema* (household tax/benefit
  arithmetic). For appropriations, regulatory mandates, business-side taxes there is no
  calculator to hand the model, so the architecture prescription ("compute the statutory
  leg mechanically") is currently **unactionable on the uncovered types** — the honest
  statement is that the forecast leg is unprotected precisely where the mechanical leg has
  no engine. Say this before someone else does.
- **Directed-derivation rescue** — *bet: transfers where the statutory chain is first-order
  arithmetic* (dollars×volume, window-length, COLA %) — A5's window-dose linearity
  (contributions ≈ 0/13/29 for none/half/full month, 5–10× noise) is the second
  parameter-type confirmation. Prediction: **fails on appropriations**, where outlay pacing
  is agency behaviour with no arithmetic identity — a registered prediction worth having on
  record before the corpus exists.

### 1.4 Minimal additional bill set (core 3 + 2 stretch)

Chosen for: real and fetchable on govinfo, type-novel, indicator with first prints, and no
collision with candidates the team already dropped (CORPUS_EXTRA_NOTES §6).

1. **ARPA, Pub. L. 117-2, §9611 (verify section) — 2021 CTC expansion + advance payments.**
   Type: refundable-credit parameter — **the demo bill's own type**, retrospective. Text
   already fetched (`bills/ARPA-2021-117publ2.txt`). Indicator: monthly advance-CTC
   disbursements, Jul–Dec 2021 (Treasury MTS line item / IRS monthly statements —
   **(verify)**; needs the direct-ingestion path the team's own notes prescribe for
   USDA-FNS). Why: a step function like FPUC, on the statute family S.3596 belongs to;
   also the maximal recall-anchoring stress test (most famous transfer of the decade).
   Closes the loop between the mechanical arm and the forecast leg on one type.
2. **IIJA, Pub. L. 117-58, div. J supplemental appropriations (highway/bridge) (verify
   division/section).** Type: appropriation, agency-paced outlays. Indicator: Census Value
   of Construction Put in Place, public highway-and-street, monthly, heavily revised
   (FRED-hosted; mnemonic ≈ TLHWYCONS **(verify)** — same og:title workaround as
   CORPUS_EXTRA_NOTES §0). Why: no persons-side mechanics, no PolicyEngine coverage, and
   the registered prediction that derivation-rescue *fails* here is the most informative
   possible outcome either way.
3. **IIJA §60502 (verify) — Affordable Connectivity Program creation** (amending CAA-2021
   §904's EBB). Type: program creation, empty history block. Indicator: USAC ACP enrollment
   tracker (public; direct ingestion). Why: no base rate to anchor and nothing to recall at
   creation — isolates pure derivation; the 2024 funding exhaustion yields a sunset unit
   from the same series for free.
4. *(stretch)* **CAA-2023, Pub. L. 117-328, div. HH §503(b) — SNAP emergency-allotment
   sunset.** Provision already verified and quoted by the team; dropped only because FRED
   lacks a monthly benefit-dollar series. USDA-FNS monthly benefit-cost ingestion (the
   notes' own named fix) makes it the cheapest type-add on the board: benefit-dollar cliff.
5. *(stretch)* **No Surprises Act, CAA-2021 div. BB.** Type: regulatory mandate. Include it
   *as* the indicator-identification stress case: no monthly first-print series measures
   the mandated quantity, and demonstrating that the product's failure mode on this type is
   upstream of forecasting (indicator selection, not forecast accuracy) is itself the
   deliverable.

With 1–3 landed, the claim upgrades from "five transfer programs" to "transfer, tax-credit,
appropriation, and program-creation types"; regulatory mandates and reporting duties remain
named exclusions. All three reuse the existing fetcher/harness pattern; the new cost is two
ingestion adapters (MTS/IRS, USAC) — a week-scale add, not a rebuild.

---

## 2 · Steelman the demo

### 2.1 The 90-second narrative (exists-only; ~210 words)

> Every bill-impact tool has a layer nobody reports: which model, what context, what
> question format. We held the bills fixed and moved only that layer — about 5,600
> preregistered runs across five enacted laws, first-print ground truth, and a red team
> whose corrections are applied in the published numbers, not hidden.
>
> Three results. The harness is the forecast: swap the model and the number moves twelve
> times its permutation null — more than any statutory rewrite we tested, and the only
> effect that survives Bonferroni. Showing the model the bill made it more confident and
> less calibrated: intervals narrowed in twelve of twelve units while coverage fell.
> And the one that matters — rewrite a statute's operative numbers, a forty-year swing in
> SNAP age caps, a tripled unemployment supplement, and forecasts on remembered periods
> don't move; relocate the same statute to 2026, where there is nothing to remember, and
> dose-response snaps monotone. Recall-anchoring, proven causally, replicated on a second
> statute family this afternoon. Maximum reasoning effort doesn't break it; restructured
> elicitation does; and with PolicyEngine in the loop the same models compute the demo
> bill's household deltas to the dollar at every tier.
>
> So the architecture: statutory leg in the calculator, bill out of the forecast prompt,
> harness config shipped with every number — and the S.3596 forward forecasts are
> registered in the ledger, scoring themselves mechanically from here on.

### 2.2 The three hardest hostile questions, with the honest answers

**Q1 — "You proved recall-anchoring on one statute family. Why should I believe it
generalises?"**
Honest answer: as of A5 it is two families and two parameter types, with the caveats
stated. SNAP age caps, future-moved to FY2027–29: median dose-spread ratio 1.63× the
repeat-noise floor versus 0.44× on the retro period; 6/8 future cells monotone in the
registered direction versus 0/8 retro (both failures are opus under the *default*
elicitation — consistent with the A3 mechanism, since decomposed elicitation goes 4/4).
That is weaker than FPUC's 2.3–47×, and the gap is informative rather than embarrassing:
FPUC's chain is arithmetic (dollars × claimants), the age-cap chain runs through an
exemption-share elasticity, and a smaller spread on a second-order channel is what a
*deriving* model should produce. The window-length variant adds a different parameter type
— dates, not dollars — tracking linearly at 5–10× noise. So the defensible claim: the
phenomenon is a property of (memorized period × default elicitation), shown in two statute
families, two parameter types, three models; the period-move test is ~30 minutes per new
family; and the forward registrations are the version of this question that scores itself.
What we do not claim: coverage of the bill types in §1's uncovered rows.

**Q2 — "Your own red team says the published dispersion test was mis-specified and only D4
survives multiple comparisons. Why trust any of it?"**
Honest answer: yes — the ratio>1 threshold was wrong (the null ratio is 0.12–0.52 by level
count), the red team found it by reproducing every published number first, and the
permutation restatement *strengthened* the headline (D4 at 12.4× its null, p<0.0003;
D1/D2 remain significant by permutation but D2 flips under state clustering and level
composition, so it is labelled suggestive). Both constructions are published; nothing was
re-run to reach the better-looking one. Effective n on the SNAP grid is ~6 after
within-state correlation; N is stated at every claim. And the meta-answer is the talk
itself: a study about instrumentation artefacts caught five of its own — parser, truncation,
thinking-budget, all non-random with respect to measured dimensions — which is the
strongest argument on offer that harness disclosure belongs next to every published number.

**Q3 — "Contamination cuts both ways: your no-bill arm already knows the outcome, so
'the bill doesn't help' is itself a backtest artefact. What actually survives?"**
Honest answer: correct, and RESULTS §5/§8 say so — retro accuracy is an upper bound and the
no-bill arm is contaminated *in the model's favour*, which biases against finding
conditioning value; the striking part is that the bill still failed to help and actively
hurt calibration, with the mechanism identified (the purpose-clause decomposition: name the
statute and forecasts move −2.65%; redact the name and the effect collapses). Surviving
claims, in order of robustness: the dispersion results (bills and truths fixed across arms,
so contamination is symmetric — harness choice moves the number regardless); the causal
recall test (immune by construction — the future arm has no realized value); the mechanical
arm (PolicyEngine-verified, history-free); and the forward lanes, which exist because
nothing retrospective settles absolute skill. What does not survive: any absolute accuracy
level, and the bake-off magnitudes (N=8, directional).

*Also be ready for, one line each:* "PolicyEngine as ground truth is circular" — per house
convention it is the reference implementation of statutory arithmetic, a model input, never
behavioural ground truth; traps (zero-delta, partial-delta) were in the case set, and the
§2(a)-only arm shows tools fix arithmetic, not extraction (opus dips to 86% feeding a
mis-read threshold into a correct calculator). "Debate was null" — no *magnitude* effect,
but it raises the forecast in 8/9 moving units (p=0.039) and inflates within-cell variance
5.4×; do not say "makes no difference" — someone will run the sign test.

---

## 3 · The missed idea (one, buildable in <1 h)

### The harness-sensitivity envelope of the demo bill's own registered forecast

**The gap.** Every dispersion number lives on retrospective spending programs; the demo
bill is a *tax* bill, and its two registered forward deltas were produced under exactly two
configs (opus/fable, one context construction, one elicitation, 3 reps). Model tier already
moves the poverty delta from −0.10 to −0.15pp and the uptake delta from +0.2 to +0.3M —
a 50% relative swing, on the study's own headline mechanism (D4), sitting unexamined in the
demo's flagship artifact. The obvious hostile question — "is the number you just registered
harness-robust?" — currently has no answer. It is also the cheapest way to put *any*
forecast-leg dispersion datum on a tax-parameter bill, the type §1 flags as uncovered.

**Design (commit as PREREG-AMENDMENT-6 before the first call; ~10 lines).**
- **Targets:** the two registered S.3596 targets, exactly as in
  `s3596_conditional_runs.jsonl` (current-law vs enacted, delta per rep).
- **Grid:** context {full_bill, operative_only (§2(a)+conforming), plain_summary,
  parameter_only ("refundable-CTC earned-income phase-in threshold $2,500 → $1, TY2026+")}
  × elicitation {paired direct, decomposed (baseline + delta as its own field)} ×
  {opus-5, fable-5} × 3 reps = 48 calls/target, **96 calls total** (~15–20 min at existing
  concurrency; reuses `forward/forward_harness.py` prompt machinery and
  `bills/S3596-stronger-start.clean.txt`).
- **Measurand:** per-config median delta; envelope = range of config medians vs
  within-config rep range — the corpus grid's own construction, so its null caveats carry
  verbatim. Nothing is scored; no truth exists; the measurand is spread, so the
  fabrication surface is zero.
- **Registered predictions:** (i) the poverty delta's *sign* survives all 16 configs;
  (ii) the uptake delta (a behavioural claim, not mechanical) loses its sign under
  `parameter_only`; (iii) tier contributes more envelope than context, consistent with D4.
  Any outcome is reportable.
- **Demo payoff:** one table — "the number we registered an hour ago, under 16 harnesses."
  Tight envelope → the forward instrument is robust and you say so. Wide envelope → the
  disclosure argument demonstrated live on the product's own demo bill, and the
  registration is amended to carry the envelope, not the point. Either way the close
  writes itself: the study's finding, applied reflexively to the study's own forward
  instrument, on the bill in front of the audience.
- **Non-duplication check:** in-flight arms (scenario-mixture, variance-auditor,
  persona-pool, instruction variants, effort scaling) are all FPUC-retro accuracy arms;
  the forward pack is single-config-per-model. Nothing currently varies harness on the
  registered S.3596 deltas.

*Considered and passed over, for the record:* (a) a "contamination premium" number —
composed baseline+derived-contribution vs direct forecast on memorized FPUC targets,
computable largely from existing A3/J decomposed runs, but N=1–3 scored units makes it an
anecdote wearing a statistic; (b) an inter-model-agreement contamination detector
(suspiciously tight cross-model consensus on memorized periods), free from existing runs
but confounded by future targets being intrinsically more dispersed — worth building the
week after, not in the next hour.
