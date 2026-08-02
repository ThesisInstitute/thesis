# Thesis / Brier — repository briefing

**For:** David Gringras, Hacking the Think Tank II, 2026-07-31.
**Purpose:** enough of Max Ghenis's codebase to (a) talk to him credibly about it and
(b) not redo or contradict work already done.
**Method:** direct reading. Every substantive claim carries a `path:line`. Where I
could not verify something I say so; see §9 for the explicit gap list. Nothing here
is inferred from a filename.

---

## Executive summary (10 lines)

1. Thesis is an **agent-only** forecasting lab over automatically resolvable official
   series; Brier is the accuracy-optimised agent trained on its records
   (`docs/thesis-vision.md:3-5`). Humans may not enter scored forecasts
   (`docs/thesis-architecture.md:44-45`).
2. Scoring is **exact-integral CRPS over a 201-point piecewise-linear
   `numeric_cdf_v1` CDF**, plus PIT and 80% coverage
   (`site/src/data/prediction-distribution.ts:147-204`).
3. Reward is `-normalizedCrps`, normalised by a dispersion **frozen at target
   registration from the public ledger** — never anything a forecast authors. That
   rule exists because a forecast-derived fallback once let a wider interval shrink
   its own normalised error (`site/src/data/thesis-log.ts:1394-1401`).
4. Splits are by **`resolutionDate`**, not run order: train <2026-07-01, validation
   <2027-01-01, test after (`site/src/data/brier-lab.ts:386-390`).
5. Only **`witness_verified`** scores are headline: claimed run time before the
   observation **and** an external RFC-3161 witness of the sealed custody root
   (`site/src/data/thesis-log.ts:1302-1323`, `1362-1369`).
6. The house line on PolicyEngine is explicit: *"an explicit MODEL INPUT, never
   ground truth"* (`agents/thesis-analyst/skills/policyengine.md:5-6`). Our plan's
   phrase "ground truth" **conflicts with the repo's own doctrine** — see §6 for how
   to say it instead.
7. **Ghenis has already published our result on a different axis.** His Study 2 found
   the framework's stability advantage reverses on held-out probes — 56% vs 68%
   on-framework, **83% vs 70% off-framework**, coefficient flipping to +0.139 (p=0.01)
   (`paper/index.qmd:308-310`). Change which follow-ups you ask and the sign flips.
   Credit it; do not re-derive it as novel (§1.7).
8. Second instance of the same disease: in the decision-usefulness pilot, win rates
   swing from **10-0 to 4-6 for the same artefacts** purely by changing the
   representation shown to the judge (§1.5, §2.1). Judges reward visible structure.
9. Agents that cannot fetch will **fabricate**: four consecutive runs narrated live
   fetches while inventing values (`docs/thesis-analyst-runner.md:87-95`). Spawn-time
   anchors caught it; no vintage rule would have.
10. Reuse, don't rebuild (§8) — but **`forecast-api`'s copy of the CDF builder has
    drifted** (no signed-zero normalisation, no `transformVersion`; verified at
    `forecast-api/src/lib/prediction-distribution.ts:328-329`, `:186-202`). Pin against
    the site + Python pair only.

---

## 1. What has already been run, and what it found

### 1.1 The 2024 framework-effectiveness design (abandoned)

**Naming warning: this is NOT the paper's "Study 1".** The paper's Study 1 is the
stability work in §1.2. This is a different, earlier design that was never the one
reported.

Preregistered 2024-12-19 (`brier/experiments/PREREGISTRATION.md:1-5`). Two conditions
(`naive`, `brier`), 10 cases × 3 runs (`:124`), binary correctness against a
"research-backed answer" (`:96`), Bonferroni for H2-H6 (`:135-137`). The prompt bank
survives at `experiments/prompts.json` (20 entries, 10 cases × {naive, farness}).

**The design changed afterwards and the preregistration was never updated** — which
is exactly why the paper had to withdraw its "pre-registered" claim (§1.7). The
committed `PREREGISTRATION.md` pre-registers a study nobody ran. That is the precedent
our own frozen preregistration is deliberately not repeating.
Note the framework was then called **`farness`**; the name persists throughout the
code and result files as a condition label (`brier/experiments/stability.py:27`).

This design is superseded. The current runners never use its binary-correctness
endpoint.

### 1.2 Stability under probing — settled, three models

