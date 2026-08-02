# Amendment 3 — the causal test of recall-anchoring (period-moved dose-response)

**Written 2026-07-31 ~12:20 EDT, committed before its first run.** Post-hoc
amendment; every rule below frozen before any Amendment-3 model call.

## Motivation

Arms J/K/P established that forecasts fail to track statutory content on
*retrospective* targets (FPUC dose-response 0/6 monotone; SNAP deltas
non-tracking; the purpose effect name-driven). All of those targets sit inside
training data, so two explanations remain entangled:

- **Recall-anchoring** — the model predicts the remembered realized world and
  ignores the counterfactual text;
- **Derivation failure** — the model cannot propagate a statutory parameter
  into a quantitative forecast at all.

Moving the *same statute* to a period with **no realized trajectory to recall**
separates them.

## Design

**Stimulus.** The verbatim FPUC provision (Pub. L. 116-260 div. N §203) with
exactly four labelled substitutions: the three operative dates moved to a
2026 window (supplement in force for weeks beginning after 2026-09-04 and
ending on or before 2026-12-26) and the inserted rate set per dose. Presented
as "the text of a bill now pending before Congress; assume it is enacted and
in force through the target month." Text is otherwise identical to the retro
arm, so the only differences between arms are the period and the existence of
a memory.

**Periods.** `retro2021` — the real unit `fpuc300.us.2021-01` exactly as in
arm J (history at the 2020-12 origin vintage). `future2026` — target
**November 2026**, history = last 60 months of `W825RC1` at today's vintage
(through 2026-06, level ≈ 35–36). No truth exists for the future arm and none
is ever scored; the measurand is **dose-response only**.

**Doses.** $100 / $300 / $900 weekly (same substitution machinery as arm J).

**Grid.** period {retro2021, future2026} × dose {third, actual, tripled} ×
model {sonnet-5, opus-5, fable-5} × elicitation {point_ci_json,
derivation_json} × 5 reps = **360 runs**.

**New elicitation `derivation_json`** (the maximal-structure arm): the model
must state, as separate JSON fields, the weekly supplement rate it read from
the text, its estimate of eligible weekly claimant volume, the computed
mechanical contribution in the series' units, the no-policy baseline, and
point + 80% CI. Tests whether explicitly-directed derivation rescues
dose-tracking.

## Metrics (per period × model × elicitation)

1. **Monotonicity**: median(third) < median(actual) < median(tripled).
2. **Dose spread**: range of dose medians ÷ within-cell repeat range (the same
   noise-floor construction as the main grid, with its known conservatism).
3. **The causal contrast (primary)**: dose spread in `future2026` minus dose
   spread in `retro2021`, per model × elicitation.
4. For `derivation_json`: does the *stated* supplement rate equal the dose
   ($100/300/900), and does the *computed contribution* scale with it — i.e.
   where exactly does the chain break, extraction or composition?

## Registered predictions

- **Recall-anchoring** ⇒ future2026 shows monotone dose-response with
  first-order spread while retro2021 stays flat (replicating J).
- **Derivation failure** ⇒ flat in both periods, including under
  `derivation_json`.
- **Elicitation rescue** ⇒ `derivation_json` monotone in both periods while
  `point_ci_json` is flat — the failure was elicitation all along.
- Mixtures reported as observed. The future arm is never scored for accuracy;
  no realized value exists and none will be claimed.

## Null

No dose spread anywhere above the repeat noise floor.

---

## Deconfound arm (appended ~15:10 EDT, committed before its runs; responds to the #61 review)

The review is correct that the original arms differ in statute-name visibility
as well as period: the retro header names Pub. L. 116-260, the future header
does not — and §2 of this study shows the name alone moves forecasts. New arm:
retro2021, identical dose machinery, with the header anonymized to match the
future arm's framing ("verbatim text of a statute; assume it is in force
through the target month"; no law name, no public-law number). opus-5 and
fable-5 × 3 doses × {point+CI, directed derivation} × 5 reps. Registered
predictions: if recall-anchoring is period-driven, unnamed-retro stays flat
under point+CI (matching named-retro) and derivation still restores tracking;
if the original flatness was name-driven, unnamed-retro shows dose-response
and the period claim must be withdrawn in favor of a name claim. Either
outcome is reported.

**Deconfound arm result (~15:25 EDT).** The second registered branch fired.
Unnamed-retro is monotone in dose in 4/4 (model × elicitation) cells —
point+CI: fable 8.1×, opus 3.0× repeat noise; derivation 7.4×/9.6× — where
named-retro under point+CI was flat 0/3. The period attribution in this
amendment's original framing is withdrawn: name-redaction alone restores
dose-response on the memorized period, matching the future arm. The
parsimonious account, consistent with the §2 name decomposition, is that
recall-anchoring is keyed by statutory identity. A named-future cell was not
run, so a residual period contribution is not excluded; identity is
demonstrated sufficient. (60 runs, 60 parsed, second transport.)

---

## Appendix (registered 2026-07-31, committed before any run): knowledge probe + fictional-identity arm

**Knowledge probe** (`knowledge_probe.py` -> `runs_probe.jsonl`). Recall
questions with NO forecasting frame: "as first published, what was the value
of {series} in {month}?" — anchored variant (last 12 history rows, ending
before the asked month) and bare variant (no history). opus-5 and fable-5,
3 reps per variant, all 36 accuracy-corpus units, no reasoning-effort param,
JSON answer + self-classified basis (known/estimate/guess). Classifier fixed
in advance: a unit is KNOWN to a model iff median |recall − first print| /
history pstdev < 0.5 across that model's anchored reps (sensitivity reported
at 0.25 and 1.0; bare variant reported as a stricter secondary). Payoff runs
on EXISTING forecast records only: stratify the registered
fable·bill·max-vs-naive and vs-persistence contrasts by KNOWN/UNKNOWN.
Branches committed now: skill surviving on UNKNOWN units = evidence of
genuine retrospective derivation; skill collapsing on UNKNOWN units =
contamination quantified and reported as such, not softened; the per-unit
recall-error vs forecast-error correlation is reported either way.

**Fictional-identity arm** (`fictional_sweep.py` -> `runs_fictional.jsonl`).
Same 36 units, real history values (scoring unchanged), ONE builder for both
frames so the paired contrast never crosses builders; frames differ only in
identity slots. REAL frame: true series title + FRED id + statute citation.
FICTIONAL frame: generic type description (no proper nouns), no series id,
the deconfound redaction extended to the statute's own short title (the
selfcheck caught an operative text repeating it inline), an explicit
self-contained-hypothetical instruction, and a post-forecast self-report
(recognized: none/suspected/identified + series_guess) as a MANIPULATION
CHECK, not a gate. Both frames carry the same in-force clause; operative
sections joined in registered order as in build_context_b. Calendar dates
and dollar amounts retained — mechanism, not identity; residual
identifiability through them is what the self-report measures. Config
mirrors the winning cell: fable-5, bill context, point+80% CI JSON,
effort=max, 3 reps per frame (216 calls). Analysis: paired real-vs-fictional
per unit (paired bootstrap seed 20260731 + sign test), overall and
stratified by probe KNOWN/UNKNOWN. Branches committed now: fictional-frame
accuracy holding on probe-KNOWN units = derivation demonstrated where recall
was available; collapse on KNOWN with survival on UNKNOWN = recall
dependence quantified per-unit. Recognition rate reported alongside
whichever branch fires.
