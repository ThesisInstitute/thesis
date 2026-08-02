# RED TEAM — adversarial audit of the bill-impact dispersion results

**Written 2026-07-31, ~1h before presentation.** Brief: assume every finding is wrong and
find out why. Everything below was RUN, not reasoned about; throwaway scripts live in the
session scratchpad (`rt_null.py`, `rt_direction.py`, `rt_denominator.py`, `rt_reparse.py`,
`rt_p4.py`, `rt_seed_cluster.py`, `rt_final.py`).

**Reproduction check.** At 10:33 I reproduced every published headline number exactly
(D1 1.806 CI [1.107, 2.652]; D2 1.532 [1.058, 2.286]; D3 0.351 [0.098, 0.763]; D4 4.647
[2.107, 6.464]; D5 1.171 [0.339, 1.940]). The analysis code does what the markdown says it
does. The attacks below are on the *design*, not on arithmetic — with one exception (§0).

---

## 0. READ THIS FIRST — the artefacts do not currently reproduce

Every input to the published results was modified *after* the results were written. Observed
mtimes during this audit (results generated 10:29:14–10:29:57):

| file | mtime | what it means |
|---|---|---|
| `results/*.md`, `summary.json` | 10:29 | the published artefacts |
| `analyze.py` | 10:37:59 → 10:39:04 → 10:47:44 | analysis code edited 3× since |
| `reparse.py` | 10:42:57 | parser edited since |
| `runs_api.reparsed.jsonl` | 10:43:00 → 10:50:17 | **data rewritten twice since** |
| `runs_api.jsonl` | still appending at 10:44:14 | sweep still running |
| `harness.py` | 10:50:52 | **prompt construction edited since** |

The sweep is still running and the prompt builder is still being edited.

Consequence, measured on a 10:44 snapshot: **the D2 row has changed.**

| | spread | noise | ratio | 95% CI |
|---|---|---|---|---|
| published `dispersion.md` (10:29) | 8.40% | 5.49% | **1.532** | [1.058, 2.286] |
| same code, current data (10:44) | 8.10% | 4.67% | **1.734** | [1.186, 2.918] |

Per-unit D2 spreads moved by up to 1.77pp (`snap.ca.2023-12` 19.95 → 21.72) and noise floors
by up to 2.89pp (`snap.fl.2023-12` 7.18 → 4.29). D1, D3, D4 and D5 are byte-identical. Also:
`summary.json` lacks the `median_shift_difference_purpose_minus_operative_pp` key that the
current `analyze.py` emits, confirming the JSON predates the code.

**Verdict: BREAKS (operationally, not scientifically).** Both D2 numbers give EXCEEDS, so no
verdict flips — but a 13% move in a headline ratio from re-running cells at temperature 1.0
is exactly the phenomenon the talk is about, and anyone who clones the repo and runs
`analyze.py` will get numbers that differ from the slide.

**Do before the talk:** stop the sweep, re-run `analyze.py`, regenerate `results/`, and put
the git SHA + a data-file SHA-256 on the artefacts. If there is no time, say the D2 row is
from a 10:29 snapshot and the sweep is still adding runs.