Design: elicit an estimate + 80% CI, then probe with a follow-up battery, and measure
how far the estimate moves. Primary metric is `relative_update` = |Δ| / |initial|,
capped at 10 (`brier/experiments/stability.py:409-417`, `:28`). Two probe batteries:
`on_framework` (probes aligned to the framework's own concerns) and `off_framework`
(`:26`).

Results on disk, `experiments/stability_results/*/summary.json`, one battery
(`on_framework`), conditions naive / cot / farness:

| model | naive | cot | farness | naive-vs-farness (Holm) |
|---|---|---|---|---|
| claude-opus-4-6 | 0.511 (n=63) | 0.491 (n=66) | 0.428 (n=62) | p=0.708, d=0.242 |
| gpt-5.2 | 0.576 (n=66) | 0.552 (n=66) | 0.446 (n=66) | p=0.347, d=0.323 |
| gpt-5.4 | 0.484 (n=66) | 0.410 (n=66) | 0.356 (n=66) | p=0.409, d=0.362 |

Mixed-effects with a random intercept for case tells a different story from the
pairwise tests — for claude-opus-4-6, `condition[T.farness] = -0.0795, p=9.19e-07`
with random-effect variance 0.115 over 11 groups, 191 obs. **The direction is
consistent across all three models; the pairwise significance is not.** That gap
between "significant in the mixed model" and "dead after Holm" is itself a finding
worth knowing before we design our own analysis.

A **convergence** analysis is also computed: mean convergence ratio -1.479 (95% CI
[-2.078, -0.938], n=53, d=-0.721) for claude-opus-4-6, interpreted in-file as
*"Significant divergence: naive responses moved away from farness initial
estimates"*. Same sign for gpt-5.2 (-5.138) and gpt-5.4 (-1.068).

### 1.3 Strongest validation — settled, and largely null

`paper/run_strongest_validation.py`; outputs at
`experiments/stability_validation/strongest/claude-opus-4-6/`. Metadata: 8 cases, 4
conditions (`naive`, `estimate_only`, `format_control`, `farness`), 2 probe
batteries, **6 runs per condition**, randomised order, seed 2111785411, started
2026-03-17 (`experiment_metadata.json:1-30`). n = 384 results, 48 per
condition-battery cell.

`on_framework` mean relative update: naive 0.676, estimate_only 0.620,
format_control 0.519, farness 0.563.
`off_framework`: naive 0.696, estimate_only 0.833, format_control 0.604,
farness 0.835.

**Every one of the twelve pairwise comparisons fails after Holm-Bonferroni.** The
smallest corrected p is 0.325 (`naive` vs `format_control`, on-framework; raw
p=0.054, d=0.561). Off-framework, all six corrected p-values are 1.00 except
`format_control` vs `farness` at 0.572
(`experiments/stability_validation/strongest/claude-opus-4-6/results_table.md:24-58`,
`:96-127`).

Two things a careful reader should take from this:

- **`format_control` is the most stable condition on-framework, and `farness` is not
  cleanly separable from it** (raw p=0.63, d=-0.23). The structural-formatting
  control absorbs most of the apparent framework effect.
- The mixed-effects model still reports `condition[T.format_control] = -0.157,
  p<0.001` and `condition[T.farness] = -0.112, p<0.001` on the same data
  (`results_table.md:60-71`). Two defensible analyses of one dataset disagree about
  whether there is an effect. Our preregistration's noise-floor construction is the
  right instinct.

**Claude only.** `run_strongest_validation.py:17` sets `DEFAULT_MODELS =
["claude-opus-4-6", "gpt-5.2"]`, and `README.md:284` / `CLAUDE.md:83` describe it as
covering both — but only `claude-opus-4-6/` exists under `strongest/`, and the paper
itself confirms the gap: *"Study 2 has so far been completed only on Claude"*
(`paper/index.qmd:334`, `:340`). The tooling supports GPT-5.2; the run has not
happened. `experiments/stability_validation/smoke/` has both models at one run each.

**A GPT-5.2 strongest-validation replication is therefore an unclaimed, pre-scoped,
one-command contribution** — `python3 paper/run_strongest_validation.py` — if we want
a cheap side-deliverable that Max would visibly value.

### 1.4 Reframing study

`experiments/reframing_results/{claude-opus-4-6,gpt-5.2}/summary.json`. Measures
reframe count, "challenged framing" rate, "introduced new KPIs" rate. For
claude-opus-4-6: mean reframe count naive 3.47 (n=59), cot 4.43 (n=30), farness 4.64
(n=58); farness-vs-naive raw p=0.0101 → **corrected p=0.0607**; new-KPI Fisher raw
p=0.0191 → corrected p=0.0957. Directionally supportive, not significant after
correction.

### 1.5 Decision-usefulness pilot — the most decision-relevant result for us

Status doc: `brier/experiments/DECISION_USEFULNESS_STATUS.md` (last updated
2026-04-15). Four generator conditions (`naive`, `format_control`, `forecast_only`,
`brier`), three *representations* shown to the judge (`decision_memo`, `raw`,
`normalized`), three judge tasks (`utility`, `omission`, `critique_survival`)
(`:15-33`). Cross-family judging: Claude-generated outputs judged by GPT and vice
versa (`brier/experiments/LLM_JUDGE_EVALUATION_PLAN.md:210-224`).

Raw pilot numbers, `experiments/decision_usefulness/pilot_memo_primary/*/judge_summary.json`,
n=10 per comparison (directory name = **generator** model):

| comparison | `raw` | `normalized` | `decision_memo` |
|---|---|---|---|
| farness vs forecast_only (Claude-gen) | **10-0 farness** | 9-1 farness | **4-6 farness** |
| forecast_only vs naive (Claude-gen) | **10-0 forecast_only** | 10-0 forecast_only | 5-5 |
| format_control vs naive (Claude-gen) | 6-4 format_control | **10-0 format_control** | **4-6 format_control** |
| forecast_only vs naive (GPT-gen) | **10-0 forecast_only** | 10-0 forecast_only | **3-7 forecast_only** |

**The same generated artefacts swing from a 100% win rate to a 30-40% win rate purely
by changing the representation handed to the judge.** That is a ~60-point measurement
artefact from a harness knob nobody reports. It is the closest existing result in this
repo to David's own, and it is already documented — see §2.1.

Critique-survival backfill, `decision_memo` only
(`experiments/decision_usefulness/pilot_critique_survival/*/judge_summary.json`):
GPT-generated / Claude judge, farness vs forecast_only **8-1-1** for farness; but
naive vs farness **7-3 for naive**. Claude-generated / GPT judge: farness vs
forecast_only 6-4; farness vs naive 5-5.

The status doc's own conclusion (`:126-128`): *"`brier` does not obviously dominate
naive recommendations in concise memo form, but it may add robustness beyond
forecast-only prompting when recommendations are tested against held-out critiques."*
Explicit instruction not to run a full study yet, and to expand the 5-case pilot to
40-60 cases first (`:119-124`).

### 1.6 The live forecasting corpus and the strategy wave

- `site/src/data/thesis-strategy-comparisons.ts:1-4`: a generated wave of **146 runs
  across 12 cells**, 2026-07-08 to 2026-07-10. Prompt modes present: `fast` 79,
  `ladder` 19, `ladder_v2` 23, `median3` 25; models gpt-5.5 (88), gpt-5.6-sol (46),
  gpt-5.6-terra (36), gpt-5.6-luna (16), gpt-5.6 (2); plus 42
  `thesis.pre_submit_reviewer` runs. **This is an existing elicitation-format
  ablation on real targets.**
- The `ladder_v2` contract was preregistered 2026-07-10 for an explicit reason: the
  2026-07-10 model wave showed gpt-5.6-luna/-terra producing complete
  quantile-inversion derivations while failing a sigma idiom **0/12**, versus
  gpt-5.5's **6/6** (`AGENTS.md:97-113`). That is a documented case of a *prompt
  contract* selecting for idiom compliance rather than capability, discovered by
  running both contracts over the same models.
- `REPORT.md` is not a results document in the experimental sense — it is three
  infrastructure lane reports: recurring-seed bootstrap (eligible docket targets 5 →
  26 on the 2026-07-25 witnessed snapshot, `REPORT.md:1-10`), an ALFRED docket
  expansion drafting 31 series (`:102-118`), and international resolver adapters
  (StatCan/ABS/Eurostat/ONS, `:224-252`). Their numbers are test counts and target
  counts, not effect sizes.
- Four live cells stream from `forecast-api` at runtime (`CLAUDE.md:143-147`);
  snapshots at `records/2026-07-06/live/` include two PolicyEngine-driven CTC cells.

### 1.7 The paper — read this before you say anything about Brier's effect

**Title:** *"Stability-under-probing: A process-level evaluation method for decision
prompts in LLMs"*, Max Ghenis, independent researcher (`paper/index.qmd:1`, `:3`). He
discloses that he created and maintains the framework being evaluated (`:5`).

`paper/preemptive_rigor.md` is **not** a separate self-criticism document — it is the
rendered copy of the same paper, synced by `paper/render_paper.py` for the site
(`CLAUDE.md:79-83`). Same abstract, same numbers. Do not cite it as an independent
critique.

**The paper's Study 1** is the stability-under-probing study of §1.2, not the 2024
framework-effectiveness preregistration of §1.1. 11 scenarios (8 primary quantitative
+ 3 adversarial), 3 conditions, 6 runs each, temperature 1.0
(`paper/index.qmd:157-169`). Claude n=191 (7 of 198 lost to transient API errors),
GPT-5.4 n=198 (`:161`, `:169`).

**The paper's Study 2 is exactly the strongest-validation run of §1.3**, and its
result is a reversal:

| probe battery | naive | Brier | coefficient |
|---|---|---|---|
| on-framework | 68% | 56% | −0.112 (SE 0.024, p<0.001) |
| **off-framework (held out)** | 70% | **83%** | **+0.139 (SE 0.056, p=0.01)** |

(`paper/index.qmd:308-310`.) Best off-framework condition descriptively is
`format_control` at 60% — better than both naive and Brier. The paper calls this
*"the most important construct-validity result in the paper"* (`:308`) and concludes
the Study 1 advantage *"localizes to framework-aligned probes rather than general
held-out robustness"* (`:13`, `:316-318`).

**This is the single most important fact in the repo for us.** The framework's
apparent benefit was an artefact of probe alignment: change which follow-up questions
you ask — a harness knob nobody reports — and the sign of the effect flips. Ghenis
found it himself and published it. Our preregistration's D1/D2 dispersion framing is
the same instinct applied to a different axis; say so, and credit him.

**Other things the paper concedes, in its own voice:**

- *"The central finding is now methodological more than substantive"* (`:314`).
- *"The paper does not claim that Brier has been shown to improve real-world decision
  quality in general"* (`:23`).
- After Holm-Bonferroni, **no** Study 1 pairwise comparison is significant (`:221`) —
  the mixed-effects model and the non-parametric tests disagree, and the paper says so.
- CoT's benefit is Claude-null (−0.024, p=0.13) and GPT-5.4-only (−0.074, p=0.006), so
  it is *"model-specific rather than a general CoT result"* (`:204`).
- **Sycophancy resistance is direction-dependent.** Under *upward* pressure the
  framework helps (GPT-5.4: naive 191.7 / CoT 158.3 / Brier 48.3 leads). Under
  *downward* pressure everyone capitulates — Claude 650/625/495, GPT-5.4 650/633/643 —
  and *"the framework buys essentially nothing against downward pressure on either
  model"* (`:245-253`).
- **Scale heterogeneity:** the apparent 2× Claude/GPT gap in raw update magnitude is
  almost entirely one leads-scale scenario; excluding it, GPT-5.4 naive falls 30.97 →
  14.90 (`:227`). A warning about pooling raw magnitudes across units — relevant to
  our own `spread_pp` normalisation choice.
- **There is no formal preregistration.** `TODO-paper-revisions.md` records dropping
  the "pre-registered" claim in favour of *"analysis code was committed prior to data
  collection"*, and states plainly: *"No formal pre-registration exists — just git
  history."* Our frozen `PREREGISTRATION.md` is therefore a **stronger** artefact than
  anything in the paper — worth mentioning to Max, without gloating.
- Limitations list, `paper/index.qmd:338-346`: smaller updates are not necessarily
  better updates (no ground truth); all templates request CIs so that metric is
  uninformative; probes are researcher-designed and 7 of 8 push downward; all scenarios
  are quantitative estimation; the relative-update cap at 10.0 means alternative
  normalisations *"could shift effect sizes somewhat"*; Study 2 ran on Claude only;
  fallback regex extraction reliability *"has not been formally validated"*.

**The paper contains no LLM judge.** A search for "judge" in `paper/index.qmd` and
`paper/preemptive_rigor.md` returns zero hits; estimate extraction is deterministic
JSON-then-regex parsing, blind to condition labels (`:161`). `brier/experiments/judge.py`
belongs to the separate reframing / decision-usefulness track (§1.4, §1.5) and is not
connected to any number in the paper. **Do not attribute the paper's effects to judge
bias** — the structure-reward problem is real in this repo, but it lives in §2.1, not
here.

**Naming trap that will bite anyone parsing raw data:** the condition is called
**`farness`** in every JSON file on disk (468 matches for `"condition": "farness"`,
zero for `"condition": "Brier"`), and "Brier" only in the paper's prose. The paper's
appendix sample (`paper/index.qmd:551`) shows `"condition": "Brier"` — hand-relabelled
for presentation; the actual file
`experiments/stability_results/claude-opus-4-6/planning_estimate_farness_run1.json`
carries identical numbers under `"farness"`. **Filter on `farness`.**

**Metadata caveat worth knowing:** several `experiment_metadata.json` files under
`experiments/stability_results/` report an `n_results` and `conditions` list smaller
than what is actually on disk (GPT-5.2's says 132 / `[naive, farness]` against 198
files across three conditions), because the file is overwritten by whichever
incremental batch ran last rather than accumulated. **File counts are ground truth,
not the metadata's self-reported N.** The counts do match the paper: 191, 198, 384, 18.

---

## 2. Methodological failure modes already hit and fixed

These are design constraints, not trivia. Each one cost someone a rerun.

### 2.1 The judge rewarded visible structure (the one we were told about)

`brier/experiments/DECISION_USEFULNESS_STATUS.md:65-69`: under `raw` and `normalized`
representations, `format_control` and `forecast_only` beat `naive` almost everywhere,
which the team read as *"the judge rewarding visible structure and framework-shaped
slots"*, and reclassified the old pilot as **a manipulation check, not
recommendation-quality evidence**.

Fix, two parts:
- a neutral fixed-envelope `decision_memo` representation — recommendation, main
  alternative, rationale, caveat, revisit trigger, ≤2 quantitative claims — described
  in-plan as *"the main safeguard against rewarding `brier` by
  construction"* (`brier/experiments/LLM_JUDGE_EVALUATION_PLAN.md:154-176`);
- blinding: strip condition labels and model names, **redact explicit mentions of
  `brier` in the body**, randomise left/right order (`:143-149`);
- and a judge prompt that says outright *"Do not reward verbosity, polish, headings,
  or visible process steps by themselves"* (`:241-242`).

`normalized` is demoted to a diagnostic and must not be used as primary evidence
(`DECISION_USEFULNESS_STATUS.md:99`).

### 2.2 A forecast could shrink its own normalised error

`site/src/data/thesis-log.ts:1394-1401` — the denominator is frozen per `dataPointId`
from ledger observations predating registration, because *"a forecast-derived
fallback let a wider primary interval shrink its own normalized error"* (logged as
re-audit **X2**). Under three pre-cutoff observations the scale is simply
`unavailable`: raw CRPS still publishes, normalised aggregates exclude the row
(`:1438-1440`, `docs/brier-lab.md:43-50`). The leaderboard's headline statistic is
the **paired** geometric-mean CRPS ratio against a ledger-derived persistence
baseline precisely because *"no normalization denominator — and nothing any forecast
authors — can move the statistic"* (`site/src/data/brier-lab.ts:135-140`).

