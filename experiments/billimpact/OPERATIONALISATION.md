# OPERATIONALISATION — today's findings, landed in the team's own pipeline

**2026-07-31, evening.** Every anchor below was read this session, from the
working tree or from the PR branches as fetched (~16:30 EDT: `pr64` =
`4d0b3685`, `pr65` = `a7165d45`, `pr63` = `cf9f6509`, `pr50` = `03c7f29a`).
Merged in the last hours and accounted for: #62 (expired-unforecast
registrations), #56, #55, #54 (Windows chain verify), #49. Line numbers on
open-PR files will drift; function names won't. Nothing here is generic
advice — each item names the artifact it lands in, sized as **one-line
policy**, **small PR**, or **design decision**.

## Findings index (cited below by number)

| # | Finding | Source |
|---|---|---|
| F1 | Model tier moves forecasts 12.4× the permutation null — the largest harness effect measured | `RESULTS.md` §1 (D4) |
| F2 | Bill text in the prompt narrowed intervals 12/12 units while 80% coverage fell 0.50 → 0.33 | `RESULTS.md` §1 |
| F3 | Effort × context interaction: fable+bill at **max** effort beats naive (−0.084 [−0.164, −0.008]) and persistence (−0.118 [−0.211, −0.035]); the **same recipe at default effort is among the worst arms** (+0.047 vs its own naive) | `RESULTS.md` §5; re-derived `CHECK2.md` items 11–12 |
| F4 | Recall-anchoring, causal: dose-response flat on memorized periods (0/3 cells), monotone 6/6 when the same statute is moved to 2026; **raising reasoning effort does not fix it, restructured elicitation does** | `RESULTS.md` §3a–3b |
| F5 | Mechanical leg: PolicyEngine tool → 100% exact at every tier (haiku 4% → 100%); the **verbatim-but-incomplete excerpt is worse input than a plain summary** (sonnet 50% vs 94%); **tools fix arithmetic, not extraction** (opus + tool + incomplete excerpt: 86%) | `RESULTS.md` §4 |
| F6 | When the model states quantiles, pushing them through `interval_anchor_v1` is strictly worse than honouring them: −0.034 [−0.068, −0.003] nCRPS; the transform's manufactured tails over-cover (0.962 observed at 90% nominal vs the model CDF's 0.870) | `CALIBRATION_LAB.md` exp. 1 |
| F7 | Stated ≫ revealed uncertainty: median revealed/stated ratio 0.26 over 728 cells; 8% of cells return the identical point on all 5 reps at temperature 1.0; the ratio correlates with miscalibration (ρ=0.209, p=1.3e-08 cell-level; unit-aggregated ρ=0.267, p=0.096 — clustering caveat applies); bill context produces a per-model double dissociation (beliefs-without-confidence, confidence-without-beliefs) that interval width alone cannot see | `CALIBRATION_LAB.md` exp. 2 |
| F8 | Interval recalibration pays only where miscalibration exists: LOO-fitted widening repairs fable's coverage (93/140 → 109/140) at flat Winkler; the same construction on already-calibrated opus buys nothing; **a scale imported from a different model/corpus makes calibration worse** (w=1.73 transfer → 0.950 coverage at 80% nominal, Winkler 1.61 → 2.29) | `CALIBRATION_LAB.md` exp. 3 |
| F9 | Two-legs gap on S.3596: mechanical −1.2pp child poverty (PR #64, build P) vs forecast-leg conditional −0.10/−0.15pp — the forecast leg concedes ~a tenth of the mechanical effect, the recall-anchoring signature | `TWO_LEGS_S3596.md` |
| F10 | Corpus coverage: every validated unit is a transfer-to-persons read through a persons-side series; appropriations, program creation, regulatory mandates, business-side tax are **uncovered**, and for several of them no mechanical engine exists | `IDEATION.md` §1 |
| F11 | The purpose-clause effect is named-statute recall: statute named → −2.65% (p=0.002); name redacted → effect collapses (p=0.29) | `RESULTS.md` §2 |
| F12 | The registered S.3596 deltas re-run under 16 harness configs: poverty delta in a −0.10 to −0.30pp band in 14/16, both outliers from the name-only context arm; uptake delta sign-stable 16/16 | PR #61 body; envelope sweep (amendment 6) |

---

## 1 · Harness disclosure block on every forecast artifact

**Finding:** F1, F3, F12. Model tier is the single largest unreported degree
of freedom; effort flips the sign of bill-context value; the two registered
S.3596 deltas already differ by 50% relative purely by model (−0.10 opus vs
−0.15 fable).

**Adoption point:** the `predictionRun` stamp — built at
`scripts/spawned_cells_to_ts.py:336-353`, contract documented at
`docs/cell-contract.md:74-81`. It already carries `model`, `agentVersion`,
`promptHash`, `toolPolicyHash`, `promptMode`, `custodyRootSha256`. Three
fields are missing that today's results show move the number: **reasoning
effort** (recorded per-run in `command.json` at
`scripts/run_thesis_analyst.py:1723` but never surfaced to the cell),
**context level** (what documents were in the prompt — bill text, summary,
mechanical grounding table, none), and **transport/reps** (aggregation k;
median3 currently encodes k only via the agent name).

**The change:** extend `predictionRun` with `reasoningEffort`,
`contextLevel`, `aggregation` (`{k, algorithm}`), and `transport` (our runs
record the API transport per-run for exactly the reason the repo records
everything else: failures correlate with measured dimensions), populated by
the converter from `command.json` the way `promptMode` already is
(`spawned_cells_to_ts.py:347`). This is the exact pattern the repo already
uses twice: `transformVersion` on every distribution
(`site/src/data/prediction-distribution.ts:105-108`) and the
`certification` block PR #64 stamps on every compute block
(`bills/stronger-start-working-families-act/bill.json`, `compute[0]`).
PR #64 did it for the mechanical side — model version, build tag, engine,
certified-pairing verdict, on the artifact, because the build refresh moved
the poverty number 3× (their own stale-number lesson). Same pattern,
forecast side. PR #65's draft cells already record `policyengine-us` version
and dataset in the `.run.json` sidecar (`scripts/pe_reform_cell.py`, run
facts around `:456-477`) — the forecast-side block makes the two lanes
symmetric.

**Size:** small PR (converter + contract doc + one trace-depth test case).

**What it would have caught:** any future reader of the S.3596 conditional
pair can attribute the −0.10 vs −0.15 split to model tier instead of
discovering it by diffing run records; and the F3 failure mode — a
bill-conditioned cell quietly produced at default effort — becomes visible
on the artifact rather than only in a buried `command.json`.

## 2 · Forecast-leg configuration policy: bill text out of the prompt at default effort

**Finding:** F2, F3, F4, F11. Bill text bought confidence, not accuracy, at
every default-effort configuration measured; it pays only at max effort; and
the mechanism (named-statute recall) means the risk is worst on famous
statutes.

**Adoption point:** three places, because this is where lanes acquire their
configuration. (a) `scripts/run_thesis_analyst.py:2557` —
`--codex-reasoning-effort` **defaults to `"low"`**. (b) The conditional-cell
lane: `agents/thesis-analyst/build_prompt.py:34-36` auto-attaches the
policyengine skill to every conditional forecast, and PR #50's
`site/src/data/bill-forecasts.ts` docstring establishes the pipeline that
will feed it ("the ingest lane auto-drafts cell specs into `drafts/`…").
(c) The skill text itself, `agents/thesis-analyst/skills/policyengine.md`.

**The change:** one-line policy in the skill (and mirrored in
`docs/cell-contract.md`'s conditional-cell note): *a bill-conditional
forecast prompt carries the mechanical leg's computed delta and the
provision reference — never the operative bill text — unless the lane runs
at maximum reasoning effort, in which case the inclusion is recorded as
`contextLevel` (item 1).* The auto-drafted cell specs from the bills lane
must therefore carry the provision *pointer* (slug + provision title +
`conditionalOn`), not the `quote` body, into the prompt context. The
default-effort guard is mechanical: if `contextLevel` includes bill text and
effort ≠ max, the runner refuses the lane the same way it refuses an
unbindable target (`--skip-unbindable` precedent, `register_targets.py`).

**Size:** one-line policy (skill + contract) now; small PR for the runner
guard when the first bill-conditional lane ships.

**What it would have caught:** nothing shipped yet violates it — which is
the point. PR #50 creates the surface (a `/bills` page with forecast links)
that will generate demand for exactly these cells; without the policy the
first implementer pastes the provision `quote` into the prompt (it is right
there in `bills/<slug>.json`) and inherits the measured-worst cell: at
default effort that configuration was +0.047 nCRPS *worse than the same
model with no bill at all*, with coverage 0.61.

## 3 · Quantile honouring: elicited quantiles must promote as `agent_reported`, never re-derive through `interval_anchor_v1`

**Finding:** F6. The cleanest same-information comparison in the calibration
lab: model states quantiles either way; scoring the transform-rebuilt CDF
instead of the model's own is −0.034 [−0.068, −0.003] worse, and the
transform's manufactured 1.5-spread tails over-cover at 90% nominal.

**Adoption point:** `materialize_run_distributions` at
`scripts/run_thesis_analyst.py:291-299`. The promotion choice is one line:
`ladder_distribution(cell) or interval_distribution(cell)` — and
`ladder_distribution` (`:222-288`, provenance `agent_reported`) returns
`None` on any malformed/missing `thresholdLadder`, silently degrading the
cell to `interval_distribution` (`:159-219`, provenance `interval_seeded`).
The same silent degrade exists wherever a quantile-native contract meets the
point+CI fallback.

**The change:** a promotion-path policy, enforced where the choice is made:
*when the sealed elicitation contract promises quantiles (`promptMode` is
`ladder`/`ladder_v2`, or any future quantile-native mode), a `None` from
`ladder_distribution` fails the run closed — it must never fall through to
`interval_seeded`.* The `or` becomes mode-aware: point+CI contracts take the
transform; quantile contracts take the model's own CDF or reject. Add the
negative test (a ladder-mode cell with a corrupted `thresholdLadder` must
*fail*, not promote) — the repo's own E-style rule that green is
indistinguishable from never-executed until seen red; `_assert_correctness.py`
in PR #64 is the house pattern for exactly this. Document the asymmetry in
`docs/cell-contract.md` next to the `predictionDistribution` note.

This also retro-justifies `ladder_v2` (`AGENTS.md:97-113`, pre-registered
2026-07-10): the quantile-native contract was motivated by idiom-compliance
selection; F6 adds the scoring-side argument — the rungs are not just easier
to elicit, honouring them is worth ~0.03 nCRPS against rebuilding them.

**Size:** small PR (one function + one negative test).

**What it would have caught:** any ladder-mode run whose rung parse failed
has been scored on a distribution whose shape the transform authored, with
provenance silently downgraded — a claimed `agent_reported` lane quietly
publishing `interval_seeded` cells. Whether that has happened is checkable
in one query over the strategy corpus (ladder runs whose cells carry
`interval_seeded`); the policy makes it impossible going forward.

## 4 · Statutory-elasticity gate: perturb the operative parameter, require the output to move

**Finding:** F4, F5, F11. 6/12 corpus-A units returned *identical* forecasts
under a 20-year-stricter and a 20-year-looser statutory rewrite; FPUC
dose-response was monotone in 0/6 default-elicitation cells on the memorized
period. A leg that does not respond to the bill's own dial is decoration,
and nothing in a green single-run pipeline reveals it.

**Adoption point:** PR #64's correctness culture is the natural carrier —
`scripts/tools/CHECKLIST.md` (gates 0–3) and
`scripts/tools/_assert_correctness.py` (the battery where "no claim is
written by hand"). Gate 2 already asserts household *direction* under the
real reform; what's missing is dose.

**The change, mechanical side (small PR):** a Gate 4 in the checklist +
battery: run the provision's reform at three doses — null (parameter set to
its current-law value; must reproduce baseline within tolerance — the
zero-delta trap from our case set), statute, and an off-statute probe (e.g.
2× the statutory change) — and require the economy/household output to be
monotone-distinct across them. The null arm is the negative control the
existing battery style demands (VAL-2's shape); a reform whose output is
flat across doses is pricing *nothing*, which is precisely the failure class
POLICYENGINE.md §1 documents the API accepting silently.

**The change, forecast side (design decision + small script):** the same
probe applied to any bill-conditional forecast lane before its cells
publish: perturb the operative parameter in the conditional framing, require
the forecast-leg delta to move — or the lane is marked recall-suspect and
fails closed. This is our amendment-6 envelope construction
(`experiments/billimpact/envelope_sweep.py`) run as a CI-style check rather
than an experiment; F12 shows it is cheap (96 calls, ~20 min) and
discriminating (both envelope outliers traced to the name-only context arm).
Nothing is scored against truth, so the fabrication surface is zero and it
never touches reward.

**Size:** small PR (mechanical) + design decision (forecast side).

**What it would have caught:** on their own current work, the mechanical
side passes — the #64 S.3596 run demonstrably responds (that is the PR's
content). The gate exists for the next hundred provisions, where F5 says the
dangerous failure is a well-formed reform pricing the wrong thing; and the
forecast side would have flagged, today, that the S.3596 conditional delta
survives 14/16 harnesses but loses integrity exactly when the prompt names
the statute without its text (F12) — the configuration item 2 bans.

## 5 · Mechanical-leg completeness: conforming amendments are load-bearing, and the mapper should say when extraction is unverified

**Finding:** F5. The verbatim-but-incomplete excerpt (§2(a) with the
conforming amendment withheld) was *worse* input than a plain-English
summary (sonnet 50% vs 94%), and the tool cannot repair it (opus + tool:
86%, feeding a mis-extracted threshold into a correct calculator).
S.3596 is itself the demonstration: §2(a) strikes "$3,000" in IRC
§24(d)(1)(B)(i), but the operative 2026 threshold is $2,500 via §24(h)(6) —
**only the §2(b) conforming amendment (striking paragraph (6)) makes the
bill do what it does.** An agent reading §2(a) alone prices the wrong
current law.

**Adoption point:** (a) PR #64, `POLICYENGINE.md` §1 (the reform-dict rules)
and `CHECKLIST.md`; the `bill.json` provision `quote` field — whose S.3596
instance *already* includes the (b) conforming amendment, the right
precedent to make mandatory. (b) PR #63, `map_bill_metrics.py::map_artifact`
(the `registry` annotation loop, `"reachable"`/`"not-yet"`/`"unmapped"`).

**The change:** in POLICYENGINE.md §1, one rule: *before a reform dict is
admissible, enumerate every amendatory instruction in the provision —
including conforming amendments — and state which parameter each maps to,
or why none does. A reform derived from an excerpt that omits an amendatory
instruction is inadmissible, exactly as an unvalidated parameter path is.*
Add the checklist line under Gate 1. In the mapper: a provision whose
`compute` blocks exist but whose amendatory-instruction enumeration is
absent (or whose `quote` is flagged partial) gets its metrics annotated one
grade down — the mapper already refuses to touch records and writes
proposal-only annotations, so this is one more annotation, not a new
authority. Note F5's asymmetry for the prompt-side corollary: if full text
cannot be supplied to a *forecast* leg, a summary is measurably safer than
an excerpt — partial statutory text is the worst of the three input classes.

**Size:** one-line policy (contract doc + checklist) + small PR (mapper
annotation).

**What it would have caught:** the #64 team got S.3596 right — and nothing
in the current gates would notice if they hadn't. `validate_reform`
(`policyengine.py:216`) checks that parameter paths *exist*, not that the
reform captures the provision's full amendatory set; a reform built from
§2(a) alone ($3,000 → $1, with §24(h)(6) left standing) validates cleanly
and prices the wrong bill. The gate that catches mis-extraction cannot live
in the calculator (F5: tools fix arithmetic, not extraction); it has to
live in the completeness discipline upstream.

## 6 · Stated-vs-revealed calibration flag on median-of-k lanes

**Finding:** F7. The ratio of exhibited to admitted uncertainty is
computable from repeat samples alone, predicts miscalibration at cell level,
and sees belief changes that interval width cannot (the F7 double
dissociation). The team already pays for the repeat samples: every median3
run is three independent rollouts of the same target.

**Adoption point:** `scripts/median_rollout_ensemble.py` — it already reads
the three constituent cells' intervals to derive the pointwise-median CDF
(docstring `:1-21`; stamps `provenance: "agent_reported"` at `:300`) and
records references to every constituent manifest. The revealed side is the
sample SD of the three constituent `pointEstimate`s; the stated side is the
median constituent 80% half-width / 1.2816 — both computable in the same
pass with no new model call.

**The change:** emit `revealedStatedRatio` (with `k`) on the derived run's
record, surfaced wherever strategy diagnostics already render
(`site/src/data/thesis-strategy-comparisons.ts` → `/brier/strategies`).
Marked diagnostic-only, `rewardEligible: false` by construction — the same
quarantine the auxiliary judges carry in the reward export
(`site/src/data/brier-lab.ts`, `auxiliaryJudges` hard-coded ineligible) —
and never a normalisation input (the X2 rule: nothing a forecast authors
may move its own denominator). k=3 makes any single ratio noisy; the value
is the aggregate view (which lanes/models systematically wobble more than
they admit) and the extreme flags (revealed = 0: the model returned the
identical number three times at temperature 1.0 — 8% of our cells did).

**Size:** small PR.

**What it would have improved:** the strategy corpus (146 runs, 12 cells,
2026-07-08→10) already contains everything needed to compute this
retroactively for every median3 suite — a free new diagnostic column over
already-recorded artifacts, in a repo whose stated purpose is comparisons
across agents and prompt modes (`AGENTS.md`, Purpose block).

## 7 · Provenance mapping for our run records, and what the forward pack still needs

**Finding:** the day's records themselves, read against the house chronology
tiers (`site/src/data/thesis-log.ts:1302-1326`) and evidence modes
(`site/src/data/strategy-lab.ts`, `evidenceMode:
"historical_replay" | "forward_only"`).

**The mapping, honestly:**

- **Retrospective corpus runs** (~7,000): `historical_replay` by
  construction — the Strategy Lab precedent applies verbatim ("replayed
  over outcomes that already resolved, carry no chronology verification,
  never enter headline calibration, rewards, or leaderboards"). Our
  `emit_cells.py` already expresses them in contract shape without
  fabricating what the records lack (no invented tool steps, no invented
  `runAt` — the harness recorded `duration_s`, not wall clock; the cells
  carry `runAt: null` and fail the depth bar honestly).
- **Forward S.3596 conditionals** (`forward/s3596_conditional_runs.jsonl`):
  `runAt` timestamps + git history = **`claimed_time_verified` ceiling.**
  They are single-shot API runs with no custody roots, and
  `classifyPublicationProof` starts at `custodyRootSha256` — no root, no
  witness tier, regardless of how many recorder snapshots include the file.
  The recorder run after merge (`gh workflow run record-forecasts.yml`)
  seals the *repo state* into the RFC-3161 chain, which is real evidence of
  existence-before-resolution, but it is not the run-level witness tier.
- **To reach `witness_verified`** (design decision, cheap, ~2-year window):
  re-emit the two S.3596 conditionals as recorded `thesis.analyst` runs —
  custody root, inventory v2, activity artifacts — before the targets
  resolve (2028-09-15 / 2028-08-31). The JSONL runs then stand as the
  preregistration evidence; the analyst runs carry the headline-eligible
  score. The link into PR #50's `/bills` surface goes through the
  registered-pair path its own docstring mandates
  (`site/src/data/bill-forecasts.ts`: "links land here only when the pair
  is actually registered" — and the farm-bill links are `example: true`
  placeholders awaiting exactly this).
- **Reasoning logs in the demo: yes.** The house rule is already "do not
  collapse full activity into a summary" (`AGENTS.md:34-49`), and our §7
  instrumentation defects are the argument made flesh — the parser defect
  was caught *because* raw responses were stored and re-parseable offline
  (`reparse.py`, 214 runs corrected without re-running). Custody norms
  apply: the 2026-07-21 credential incident
  (`docs/thesis-analyst-runner.md:151-185`) means logs pass the env-var
  allowlist + stream redaction before anything is sealed or shown.

**Size:** design decision (re-emission) + no code for the mapping itself.

## 8 · Bill-type coverage map: what the mapper may call validated

**Finding:** F10, F5. Validation evidence is dense on exactly one column of
the bill-type matrix — transfers to persons read through persons-side
series — and the architecture prescription ("compute the statutory leg
mechanically") is currently *unactionable* on appropriations, regulatory
mandates, and reporting duties, where no calculator exists.

**Adoption point:** PR #63, `map_bill_metrics.py`. Its `registry`
annotation answers "is this series registered?" — necessary, not
sufficient. A metric can be `reachable` while sitting on a bill type where
the forecast leg has zero validation evidence and the mechanical leg has no
engine.

**The change:** a second, orthogonal annotation from a static table keyed by
provision type, in the mapper or as a doc table it references:

| Provision type | Mechanical leg (evidence, not capability) | Forecast leg |
|---|---|---|
| Eligibility restriction (SNAP-class) | untested by us (PE models the domain; our mechanical validation was CTC-only) | **validated, dense** (2,520-run grid) |
| Flat dollar supplement (FPUC-class) | arithmetic identity (derivation-rescue confirmed) | **validated, dense** (causal dose work) |
| Household tax / refundable credit (S.3596-class) | **validated to the dollar with tool** | thin — forward registrations only |
| COLA / formula repeal / protection sunset | untested by us | thin (bake-off units only) |
| Appropriations, program creation, regulatory mandate, business-side tax, reporting duty | **no engine exists** (IDEATION §1.3: the prescription is unactionable here) | **unvalidated** |

Metrics on the last row promote with an explicit `unvalidated` marker in the
`.mapped.json` (the mapper is proposal-only, so this is annotation, not
gate-keeping); the `rationale` disclosure field PR #50 already defined on
`BillMetric` (`site/src/data/bills.ts`) is the natural surface to say *why*.
The IDEATION §1.4 additions (ARPA-CTC advance payments, IIJA highway
appropriation, ACP creation) are the cheapest upgrades of specific rows from
unvalidated to thin.

**Size:** small PR (static table + annotation + test).

**What it would have caught:** PR #50's `farm-bill-2-0.json` spans SNAP and
Medicaid provisions (covered types) — fine. The first appropriations or
regulatory bill through the lane would otherwise ship metrics whose
forecast-leg reliability nothing measured, wearing the same `reachable`
badge as an FPUC-class metric with 1,380 runs behind it.

## 9 · The queued-run widening prior should be fitted, not asserted

**Finding:** F8. A fixed interval-scale imported from nowhere in particular
is exactly the construction the calibration lab shows failing: widening
repairs the under-covering model and *degrades* the calibrated one, and a
scale fitted on the wrong cohort over-covers at 2.29 Winkler vs 1.61.

**Adoption point:** `forecast-api/src/lib/policyengine.ts:66-73` —
`CTC_CALIBRATION_PRIOR.uncertaintyMultiplierWhenQueued: 1.4` (self-labelled
`"prototype calibration prior"`), echoed by PR #64's POLICYENGINE.md §4
("pending → widen the forecast interval") and §7's stored-prior rule.

**The change:** keep the *rule* (pending runs must widen — correct, and
honestly traced), replace the *constant*: fit w by minimum Winkler on
resolved first prints, leave-one-out, per model — the EXP3 recipe, proper
score so it cannot be gamed by width — and record the fit cohort next to the
value the way the prior already records `source`. Our own sealed-ledger
check bounds the ambition honestly: only 11 score-carrying reward rows pair
a stored forecast with an outcome today (2 with a normalization scale), so
the fit is not yet powered *within the lab* — which is itself the argument
for accumulating resolved forward rows (item 7) before promoting any
multiplier from prototype to calibrated. Until then the 1.4 stays labelled
what it is.

**Size:** design decision now; small PR when the resolved cohort exists.

**What it would have caught:** nothing yet — the prior is honestly
prototype-labelled. The trap is the day someone transplants it: F8's
cross-model transfer is the measured demonstration that a widening constant
is a property of (model × corpus), not a universal safety factor.

---

## If the team adopts three things tomorrow (ranked by value/effort)

1. **Quantile honouring fail-closed** (item 3): one function
   (`run_thesis_analyst.py:296`), one negative test; removes a silent
   provenance downgrade worth a measured −0.034 nCRPS, and one query tells
   you whether it has already bitten.
2. **Harness disclosure block** (item 2 fields, item 1): converter +
   contract doc; the pattern (`certification`, `transformVersion`) is
   already house style, and F1/F3 say model + effort are the two fields
   that move numbers most.
3. **Conforming-amendment rule + Gate 4 dose probe** (items 5, 4,
   mechanical half): two checklist lines and a battery entry in PR #64's
   own idiom; guards the failure class (mis-extraction) that the
   calculator provably cannot catch.

Then, in order: forecast-leg context/effort policy (item 2 — one line now,
guard when the first bill-conditional lane ships); mapper coverage
annotation (item 8); revealed/stated ratio on median3 (item 6);
re-emit S.3596 conditionals as recorded analyst runs for the witness tier
(item 7); registered-delta envelope as a lane check (item 4, forecast
half); fitted widening prior once resolved rows exist (item 9).