*Audit hygiene note:* all numbers below other than the published-value columns were computed
against a frozen 10:44 copy of `runs_api.reparsed.jsonl`, so they are internally consistent
even though the live file has moved again since. The one check that used `harness.py`
directly (Attack 4's prompt reconstruction) was run before harness.py's 10:50 edit; its
conclusion does not depend on that file, because the corroborating evidence
(`context_meta.substitutions` = 3 on all 120 runs) is stored in the run records themselves.

---

## Ranked: what you will actually be asked, and the honest one-line answer

| # | The question | Honest answer |
|---|---|---|
| 1 | *"Ratio > 1 isn't a null. Your numerator is a range of medians-of-5 and your denominator is a mean of ranges-of-5 — under H₀ that ratio is nowhere near 1."* | Correct, and I got the threshold wrong: under a true null the expected ratio is **0.12–0.52 depending on level count**, not 1. Re-tested by permutation, D1/D2/D4 are *more* significant than reported (all p < 0.001), so the headline survives — but the "> 1" rule is not the test I should have used. |
| 2 | *"You call D3 null, but does debate move the forecast?"* | It does: **debate raises the forecast in 8 of the 9 units where it moves at all, sign test p = 0.039, median +1.04%.** The range statistic throws away sign, so a small consistent directional effect is invisible to it. D3's NULL should be restated as "no *magnitude* effect; there is a consistent *directional* one." |
| 3 | *"Isn't the debate arm's own noise what makes debate look null?"* | Yes. Debate's within-cell range is **5.4× single-pass's** (3.76% vs 0.69%), and the noise floor averages over both arms — the treatment inflates the denominator used to declare it null. Any scaffolding that adds stochasticity is biased toward NULL by construction. |
| 4 | *"Is D1 driven by the preamble arm?"* | Yes, and that is the finding. Drop `purpose_only` and D1 goes **NULL under the published rule** (1.234, CI [0.90, 2.00]); restricted to statutory-text-only levels it is 1.118, CI [0.78, 2.09], NULL. The preamble moves the forecast **~4× more than the operative text** (−2.65% vs −0.69%). |
| 5 | *"Your 12 units are 6 states × 2 months — those aren't independent."* | Correct for D3/D4 (within-state r ≈ 0.96–0.98, effective n ≈ 6). Under a state-clustered bootstrap **D2 flips to NULL** ([0.96, 2.38] published data; [0.97, 2.93] current). D1 and D4 survive. |
| 6 | *"No multiple-comparisons correction anywhere?"* | None applied. FWER across the 5 dispersion tests alone is 0.23; across the ~11 reported CI verdicts, 0.43. **Only D4 survives Bonferroni.** D1 and D2 both go NULL at α = 0.01. |
| 7 | *"P4 elasticity is exactly zero — did the perturbation reach the model?"* | Yes, verified: `substitutions=3` on all 120 severe/inert runs, and I reconstructed the prompts — the age caps really read 31/33/35 vs 71/73/75. **This attack fails; the claim holds.** |
| 8 | *"You say conditioning gives no skill — but which way do the point estimates lean?"* | All four **positive (worse)**, and 80% interval coverage falls from 0.50 to 0.325 while intervals narrow in **12/12 units (p = 0.0005)**. "No detectable skill" is true but soft: the bill makes the model more confident and no more accurate. |
| 9 | *"Why does D5 use 11 units?"* | It drops `snap.ca.2024-03` because its noise floor is exactly zero — i.e. the **most insensitive unit in the corpus**. That is selection on the denominator and it inflates the D5 ratio from 0.97 to 1.17. |

---

## Attack 1 — the noise-floor denominator. **VERDICT: BREAKS the test, STRENGTHENS the finding.**

### The problem
`dimension_spread()` (analyze.py:836–842) computes

- numerator = range over `k` levels of the **median of 5 draws**
- denominator = **mean over `k` cells** of the **range of 5 draws**

and `classify_ratio()` (analyze.py:897–904) declares EXCEEDS when the ratio's CI excludes
**1**. Under a true null those two quantities have different expectations: the SD of a
median-of-5 is ≈0.54σ while the expected range of 5 is ≈2.33σ. The correct null threshold is
`d₂(k) × 0.54 / 2.33`, not 1.

`dispersion.md` §"Two properties of this construction" *states* both problems honestly —
and then does not correct for either. Stating a bias is not the same as removing it.

### Measured null thresholds

Normal-theory simulation (20,000 draws per k) and a within-unit exchangeable permutation on
the real draws (4,000 draws, which handles the model's discrete round-number outputs):

| k levels | normal-theory median ratio under H₀ | 95th pctile | empirical permutation null (real data) |
|---|---|---|---|
| 2 (D3) | 0.223 | 0.697 | 0.124–0.138 |
| 3 (D5) | 0.370 | 0.819 | 0.260–0.284 |
| 4 (D2, D4) | 0.458 | 0.890 | 0.358–0.451 |
| 5 (D1) | 0.522 | 0.943 | 0.442 |

**The published test compares against a threshold 2–8× too high.** It is not conservative in
the way the doc claims — it is *mis-specified*, and the direction of the error happens to be
conservative for the EXCEEDS verdicts and anti-conservative for the NULL ones.

### Corrected numbers (permutation p-values, within-unit exchangeable null)

| dim | k | observed ratio | null median | obs/null | permutation p | published verdict | corrected |
|---|---|---|---|---|---|---|---|
| D1 `policy_context` | 5 | 1.806 | 0.442 | **4.09×** | **< 0.0003** | EXCEEDS | EXCEEDS (stronger) |
| D2 `elicitation` | 4 | 1.734 | 0.358 | **4.84×** | **< 0.0003** | EXCEEDS | EXCEEDS (stronger) |
| D3 `pipeline` | 2 | 0.351 | 0.138 | 2.54× | 0.0012 | NULL | see below |
| D4 `model` | 4 | 4.647 | 0.376 | **12.4×** | **< 0.0003** | EXCEEDS | EXCEEDS (much stronger) |
| D5 `magnitude` | 3 | 1.171 | 0.284 | 4.12× | < 0.0003 | NULL | see below |

**Caveat I will not paper over.** The exchangeable permutation assumes each level has the
same within-cell variance. That is badly false for D3 (debate 5.4× noisier than single-pass)
and false for D5 (inert 3× noisier than actual). So the permutation p-values for D3 and D5
are **not trustworthy**, and I am not claiming D3 and D5 "really" exceed. A heteroscedastic
null built by resampling within each level and re-centring gives D3 p = 0.30 — but that
construction is itself biased upward (a with-replacement resample of 5 values contains both
extremes only 42% of the time, so it systematically deflates the denominator). Neither null
settles D3. **The test that does settle it is directional — see Attack 2.**

### Corrected wording

> Replace "ratio 1.81, exceeds 1" with: *"the observed dispersion is 4.1× the dispersion
> obtained when level labels are permuted within units (permutation p < 0.001, 4,000 draws).
> Ratios are not comparable to 1; the null value of this statistic depends on level count and
> is 0.12–0.52 here."*

Delete the sentence "the expected ratio is below 1, so a NULL verdict is weaker evidence and
an EXCEEDS verdict correspondingly stronger" and replace it with the measured null per row.

---

## Attack 2 — level-count scaling and the discarded sign. **VERDICT: D3's NULL BREAKS.**

### Level count
The permutation null in Attack 1 is computed at each dimension's own `k`, so it is
level-count-invariant by construction. Re-ranking dimensions on `obs/null`:

**D4 (12.4×) ≫ D2 (4.8×) > D5 (4.1×) > D1 (4.1×) > D3 (2.5×)**

versus the published raw-ratio ranking D4 > D1 > D2 > D5 > D3. D2 and D5 move up. The
existing "compare against 1, never against another dimension" caveat is right in spirit but
gives the wrong reason — the fix is not "don't compare", it is "divide each by its own null".

### The sign problem — this is the real break
The range statistic is symmetric in levels and discards direction, so a small but perfectly
consistent shift is invisible to it. Testing D3 directionally (paired, per unit):

```
snap.ca.2023-12  single 4,950,000  debate 4,950,000    +0.000%
snap.ca.2024-03  single 4,950,000  debate 5,000,000    +1.010%
snap.fl.2023-12  single 2,820,000  debate 2,850,000    +1.071%
snap.fl.2024-03  single 2,850,000  debate 2,900,000    +1.754%
snap.ny.2023-12  single 2,850,000  debate 2,900,000    +1.724%
snap.ny.2024-03  single 2,870,000  debate 2,900,000    +1.017%
snap.oh.2023-12  single 1,430,000  debate 1,430,000    +0.000%
snap.oh.2024-03  single 1,440,000  debate 1,430,000    -0.690%
snap.pa.2023-12  single 1,830,000  debate 1,950,000    +6.400%
snap.pa.2024-03  single 1,780,000  debate 1,950,000    +9.290%
snap.tx.2023-12  single 3,450,000  debate 3,450,000    +0.000%
snap.tx.2024-03  single 3,450,000  debate 3,500,000    +1.449%
```

**UP in 8, DOWN in 1, unchanged in 3. Exact two-sided sign test on the 9 non-zero units:
p = 0.0391.** Median signed shift +1.044% (bootstrap 95% CI [0.000, +1.739]). Run-level
Mann-Whitney (60 vs 60, bucketed) p = 0.001. The sign test is unaffected by the
heteroscedasticity that invalidates the permutation null, so this is the clean test.

**Corrected wording for D3:**

> *"D3 `pipeline` — NULL on magnitude: the across-level spread (median 1.04% of the
> unconditioned forecast) is smaller than the within-cell noise floor. But the effect is
> **directionally consistent**: the Skeptic/Verifier/Judge pipeline raises the forecast in
> 8 of the 9 units where it moves at all (sign test p = 0.039, median +1.04%). Adding a
> debate stage does not change the answer by more than run-to-run noise, but when it does
> move the answer it moves it the same way — upward — nearly every time."*

Do **not** say "the debate pipeline makes no difference." Someone will run the sign test.

### Attack 3 (bonus, discovered here) — the self-defeating denominator. **VERDICT: WEAKENS D3 and D5.**

The noise floor is `fmean` over the dimension's **own** cells (analyze.py:839). Per-level
within-cell ranges, median across units:

| dimension | quietest level | noisiest level | ratio |
|---|---|---|---|
| D1 | operative_only 0.69% | none 3.27% | 4.7× |
| D2 | point_ci_json 0.69% | cot_then_json 6.69% | 9.7× |
| **D3** | **single_pass 0.69%** | **debate 3.76%** | **5.4×** |
| D4 | haiku 0.57% | opus 2.43% | 4.3× |
| D5 | actual 0.69% | inert 2.06% | 3.0× |

Any treatment that adds stochasticity raises the denominator it is judged against. D3's
noise floor of 2.97% is more than half contributed by debate itself. Switching the
denominator to the **reference cell only** (a defensible reading of the prereg, which says
only "the range across the 5 repeats within a cell" and never specifies aggregation):

| dim | published (mean over all cells) | reference-cell denominator |
|---|---|---|
| D1 | 1.806, EXCEEDS | 1.428 CI [0.91, 5.19], **NULL** |
| D2 | 1.532, EXCEEDS | 3.392 CI [1.73, 11.03], EXCEEDS |
| D3 | 0.351, NULL | 0.562 CI [0.00, 2.28], NULL |
| D4 | 4.647, EXCEEDS | 2.635 CI [1.54, 9.93], EXCEEDS |
| D5 | 1.171, NULL | 0.848 CI [0.34, 4.00], NULL |

The prereg does not pin this choice, so it is an undocumented researcher degree of freedom,
and **D1's verdict flips under a reasonable alternative**. Say so, or pre-commit to the
mean-over-cells definition in writing and note that D1 is sensitive to it.

---

## Attack 3 — the mid-flight parser correction. **VERDICT: HOLDS.**

I tried hard to break this and could not.

**What it did**, per elicitation level:

| elicitation | n | v1 parsed | v1 point was a YEAR | v2 parsed | changed | rescued | lost |
|---|---|---|---|---|---|---|---|
| point_ci_json | 1620 | 1620 | 0 | 1620 | 0 | 0 | 0 |
| forced_choice_bins | 300 | 300 | 0 | 300 | 0 | 0 | 0 |
| cot_then_json | 300 | 300 | 4 | 297 | 6 | 0 | 3 |
| **free_text** | **300** | **300** | **210** | **299** | **258** | 0 | 1 |
| TOTAL | 2520 | 2520 | 214 | 2516 | 264 | 0 | 4 |

97.7% of all changes are free_text — confirmed asymmetric across a measured dimension, as
the docstring says. **But the [0.2×, 5×] band is not doing the work.** Across the entire
corpus the band rejected exactly **three** numbers: two below (at 0.013× and 0.017× the last
observed value — plainly not caseloads) and one above (12.6×). Zero forecasts were clipped.
`analyze.py`'s independent [0.1×, 10×] plausibility flag fires on **zero** runs.

The rescue is a year-filter, not a scale filter, and it fires on 210/300 free_text runs
because prose says "December 2023". The fix is correct and the band is inert. The four
remaining parse failures are all `max_tokens` truncations, counted and reported.

**Residual (minor, disclose it):** 271/300 free_text runs land in `prose_bracketed_v2`, a
heuristic that takes the first triple satisfying `b<a<c` or `a<b<c`. One run used
`prose_spread_v2`, which takes the *middle of all in-band numbers* — a value the model never
designated. That is 1 run in 2,516; not material, but say the number if asked.

**Does D2 survive dropping free_text?** Under the published rule, **no**: 1.859 CI
[0.98, 2.85] → NULL. But that is the mis-specified threshold again (obs/null = 4.8, still
significant by permutation), not a reparse artefact. The honest statement is that **D2's
verdict is not robust to level composition** — drop free_text *or* forced_choice_bins and it
goes NULL under the published rule:

| D2 level set | ratio | 95% CI | published rule |
|---|---|---|---|
| all 4 | 1.734 | [1.17, 2.92] | EXCEEDS |
| drop point_ci_json | 1.647 | [1.04, 2.28] | EXCEEDS |
| **drop free_text** | 1.859 | [0.98, 2.85] | **NULL** |
| drop cot_then_json | 3.048 | [1.49, 4.50] | EXCEEDS |
| **drop forced_choice_bins** | 0.415 | [0.15, 0.77] | **NULL** |

---

## Attack 4 — P4 elasticity = exactly 0.000. **VERDICT: HOLDS, and can be stated much more sharply.**

### The treatment was applied. Verified three ways.

1. `context_meta.substitutions` = **3 on all 60 severe and all 60 inert runs**, 0 on all
   2,400 actual runs. No exceptions.
2. `prompt_chars` identical across arms (5,785–5,796) — as expected, since the substitution
   swaps two-digit numerals.
3. I reconstructed the prompt from `harness.py` + `provisions.json` and diffed:

```
actual   subs=0 len=3820 ages=['over 51 years of age','over 53 years of age','over 55 years of age']
severe   subs=3 len=3820 ages=['over 31 years of age','over 33 years of age','over 35 years of age']
inert    subs=3 len=3820 ages=['over 71 years of age','over 73 years of age','over 75 years of age']
actual==severe: False   severe==inert: False
```

**This attack fails. The perturbation reached the model.**

### Is the zero a discreteness artefact? Partly — and the fix makes the finding stronger.

The model emits round numbers: 220 distinct point values across 2,516 runs; the modal grid
step is 0.27%–1.01% of the caseload depending on unit. D1's median spread is ~10 grid steps
and D3's is ~3, so the measurement is coarse but not degenerate. Six of the twelve exact
zeros are genuine — the raw draws differ across arms in **11/12 units**, so the model *is*
responding; the medians just land on the same rung.

### The sharper claim the data supports

The interesting structure is not "elasticity ≈ 0". It is that the model **detects that the
text was tampered with and moves — but not in a direction related to the tampering**:

| unit | actual | severe (−20 yrs) | inert (+20 yrs) | |
|---|---|---|---|---|
| snap.ca.2024-03 | 4.950M | 4.950M | 4.950M | no response at all |
| snap.fl.2023-12 | 2.820M | **2.850M** | **2.850M** | severe = inert, both displaced |
| snap.oh.2023-12 | 1.430M | **1.440M** | **1.440M** | severe = inert, both displaced |
| snap.oh.2024-03 | 1.440M | **1.450M** | **1.450M** | severe = inert, both displaced |
| snap.pa.2024-03 | 1.780M | **1.830M** | **1.830M** | severe = inert, both displaced |
| snap.tx.2023-12 | 3.450M | **3.350M** | **3.350M** | severe = inert, both displaced |

**6 of 12 units give literally identical forecasts under a 20-year-stricter and a
20-year-looser rewrite of the same clause, and in 5 of those the forecast has moved away from
the unmodified statute.** Directionally, severe sits *above* inert (the wrong way — stricter
should mean fewer recipients) by a mean of +1.11%, with 4 units wrong-signed, 2 right-signed,
6 tied, sign test p = 0.6875.

**Corrected wording for P4:**

> *"The forecast responds to the fact that the statutory text changed but not to the
> direction of the change. In 6 of 12 units a 20-year-stricter and a 20-year-looser rewrite
> of the identical clause produce the identical median forecast, and in 5 of those the
> forecast has nonetheless moved away from the unmodified statute. Where the arms do differ,
> the sign is wrong as often as right (4 vs 2, p = 0.69). This is not insensitivity to the
> prompt; it is sensitivity to perturbation without comprehension of it."*

That is a stronger, more falsifiable statement than "elasticity ≈ 0", and it forecloses the
obvious rebuttal ("your treatment never reached the model").

### One genuine defect in the D5 line

`dimension_spread` drops any unit whose noise floor is exactly zero (analyze.py:845–846).
For D5 that drops `snap.ca.2024-03` — **the single most insensitive unit in the corpus**
(all 15 draws across all three arms identical at 4.95M). This is selection on the
denominator, and it inflates the result:

- published (11 units): spread 2.13%, noise 1.82%, **ratio 1.171**
- all 12 units: spread 1.75%, noise 1.80%, **ratio 0.969**

Both are NULL, so the conclusion is unaffected, but **the published number is 21% too high
and it is too high for the worst possible reason** — the unit that most supports the
memorisation thesis was excluded because it was too insensitive to divide by. Report 0.97 or
report 1.17 with the exclusion stated in the row, not in a footnote.

Also: D5's bootstrap distribution has only **73 distinct values in 20,000 draws** (top two
atoms carry 9.7% and 9.4% of the mass). A percentile CI on a median of 11 discrete values is
not a reliable interval. Quote D5's CI with that caveat or not at all.