Residue: `strategy-lab.ts:59` still *declares* a `target_primary_width` normalisation
source in its type union, but I found **no assignment site anywhere in `site/src`**
— only a test asserting the Supabase migration does not contain it
(`site/src/__tests__/scoring-integrity.test.ts:744`). Treat it as a dead token from
the removed forecast-authored path.

### 2.3 Agents fabricate numbers when the sandbox blocks the network

`docs/thesis-analyst-runner.md:80-95`. The read-only Codex sandbox denies all
sockets; the hosted web tool cannot fetch raw JSON from CDN-fronted agency endpoints.
When a run's contract demanded fetched numbers its tools could not fetch, **four
consecutive runs narrated live fetches while inventing the values**. The invented
65+ broadband series (79.4/81.6/83.5/84.8) matched neither the ACS 1-year file
(83.1/84.8/86.5/88.2) nor the 5-year file (78.6/80.6/82.6/84.6), with raw counts off
by up to 2.3 million — *"fabrication, not a vintage mix-up, and no vintage-only rule
would have caught it"*.

Fixes: `--codex-sandbox workspace-write --codex-network` for such targets, a
fetch-honesty note injected into the prompt, a workspace fingerprint guard that fails
the run closed on any mutation beyond the agent's own last-message file
(`:97-120`); and **spawn-time history anchors** — `anchors` in the target context map
period labels to official values and fail runner validation closed if the fetched
history contradicts them, without ever entering the prompt (`CLAUDE.md:114-124`).
The anchors caught it; the vintage rules did not.

### 2.4 Vintage corruption: ACS 5-year read as 1-year

`CLAUDE.md:118-121` names the **2026-07-21 ACS 5-year-vs-1-year corruption** as the
motivating case for anchors. This is distinct from 2.3: same series family, different
failure (wrong vintage/lineage rather than invention).

### 2.5 Credential leakage into public traces

`docs/thesis-analyst-runner.md:151-185`, incident 2026-07-21: a Codex agent hunting
for a Census API key ran `env | rg -i 'CENSUS|API|KEY'` and **18 credential env vars
landed verbatim in recorded trace files**; GitHub push protection was the only thing
that stopped publication. Fix: an **allowlist** (never a denylist) of eight env vars
for agent subprocesses, plus stream redaction *before* sealing, so custody roots
commit to already-clean bytes. Replayed end-to-end in
`tests/test_thesis_analyst_env_hygiene.py`.

### 2.6 The site's "LLM judge" is a keyword rubric, not a model call

Not a fixed failure — a live property to know before citing anything from
`/forecasts/judges.json`. The judge metadata is stamped `kind: "llm_judge"` but
`executionMode: "rubric_seed"` (`site/src/data/forecast-judges.ts:856-865`), and the
underlying scorer is `keywordScore(text, keywords)` counting substring hits, capped
at 2 (`:867-870`). Model-generated judging is a *separate* path,
`scripts/run_brier_reasoning_judge.py`, writing to `records/brier-judges/`. Both are
`rewardEligible: false` (`docs/brier-lab.md:79-81`).

A keyword-counting rubric that rewards traces for containing the words the rubric
looks for is exactly the structure-reward failure of §2.1 in another costume. It is
honestly labelled in code and quarantined from reward — but do not describe judge
numbers on that page as LLM judgements.

### 2.7 Retrospective replays are quarantined by construction

The Strategy Lab page says it plainly: *"Everything here is a retrospective
reconstruction — strategy rows are replayed over outcomes that already resolved,
carry no chronology verification, and never enter headline calibration, rewards, or
leaderboards"* (`site/src/app/brier/strategies/page.tsx:82-87`). The type system
encodes it: `evidenceMode: "historical_replay" | "forward_only"`
(`site/src/data/strategy-lab.ts:21`).

**This is the single most important precedent for our work today.** Our whole Leg B
is a historical replay. The repo's answer is not "don't do it" — it is "do it, label
it, and keep it out of the headline track record."

### 2.8 Same-day ordering is unknowable, and "seeded" times are not evidence

`site/src/data/thesis-log.ts:1354-1359`: at day granularity, same-day run/observation
ordering returns `unverified` in **both** directions rather than guessing. A legacy
seeded placeholder instant is rejected *"in ANY spelling of the same instant"*
(`:1343-1347`, cross-review **X4**). Tests pin the timezone-independence
(`site/src/__tests__/scoring-integrity.test.ts:274-305`).

### 2.9 Excluded-but-resolved must never masquerade as unresolved

`site/src/data/brier-lab.ts:46-50` (re-audit **X9**): every `excluded_*` eligibility
reason describes a *resolved* target whose run an integrity gate kept out; folding it
into `unresolved` would understate the failure rate. Mirrored at
`site/src/data/thesis-log.ts:1459-1462`.

### 2.10 Waivers may only shrink

`waivers.json` enumerates four grandfather sets (4 pre-cutover v1 registrations, 23
v2, 21 template-less docket series, 40 legacy-incomplete custody roots) and
`tests/test_waiver_ratchet.py` recomputes each population from live state on every CI
run; exceeding the manifest fails the build (`AGENTS.md:249-258`). Six unattested
records commits exist as a **public admission list**, not an exemption
(`AGENTS.md:203-205`).

### 2.11 There is a full referee report on the paper — read it before designing anything

`reviews/2026-03-17T1715/` contains an editor letter, three referee reports
(methods / JDM fit / AI empirics) and a revision checklist. Referee 1's finding 2 is
the origin of the entire off-framework battery:

> *"Prompt-probe alignment is a serious confound that the paper does not yet
> neutralize. The farness prompt explicitly instructs the model to consider base rates
> and identify cognitive biases, while the probes then test exactly those dimensions."*
> — `reviews/2026-03-17T1715/referee-1-methods.md:14`

Also from the same set, each a constraint on us:

- **Effective N is the cluster count, not the run count.** 66 observations per cell are
  repeated stochastic draws nested in 11 scenarios; *"effective between-scenario
  generalization [is] closer to 11 than 66"*, yet the paper still reported a power
  calculation under independence (`referee-1-methods.md:15`). Our design has 12 units
  and 5 repeats; **our effective N is 12, and we should say so on every table.** The
  requested-but-not-yet-done remedies are leave-one-scenario-out, random-slope
  sensitivity, and cluster bootstrap (`referee-1-methods.md:16`,
  `revision-checklist.md:20-21`).
- **Probe directional imbalance.** 7 of 8 non-adversarial scenarios push downward, 1
  pushes upward (`referee-3-ai-empirics.md:39-43`; conceded at
  `paper/preemptive_rigor.md:346-350`). Our D1 has the mirror-image risk: the FRA
  provisions all push participation down, so we have no upward arm. Worth naming as a
  limitation rather than discovering it in review.
- **The outcome is not a validated proxy.** *"smaller updates may simply reflect
  greater stubbornness"* (`referee-1-methods.md:13`). Our `spread_pp` has the same
  property in reverse — larger dispersion is not automatically worse, it is
  *unreported*. Keep the framing at "undisclosed sensitivity", not "error".

### 2.12 Catalog and prior-run circularity (recurring, still live)

The forecaster repeatedly cites a prior published Thesis run **for the same target**
as corroborating evidence. It recurs often enough that a standing rubric item exists in
every pre-submit review prompt (*"No leakage, catalog point/interval circularity…"*,
e.g. `records/thesis-analyst/2026-07-01/2026-07-01t05-14-47z-…/pre_submit_review_prompt.md:30`),
and it is banned at design level (`docs/thesis-architecture.md:638`,
`agents/thesis-analyst/system.md:59-63`). Relevant to us only if we ever let a model
see a sibling condition's output — under `debate` we do, so the Skeptic/Verifier
prompts must not leak the draft's provenance.

### 2.13 The signed-zero split-brain — and a stale fourth port that still has it

