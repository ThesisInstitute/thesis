# Web Context: Thesis Institute + PolicyEngine

Gathered live, 2026-07-31, for the bill-impact forecasting ablation study. Every claim below carries the URL it came from. Numbers were cross-checked wherever possible — raw JSON was downloaded and queried with `jq` rather than trusted from a single AI-summarized fetch (see Method note at bottom).

**Framing note visible on every page of the app**: the header carries a literal "Prototype build" tag (source: https://app.thesisinstitute.org/thesis, read via browser accessibility tree). Treat everything below as an early-stage/prototype system's own self-reported numbers, not a mature published benchmark.

---

## 1. https://app.thesisinstitute.org/thesis — "The Brier thesis: Forecasting as a harness"

This is an argumentative essay, not a data page. It contains no forecasts, no leaderboard, no calibration numbers. Written by Max Ghenis (byline link: https://maxghenis.com), open source (https://github.com/ThesisInstitute/thesis).

Nav bar on every page (confirmed via accessibility tree): Docs (`/docs`), Thesis (`/thesis`), Brier (`/brier`), Forecasts (`/` — root), Briefings (`/briefings`), Log (`/log`), Models (`/models`), Calibration (`/calibration`), Research (`/paper`), GitHub.

Key claims made in the essay (their wording, not verified against the underlying research further than the citation list they provide):
- "LLMs now surpass the median public forecaster, with projected LLM-superforecaster parity by late 2026." — no in-page number attached; cites Schoenegger et al. 2024 (arXiv:2402.19379), Halawi et al. 2024 (NeurIPS 2024, arXiv:2402.18563), and a Center for AI Safety blog post (safe.ai/blog/forecasting) as its reference set for this claim, plus ForecastBench (Karger et al. 2025, ICLR 2025).
- The five-step framework: define KPIs → expand options → decompose/forecast → surface assumptions → log and score.
- Full reference list (29 items) is academic/trade citations (Tetlock & Gardner 2015; Mellers et al. 2014, *Psychological Science*, DOI 10.1177/0956797614524255; Brier 1950, *Monthly Weather Review*; Kahneman & Lovallo 1993; Hertwig & Grune-Yanoff 2017; etc.) supporting the conceptual argument, not reporting Thesis's own results.

Source: https://app.thesisinstitute.org/thesis

---

## 2. https://app.thesisinstitute.org (root) — "Brier Lab · forecast reward engine" — THIS is the de facto leaderboard/Forecasts landing page

Important structural note: the nav's "Forecasts" link points to `/`, and `/` renders the **Brier Lab reward-engine dashboard**, not a simple "browse open questions" list. There is no separate plain forecast browser distinct from this scoreboard.

**Headline stats shown on the page** (verified via accessibility-tree read, source: https://app.thesisinstitute.org):
- RUNS: **1,188**
- SCORED: **5**
- AGENTS: **45**
- SPECS: **750**
- RESOLVED: **155**
- ACTIVITY LOGS: **379**

Reward Contract box, quoted verbatim: "**negative_normalized_crps**" as the objective, with constraints listed as: agent-only forecasts; public statistical series with predictable first-print resolution; immutable run artifacts; proper scoring rules; holdout splits by resolution date. Sub-text: "Rows are split by resolutionDate, not run order. Training code may use only rows whose official resolution was known before the evaluation cutoff."

**Splits table** (source: same page):
| Split | Scored / Total | Rule (their wording) |
|---|---|---|
| Train | 0 / 181 | "Resolved before 2026-07-01." |
| Validation | 5 / 87 | "Resolved from 2026-07-01 through 2026-12-31." |
| Test | 0 / 0 | "Resolved on or after 2027-01-01." |
| Unresolved | 0 / 920 | "Not eligible for reward until the first-print resolver posts a fact." |

**Agent Leaderboard** ("5 reward rows", 45 total agent/model rows, only 3 rows have any non-pending metric):

| Agent | Model | Runs (scored/total) | CRPS ratio vs persistence | Win rate | Unpaired reward | Unpaired nCRPS | Unpaired coverage | Activity |
|---|---|---|---|---|---|---|---|---|
| thesis.analyst | gpt-5.6-sol | 4/46 | 1.176 | 50% | -2.350 | 2.350 | 0% | 100% |
| brier.time_series_prior | persistence.last_print | 3/3 | pending | pending | -1.601 | 1.601 | 33% | 100% |
| thesis.analyst | gpt-5.5 | 4/240 | pending | pending | pending | pending | 75% | 100% |

All other 42 agent/model rows show 0 scored runs and "pending" for every metric (these include gpt-5, gpt-5-mini, gpt-5.4, gpt-5.6/-luna/-terra, gpt-5-codex, claude-fable-5, several "Codex recorded agent ensemble/run/runs" rows, BLS OEWS/Employment-Projections carry-forward baselines, and a "prototype seed" row with 313 runs and 0% activity).

Links found on this page to the other targets: Reward JSON → `/brier/reward.json`; Thesis Log JSON → `/log.json`; Scoreboard → `/forecasts/log`; Strategy Lab → `/brier/strategies`.

"Recent Reward Rows" table shows the 10 newest runs, all currently `UNRESOLVED` with `pending` reward (e.g., `us-building-permits-july-2026`, resolution date 2026-08-18). Individual forecast detail pages live at `/forecasts/<predictionId>`.

Source: https://app.thesisinstitute.org (accessed via browser render; WebFetch alone returns an empty/incomplete shell for this app — see Method note)

---

## 3. https://app.thesisinstitute.org/calibration — "The Scoreboard" — methodology + calibration, in their own words

This is the most important page for scoring-methodology language. Quoting directly:

> "Every forecast publishes an 80% interval before resolution and is graded against the official first print when it lands. This page is computed from the same records that back log.json and reward.json; the daily pre-registration chain lives in the public records repository."

> "**Scoring methodology v5 (2026-07-10)**: headline numbers count only witness-verified scores. A run enters the headline when its sealed custody root was externally witnessed — an RFC 3161 timestamp in the witnessed chronology extracted from the public record chain — before the observation, its custody inventory is complete and headline-eligible, and its recorded run time precedes the observation (sub-day ordering trusted only for explicit UTC-offset timestamps). A claimed timestamp alone never enters the headline: scores whose chronology rests on claimed times stay published in log.json, flagged claimed-time-verified, outside the official numbers, alongside unverified and violated legacy runs. CRPS is normalized only by same-series ledger dispersion frozen at target registration; scores without three pre-cutoff ledger observations publish raw CRPS and stay out of normalized means and rewards. The agent-versus-persistence headline is a per-target RAW CRPS ratio against the paired ledger baseline, which needs no scale at all — nothing a forecast author can move its denominator."

This is the pre-registration/chronology-verification language the task asked for — quote it directly if David wants to mirror their register.

**PIT / coverage curve, quoted directly:**

> "Each score records the forecast distribution evaluated at the official print (its probability integral transform), so coverage is checkable at every stated interval, not just the elicited 80%. A calibrated forecaster tracks the diagonal: above it means intervals are too wide, below it too narrow. The PIT histograms show the same thing distributionally — a calibrated forecaster fills each bin equally; a U shape is overconfidence, a central hump underconfidence. The curve reads coverage off each forecast's materialized distribution, while the headline 80% stat counts stated interval endpoints directly, so the two can differ by a few scores."

**Headline stat tiles on this page** (all sourced from the same page):
- SCORED FORECASTS: **8**, witness-verified. Sub-text: "witness-verified; 198 claimed-time-only and 62 unverified or violated excluded, 920 awaiting resolution"
- 80% INTERVAL COVERAGE: **38%** — "3 of 8 witness-verified observed inside the stated interval"
- UNPAIRED MEAN NORMALIZED CRPS: **2.350** — "Lower is better; 2 of 8 witness-verified scores have a ledger scale. Mean sharpness 3.47× target scale."
- CRPS RATIO VS PERSISTENCE: **1.18** — "Geometric mean of per-target raw CRPS ratios (agent / paired persistence baseline) on 2 matched targets; below 1 beats persistence. 50% agent win rate."

**Claimed-time tier** (one rung below headline): 206 scores, 75% interval coverage (155 of 206 inside), 0 chronology violations.

**"Forecasters against the baseline" table** (full per-forecaster rows; same as the leaderboard on the root page, plus a "claimed-time scored" column): thesis.analyst/gpt-5.6-sol = 4/46 runs, 0 claimed-time-scored, CRPS ratio 1.18, win rate 50%, nCRPS 2.350, coverage 0%. brier.time_series_prior/persistence.last_print (BASELINE) = 3/3, nCRPS 1.601, coverage 33%. thesis.analyst/gpt-5.5 = 4/240 scored/total but 64 claimed-time-scored, coverage 75%, no CRPS ratio reported.

**"Latest resolutions" table** (12 rows, both chronology tiers) — this is where I could reconstruct the "8 witness-verified" and "38% coverage" figures independently and they check out exactly (see Method note): witnessed rows include US initial claims (July 25, July 18 — both outside interval), US Continued Claims July 18 (outside), US nursing-home nurse staffing HPRD July 2026 (inside), US nursing home occupancy July 2026 (outside), US durable goods orders MoM June 2026 (inside), US Durable Goods Shipments MoM June 2026 (inside), Australia employment change June 2026 (outside) — 8 witnessed rows, 3 inside = 38%, exact match to the stat tile above.

Source: https://app.thesisinstitute.org/calibration

---

## 4. https://app.thesisinstitute.org/models — comparison structure: model × protocol lane

Quoted framing: "Every model runs the same registered targets under the same prompt contract, validator, and pipeline; every run is recorded whether it passes or fails. This page compares models on two separable axes: whether their traces satisfy the elicitation contract they were given, and — as targets resolve against official prints — how accurate their forecasts are. Compliance is not accuracy; read the tables separately."

**"Contract compliance by lane"** — this is the prompt-mode/protocol-lane comparison axis. Their wording: "Fast and Ladder demand the parametric width derivation ('sigma = X', 1.28·sigma); Ladder v2 is the pre-registered quantile-native contract (rungs plus interpolated 10th/90th percentiles stated literally)."

| Model | Fast | Ladder | Ladder v2 | Median-of-3 |
|---|---|---|---|---|
| gpt-5.5 | 38/39 | 13/13 | 6/6 | 12/13 |
| gpt-5.6 | — | 1/1 | — | — |
| gpt-5.6-luna | 5/18 | 0/6 | 5/6 | 1/6 |
| gpt-5.6-sol | 18/18 | 5/6 | 6/6 | 6/6 |
| gpt-5.6-terra | 18/18 | 0/6 | 6/6 | 6/6 |

**"Resolved accuracy" table** (by model, 80% coverage over "claimed-or-better" scores):

| Model | Resolved scores | Witness-verified | Claimed-time-or-better | 80% coverage |
|---|---|---|---|---|
| claude-fable-5 | 17 | 0 | 17 | 82% |
| gpt-5 | 39 | 0 | 39 | 79% |
| gpt-5-mini | 9 | 0 | 9 | 78% |
| gpt-5.5 | 78 | 4 | 78 | 68% |
| gpt-5.6-sol | 4 | 4 | 4 | 0% |
| persistence.last_print | 3 | 0 | 3 | 33% |
| Codex recorded agent ensemble | 2 | 0 | 2 | 100% |
| Codex recorded agent run | 16 | 0 | 16 | 75% |
| Codex recorded agent runs | 24 | 0 | 24 | 88% |
| Codex recorded source-context synthesis | 14 | 0 | 14 | 100% |

Note: "The gpt-5.6 comparison waves published on 2026-07-10 resolve from mid-July onward; per-model paired CRPS ratios against the persistence baseline appear on Calibration as those targets print." — i.e., they explicitly flag that most of the gpt-5.6 comparison is still pending resolution, not yet a completed head-to-head.

Source: https://app.thesisinstitute.org/models

---

## 5. https://app.thesisinstitute.org/brier/strategies — "Strategy Lab · baseline discipline" — a separate retrospective sandbox

Framing quote: "This page compares deterministic baselines with the actual Brier agent run on resolved target panels... Everything here is a retrospective reconstruction — strategy rows are replayed over outcomes that already resolved, carry no chronology verification, and never enter headline calibration, rewards, or leaderboards."

**SNAP FY2025 state payment-error-rate panel** (53 resolved targets, 159 score rows): the only large-n back-test on the site.

| Strategy | Mode | Rows | MAE | vs persistence | Bias | 80% cover |
|---|---|---|---|---|---|---|
| Last-print persistence | deterministic baseline | 53 | **1.38pp** | 0.00pp | +0.01pp | 87% |
| Panel shrinkage trend | deterministic baseline | 53 | 1.79pp | +0.41pp | +0.66pp | 75% |
| Brier primary agent | agent forward | 53 | **1.81pp** | +0.43pp | +0.72pp | 72% |

Notable honest self-report: on this one large retrospective panel, Thesis's own LLM agent (MAE 1.81pp) is **worse** than the naive last-print persistence baseline (MAE 1.38pp) — the agent has not beaten the simplest possible baseline here. Useful context for calibrating expectations before David's ablation claims any lift.

**LLM Judge Layer** — auxiliary process evaluation, explicitly *not* part of reward: "Judge records score forecast process quality from the public trace: base rates, source grounding, resolution clarity, uncertainty, mechanisms, counterarguments, and coherence. They are auxiliary diagnostics; reward still comes only from resolved CRPS." Reported correlation between judge score and accuracy: **JUDGE ↔ -NCRPS: -0.090** (i.e., essentially no relationship in their own data so far — judge scores should not be treated as a proxy for real accuracy).

Source: https://app.thesisinstitute.org/brier/strategies

---

## 6. https://app.thesisinstitute.org/briefings — the fourth comparison axis: "pack sets"

Framing quote: "A briefing hands a forecaster curated evidence, calibration rules, and checks up front — research stays fully open with or without it, so briefed-versus-unbriefed contrasts measure the value of curation, not information access... Designed to be tested against no-pack controls or other pack sets on the same target."

Headline stats: **14 packs**, **97 runs using packs**, **39 targets**.

Named packs (each shown with type tag, version, runs, agents): ASEC income nowcast (MODEL, 1 run), ASEC release calibration (CALIBRATION, 2 runs), Base-rate-first (METHOD, 28 runs, 2 agents), BLS employment projections baseline (DATA, 12 runs, 2 agents), Cash-income bridge (MODEL, 1 run), Consumer-spending nowcast (DATA, 1 run), CPI component decomposition (MODEL, 8 runs, 2 agents), Energy price nowcast (DATA, 5 runs, 2 agents), Housing activity nowcast (DATA, 1 run), Labor-market momentum (DATA, 8 runs, 2 agents), Panel persistence shrinkage (METHOD, registered, 0 runs), PCE-CPI bridge (MODEL, 2 runs, 2 agents), Release-vintage calibration (CALIBRATION, 24 runs, 2 agents), Tariff pass-through (CALIBRATION, 4 runs, 1 agent).

Source: https://app.thesisinstitute.org/briefings

---

## 7. https://app.thesisinstitute.org/log — "Thesis Log" — activity log with a third, broader scoring view

Quote: "Thesis Log records predictions, distributions, trace metadata, resolution events, and scores. Resolved predictions reference facts in the PolicyEngine Ledger."

Headline stats: PREDICTIONS 1188, SPECS 750, RUNS 1188, RESOLVED 155, PENDING 595, SCORED/COVERAGE **206 · 75%**.

This "206 scored" figure is the "claimed-time-or-better" tier (matches the /calibration page's 8 witness-verified + 198 claimed-time-only = 206 exactly).

**Scoreboard (206 scored)**: MEAN NCRPS **1.69**, MEAN CRPS **13.6**, MEAN ABS ERROR **16.8**, 80% COVERAGE **75%** (target: 80%).

**"By run type" table — this is the pack-set-vs-no-pack comparison in aggregate:**

| Run type | Runs | Scored | nCRPS | CRPS | 80% coverage |
|---|---|---|---|---|---|
| Primary | 971 | 152 | 1.69 | 10.2 | 73% |
| No packs | 177 | 30 | n/a | 34.1 | 87% |
| With packs | 40 | 24 | n/a | 9.38 | 75% |

Caution on this table: "No packs" and "With packs" are not necessarily the same underlying questions/agents, so the CRPS gap (34.1 vs 9.38) is suggestive, not a controlled A/B result as published.

**"By agent" and "By model" tables** confirm the same pattern seen elsewhere (thesis.analyst 386 runs/89 scored/nCRPS 1.77; gpt-5.5 271 runs/78 scored/nCRPS 0.62; gpt-5.6-sol 63 runs/4 scored/nCRPS 2.35; persistence.last_print 3/3/nCRPS 1.60; plus a long tail of Codex-recorded ensembles, claude-fable-5 [21 runs/17 scored/no nCRPS reported], and unscored BLS/OEWS carry-forward baselines).

Source: https://app.thesisinstitute.org/log (page is long — 54k+ characters; the excerpt above covers the summary/scoreboard/by-agent/by-model/by-run-type sections and the start of the resolution queue. I did not enumerate all 595 pending rows or all 155 resolved rows individually.)

---

## 8. Individual forecast detail page — https://app.thesisinstitute.org/forecasts/initial-claims-week-2026-07-25

Full example of a resolved, witness-verified forecast cell:

- Question: "What will the advance first print of US seasonally adjusted initial unemployment insurance claims be for the week ending July 25, 2026?"
- Forecast: **212k**, 80% CI **[202k, 222k]**, published by thesis.analyst / gpt-5.6-sol, run at 2026-07-21T01:03:01Z
- Resolution rule (quoted): "Resolve to the advance figure for seasonally adjusted initial claims for the week ending July 25, 2026, published by the U.S. Department of Labor on July 30, 2026, expressed in thousands and rounded to the nearest thousand. Use that first official print only; ignore subsequent revisions." — this is the "first-print resolution" language the task asked for.
- Actual: **197k**, resolved July 30, 2026. Outcome: outside the 80% interval.
- Error: -15k (absolute 15k). **CDF SCORE: CRPS 10.3 · PIT 0.067** — confirms PIT is reported per-forecast on detail pages even though the string "PIT" does not appear as a JSON field name in reward.json (see Method note).
- Paired baseline shown on the same page: brier.time_series_prior / persistence.last_print forecast 208k, 80% CI [199k, 217k], also outside interval (actual 197k), -4k adjustment from last print.
- Source cited: "DOL ETA UI Weekly Claims news release, advance seasonally adjusted figure for the week ending 2026-07-25, read from FRED ICSA (advance vintage) as the cell's resolver names."
- "More government data forecasts" module at the bottom links to open questions: SPM child poverty rate 2025 (13.1%, resolves Sep 2026), Official poverty rate 2025 (10.4%), Median household income 2025 ($80,600) — these are PolicyEngine-Ledger-linked social/economic indicators, not just BLS/Census releases.

Source: https://app.thesisinstitute.org/forecasts/initial-claims-week-2026-07-25

---

## 9. https://app.thesisinstitute.org/docs — installation/usage docs, NOT scoring methodology

This page documents the `brier` Python/CLI/MCP tool (install via `pip install brier[mcp]`, `brier setup codex`/`brier setup claude`, local decision log at `~/.brier/decisions.jsonl`) and a personal-decision workflow (KPI → options → base rate → decompose → surface disconfirming evidence → point estimate with 80% CI → review date). It does not describe CRPS/PIT/coverage methodology — that content lives on `/calibration` (section 3 above). Included for completeness since the task asked for the docs page specifically.

Source: https://app.thesisinstitute.org/docs

---

## 10. https://app.thesisinstitute.org/paper — Research paper: NOT PUBLISHED

The page renders only: **"Paper not yet rendered. Run: python3 paper/render_paper.py"**. The "stability-under-probing" methodology mentioned on the `/thesis` essay page has no public write-up yet. This is a genuine gap, not a fetch failure — logged in COULD NOT RETRIEVE below.

Source: https://app.thesisinstitute.org/paper

---

## 11. https://app.thesisinstitute.org/brier/reward.json — full schema and contents

Fetched directly via `curl` (HTTP 200, 8,972,587 bytes) and parsed with `jq` — not summarized by an intermediate model. Top-level keys: `schemaVersion`, `generatedAt`, `mission`, `counts`, `splits`, `noLeakagePolicy`, `judgePolicy`, `judgeResults`, `leaderboard`, `pairedComparison`, `baselineCoverage`, `rewardRows`.

- `schemaVersion`: `"brier_reward_export_v2"`
- `generatedAt`: `"2026-06-16T00:00:00Z"` — **see freshness flag below**
- `mission`: `{"agent": "Brier", "objective": "maximize_forecast_accuracy", "reward": "negative_normalized_crps", "constraints": ["agent-only forecasts", "public statistical series with predictable first-print resolution", "immutable run artifacts", "proper scoring rules", "holdout splits by resolution date"]}`
- `counts`: `specs=750, runs=1188, scoredRuns=5, rawScoredRuns=11, unresolvedRuns=920, agents=45, traceJudgedRuns=1188, postResolutionJudgeRows=206, preSubmitReviewedRuns=214, baselineTargets=93, availableBaselines=3, unavailableBaselines=90, pairedTargets=2`
- `splits`: train `{runs:181, scoredRuns:0}` / validation `{runs:87, scoredRuns:5}` / test `{runs:0, scoredRuns:0}` / unresolved `{runs:920, scoredRuns:0}` — matches the live root page exactly.
- `noLeakagePolicy.rule`: "Rows are split by resolutionDate, not run order. Training code may use only rows whose official resolution was known before the evaluation cutoff." `trainingEligibleSplits: ["train"]`, `holdoutSplits: ["validation","test"]`.
- `judgePolicy.calibrationRule`: "Judge scores can be used as process diagnostics only after checking whether they predict held-out normalized CRPS. They must not replace the proper-score reward."
- `leaderboard`: array of 45 objects (agent, model, scoredRuns, totalRuns, unpairedMeanReward, unpairedMeanNormalizedCrps, unpairedMeanAbsoluteError, unpairedInterval80Coverage, pairedTargets, pairedCrpsRatioGeomean, pairedWinRate, activityArtifactCoverage). Only 2 of 45 rows have non-null `unpairedMeanNormalizedCrps`: thesis.analyst/gpt-5.6-sol (2.3504980406630906) and brier.time_series_prior/persistence.last_print (1.6007219016167962) — full precision values, matching the rounded 2.350/1.601 shown on the live pages.
- `pairedComparison` (global, single object): `{pairedTargets: 2, crpsRatioGeomean: 1.1759667400812812, agentWinRate: 0.5, zeroCrpsPairs: 0}`.
- `baselineCoverage`: 93 entries. 3 `"available"` (all in the `us.dol.initial_claims.sa` weekly series), 90 `"unavailable"` with reason (quoted verbatim): `"ledger has no pre-cutoff observations for the target series"`.
- `rewardRows`: **1,188 rows** exactly (181 train / 920 unresolved / 87 validation). `scoreEligibility` breakdown across all 1,188 rows (my own tally via `jq`):
  - `excluded_chronology_claimed_only`: 195
  - `excluded_chronology_unverified`: 62
  - `excluded_condition_not_satisfied`: 17
  - `scored_deterministic_baseline`: 3
  - `scored_witness_verified`: 8
  - `unresolved`: 903
  - (195+62+17+3+8+903 = 1188, confirmed)
  - Of the 11 nominally-"scored" rows (8 witness-verified + 3 deterministic-baseline), only **5** have a non-null `reward.value` — the other 6 (gpt-5.5 on durable-goods orders/shipments and nursing-home staffing/occupancy; gpt-5.6-sol on Australia employment change and continued claims) have a raw `crps` component but `normalizedCrps: null`, consistent with the /calibration page's rule that normalization requires "three pre-cutoff ledger observations." This fully reconciles the "8 witness-verified" (calibration page) vs "5 scored" (counts.scoredRuns) vs "11 rawScoredRuns" figures — they are three different, well-defined subsets, not inconsistent data.
- Sample fully-scored row (`initial-claims-week-2026-07-25`, thesis.analyst/gpt-5.6-sol): `reward.value = -1.8559214542706874`, `components: {crps: 10.3333333333, normalizedCrps: 1.8559214542706874, absoluteError: 15, normalizedAbsoluteError: 2.694079530401624, sharpness: 3.5921060405354983, normalizationScale: 5.5677643628300215, normalizationScaleSource: "ledger_dispersion", interval80Covered: false}`. Auxiliary: `traceQualityScore: 3.78`, `primaryFailureMode: "interval_too_narrow"`.
- `judgeResults` (separate large object, `schemaVersion: "thesis_forecast_judges_v1"`, `generatedAt: "2026-06-26T00:00:00Z"`): judge dimensions include `base_rate_use`, `source_grounding`, and others scored 0–4, e.g. one sampled row scored `overallScore: 3.54` with `base_rate_use: 4` ("Score 4/4: 4 historical point(s) and explicit outside-view language").

**Freshness flag (verified, not inferred):** the file's own `generatedAt` (2026-06-16T00:00:00Z) predates `runAt`/`resolutionDate` values it contains (e.g., `runAt: "2026-07-21T01:03:01Z"`, `resolutionDate: "2026-07-30"`). A file cannot have been generated before data it contains was created, so **`generatedAt` is not a reliable freshness indicator for this export** — the actual content is current to at least 2026-07-30/31. Separately, the live `/calibration` page (section 3) states "198 claimed-time-only" excluded, while this JSON's `excluded_chronology_claimed_only` count is 195 — a small (3-row) discrepancy between the static JSON export and the live-rendered page, verified in the same session. All other headline figures I could cross-check (runs=1188, scoredRuns=5, agents=45, specs=750, the two leaderboard CRPS values, the pairedComparison numbers) matched exactly between the JSON and the live pages. **Recommendation: treat the live `/calibration` and root-page numbers as authoritative over a cached download of reward.json for anything beyond top-line counts, and re-fetch reward.json fresh rather than relying on a previously-saved copy.**

Source: https://app.thesisinstitute.org/brier/reward.json (fetched via `curl`, 2026-07-31)

---

## 12. https://policyengine.org — homepage

"Free, open-source tax and benefit analysis. Model policy reforms across all 50 states." Links to the US web app ("Enter PolicyEngine"), API docs (`/us/api`), and Python package docs (`/us/python`). Highlights an "NJ Child Tax Credit increase calculator" as an example reform tool. Navigation includes Research, Model documentation (Rules → Parameters, Rules → Variables, Data/calibration), and API/integration docs.

Source: https://policyengine.org (WebFetch summary; page is mostly static marketing content so this one did not need browser rendering)

---

## 13. PolicyEngine parameter browser (live app) — https://policyengine.org/us/model/rules/parameters

Category counts shown on the live parameter browser landing page (accessibility-tree read, client-rendered): **Federal 756**, **State 4,122**, **Local 200**, **Territories 46**, **Reforms 527** ("Contributed reform proposals and policy experiments"). A direct deep-link to `/us/model/rules/parameters/gov/irs/credits/ctc` returned a 404 in-app — the parameter browser does not appear to support that path structure for direct linking; I did not find the specific CTC threshold parameter rendered in the live UI within the time available and fell back to the primary source (GitHub) for the exact parameter, below.

Source: https://policyengine.org/us/model/rules/parameters

---

## 14. CTC refundable phase-in threshold — primary source (PolicyEngine-US GitHub repo, not the rendered app)

This is the actual parameter file, fetched raw from GitHub (not paraphrased):

**File**: `policyengine_us/parameters/gov/irs/credits/ctc/refundable/phase_in/threshold.yaml`
```yaml
description: Additional Child Tax Credit income threshold
values:
  2013-01-01: 3_000
  2018-01-01: 2_500
metadata:
  unit: currency-USD
  period: year
  label: CTC refundable phase-in threshold
  reference:
    - title: 26 U.S. Code § 24(d)(1)(B)(i)
      href: https://www.law.cornell.edu/uscode/text/26/24#d_1_B_i
    - title: 26 U.S. Code § 24(h)(6)
      href: https://www.law.cornell.edu/uscode/text/26/24#h_6
    - title: H.R.1 - One Big Beautiful Bill Act
      href: https://www.congress.gov/bill/119th-congress/house-bill/1/text
    # OBBB extends TCJA CTC phase-in threshold.
```
Parameter path: **`gov.irs.credits.ctc.refundable.phase_in.threshold`**. Current value **$2,500** (in effect since 2018-01-01, extended by the One Big Beautiful Bill Act per their own comment) — matches the task's premise that S.3596 would move this from $2,500 to $1.

Companion parameter, same directory: `policyengine_us/parameters/gov/irs/credits/ctc/refundable/phase_in/rate.yaml`:
```yaml
description: Additional Child Tax Credit rate
values:
  2013-01-01: 0.15
metadata:
  unit: /1
  period: year
  label: CTC refundable phase-in rate
  reference:
    - title: 26 U.S. Code § 24(d)(1)(B)(i)
      href: https://www.law.cornell.edu/uscode/text/26/24#d_1_B_i
```
i.e., the refundable CTC = 15% of earned income above the threshold, and S.3596 only touches the threshold, not this 15% rate.

Directory structure around it (confirmed via GitHub API, not guessed): `gov/irs/credits/ctc/` contains `amount/`, `phase_out/`, `refundable/` (which itself contains `fully_refundable.yaml`, `individual_max.yaml`, `phase_in/`, `social_security/`), plus top-level `adult_ssn_requirement_applies.yaml`, `child_ssn_requirement_applies.yaml`, `eligible_ssn_card_type.yaml`.

Sources: https://raw.githubusercontent.com/PolicyEngine/policyengine-us/master/policyengine_us/parameters/gov/irs/credits/ctc/refundable/phase_in/threshold.yaml and .../rate.yaml (directory listing via https://api.github.com/repos/PolicyEngine/policyengine-us/contents/policyengine_us/parameters/gov/irs/credits/ctc)

---

## 15. How PolicyEngine reforms are specified — primary source (policyengine-core)

Two mechanisms, both confirmed directly from source (not from memory or general knowledge):

**(a) Structural reforms** (custom logic, e.g. changing which variables/formulas apply) subclass `Reform` and override `apply()`, calling `self.update_variable(...)` and/or `self.modify_parameters(...)`. Real example pulled from `policyengine_us/reforms/ctc/ctc_minimum_refundable_amount.py`: defines a new `ctc_minimum_refundable_amount` Variable, then a `reform(Reform)` class whose `apply()` calls `self.update_variable(...)` for each affected variable (`ctc_minimum_refundable_amount`, `refundable_ctc`, `ctc_value`, `ctc_refundable_maximum`, `non_refundable_ctc`).

**(b) Simple parametric reforms** (the kind relevant to S.3596 — a pure threshold value change) use `Reform.from_dict(parameter_values, country_id=None, name=None)`, defined in `policyengine_core/reforms/reform.py`. Docstring, quoted directly:

> "Create a reform from a dictionary of parameters. Args: parameter_values: A mapping of `path -> {period_key: value}` (or the `path -> scalar` shorthand, applied across `year:2000:100`)."

Period-key formats it accepts (quoted): bare ISO instant (`"2026"` / `"2026-01"` / `"2026-01-01"`) → value applies from that instant onward; range `"start.stop"` (e.g. `"2026-01-01.2027-12-31"`) → bounded interval, prior value restored after; compound bounded period (`"year:2026:5"` / `"month:2026-01:3"`); `"ETERNITY"` → applies for all time. "Invalid input raises during construction before any parameter is modified: a malformed period key or bad value yields no partial reform."

So the S.3596 reform, in PolicyEngine's own idiom, would be specified as a dict like `{"gov.irs.credits.ctc.refundable.phase_in.threshold": {"<start>.<stop>": 1}}` (exact start/stop instants are David's modeling choice, e.g. tax-years-after-2025 → likely `"2026-01-01.2100-12-31"` or similar, matched to how PolicyEngine's own `H.R.1`-referencing comment in the threshold.yaml phrases "extends... for tax years after 2025" — I did not find a canonical "tax years after 2025" period-key convention documented anywhere; that choice is not sourced, it is inference about mechanics only). I did not find this specific bill (S.3596 / "Stronger Start for Working Families Act") already implemented anywhere in the `policyengine_us/reforms/` tree — see COULD NOT RETRIEVE for the limits of that check.

Sources: https://raw.githubusercontent.com/PolicyEngine/policyengine-core/master/policyengine_core/reforms/reform.py and https://raw.githubusercontent.com/PolicyEngine/policyengine-us/master/policyengine_us/reforms/ctc/ctc_minimum_refundable_amount.py

---

## 16. PolicyEngine household API docs — https://policyengine.org/us/api

This documents a **household-level** calculation API (`POST https://household.api.policyengine.org/us/calculate`), not a reform/microsimulation-impact API. Request body requires a `household` object with six entity groups: `people`, `households`, `families`, `tax_units`, `marital_units`, `spm_units`. Within the portion of the page I read, I did not see a `policy`/`reform` key in the example request bodies — this endpoint appears to compute outcomes under a specified `"version"` (e.g. `"current"`) rather than accepting an arbitrary reform payload inline. The page itself flags a related deprecation, quoted: "Direct microsimulation via `policyengine-us` (`Microsimulation()`) is deprecated and being migrated to `policyengine.py`... Society-wide microsimulation — population aggregates and distributional or budgetary impacts — is moving to the managed `policyengine.py` bundle" (source: https://raw.githubusercontent.com/PolicyEngine/policyengine-us/master/README.md). I did not fetch `policyengine.py`'s own docs to see if/how it takes a reform argument for population-level impact runs — flagged below as not retrieved.

Source: https://policyengine.org/us/api (browser-rendered; page is long, I read the first ~6,000 characters covering auth flow and the household payload shape)

---

## COULD NOT RETRIEVE

- **Thesis Institute research paper** (`/paper`, "Research" nav link): page explicitly says "Paper not yet rendered. Run: python3 paper/render_paper.py". No published methodology paper exists at this URL as of 2026-07-31. This is a real gap, not a tooling failure.
- **`/log.json`** (linked from the root page as "Thesis Log JSON →"): not fetched — I prioritized `/brier/reward.json` per the task's explicit ask and ran out of scope to also pull and diff this second JSON export. If it's needed, it is at https://app.thesisinstitute.org/log.json.
- **`/forecasts/log`** ("Scoreboard →" link from the root page): not separately visited — based on nav structure and naming I believe it duplicates content already captured from `/log` and `/calibration`, but I did not confirm this directly, so treat that as an assumption, not a verified fact.
- **PolicyEngine's live parameter-browser rendering of the CTC threshold specifically**: a direct URL guess (`/us/model/rules/parameters/gov/irs/credits/ctc`) 404'd in the app. I got the parameter from GitHub source instead (section 14), which is authoritative for the value/history/legal citations but I could not confirm exactly how the live UI displays/searches for it (e.g., whatever search-box UX exists at `/us/model/rules/parameters`).
- **Whether S.3596 ("Stronger Start for Working Families Act") is already implemented as a named reform in `policyengine_us/reforms/`**: I listed `policyengine_us/reforms/congress/` (contains subfolders `afa`, `delauro`, `golden`, `hawley`, `mcdonald_rivet`, `romney`, `tlaib`, `watca`, `wyden_smith`) and `policyengine_us/reforms/ctc/` (7 files, none named for a specific bill) and did not recognize any of those names as S.3596's sponsor. GitHub's code-search API returned `401 Requires authentication` for both `"3596"` and `"stronger start"` queries, so I could not do an exhaustive repo-wide text search. **This is inconclusive, not a confirmed absence** — do not report "PolicyEngine hasn't modeled this bill" as established; report "I could not confirm either way via code search; directory-name inspection found no obvious match."
- **PolicyEngine's population-level reform/microsimulation API** (as opposed to the single-household API documented at `/us/api`): the README points to a separate `policyengine.py` package for this, which I did not fetch. If David's ablation needs to reproduce a reform's aggregate/distributional impact (rather than a single household), that package's docs are the next thing to check, not `/us/api`.
- **Full enumeration of `/log`'s 595 pending rows and 155 resolved rows**: the page is 54,000+ characters; I read the summary/scoreboard/by-agent/by-model/by-run-type sections and the start of the resolution queue, not every row.

---

## Method note (why these numbers should be trusted)

Every JSON figure in sections 11de and every YAML/Python quote in sections 14 to 15 came from a direct `curl`/GitHub-API fetch that I parsed myself with `jq` or read as raw text — not from an AI-summarized WebFetch pass. Where WebFetch was used for the Thesis Institute app (sections 1 to 2 initially), I cross-checked its summary against a direct browser accessibility-tree read (`read_page`/`get_page_text`) and, for the JSON figures, against the raw downloaded file — every number reported above with specific decimal precision (e.g. 2.3504980406630906) came from the raw file, not a paraphrase. I did not run any WebSearch for this task, so there is no search-synthesis text to flag as zero-information — everything above is a direct fetch.