---

## Attack 5 — the horizon confound. **VERDICT: WEAKENS the framing, does not break D1.**

The forecaster sees history to 2021-06 and must forecast 30–33 months out. Measured:

- mean |realised − last observed| = **328,885 persons** (drift 0.4%–27.6% by unit)
- mean CRPS across all 2,516 scored runs = **158,255 persons**
- the entire D1 dispersion (3.54% of a ~2.9M median caseload) = **101,775 persons**

So the whole headline dispersion is **0.64× the mean forecast error the tool is already
making**, and ~0.3× the trend movement it has to predict.

**Both sides:**

*Makes D1 weaker.* Everything is measured on a forecast whose error is dominated by
30-month trend uncertainty. A 3.5% harness-induced wobble sits inside a ±10% error band, so
"scaffolding moves the answer" is a claim about a quantity nobody should be trusting to 3.5%
anyway. And the CRPS/skill leg has essentially no power: the policy signal is a few percent
of caseload against a 328k-person drift.

*Makes D1 stronger.* The prereg says this explicitly (lines 57–65) and predicts it biases
the dispersion test **toward the null** — a wobble at fixed temperature does not get larger
because the horizon is long. It gets *harder* to distinguish from the model's own noise,
because the model's own noise also grows with horizon. Finding a 4× excess over the
permutation null despite that is a result *in spite of* the horizon.