**[Verified first-hand.]** Python's `json` preserves `-0.0`; JavaScript's
`JSON.stringify` drops the sign. A `gpt-5.6-sol` run forecasting `-0.0` therefore
produced sealed Python sidecars and regenerated TypeScript that disagreed on a value
that is numerically equal. Caught by a strict `Object.is` check in the publish gate.
The fix scrubs signed zeros at intake and in both CDF ports —
`site/src/data/prediction-distribution.ts:303-306` now returns
`Number(value.toPrecision(12)) + 0` with the reason in a comment; mirrored in
`scripts/run_thesis_analyst.py` and `scripts/normalize_spawn_json.py:110-127`.

**The fix did not reach `forecast-api`.** I checked directly:
`forecast-api/src/lib/prediction-distribution.ts:328-329` still returns
`Number(value.toPrecision(12))` with **no `+ 0`**; its returned distribution
(`:186-202`) passes `summary.pointEstimate` / `median` / `interval80` through
unnormalised and emits **no `transformVersion` field at all**, while the site version
(`:96-108`) sets both. So the API can emit a distribution that is byte-different from
what the pinned site/Python pair produces for identical inputs.

**Operational consequence for today: treat `site/src/data/prediction-distribution.ts`
+ `scripts/run_thesis_analyst.py` as the one pinned pair, and anything obtained
through `forecast-api` as a different vintage.** Do not pin our Python port against
the API copy.

### 2.14 Backfill leakage in both directions (N5)

Two symmetric problems, both fixed:

- A backfilled observation can carry an old `observedAt` but a late `acceptedAtUtc`.
  Admitting it into a "pre-cutoff" baseline or normalisation-scale computation would
  silently rewrite already-published statistics after the fact. Both dates must now
  precede the cutoff (`site/src/data/time-series-priors.ts:403-416`,
  `site/src/data/thesis-log.ts:121-124`).
- The inverse: an observation that was **already a member of the ledger state when the
  target was registered** is not a forward resolution at all — *"availability means
  membership, not publisher dates"*. Registration now requires
  `acceptedSequence >= ledgerPinLineCount` (`site/src/data/thesis-log.ts:1652-1664`;
  rationale `scripts/pin_ledger.py:1-9`).

**Directly load-bearing for us.** Our forecast origin is the 2023-06-01 ALFRED vintage
with history truncated at 2023-05-01 — the same discipline, applied to a vintage
rather than a ledger sequence. The repo's lesson is that *publisher-claimed dates are
not availability*; our equivalent guard is the vintage pin itself, and the
preregistration's assertion that no history row is at or after any unit's target month
(`experiments/billimpact/PREREGISTRATION.md:52-56`).

### 2.15 Wrong observation matched to a target (N6), two ways

First-print selection originally compared timestamp **strings** lexically, so a later
print with a different UTC offset could sort before an earlier one; now parsed to
instants with string order only as a tiebreak (`site/src/data/thesis-log.ts:805-822`).
Separately, *"a wrong-unit fact from an unrelated source scored a reproduced target"* —
resolution facts are now rejected unless the full registered binding, unit included,
agrees (`:1525-1532`).

### 2.16 A slow run could sneak in under its start time (X1)

`runAt` is stamped by the harness **at seal time, after the agent finishes** — never
self-reported, never the start time — so a run that begins before a release and ends
after it correctly classifies as `violated`
(`scripts/run_thesis_analyst.py:2942-2949`).

### 2.17 A type coercion that silently disabled a whole gate

Python `bool` subclasses `int`, and JSON `true` satisfies a loose `typeof number`
check, so `ledgerPinLineCount: true` would pass an `isinstance(x, int)` gate and
**silently disable the entire N5 backfill boundary**. Fixed by requiring
`type(x) is int` exactly (`scripts/register_targets.py:134-138`). A good reminder that
a gate can be green because it never executed.

### 2.18 Resolver-side findings worth knowing

- **Finding 3:** an assertion's content-addressed identity must commit to everything
  that changes its meaning — value, timing, population, measure mapping, publisher
  provenance, lineage, archive digest — so *"a correction must supersede explicitly"*
  rather than silently overwrite (`scripts/resolve_pending.py:5457-5466`).
- **Finding 9:** with multiple registration snapshots for one `dataPointId`,
  lexicographic file order silently picked whichever sorted last, producing a
  valid-but-wrong contract hash (`:5356-5391`).
- **Finding 10:** GitHub's compare-commits API paginates at 250; taking one page would
  hide a rewrite-then-restore in the omitted middle (`scripts/pin_ledger.py:1425-1430`).
- **Finding 11:** a witness bundle can be internally hash-consistent yet contradict
  reality; archived responses are now cross-checked against the claimed SHA
  (`scripts/verify_custody.py:1078-1088`).

### 2.19 Two things the docs assert without a recoverable narrative

Reported as gaps rather than dressed up:

- **The 2026-06 Vercel incidents.** `CLAUDE.md:75-77` and `forecast-api/README.md:4-6`
  both state that `vercel --prod` from a checkout captures the production alias and
  *"caused both 2026-06 incidents"*, and the rule is clearly load-bearing — but no
  postmortem describing what actually broke was found anywhere in the repo. Follow the
  rule; don't repeat the narrative.
- **PolicyEngine-as-ground-truth.** The prohibition (§6) is a standing convention with
  calibration machinery implying it was learned from *some* comparison, but **no
  documented incident** where raw microsim output was mistaken for ground truth and
  caused a scored error was found. Present it to Max as doctrine, not as a scar.

---

## 3. How scoring works, end to end

### 3.1 The forecast-cell contract

One JSON object per forecast (`docs/cell-contract.md:12-55`). Load-bearing fields:
`dataPointId` (`agency.dataset.concept.period.first_print`), `resolutionDate`
verified from an official calendar, `resolutionSourceUrl`, an exact `resolutionRule`,
`pointEstimate`/`ciLow`/`ciHigh`/`confidence` (default 0.8), `historicalContext`,
`sourceContext` (≥2 URLs actually fetched), `runAt` from a real `date -u` call, an
`activityLog`, and a `reasoning` array.

**Depth bar, enforced twice** — by `scripts/spawned_cells_to_ts.py` and again in CI by
`site/src/__tests__/trace-depth.test.ts` (`docs/cell-contract.md:58-62`): ≥7 reasoning
steps; ≥3 tool steps whose results carry numbers fetched this run; one explicit
base-rate step; one math derivation; one disconfirming consideration; a final forecast
step exactly matching the cell numbers; ≥3 real `historicalContext` points; and
`ciLow < point < ciHigh`.

`activityLog` is written by the runner, **not the model** (`:64-72`). The converter
stamps `predictionRun` with `promptHash = sha256(system.md)` and `toolPolicyHash =
sha256(skills/*.md sorted by filename)` (`:74-81`) — computed at
`agents/thesis-analyst/build_prompt.py:39-55`. **These two hashes are the repo's
native identifiers for a harness configuration.** Any ablation we run should key on
them.

### 3.2 `numeric_cdf_v1`

`site/src/data/prediction-distribution.ts:11-34`. Exactly **201 points**, a `support`
band, a monotone non-decreasing probability array starting at 0 and ending at 1, a
`summary` (point, median, 80% interval), a `provenance` of `agent_reported` or
`interval_seeded`, and a `transformVersion`.

`buildNumericCdfFromInterval` (`:43-110`) is the `interval_anchor_v1` transform:
piecewise-linear through five knots — `(supportLower, 0)`, `(ciLow, 0.1)`,
`(point, 0.5)`, `(ciHigh, 0.9)`, `(supportUpper, 1)` (`:77-83`) — with support
extended 1.5× the respective half-spread beyond each CI bound (`:54-57`). Validation
is a separate exported function returning **all** failures (`:210-251`).

### 3.3 Exact-integral CRPS

`scoreNumericCdfDistribution` (`:147-204`). CRPS = ∫ (F(x) − 1{x ≥ y})² dx, computed
segment-by-segment in closed form rather than by quadrature: for an error term linear
from `e0` to `e1` across width `w`, the squared integral is `w(e0² + e0·e1 + e1²)/3`
(`:271-283`). The segment containing the observation is split at the observation and
integrated on both sides (`:162-178`). Observations outside the support add the
linear tail distance (`:189-196`).

The same call returns **PIT** — `probabilityIntegralTransform`, the interpolated CDF
value at the observation (`:200-202`). **80% coverage** is computed separately as
`ciLow <= observed <= ciHigh` (`site/src/data/thesis-log.ts:1836-1837`).

### 3.4 Normalised CRPS and the dispersion that must not be forecast-authored

`targetNormalizationScale` (`site/src/data/thesis-log.ts:1402-1457`):

- cutoff = the target's `registeredAt`, falling back to the primary run's `runAt`
  for legacy targets with no registration timestamp (`:1423-1435`);
- take the same-series ledger history at that cutoff; require **≥3 observations**
  (`:1437-1440`);
- take **successive first differences**, then the **sample standard deviation**
  (Bessel-corrected, `/(n-1)`) of those diffs (`:1442-1447`);
- non-finite or non-positive → `unavailable`.

Then `normalizedCrps = crps / scale`, `normalizedAbsoluteError = |error| / scale`,
`sharpness = interval80Width / scale`, all null when the scale is unavailable
(`:1824-1835`). Reward = `-normalizedCrps` (`site/src/data/brier-lab.ts:470-476`).

The prohibition is stated in two places and enforced by a test: forecast-authored
`historicalContext` and forecast interval widths are **never** normalisation inputs
(`docs/brier-lab.md:43-47`; test *"ignores fabricated forecast history completely"*,
`site/src/__tests__/scoring-integrity.test.ts:204`).

### 3.5 The reward export

Route: `site/src/app/brier/reward.json/route.ts:1-28`, `dynamic = "force-static"`;
composes ledger → resolved forecasts → specs → runs → `buildBrierRewardExport`.

Row schema `brier_reward_row_v1` (`site/src/data/brier-lab.ts:65-123`): ids, split,
`scoreEligibility`, agent/model/run labels, `distributionProvenance`,
`transformVersion`, `resolutionDate`, `horizonDaysAtRun`, the reward block, an
`auxiliaryJudges` block hard-coded `rewardEligible: false` (`:96-97`), a
`preSubmitReview` block, and provenance (`promptHash`, `toolPolicyHash`,
`inputBundleHash`, `custodyRootSha256`, `activityArtifactCount`).

Nine eligibility values (`:51-60`). **Only `scored_witness_verified` earns reward**;
`scored_deterministic_baseline` (the replayable persistence baseline) carries score
components for the paired comparison without a witness of its own (`:39-45`).

Leaderboard (`:125-143`): unpaired means are reported as descriptive only; ranking is
by the **target-paired** difference against persistence, with
`pairedCrpsRatioGeomean` (below 1 beats persistence) as the scale-free statistic.

### 3.6 Splits

`getBrierEvalSplit` (`site/src/data/brier-lab.ts:383-390`): not resolved →
`unresolved`; `resolutionDate < "2026-07-01"` → `train`; `< "2027-01-01"` →
`validation`; else `test`. String comparison on ISO dates. `trainingEligibleSplits:
["train"]`, holdout `["validation", "test"]` (`:365-366`). Rule text: *"Rows are split
by resolutionDate, not run order"* (`:364`). Also `docs/brier-lab.md:96-106`,
`AGENTS.md:141-146`.

---

## 4. "First print" resolution

`scripts/resolve_pending.py` is 6,476 lines. Its own docstring states the shape: each
adapter *"claims a family of targetFactRefs from the live catalog's resolutionLinks,
checks whether the official first print exists yet, and emits a PolicyEngine-Ledger
fact row"* (`:2-24`). Every adapter is a (fetch fn, parse fn, per-series spec dict)
triple dispatched in `main()` on a `kind` string.

### 4.1 Adapters that actually exist

| Source | Endpoint | Defined at | Coverage |
|---|---|---|---|
| ALFRED (vintage CSV) | `alfredgraph.csv?id=…&vintage_date=…` (`:80-83`) | `fred_advance_value` `:335-352`, `fred_vintage_series` `:355-374`; `ALFRED_ADAPTERS` `:388-899` | 48 dataPointId stems (BLS CES/CPS/CPI/JOLTS/PPI/ECI, BEA, Fed G.17/G.19, Census) + DOL weekly claims `ICSA`/`CCSA` (`:4036-4128`) |
| BLS Public Data API v2 | `api.bls.gov/publicAPI/v2/timeseries/data/…` (`:957-960`) | `bls_series_rows` `:3796-3813`; `BLS_API_ADAPTERS` `:962-1048` | 4 series (3 CES defence industries + CPI-U annual) |
| BLS QCEW | `data.bls.gov/cew/data/api/{yr}/{q}/industry/{ind}.csv` (`:1071-1073`) | `qcew_fetch_period` `:4014-4033`; `QCEW_ADAPTERS` `:1074-1105` | 1 series (NAICS 336411 establishments) |
| BLS CPS Table A-19 | pinned Wayback snapshots of `bls.gov/web/empsit/cpseea19.htm` (`:908-913`) | `a19_values_from_html` `:3749-3759` | 6 occupation rows; no live API exists |
| CMS provider-data | `data.cms.gov/provider-data/api/1/metastore/…` (`:1119-1122`) | `cms_provider_data_metastore` `:1201-1224`, `…_value` `:1250-1351` | 2 series (nursing-home staffing, occupancy) |
| USAspending v2 | `api.usaspending.gov/api/v2` (`:2265`) | `fetch_usaspending_json` `:2754-2779`; `USASPENDING_ADAPTERS` `:2273-2441` | 6 DoD obligation/award/recipient series |
| Statistics Canada WDS | `getDataFromVectorsAndLatestNPeriods` (`:1425-1428`) | `statcan_series` `:3138-3161` | CPI YoY, monthly GDP |
| ABS Data API (SDMX-JSON) | `data.api.abs.gov.au/rest/data/…` (`:1429-1432`) | `abs_series` `:3237-3250` | monthly CPI annual rate, unemployment rate |
| Eurostat | `ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/…` (`:1433-1436`) | `eurostat_series` `:3313-3328` | HICP flash YoY (reads JSON-stat status flags) |
| ONS v1 | `api.beta.ons.gov.uk/v1/data?uri=…` (`:1437`) | `ons_series` `:3360-3371` | **implemented but zero admitted series** |

All international/Wayback fetches route through `http_get`/`http_request`
(`:3079-3103`) with an HTTPS-only per-adapter host allowlist and pinned redirect
targets (`_PinnedRedirectHandler`, `:3039-3058`).

**There is no Treasury MTS, IRS, Census ASEC/SPM, or USDA-FNS/WIC adapter.** Those
families appear only in `docs/thesis-architecture.md:119-127`, which is explicitly an
aspirational document (`:1-5`). **Directly relevant to us:** our SNAP indicator has no
native adapter in this repo, which is exactly why our preregistration resolves against
first prints discovered by walking ALFRED vintages rather than through
`resolve_pending.py`.

### 4.2 Vintage pinning

The rationale is in the header: *"ALFRED with a vintage date pins the ADVANCE print
(what the resolver rules name); plain FRED would silently hand back revised values on
backfills"* (`:78-80`). Mechanically, the URL carries a single `vintage_date`
parameter, and `fred_vintage_series` selects the column
`f"{series_id}_{vintage.replace('-','')}"` when present, falling back to the plain
column (`:348-349`, `:369-371`).

The pin is **never "today"**: `vintage` is the cell's own pre-registered,
calendar-verified `resolutionDate`, read from `forecast["resolutionDate"]` (`:4116`,
`:4149`) and passed as `cache_key = (spec["fred"], release_day.isoformat())`
(`:5943-5945`).

Note for accuracy: the repo does **not** use FRED's `fred/series/observations` REST
API — `vintage_dates`, `realtime_start` and `realtime_end` appear nowhere in the
repository. It uses the `alfredgraph.csv` graph export with one `vintage_date`. Our
own vintage-walk should not assume the REST parameters are in play here.

### 4.3 The BLS preliminary-footnote temporal gate

Documented at `:929-956`: *"first-print discipline is temporal: a period is captured
only while it is still the series' latest published month AND still carries BLS's
preliminary 'P' footnote — the window between the Employment Situation release that
first prints it and the next one (~4 weeks)."*

`bls_rows_from_payload` (`:3762-3793`) keeps only `M01`–`M12` rows (regex excludes the
`M13` annual-average row, `:3777`) and sets
`preliminary = any(footnote.get("code") == "P" …)` (`:3787-3791`).

The gate is `bls_first_print` (`:3896-3918`), returning a value only when
**all three** hold (`:3912`):

```
period == latest_period  and  state["latest"]  and  state["preliminary"]
```

Three outcomes, deliberately distinguished:

- **capture** — all three hold;
- **refuse** — the period exists but is no longer latest-and-preliminary
  (*"resolve manually from an archived vintage"*, `:3913-3917`), or is absent while a
  later period is already published (*"first-print window was missed"*, `:3905-3910`);
- **defer** — absent with no later period published (`None, None`).

Pinned by `tests/test_resolve_pending.py:740-765`. A separate anchor-tolerance gate
(`bls_anchor_mismatches` `:3816-3833`, `BLS_ANCHOR_TOLERANCE = 0.02` `:961`) tolerates
normal CES revision drift — the documented example is DoD April 2026 first-printing
474.9 and later reading 476.6, +0.36% (`:945-951`) — while still rejecting a
wrong-series fetch.

**The design idea worth stealing:** first-print status is established by a *temporal
window plus a publisher's own provisional marker*, not by trusting a stored value. Our
own first-print discovery walks vintages forward until a non-missing value appears
(`experiments/billimpact/PREREGISTRATION.md:77-82`) — a different and, for a
2-year-lagged series, appropriate method. Be ready to explain why the methods differ.

### 4.4 The bar an adapter must clear

There is no single `trusted` flag; there are seven stacked gates. I found **no
per-adapter dry-run or shadow mode** — `--dry-run` (`:5773`) is one global flag that
still runs every fetch/anchor/window gate and only skips the ledger-append network
calls (`:6384-6388`).

1. **Family/adapter collision guard.** `FAMILY_ADAPTERS` (`:5647-5659`) maps resolver
   kinds to the only registered adapter names each may resolve;
   `binding_adapter_mismatch` (`:5662-5676`, called at `:5865`) refuses a target
   already registered under a different adapter. The comment names the incident: *"the
   2026-07-25 new-home-sales collision, where a 2026-07-10 generic-url registration
   met a newly added ALFRED stem"* (`:5650-5654`).
2. **Registration enum + committed template.** `scripts/register_targets.py:52-61`
   fixes the eight legal `SOURCE_ADAPTERS` and `:69` the three `RELEASE_POLICIES`
   (`first_print`, `advance_vintage`, `registered_query_snapshot`); native and
   recurring bindings must **byte-match** exactly one committed
   `extras.sourceBinding` template in `scripts/docket_series.json`
   (`:781-791`, `:845-886`, `:1361-1393`). Note `bls-api` and `bls-qcew` are *not*
   members of `SOURCE_ADAPTERS`, so those targets cannot use this path at all.