**Which is right: the second, for D1; the first, for the skill leg.** The dispersion test is
a within-forecaster comparison at fixed everything-else, so horizon enters both numerator and
denominator and largely cancels. The *accuracy* test is not protected that way and should be
described as underpowered rather than as a null.

**Corrected wording:** keep the dispersion claim; downgrade the skill claim from "no
detectable skill" to *"this design cannot detect skill at this horizon — the policy signal is
~3% of caseload against a 328k-person, 30-month trend error, and the CIs are correspondingly
uninformative."* The current wording invites "so your experiment couldn't have found skill
either way", and the answer is: correct, and that is a property of the only vintage of this
series that existed at the forecast origin.

---

## Attack 6 — multiple comparisons. **VERDICT: BREAKS D1 and D2 under any correction.**

`primary_analyses.md` states a Bonferroni alpha of 0.0125 for P1–P4 and then **never applies
it to a single confidence interval**. Every CI in every artefact is a 95% percentile CI.

Reported CI-based verdicts: 5 dispersion ratios + 5 pooled-robustness variants + P3 shift +
P4 elasticity + 4 skill levels ≈ 16 interval-based decisions. FWER for independent tests:

| m tests | FWER at α=0.05 | Bonferroni α | required CI level |
|---|---|---|---|
| 5 | 0.226 | 0.0100 | 99.00% |
| 9 | 0.370 | 0.0056 | 99.44% |
| 11 | 0.431 | 0.0045 | 99.55% |
| 16 | 0.560 | 0.0031 | 99.69% |