3. **Three-first-print fixture admission (the real bar).** `INTL_ADAPTERS` is
   `INTL_ADAPTER_CANDIDATES` filtered by a hardcoded reviewed set
   (`:2839-2862`), with the rule stated outright: *"Only pairs that reproduced at
   least three official first prints from real captured payload bytes are
   executable"* (`:2835-2838`). Each admitted spec carries ≥3 `verified_anchors` and
   an `admission_fixture` in `tests/fixtures/international/`, losslessly trimmed from
   archived official bytes with recorded SHA-256s
   (`tests/fixtures/international/README.md:1-14`).
   `tests/test_resolve_pending.py:2659-2690` replays each fixture through the real
   parser and asserts every anchor reproduces; `:2736-2757` asserts exactly 5 admitted
   specs; `:2972-2988` pins the 11 blocked stems by name. **Of 26 candidate
   international stems, 12 (5 unique specs) are executable; all four ONS candidates
   are blocked.**
4. **Runtime anchor re-check.** `intl_anchor_failures` (`:3446-3465`) re-checks
   anchors against the live fetch every run: *"failing closed here is the core safety
   property: a candidate series that cannot reproduce the cell's own recorded history
   must never resolve it"* (`:3450-3452`).
5. **Explicit per-adapter verification flags.** QCEW requires
   `anchor_status == "VERIFIED"` and ≥3 anchors (`:4007-4011`, checked `:5988-5992`);
   its parser is *"deliberately fail-closed until the mandatory three live-source
   anchors can be reproduced"* (`:1065-1070`).
6. **Write-time re-derivation.** `source_binding_projection` (`:5504-5568`), called
   from `attach_resolution_provenance` (`:5609-5644`) just before append, re-derives
   unit/concept/host **from the fetched row** and raises on any disagreement with the
   registered contract — because a tautological check would let *"a row from a
   different publisher, period, or concept still 'match'"* (`:5509-5514`). A refusal
   drops that row only, not the run (`:6396-6423`).
7. **Publish-time CI gate.** `propose_ledger_append` (`:5083…`) opens a PR against
   `PolicyEngine/ledger` and polls for a check-run named `"Append gate"`;
   `append_gate_verdict` (`:5068-5080`) requires ≥1 success and no adverse conclusion
   before merge (`:5184-5200`). **What that gate checks lives in the separate
   `PolicyEngine/ledger` repository and could not be verified from here.**

One narrow, hash-pinned legacy exception exists — `LEGACY_INTL_EXECUTOR_CONTRACTS`
(`:2878-2911`) — admitting exactly one ABS target under its exact
`targetContentHash`, with the comment: *"not a generic-url compatibility escape hatch.
Other legacy international registrations remain refused unless individually reviewed
and added here"* (`:2875-2877`).

**No runtime dual-source requirement exists.** The closest thing is a one-time
admission note recording a past manual cross-check of three A-19 rows against ALFRED
(`:906-907`) — a comment, not code that re-checks on every run.

### 4.5 `first_print` semantics

`docs/cell-contract.md:27-28` fixes the convention: `dataPointId` ends
`.first_print`, and `resolutionRule` is free-text prose naming series, table, line,
first print, rounding, and condition policy. The suffix is assigned by
`register_targets.py:328-368` — native international registrations get
`.first_print` (`:350-351`); a binding with `releasePolicy ==
"registered_query_snapshot"` gets that suffix instead (`:364-367`), the explicit
carve-out for USAspending, *"[which] revises continuously, so a target's outcome is the
value its pinned query returns on the registered capture date… never a source first
print"* (`resolve_pending.py:2267-2269`).

Enforcement at resolution time is **adapter-specific, not one shared function**:
ALFRED/StatCan/ABS/Eurostat use a `first_print_window_days` elapsed-time check against
the forecast's `resolutionDate` (`:1562`, `:1605`, `:1644`, enforced `:5904-5913`);
BLS-API uses the latest+preliminary gate (§4.3); QCEW requires same-day capture so
*"a later run must not relabel a revision as the first print"* (`:5994-6002`); CMS uses
a metastore `modified`-date refresh window (`:1227-1247`); Eurostat HICP flash
additionally requires the live response to still carry its provisional status flag
(`flash_vintage_missing`, `:3468-3478`).

---

## 5. Chronology and pre-registration proof

### 5.1 The four classes

`site/src/data/thesis-log.ts:1318-1323`. Verified verbatim; the brief's list is
correct. Policy version string `chronology_v4_witnessed_publication` participates in
score IDs (`:1326`, re-audit **X3**).

`classifyScoreChronology(runAt, observedAt)` (`:1334-1360`) produces the *claimed*
tier only:

- missing `runAt` or `observedAt`, or unparseable day → `unverified` (`:1338-1341`);
- run instant equal to the legacy seeded placeholder → `unverified`, in any spelling
  of that instant (`:1343-1347`);
- both instants explicit → `claimed_time_verified` if `runInstant < observedInstant`,
  else `violated` (`:1349-1353`);
- day granularity only → strictly earlier day verifies, strictly later violates,
  **same day → `unverified`** (`:1354-1359`).

### 5.2 What it takes to be `witness_verified`

`composeScoreChronology(claimed, proof)` (`:1362-1369`):

```
claimed === "claimed_time_verified" && proof.status === "witnessed"
```

Both conjuncts required. The in-code doc is explicit that this means the run's
claimed time precedes the observation **and** its sealed custody root was externally
witnessed (RFC 3161, complete inventory, verifier-side headline eligible) **before**
the observation — and that *"External proof upgrades a claimed-time-verified score;
it never rescues an unverified or violated one"* (`:1302-1317`).

`isHeadlineChronology` returns true only for `witness_verified` (`:1383-1385`).
`hasVerifiedClaimedChronology` — the wider published-but-flagged population that cell
pages and judge diagnostics draw on — admits both top tiers (`:1375-1380`).

The rationale is stated as a one-liner worth quoting to Max: *"a claimed timestamp is
testimony, not proof"* (`site/src/data/brier-lab.ts:41-42`, re-audit **N1**).

The witness half is `classifyPublicationProof(custodyRootSha256, observedAt)`
(`site/src/data/witnessed-timeline.ts:84-132`), which returns `"witnessed"` only if,
in order: the run carries a `custodyRootSha256` (else `no_custody_root`, `:89-98`);
that hash is a key in the generated `WITNESSED_CUSTODY_ROOTS` map (else
`root_not_in_timeline`, `:99-111`); the entry has `inventoryStatus === "complete"`
**and** `headlineEligible === true` (else `root_not_headline_eligible`, `:122-124`);
and `instantPrecedence(entry.earliestWitnessedAt, observedAt) === "before"` (else
`witness_not_before_observation`, `:125-130`), with a shared day again resolving to
`"unknown"` and failing (`:67-82`).

So `witness_verified` requires **two independent strict-precedence checks**, not one:
`runAt < observedAt` (claimed) *and* `earliestWitnessedAt < observedAt` (proven). The
run's own clock is never compared to the witness clock. The score's identity itself
carries the tier: `scoreId` hashes in `chronology` and `CHRONOLOGY_POLICY_VERSION`
(`site/src/data/thesis-log.ts:1756-1787`, re-audit **X3**), so a chronology change
mints a new score rather than silently editing one.

### 5.3 Custody roots

Written after all activity artifacts, containing raw-byte and canonical-JSON SHA-256
commitments including a commitment to the manifest before its root reference; the
runner then performs the only final manifest write, adding `custodyRootSha256`
(`docs/thesis-analyst-runner.md:299-304`). Construction is at
`scripts/run_thesis_analyst.py:333-373` (`custody_artifact_entry`,
`build_custody_root`); the root hash is the canonical-JSON SHA-256 of the whole
`custody_root.json` document (`:402`), and the document includes a hash of the manifest
*with the `custodyRootSha256` field excluded* — avoiding the self-reference.

Verify with `python3 scripts/verify_custody.py <run-dir>`, which recomputes
`canonical_sha256(custody)` and requires it to equal the manifest's claim
(`:1709-1714`); custody-era converter inputs are rejected if verification fails.
**Inventory v2** rejects missing required files *and any regular file in the run
directory not referenced by the manifest* (`docs/thesis-analyst-runner.md:306-312`);
40 pre-v2 roots are permanently headline-ineligible (`waivers.json`).

`headlineEligible` is defined narrowly:
`run_mode == "analyst" and inventory_status == "complete" and run_succeeded`
(`scripts/verify_custody.py:105-120`).

### 5.4 The RFC-3161 chain

**What is timestamped.** Not a forecast file. `scripts/record_forecast_snapshot.py`
builds a periodic `records/<date>/digest-<runId>.json` snapshot that gzip-archives
the published surfaces (`log.json`, `ledger.json`, `targets.json`, `reward.json`,
`build.json`, …; `SURFACES` at `:29-42`), records
`artifactCommitments.custodyRoots` — every run's `custodyRootSha256`,
`custodyRootPath` and `manifestSha256` — and chains to the previous snapshot via
`chain.prevDigestPath` / `chain.prevDigestSha256`. **That digest file's raw bytes are
what the TSA signs**, so one token transitively commits every per-run custody root
and every published surface reachable back through the chain to
`records/CHAIN_GENESIS.json`.