Recomputing the dispersion CIs at the corrected level (4,000 draws, published data):

| dim | ratio | 95% (published) | 99% (Bonf m=5) | 99.55% (Bonf m=11) |
|---|---|---|---|---|
| D1 | 1.806 | [1.11, 2.66] EXCEEDS | **[0.99, 3.11] NULL** | **[0.89, 3.32] NULL** |
| D2 | 1.734 | [1.17, 2.92] EXCEEDS | **[0.75, 3.20] NULL** | **[0.55, 3.20] NULL** |
| D3 | 0.351 | [0.09, 0.77] NULL | [0.00, 1.03] NULL | [0.00, 1.49] NULL |
| **D4** | **4.647** | [2.16, 6.41] EXCEEDS | **[1.84, 7.80] EXCEEDS** | **[1.77, 7.99] EXCEEDS** |
| D5 | 1.171 | [0.34, 1.94] NULL | [0.33, 3.00] NULL | [0.31, 3.00] NULL |

**Only D4 survives family-wise correction against the threshold of 1.** Against the
*corrected* permutation null (Attack 1), D1, D2 and D4 all survive at m=11 — the permutation
p-values are < 0.0003, well inside 0.0045. So the right move is to fix the null, not to
retreat. But if anyone applies Bonferroni to the published construction, D1 and D2 go.

**Mitigating fact worth having ready:** the five tests are not independent, so the FWER
numbers above are upper bounds. The reference cell
(`operative_only/point_ci_json/single_pass/sonnet/actual`) is a level in **all five**
dimensions — the same 60 runs contribute to every numerator and to 20–50% of every
denominator. That reduces FWER but it also means the five "independent dimensions" share a
common spine, which is worth saying out loud before someone else says it.

**Corrected wording:** *"Verdicts are reported at a nominal 95% interval without family-wise
correction across five dimensions; treat any single marginal verdict (D1, D2) as
exploratory. Only D4 clears Bonferroni against the naive threshold; D1, D2 and D4 clear it
against the permutation null."*

---

## Attack 7 — other findings

### 7a. Unit non-independence. **VERDICT: BREAKS D2, holds elsewhere.**

12 units = 6 states × 2 target months. Within-state correlation of the per-unit spread
(Dec vs Mar), with the design effect for cluster size 2:

| dim | r(Dec, Mar) | design effect | effective n |
|---|---|---|---|
| D1 | +0.110 | 1.11 | 10.8 of 12 |
| D2 | +0.714 | 1.71 | 7.0 of 12 |
| D3 | +0.960 | 1.96 | 6.1 of 12 |
| D4 | +0.976 | 1.98 | 6.1 of 12 |
| D5 | +0.544 | 1.54 | 6.5 of 12 |

For D3, D4 and D5 the two months of a state are effectively **one observation**. The unit
bootstrap therefore overstates precision by up to √1.98 ≈ 1.4× in SE terms.

Clustered bootstrap resampling **states** (6 clusters, both months together, 4,000 draws):

| dim | ratio | unit bootstrap | state-clustered bootstrap | change |
|---|---|---|---|---|
| D1 | 1.806 | [1.107, 2.663] | [1.179, 2.694] | holds |
| **D2** | 1.532 | [1.015, 2.253] | **[0.962, 2.376]** | **EXCEEDS → NULL** |
| D3 | 0.351 | [0.091, 0.770] | [0.152, 1.585] | holds (NULL) |
| D4 | 4.647 | [2.156, 6.408] | [1.913, 7.888] | holds |
| D5 | 1.171 | [0.339, 1.940] | [0.336, 1.885] | holds (NULL) |

On the current (10:44) data D2 clustered is [0.97, 2.93] — still includes 1. **D2 is NULL
under the correct clustering, on both data snapshots.**

Say "N = 12 unit-forecasts from 6 states", and report the state-clustered CI as primary.

### 7b. Seed sensitivity of the published D2 verdict. **VERDICT: BREAKS (published number).**