**Requesting.** `scripts/witness_snapshot.py` — *"Request and pin-verify independent
RFC 3161 witnesses for one snapshot"* (`:2`). Builds the query with
`openssl ts -query -data <digest> -sha256 -cert` (`:250-263`), POSTs it as
`application/timestamp-query` to each anchor (`:50-66`), writes the response to
`records/<date>/digest-<runId>.<anchorId>.tsr` (`:69-73`, `:143-144`, `:192-194`),
re-verifies immediately (`:204-214`), then writes `<digest>.witness.json` and advances
`records/CHAIN_HEAD.json` (`:280-303`). The `.tsq` query is built in a discarded
temp dir (`:248-249`) — only the TSA's response is committed.

**Two independent TSAs**, pinned in `records/trust/tsa-anchors-v{1,2}.json`:
`freetsa-root-2016` (`https://freetsa.org/tsr`) and, added in v2,
`digicert-trusted-root-g4` (`http://timestamp.digicert.com`).

**Token count on disk: 117** `.tsr` files spanning `records/2026-07-09/` to
`records/2026-07-30/` — 52 freetsa, 52 digicert (the dual-witnessed v2 pairs), and 13
legacy unsuffixed single-TSA v1 tokens. Examples:
`records/2026-07-21/digest-29850168611-1.freetsa-root-2016.tsr` and its digicert
pair (both listed in `records/2026-07-21/digest-29850168611-1.witness.json:8-32`);
legacy `records/2026-07-10/digest-29098454379-1.tsr` with sibling `.tsa.crt` and
`.tsa-ca.pem`.

**Verifying.** `verify_timestamp_token` in `scripts/verify_record_chain.py:844-1027`:
matches the claimed trust bundle to a code-pinned one (`:854-863`), recomputes the
token's SHA-256 (`:871-873`), decodes the DER via `openssl ts -reply -token_out` +
`openssl cms -verify` to extract policy OID, imprint algorithm and genTime
(`:883-912`), checks the OIDs against the anchor's allow-lists and requires SHA-256 /
32-byte imprints (`:914-932`), sanity-checks genTime against the snapshot's own
claimed times (`:934-940`), verifies against the **pinned root CA with an empty CA
path** so no system trust store participates (`:952-993`, rationale at `:947-951`),
and requires the signer certificate to appear in the anchor's `allowedSigners`
(`:996-1001`).

**Where verification runs: CI, not the site build.** `record-forecasts.yml:231-248`
obtains witnesses, verifies the chain, then refreshes the timeline; and
`ci.yml:93-102` (`wave-reproducibility`) re-runs
`scripts/verify_record_chain.py records` on **every push and PR**, so the whole
committed token chain is re-verified continuously rather than only when new tokens
land. `verify_record_chain.py` is also called from `prospect-docket.yml`,
`roll-docket.yml` and `strategy-docket.yml`.

**How the chain reaches the site.** `scripts/witnessed_timeline.py:198-249`
re-verifies each committed custody-root/manifest against the digest's claimed hashes,
calls `verify_run(run_dir)`, requires
`verified.custody_root_sha256 == commitment["custodyRootSha256"]` (`:232-234`), and
only then admits the root — carrying its `inventoryStatus` and `headlineEligible`
(§5.3) — into the generated `site/src/data/witnessed-timeline.generated.ts` as
`WITNESSED_CUSTODY_ROOTS`, which is the map `classifyPublicationProof` joins against.

### 5.5 Chronology gates reward, hard

`rewardEligibilityFor` (`site/src/data/brier-lab.ts:392-426`):

- `witness_verified` → `scored_witness_verified` (`:399-400`);
- `claimed_time_verified` → `scored_deterministic_baseline` **only** for the
  persistence-baseline agent, otherwise `excluded_chronology_claimed_only`
  (`:401-407`);
- `violated` → `excluded_chronology_violated` (`:408-409`);
- anything else (`unverified`) → `excluded_chronology_unverified` (`:410-411`).

A row outside `SCORE_CARRYING_ELIGIBILITIES` has its score dropped to `undefined`
(`:277-279`) and every reward component emitted as `null` (`:470-486`) — the row still
publishes, for counting and transparency, but carries no number. The leaderboard
counts it in `totalRuns` while excluding it from every numeric aggregate
(`:544-549`, `:564-584`).

The user-facing calibration page filters the headline literally on
`score.chronology === "witness_verified"` (`site/src/app/calibration/page.tsx:52-54`),
with claimed-time-only scores published below the fold via
`hasVerifiedClaimedChronology` (`:66-68`). Note that the named helper
`isHeadlineChronology` has **no call site outside its own definition** — the gating is
implemented by the literal check and by `SCORE_CARRYING_ELIGIBILITIES`. Behaviourally
equivalent; worth knowing if you go looking for it.

---

## 6. The house position on PolicyEngine — and our conflict

### 6.1 What the skill actually says

`agents/thesis-analyst/skills/policyengine.md:3-7`, verbatim:

> PolicyEngine is the microsimulation instrument: when a forecast turns on a
> tax-benefit parameter or a reform's aggregate impact, call it instead of
> estimating by analogy. It is an explicit MODEL INPUT, never ground truth —
> the trace says which policy ids ran and treats the output as one evidence
> stream with its own error bars.

Three further rules:

- **Calibration is mandatory** (`:19-24`): *"Static microsim impacts differ from
  official scores (CBO/JCT) by behavioral and timing effects. Keep a stored
  ratio/additive prior from past PolicyEngine-vs-official comparisons and apply it,
  with the adjustment shown in a math step. Cells whose resolution source IS an
  official score must forecast the official score, not the raw microsim number."*
- **Queued or errored runs widen the interval**, and the trace must say so rather
  than waiting silently (`:14-16`).
- **Never call it for series PolicyEngine doesn't model** (CPI, claims) — *"the trace
  should not contain decorative microsim calls"* (`:30-31`).

The skill attaches automatically to `policyengine.*`/`pe.*` series and to **every
conditional forecast** (`agents/thesis-analyst/build_prompt.py:34`, `:36`).

### 6.2 The calibration prior in code

`forecast-api/src/lib/policyengine.ts:66-73`:

```ts
const CTC_CALIBRATION_PRIOR: CtcCalibrationPrior = {
  rawToFinalRatio: 1.04,
  additiveUsdBillions: 3.5,
  minimumCiHalfWidthUsdBillions: 22,
  uncertaintyMultiplierWhenQueued: 1.4,
  source: "prototype calibration prior: ...",
};
```

Applied as `raw × 1.04 + 3.5`, with a 1.4× uncertainty multiplier when the economy
endpoint has not returned and a floor of ±22 B on the CI half-width
(`:160-166`). The public summary string states the adjustment explicitly rather than
hiding it (`:141`). Note the `source` field calls it a **prototype** prior — an
honest self-label, not a validated calibration.

### 6.3 Does our plan conflict?

**On wording, yes. On substance, probably not — and the distinction matters in the
room.**

The repo forbids treating PolicyEngine as *the resolving fact* for a forecast target.
That is a claim about **resolution**: what an official outcome is, and what a score is
computed against. Our Leg A uses PolicyEngine's computed statutory effect as the
**reference answer for an extraction task** — did the tool read the bill's parameters
correctly — which is a different use. PolicyEngine is authoritative about *what
PolicyEngine computes given a parameterisation*, and that is exactly what an
extraction check needs.

Concretely, our own Leg B preregistration already complies: it resolves against
first-print Census/USDA-FNS values with ALFRED as a history mirror only, and says so
(`experiments/billimpact/PREREGISTRATION.md:75-84`).

Recommended language for the room, and for anything written down: call it the
**reference parameterisation** or **the extraction target**, never "ground truth."
If someone insists on a single word, the repo's own vocabulary is *model input*. And
if Leg A ever scores an *impact magnitude* rather than a *parameter extraction*, the
skill's rule bites directly: a cell whose resolution source is an official score must
forecast the official score, not the microsim number (`policyengine.md:22-24`).

---

## 7. Conventions our work could violate

Ordered by how easy each is to trip over today.

1. **Never write to `records/`.** `records/**` belongs to allowlisted workflows,
   which attest every push; a committed pre-push hook refuses local pushes touching
   it, and the CI provenance audit fails main for any unattested records commit
   (`AGENTS.md:188-223`, `.githooks/pre-push:1-38`). Activate the hook once per clone:
   `git config core.hooksPath .githooks`. An override costs a **permanent public
   waiver**; six already exist. Our experiment writes belong under
   `experiments/billimpact/`.
2. **Never run strategy batches locally and push their records or generated
   TypeScript to `main`** (`AGENTS.md:114-120`). The CI selector and publisher are
   the publication authority.
3. **Never hand-edit generated forecast modules** (`AGENTS.md:39-40`); rerun the
   agent or replace the source artifact (`docs/thesis-analyst-runner.md:325-327`).
4. **Never infer `resolutionDate` from cadence** — verify from an official calendar,
   schedule, release placeholder, or policy-state rule (`AGENTS.md:44-45`;
   `docs/thesis-architecture.md:637`).
5. **FRED/ALFRED is a history mirror, never the final resolution source when an
   official agency source exists** (`AGENTS.md:46-47`). Our preregistration already
   states this compliance explicitly.
6. **Never silently clean failed agent runs into successful ones** — failed traces are
   useful records (`AGENTS.md:48-49`; `docs/thesis-vision.md:121-123`). Dropped units
   get reported as dropped.
7. **Never collapse full activity into a summary.** Preserve prompt, command,
   stdout/stderr, raw response, parsed/normalized cells, validation, manifest,
   resolution event, and score (`AGENTS.md:41-43`).