Running the published D2 bootstrap with 200 different seeds (2,000 draws each, published
data): the CI lower bound ranges **0.891 to 1.078**, and **only 65.5% of seeds produce
EXCEEDS**. D1 (100%), D4 (100%), D3 (0%) and D5 (0%) are seed-stable. On the current 10:44
data D2 is seed-stable at 100%, but the *published* D2 verdict is a coin flip weighted 2:1.

The published artefacts do not record the number of bootstrap draws as a sensitivity
parameter. Raise draws to ≥20,000 for the final run and report the seed.

### 7c. D1's substantive story is the opposite of the headline. **VERDICT: WEAKENS the framing; the underlying result is the best thing here.**

Directional shifts vs `none`, per unit:

| D1 level | median shift | DOWN | UP | ZERO | sign p |
|---|---|---|---|---|---|
| `summary` (plain-English description of the actual restriction) | **−0.35%** | 6 | 1 | 5 | 0.125 |
| `operative_only` (§§311/312/314 verbatim, the real eligibility cut) | **−0.69%** | 7 | 1 | 4 | 0.070 |
| `operative_plus_purpose` | −2.56% | 8 | 1 | 3 | 0.039 |
| **`purpose_only` (§313, a pure statement of purpose, no eligibility change)** | **−2.65%** | **10** | **0** | **2** | **0.002** |

The text with **no operative content** moves the forecast ~4× further than the text that
actually restricts eligibility, and it is the only level clearing Bonferroni. Paired test I
ran that is not in the artefacts (the code computes it —
`median_shift_difference_purpose_minus_operative_pp`, analyze.py:1215 — but `summary.json`
predates that key): **`purpose_only` is more negative than `operative_only` in 8 of the 9
units where they differ, sign test p = 0.039, median gap −1.60pp, bootstrap CI
[−3.17, 0.00].**

`primary_analyses.md` labels this "P3 VERDICT: MIXED" on the grounds that the two shifts are
not *concordant* more often than chance (6/7, p = 0.125). That is a true statement about a
weak test and it buries the strong one. The pre-registered question was whether
`purpose_only` "produces a comparable downward shift" — it does not produce a comparable
shift; it produces a **larger** one.

**Rival explanation I checked and could not fully dismiss:** `operative_only` is 607 words
containing 21 amendatory constructions ("by striking ``or'' at the end and inserting"),
unreadable without the underlying U.S. Code; `purpose_only` is 105 words of plain declarative
English. So "the model responds to legible text, not to operative text" is a live
alternative to "the model treats a preamble as if it were the statute". **But `summary` is
also plain English (95 words), describes the actual restriction, and moves the forecast
LESS than the purpose clause (−0.35% vs −2.65%)** — so legibility alone does not explain it.
Have that exchange ready; it is the sharpest question a careful listener will ask.

**Corrected wording:** promote this from P3-MIXED to a headline. Something like:
*"Conditioning on the bill's statement of purpose moves the forecast down by 2.65% (10/12
units, p = 0.002); conditioning on the operative eligibility restriction moves it down by
0.69% (7/12, p = 0.070). The preamble outweighs the statute in 8 of the 9 units where they
differ (p = 0.039). A legibility confound is possible — the operative text is amendatory —
but the plain-English `summary` arm moves the forecast least of all, which the legibility
story does not predict."*

### 7d. The skill null understates the problem. **VERDICT: WEAKENS (in your favour).**

| level | mean ΔCRPS (normalised) | units worse | 80% coverage | mean width | mean PIT |
|---|---|---|---|---|---|
| `none` (baseline) | — | — | **0.500** | 309,000 | — |
| `summary` | **+0.306** | 7/12 | 0.417 | 267,000 | 0.595 |
| `operative_only` | **+0.221** | 5/12 | 0.317 | 233,833 | 0.613 |
| `purpose_only` | **+0.199** | 8/12 | 0.283 | 289,500 | 0.676 |
| `operative_plus_purpose` | **+0.463** | 8/12 | 0.283 | 242,833 | 0.636 |

All four point estimates are **positive — i.e. worse**. Coverage of a nominal 80% interval
falls from 0.50 unconditioned to 0.325 conditioned. And the mechanism is unambiguous:
**intervals narrow in 12 of 12 units (sign test p = 0.0005, median narrowing 43,250 persons,
−14.0%)**, while accuracy does not improve.

"No detectable skill from conditioning on the bill" is defensible but soft. The measured
pattern is *overconfidence*: giving the model the statute makes it commit harder to a number
that is no better. Per-unit coverage falls in 8/12 (p = 0.109) — directional, not
significant, so state the width result (which is significant) and the coverage level
(which is descriptive), and do not claim the coverage drop is established.

Suggestive but **not** significant, so flag it as such if you use it: conditioning also cuts
run-to-run dispersion (unconditioned median within-cell range 3.27% vs 0.69–1.56%
conditioned; lower in 9/12 units, sign p = 0.146).