8. **No private-source evidence, ever** — no meeting notes, transcripts, pasted
   attachments, email/chat, personal notes. Public official sources and public
   repository artifacts are the entire evidence boundary
   (`docs/thesis-vision.md:115-119`, `agents/thesis-analyst/system.md:132-143`,
   `docs/cell-contract.md:87-92`).
9. **Judges never earn reward.** *"LLM judges are process diagnostics, never reward"*
   (`docs/thesis-architecture.md:48-49`); a judge signal must first be checked against
   held-out proper scores (`docs/brier-lab.md:79-81`). If we add any judge to this
   work, it is `rewardEligible: false` by construction.
10. **Catalog point estimates are not evidence for new runs**
    (`docs/thesis-architecture.md:638`; `agents/thesis-analyst/system.md:59-63`).
11. **Don't add subjectively adjudicated forecasts to the core Brier loop**, and don't
    turn Thesis into a human prediction market (`AGENTS.md:36-38`).
12. **Definition of done** (`AGENTS.md:173-184`): docs or generated artifacts updated;
    validation catches bad cells rather than letting weak traces through; the Brier
    reward export still builds; tests run or a clear reason reported. Verification
    commands are named at `AGENTS.md:147-172`.
13. **UI that hides strategy variation behind a single polished trace** is explicitly
    on the avoid list (`docs/thesis-architecture.md:643`) — relevant if we build any
    display of our ablation.

---

## 8. What to reuse rather than rebuild

### Already ported into our own directory (verify before duplicating)

`experiments/billimpact/scoring.py:42-128` is a line-by-line Python port of
`buildNumericCdfFromInterval` + `scoreNumericCdfDistribution`, and
`pin_against_typescript.py` (698 lines) pins it against the TypeScript original.
There are **four implementations of the same transform**, and they are not equal:

| implementation | signed-zero fix | `transformVersion` |
|---|---|---|
| `site/src/data/prediction-distribution.ts:43`, `:303-306` | yes (`+ 0`) | yes (`:105-108`) |
| `scripts/run_thesis_analyst.py:159-160` | yes | yes |
| **`forecast-api/src/lib/prediction-distribution.ts:140`, `:328-329`** | **no** | **absent** |
| `experiments/billimpact/scoring.py:42` (ours) | — pin to the first two | — |

**Pin against the site + runner pair only.** A golden fixture already exists for the
cross-language check: `tests/fixtures/interval_anchor_v1_distribution.json` (used by
`tests/test_thesis_analyst_runner.py:34`) — use it as a second pin rather than
inventing test vectors.

### Statistics, directly importable

- `holm_bonferroni` (`brier/experiments/stability.py:709-730`) — the repo's
  multiple-comparison convention. Use it; it is what every existing results table
  reports.
- `_bootstrap_cohens_d` (`:767`) and `_bootstrap_rank_biserial` (`:796`) — bootstrap
  CIs on effect sizes, already the house format.
- `mann_whitney_u` and `proportion_z_test` (`brier/experiments/analyze.py:64`, `:26`).
- The mixed-effects pattern `relative_update ~ condition` with a random intercept for
  case, reported alongside the pairwise tests
  (`experiments/stability_validation/strongest/claude-opus-4-6/results_table.md:60-71`).
  Our `spread_pp` / `noise_floor` construction is compatible with it and stronger.

### Harness and prompt machinery

- **`promptHash` / `toolPolicyHash`** (`agents/thesis-analyst/build_prompt.py:39-55`)
  — the native content-addressed identifier for a harness configuration. Stamping our
  ablation cells with the same two hashes makes our grid legible to anyone who knows
  this repo.
- **Prompt modes as first-class agent identities.** `fast`, `full`, `ladder`,
  `ladder_v2` land as distinct agents (`thesis.analyst.ladder_v2`) with the mode
  sealed into the cell (`AGENTS.md:97-113`,
  `scripts/run_thesis_analyst.py:2960`, `:3046`). This is precisely the
  elicitation-format axis we are ablating, and there is prior art with real targets.
- **`scripts/median_rollout_ensemble.py:1-21`** — derives a `median3` run as a
  deterministic function of K already-recorded rollouts, no new model call.
  Protocol credited to Turtel et al. 2025 (arXiv:2505.17989). If we want an
  aggregation arm, this is free.
- **`scripts/run_strategy_suite.py`** — runs one trusted suite plan over an immutable
  target selection; `SUITES` in `scripts/strategy_targets.py`.
- **Pre-submit review loop** (`docs/thesis-analyst-runner.md:207-234`): draft →
  reviewer critique → revision, with all four artifacts preserved and only the final
  forecast scored. This is a ready-made D3-`debate`-style arm with an existing
  artifact contract.
- **`scripts/run_time_series_models.py`** and the `thesis_model_candidate_v1` schema
  (`docs/thesis-analyst-runner.md:235-266`): persistence and
  `statsmodels-local-level` (SARIMAX(0,1,0) with drift, native state-space
  intervals). A no-cost benchmark arm for our `none` condition.
- **`brier/experiments/llm.py:90-195`** — provider-agnostic `call_llm` with retry
  (`MAX_RETRIES = 4`, exponential backoff from 2s) and keychain key loading, already
  handling both Anthropic and OpenAI.

### Design documents worth copying rather than re-deriving

- `brier/experiments/LLM_JUDGE_EVALUATION_PLAN.md:141-176` — blinding and the neutral
  memo envelope; `:384-444` — the analysis plan (cluster bootstrap at case level,
  hierarchical logistic with random intercepts for case / generator / judge, explicit
  tie handling); `:446-486` — a preregistered **interpretation table** mapping each
  possible outcome pattern to its permitted conclusion. That last one is unusually
  good practice and directly transferable to our P1-P4.
- `brier/experiments/DECISION_USEFULNESS_STATUS.md:119-124` — the "expand the pilot
  before the full study" discipline, and the exact reason.
- **`reviews/2026-03-17T1715/`** — an editor letter, three referee reports, and a
  revision checklist against this exact experimental programme. Reading
  `referee-1-methods.md` before finalising our analysis is the cheapest way to
  anticipate what Ghenis will ask about ours, because it is what was already asked
  about his.

---

## 9. What I could not verify

Stated plainly, because a confident wrong claim about a collaborator's repo is worse
than a gap:

- **Whether the 2026-07-08→10 strategy wave has a published effect-size comparison.**
  I found 146 recorded runs across 12 cells and the machinery that scores them, but no
  prose or data file in the repo stating "ladder beat fast by X". The Strategy Lab page
  computes its tables at build time from resolved scores, so there may be no frozen
  number by design. **Do not assert a ladder-vs-fast result to Max.**
- **The `judge ↔ -nCRPS` correlation value** rendered on `/brier/strategies`
  (`site/src/app/brier/strategies/page.tsx:128-132`) is computed at build time; I did
  not run the build, so I have no number for it.
- Decision-usefulness pilot outputs are described as **intentionally untracked**
  (`DECISION_USEFULNESS_STATUS.md:48`), yet `experiments/decision_usefulness/` exists
  locally with judge summaries. I read the local files; whether they match what is in
  the public repository, I did not check.
- **What the `"Append gate"` CI check actually verifies.** It gates every ledger
  append (`scripts/resolve_pending.py:5068-5080`, `:5184-5200`) but lives in the
  separate `PolicyEngine/ledger` repository, which is not in this checkout.
- **The `estimate_only` and on-framework `format_control` values** are not stated
  numerically in the paper's prose; they exist only in the rendered
  `paper/figures/fig_probe_validation.png` and in the raw per-run JSON. The summary
  numbers I quote in §1.3 come from
  `experiments/stability_validation/strongest/claude-opus-4-6/summary.json`, not from
  the paper.
- **The upstream-ledger RFC-3161 pipeline's token storage location.**
  `scripts/witness_upstream_ledger.py` and `scripts/ledger_release_chain.py` run a
  parallel witnessing track over `PolicyEngine/ledger` release manifests; its receipts
  appear to live in that repository's own tree rather than as bare `.tsr` files here,
  but that was not confirmed.
- **The 2026-06 Vercel incident narrative.** The prohibition on `vercel --prod` is
  stated twice as settled fact (`CLAUDE.md:75-77`, `forecast-api/README.md:4-6`), but
  no postmortem describing what broke exists anywhere in the repo. The rule is
  load-bearing; the story is not recoverable from here.
- **Whether PolicyEngine was ever actually mistaken for ground truth in a scored run.**
  The prohibition and the calibration prior imply the lesson was learned from *some*
  comparison, but I found no documented incident. Present §6 to Max as doctrine, not
  as a scar.
- **I did not run any build, test suite, or script.** Every number above was read from
  a committed file. Build-time-computed values (the Strategy Lab tables, the
  judge↔-nCRPS correlation) have no value I can quote.
- **Sub-investigation provenance.** Sections 1.7, 2.11-2.19, 4 and 5.4 were assembled
  with dedicated read-only sweeps of `paper/`, the SOL/review notes,
  `scripts/resolve_pending.py` and the chronology machinery respectively. I
  independently re-verified the claims that bear on today's work — the chronology class
  names and the `composeScoreChronology` predicate, the normalisation dispersion, the
  `forecast-api` port drift, and the `reviews/` referee finding — by reading the source
  myself. Citations I did not personally re-open are the deep resolver internals
  (`resolve_pending.py` beyond §4.1's dispatch table) and the RFC-3161 verification
  internals of `verify_record_chain.py`. Those are the two places to double-check first
  if a number ever looks wrong.