### 7e. Bugs in `analyze.py`. **VERDICT: no arithmetic bug found.**

I reproduced every published number from the code. Things that are *design* choices rather
than bugs, but which an adversary will call bugs:

1. **Zero-denominator exclusion** (line 845) — drops the most-insensitive unit from D5.
   Documented above. This is the closest thing to a real defect.
2. **`noise_floor` = mean over the dimension's own cells** (line 839) — the self-defeating
   denominator of Attack 3. Not specified in the prereg.
3. **Percentile bootstrap, not BCa** — with n=12 and a heavily atomic statistic (D5: 73
   distinct bootstrap values in 20,000 draws) the percentile CI is not trustworthy. D1 (877
   atoms), D2 (583), D3 (673) and D4 (849) are better but still coarse.
4. **Shared reference cell** — the same 60 runs are a level in all five dimensions and 20–50%
   of every noise floor. The five tests are correlated by construction.
5. **`claude-fable-5` added to D4 after the prereg freeze.** Disclosed in
   `primary_analyses.md`, and I verified it does not manufacture the result: D4 on the three
   pre-registered models only is **ratio 4.098, CI [2.06, 8.02], still EXCEEDS** (vs 4.647
   with four). Fable is the highest arm (+3.48% vs sonnet, 10/12 units, p = 0.002) but D4
   holds without it. **This attack fails.**
6. **Run-level Mann-Whitney tests** (P3, D3) pool 60 runs as independent when they are 5
   repeats × 12 units. Those p-values are not valid; the sign tests are. The doc already
   flags the p-values as bucketed but not as non-independent.

---

## Summary: what BREAKS, what WEAKENS, what HOLDS

**BREAKS**
- **The "ratio > 1" null threshold.** Correct null is 0.12–0.52 by level count. Every verdict
  must be restated against a permutation null. (Net effect on the headline: favourable.)
- **D3 "NULL" as a substantive claim.** Debate raises the forecast in 8/9 units, p = 0.039.
- **D2's verdict under state clustering** ([0.96, 2.38] published; [0.97, 2.93] current) and
  under 34.5% of bootstrap seeds as published.
- **D1 and D2 under any family-wise correction** (only D4 survives against threshold 1).
- **Reproducibility right now** — run files are being written during the session; the
  published D2 row already differs (1.532 → 1.734).

**WEAKENS**
- D1 is carried by the `purpose_only` arm; drop it and the published rule returns NULL.
- D5's ratio is inflated 21% (0.97 → 1.17) by excluding the most insensitive unit.
- The skill leg is underpowered by the 30-month horizon, not merely null.
- The noise floor is inflated by the noisiest level of each dimension — biases every
  variance-adding treatment toward NULL.

**HOLDS**
- **The reparse.** The [0.2×, 5×] band clipped zero forecasts (3 numbers total corpus-wide,
  none plausible caseloads). The correction is a year-filter and it is right.
- **P4's treatment application.** substitutions=3 on all 120 runs; prompts verifiably differ.
  The memorisation reading is available and can be stated more sharply than it is.
- **D4.** Largest effect, survives Bonferroni, survives clustering, survives dropping the
  post-prereg Fable arm (4.098 vs 4.647), 12.4× its permutation null. This is the most
  defensible number in the deck.
- The arithmetic. Every published figure reproduced exactly from the code.

---

## The single most dangerous question in the room

> **"Your noise floor is the range of five single draws and your signal is the range of
> per-level medians of five draws. Those aren't the same estimator — so what is the expected
> value of your ratio when the dimension does nothing at all? Because it isn't 1."**

It is 0.12 to 0.52 depending on level count. The honest answer, delivered before anyone else
gets to it:

> *"It isn't 1 — under a within-unit permutation null it is 0.44 for a five-level dimension
> and 0.12 for a two-level one, so my threshold was 2 to 8 times too strict. I flagged the
> asymmetry in the write-up and then failed to correct for it. Re-tested against the
> permutation null the three positive results get stronger, not weaker: policy context 4.1×
> its null, elicitation 4.8×, model tier 12.4×, all p < 0.001. What it costs me is the
> pipeline null — against the right null, and more importantly against a directional sign
> test, debate raises the forecast in eight of the nine units where it moves at all,
> p = 0.039. So the corrected claim is that the debate scaffold doesn't change the answer by
> more than sampling noise, but when it does move the answer it moves it the same way almost
> every time."*

Leading with that converts the room's best attack into a demonstration that you red-teamed
your own construction. Waiting to be asked converts it into "the headline test was
mis-specified and he didn't notice."

**Second most dangerous, and the one with no good answer:** *"Which of your five dimensions
survives correction for the fact that you ran five of them?"* — Only D4. Have the permutation
p-values ready, because they are what rescues D1 and D2.
