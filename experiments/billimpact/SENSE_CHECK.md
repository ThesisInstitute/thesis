# SENSE CHECK — pre-demo audit against the room (2026-07-31, finalized ~12:50 EDT)

Reviewer stance: knowledgeable, skeptical-but-fair audience member — Max Ghenis,
David Trimmer, policy researchers, AI-tool builders. People who know CRPS, know
model tiers cold, know these programs, and recompute sign tests in their heads.

Surfaces reviewed, at their **current** states: `RESULTS.md` (12:20 commit,
"§§1–5 final, checker-gated"), `TWO_LEGS_S3596.md` (11:54, unchanged since),
`forward/FORWARD-S3596.md` (11:34), `results/demo_page.html` — reviewed
**twice**, before and after its 12:15 revision (new title/h1, new §08 "Both
legs, same bill", new §09 "sixteen harnesses", revised lever) — both demo
figures read as images, the PR #61 body, and the substrate they cite
(`results/*.md`, `CHECK2.md`, `final_multimetric.json`, `runs_envelope.jsonl`,
`s3596_conditional_runs.jsonl`, `envelope_sweep.py`, ground-truth files, PR
#64). Every inherited number was checked against primary sources on the web;
the appendix records exactly what was and was not confirmed.

Ranked. Each item: where, why it is a red flag *to this audience*, exact
replacement wording.

---

## RED FLAGS

### 1. "−1.2pp" misreads PR #64's relative "−1.2%" — the mechanical effect is −0.20pp, and the page's new §08 headline ("roughly ten times") is a units artifact

**Where:** `results/demo_page.html` §08 — display-type card "**−1.2pp** child
poverty · Mechanical leg · PR #64", h2 "The mechanical leg prices S.3596 at
roughly ten times what the forecast leg concedes," and the paragraph "Its
direction and size are what recall-anchoring (04) predicts." Also
`TWO_LEGS_S3596.md` lines 7–9 ("**child poverty −1.2pp** (17.02% → 16.82% …)",
"stale published numbers (−$1.6B / **−0.4pp**)") and its "The gap is the
finding" paragraph ("a 10x delta gap is not a units artifact").

**Why it's fatal here:** PR #64 (Trimmer's own PR) reports "child poverty
**−1.2%** (17.02%→16.82%)". 17.02 − 16.82 = **0.20 percentage points**; −1.2%
is the *relative* change (0.20/17.02) — PolicyEngine's house convention, which
their published page for this same bill uses ("Reduces child poverty by 0.4%"
beside "Gini … 0.024%"; verified today). Both docs quote the very levels that
refute their own "pp" label. Compared consistently, the forecast leg
(−0.10/−0.15pp against −0.20pp; or ≈−0.7/−1.1% against −1.2% relative)
concedes **one-half to three-quarters** of the mechanical effect — a factor of
1.3–2.0, not 10. "Roughly ten times" is wrong by ~5–7x; "not a units artifact"
asserts the opposite of what is true; and the recall-anchoring *size* claim
dies with it (the direction survives, weakly). Trimmer wrote the source PR;
Max builds microsims; either spots 17.02−16.82 ≠ 1.2 in seconds, on a
conference screen, in a section that is *about their work*.

**Replacement (page §08):** card value "−0.20pp <small>child poverty · −1.2%
relative</small>"; h2 → "Composed at the reference config, the two legs land
within a factor of two." Body paragraph →

> The two legs measure different things — PolicyEngine's poverty measure on
> the build-P population (2026, static) against the Census SPM child rate for
> CY2027 — so the levels are indicative, not commensurable. Read that way,
> the registered forecast deltas (−0.10 to −0.15pp) sit at one-half to
> three-quarters of the mechanical −0.20pp: the composed forecast is
> *consistent with* the mechanical leg at the reference config. The
> order-of-magnitude risk is not in the composition — it is in the harness
> (see 09: the same delta runs −1.5pp to 0.00pp when only the bill's name is
> shown). Keep the closing double-count paragraph as is — "no backtest can
> validate the composition step" is exactly right.

**Replacement (TWO_LEGS):** "budgetary impact −$1.83B; child poverty
**−0.20pp** (17.02% → 16.82%; −1.2% relative, PE poverty measure, 2026)" and
"stale published numbers (−$1.6B / −0.4% relative)". Rewrite "The gap is the
finding" along the §08 lines above — the honest 10x in this study is
context-vs-context (full-bill −0.1/−0.2pp vs name-only −1.5pp), not
mechanical-vs-forecast. Note: commit message `8f4f9894` ("mechanical
(-1.2pp, PR64)") carries the error immutably; one more reason the docs must be
corrected before anyone reads the log.

Incidental upside: correcting this *dissolves* the worst adjacency on the page
— §08's "−1.2pp" currently sits one scroll above §09's "name-only · fable-5 ·
−1.5pp", inviting "the recall arm approximately reproduces the mechanical
number." At −0.20pp there is no coincidence left to misread.

### 2. The page's §5-family claims are five minutes older than the checker-gated final §5 — and they now disagree on the headline result

**Where:** demo page (12:15) §06 Leg 2 ("Best measured arm — **opus-5, no
bill text: nCRPS 0.243** vs persistence 0.326 (N=28); 19/28; bootstrap CI
excludes zero"), §06 h2 ("…forecast **without bill text**…"), §06 lever
("opus-5 + bill, effort max: nCRPS **0.214** · coverage 0.83 (default: 0.268 ·
0.79; n=117) · as of 12:00"), §03 chip ("Δ +0.052 … out of sample the
bill-text arm loses"). Versus `RESULTS.md` §5 (12:20, "final", CHECK2 items
11–12) whose canonical-batch table says:

- best arm = **fable · bill · effort=max: 0.208**, Winkler 1.30, cov 0.75;
  **−0.118 [−0.211, −0.035] vs persistence** (22/28) and −0.084 [−0.164,
  −0.008] vs its naive;
- opus · no-bill = **0.253** (not 0.243 — that was batch B1), cov 0.82;
- opus · bill · effort=max = **0.247 vs default 0.261 — n.s.** (−0.006
  [−0.046, +0.042]): the opus effort win the lever quotes evaporated in the
  final batch; the significant effort effect is *fable's*;
- result 2 is an *interaction*: "Bill text harms at default effort and pays
  only at max effort" (fable +0.047 → −0.084).

**Why:** anyone cross-reading the page and RESULTS.md — the natural first act
of this room — finds the page naming a different best arm than the repo's own
final, checker-gated table, with numbers from a batch CHECK2 explicitly says
has drifted. Worse, the page's architecture plank "forecast leg: frontier
tier, **no bill text**" is now contradicted by the repo's own headline: the
best measured arm *reads the bill* at max effort. And §03's "out of sample the
bill-text arm loses" is true only at default effort — the file's own result 2
says so.

**Replacement:** re-derive every §5-family number on the page from the final
table (one batch state, per CHECK2's own instruction) and restate the leg:

- Leg 2 title: "Outcome forecast: frontier tier — bill text only with max
  reasoning effort". Bullets: "Best measured arm — fable-5 · bill · max
  effort: nCRPS 0.208, Winkler-leading, coverage 0.75; beats persistence
  −0.118 [−0.211, −0.035] (22/28 units, N=28)." / "The same recipe at default
  effort is among the worst arms (+0.047 vs its naive; coverage 0.61) — bill
  text harms at default effort and pays only when the reasoning budget is
  there to use it." / "Best bill-blind arm: opus-5 no-bill 0.253 (cov 0.82) —
  the safe default when effort is constrained." Add the anti-pull-quote
  sentence regardless of framing chosen: "**The statutory delta still never
  comes from model memory** — it enters computed, from Leg 1, at composition
  (Findings 3–4)."
- Lever chip: quote the final batch or drop numerals: "Reasoning effort ×
  bill text is the dominant interaction: fable+bill goes from worst-arm
  (+0.047) at default effort to best-arm (−0.084) at max. Effort still does
  not restore statute-tracking on memorized periods (0/4 levels, 240 runs) —
  structure does (04)." (Also fixes the current chip's "improved accuracy and
  calibration": 0.79 → 0.83 coverage is a move *away* from nominal, not
  improved calibration.)
- §03 chip: append "at default effort (the max-effort interaction is Finding
  5's result 2)" to "the bill-text arm loses".

### 3. Witness-tier and "registered" overclaims on the page

**Where:** §07 lede: "runs committed with timestamps and **sealed by the
recorder workflow (RFC-3161 witness)**" (survives the 12:15 revision —
line 589); §07 chip "**per-config lanes registered**" with "4 lanes × 3 reps
running"; §09 lede "the S.3596 deltas **registered this morning**".

**Why:** the chronology tiers are the hosts' own credibility machinery. The
recorder has not run — the PR is open; `FORWARD-S3596.md`'s own "To register"
section lists merge + `gh workflow run record-forecasts.yml` as *future*
steps, and correctly calls the current state "claimed-time chronology from git
history." Claiming "sealed … RFC-3161" on the demo surface is the exact
vocabulary misuse this room owns. Same for "registered": the *targets* are
registered; the conditionals are committed; the lanes are prepared (runs exist
for 4 of 16 targets; the lane session was cancelled mid-run per FORWARD).

**Replacement:** §07 lede: "…runs committed with timestamps — claimed-time
chronology from git history, sealed to the witness-verified tier when the
recorder workflow runs on merge (RFC-3161; one command, in
`forward/FORWARD-S3596.md`)." §07 chip: value "per-config lanes **prepared**";
body "16 near-resolving targets selected; 4 lanes × 3 reps complete on the
first four, rest queued; registration = merge + recorder seal, pending…" §09:
"the S.3596 deltas recorded this morning (registration pending merge)".

### 4. FORWARD's fable-CTC row doesn't reconcile, and the page card papers over it with "agrees"

**Where:** `forward/FORWARD-S3596.md` table — fable CTC row "48.5 · 48.9 ·
**+0.3 M**" (48.9 − 48.5 = **+0.4**); demo page §07 CTC card — "fable-5
**agrees, at** +0.3M" with fable's levels omitted.

**Why:** this room reproduces derived numbers from the payload as published; a
Δ column that its own adjacent columns contradict is the cheapest possible
catch. The +0.3 is legitimate (median of within-run deltas: 0.4/0.3/0.2) but
nothing says so. And "agrees" is corroboration language between two arms of
the same experiment — two LLMs sharing a prior is not agreement evidence.

**Replacement:** FORWARD footnote: "Δ = median of within-run deltas; for
fable-CTC this differs from the difference of scenario medians (48.5 → 48.9;
per-rep Δ 0.4/0.3/0.2 → +0.3)." Page card: replace "agrees, at +0.3M" with
"48.5M → 48.9M · within-run Δ +0.3M" and delete the word "agrees". (All other
medians in the table and cards reproduce exactly from
`s3596_conditional_runs.jsonl` — independently recomputed here and in CHECK2
item 10.)

### 5. "10/12 units, p=0.002" reads as a wrong sign test — state the denominator

**Where:** `RESULTS.md` §2 text and table; demo page §02 purpose-clause chip
("moved forecasts down in 10/12 units — … p=0.002" wording family) and §04
fine print ("10/12 down, p=0.002"); `PREREG-AMENDMENT-2.md` line 11.

**Why:** a sign test on 10/12 is p=0.039 two-sided, and this crowd computes
binomial tails in their head. The construction is actually correct —
zero-shift units drop, so it is 10/10 nonzero → p=0.00195
(`analyze.py:1347`) — but no surface says so, making a right number look wrong
by 20x.

**Replacement (everywhere the pair appears):** "down in 10 of 12 units (two
unmoved; sign test on the 10 nonzero units, p=0.002)". The neighboring "8/9
*moving* units (p=0.039)" is the model wording — copy it.

### 6. Inherited history tables: SPM row fully verified; the CTC row is not — relabel before anyone projects a prompt

**Where:** `envelope_sweep.py` TARGETS (in-prompt "HISTORY (as published)":
SPM 2021 5.2 / 2022 12.4 / 2023 13.7 / 2024 13.4; CTC TY2019 48 / TY2021 61 /
TY2022 49) and `site/src/data/forecast-cells.ts` (lines 642–647, 1104–1110,
2937–2942, and the `irs.lookup` reasoning step at 2965–2967). Not rendered on
the demo page — exposure is projected prompts, the site's cell pages, or a
direct "where's that from?".

**Verified — keep:** all four SPM values, including 2024 = 13.4 (Census
September-2025 release; appendix). Keep the "(expanded monthly CTC in
effect)" annotation on 2021.

**Not verified — fix:**
- **61 (TY2021):** real and children-denominated, but it is Treasury/IRS
  *advance-payment* coverage ("more than 61 million children", Dec-2021
  disbursement) — not an SOI tabulation of children claimed on returns. Right
  number, wrong implied source.
- **48 (TY2019):** could not be verified as *children*. Best-sourced match:
  ~48 million **filers/returns** claiming the CTC (Tax Foundation primer) — a
  returns-vs-children conflation until shown otherwise.
- **49 (TY2022):** **no source found.** SOI TY2022 materials show ACTC on
  17.8M returns and $110.4B total CTC; the SOI TY2022 CTC research paper
  (24rpctcunderclaims.pdf, read in full) yields no qualifying-children total.

**Prescription:** relabel per-row (e.g. "TY2021 61 — children covered by
advance payments, Treasury; TY2019 ~48 — returns claiming CTC, children count
not published; TY2022 — none published") or drop TY2019/TY2022. The
registered target's own resolution rule already hedges ("…or the closest
directly comparable official count") — align the history label with that
hedge. No re-runs; disclose the prompt's labels if asked. Also pre-brief the
presenter: fable's raw `mechanism` text says "$3,000 to $1" — the *statutory*
layer (§2(a) strikes "$3,000" from IRC §24(d)(1)(B)(i); §2(b) strikes
§24(h)(6), the $2,500 override), while every surface says "$2,500 → $1" — the
correct *operational* delta. Both are right at their own layer; FORWARD links
the raw JSONL, so someone may open it.

### 7. The FPUC surfaces never say the units — and this is a BEA-literate room

**Where:** `results/demo_recall_anchoring.png` y-axis "UI outlays (**units as
published**)"; page §04 chip "(first print 570.6)" and stepper "≈ the
remembered 570"; §04 derivation panel "(UI outlays, annualized $B)".

**Why:** 570.6 is `W825RC1` — personal current transfer receipts:
unemployment insurance — monthly, **billions of dollars at a seasonally
adjusted annual rate**. Verified: BEA "Personal Income and Outlays, January
2021" (2021-02-26), Table 3 line 26: "…281.1 307.8 **570.6**" (Nov, Dec 2020,
Jan 2021, SAAR) — the Dec→Jan jump *is* the $300 FPUC restart the corpus
targets. "Units as published" is a dodge; a BEA-literate reader silently
converts and wonders why the page didn't; anyone else may read 570.6 as a
monthly flow.

**Replacement:** y-axis "UI benefits, $B (seasonally adjusted annual rate —
BEA W825RC1)"; figcaption add "Values are SAAR: Jan-2021's 570.6 ≈ $47B paid
in the month"; chip "first print 570.6 ($B, SAAR)"; derivation title "(UI
outlays, $B SAAR)". The widget's arithmetic (300 × 2.0M × 52 ≈ 31; 36 + 31 =
67) is already exactly right *as* SAAR — worth saying aloud that the model
annualized correctly.

### 8. §09 envelope surface — three small pins before it is quoted

**Where:** page §09 (new at 12:15) and the "S.3596 envelope §9 integration"
still landing in `RESULTS.md` per the banner.

The band numbers all reproduce from `runs_envelope.jsonl` (recomputed here:
14/16 poverty configs in [−0.30, −0.10]; both outliers name-only — fable
paired −1.5 (reps −1.5/−1.9/−1.1), fable decomposed 0.00; CTC 16/16 positive,
+0.3 to +1.2M). Pins: (i) one CTC cell (summary · fable · paired) has **n=2**
— say "medians of 3 reps (one cell n=2)"; (ii) when the RESULTS §9 lands,
keep every mechanical number out of and away from the envelope table (with
item 1 fixed, −1.5-vs-−0.20 has no accidental-corroboration reading left —
preserve that); (iii) frame the name-only outlier as the *recall channel*
("where only the name is shown, the delta can inflate ten-fold or vanish" —
the page's current sentence, which is right; if it ever landed near the
mechanical number, agreement would indict the arm, not validate it).

### 9. Internal staleness inside RESULTS.md after the §5 refresh

**Where:** `RESULTS.md` §8 — "N = 20 retrospective units across 5 laws … the
bake-off is N=8" — contradicting §5 ("Corpus B expanded to 28 units", powered,
significant) and the totals line ("28 retrospective units"). Totals line also
still reads "~5,600 … arms landing at time of writing" although the banner
says §§1–5 final (bake-off alone added ~1,900 records per CHECK2). And §5's
aggregation claim quotes 0.243 (batch B1) two lines under a table whose
canonical opus·no-bill row is 0.253 — quote one batch state (CHECK2's own
instruction).

**Replacement (§8):** "The held-out evaluation is N=28 units within 4 events
(months within an event are not independent); the original amendment-frozen
bake-off was N=8 before the powered expansion." Update the totals line at
freeze; tag the 0.243→0.231 aggregation claim with its batch.

### 10. Smaller, still worth ten minutes

- **Uncommitted design vs the "100%" stat.** `quantile_sweep.py` +
  `runs_quantile.jsonl` are untracked while the page stat-strip claims "100%
  of designs committed to git before their first run" and the banner lists
  quantile-CDF as landing. Commit the runner before any quantile number
  surfaces, or scope the stat.
- **Footer honesty notes were compressed in the 12:15 revision.** The
  specific defect list (calendar-year parser, 214 runs; 1.17 → 0.97
  denominator correction; 20 CTC cells counted as wrong) is now "documented
  in the repository." For this room the specifics were a credibility asset —
  restore one line: "including a prose parser that read calendar years as
  forecasts (214 runs, corrected offline with v1 parses preserved) and a
  denominator-selection artifact our red team caught (1.17 → 0.97)."
- **Run-count sync:** hero "roughly 6,000 scored runs" vs RESULTS "~5,600 …
  at time of writing" — pick the freeze number and make hero, statstrip, and
  RESULTS agree.
- **RESULTS §4 editing scar:** "fable ran only the full-bill conditions and
  is marked — elsewhere." is a broken sentence; suggest "…conditions; its
  other cells are marked '—' in the table."
- **Dispersion figure verdict boxes** show the naive ratio construction §1
  itself corrects; verdicts match the pre-registered bootstrap test, so add
  one figcaption clause: "verdict boxes show the pre-registered ratio test;
  the red-team permutation restatement (RESULTS §1) strengthens every EXCEEDS
  verdict."
- **Hero tone (optional):** "Teams everywhere are building bill→forecast
  tools. Nobody measures the plumbing." — in front of the team whose lab
  measures forecasts for a living, consider "Nobody — including us, until
  this morning — measures the plumbing."
- **Spoken-register guard:** no file calls sonnet "mid-tier" (checked) — keep
  it that way live ("smaller/faster tier", or name models plainly). For §05,
  the only correct frame is the one already used: the tool saturates every
  tier; the 4% no-tool row is haiku's own capability. And have the corpus-A
  calibration answer ready: *nobody* was calibrated — sonnet/haiku
  under-cover (0.50 → 0.02–0.32 with bill text), opus over-covers (0.97–1.00,
  widths ~4 history-SDs), fable nearest nominal (0.82–0.87); coverage above
  0.90 on a nominal-80 interval is miscalibration in the wide direction, not
  caution.

---

## CLEARED (checked, fine as they stand)

- **§5 final table's metric discipline** — Winkler beside nCRPS with the
  "charges for width and for misses" gloss, coverage on every row, "narrower
  arms exist only at collapsed coverage," instruction/scaffold arms shown as
  ranges and marked n.s. This is exactly how to survive a forecaster
  audience; mirror it in anything spoken (see item 10's guard for the arms
  with cov80 0.90–1.00 in `final_multimetric.json`/CHECK2 items 8–9).
- **Haiku/tools framing** (`RESULTS.md` §4; page §05): "the tool converts
  every model to 100% — haiku 4→100" everywhere; no-tools is the page's
  default view, so capability shows first; the §2(a)-trap and
  tools-fix-arithmetic-not-extraction (86%, n=70) framings are correct and
  now N-stated.
- **"Ground truth" doctrine:** applied to first prints (data) only;
  PolicyEngine is "reference implementation … a model input, never ground
  truth for behavior" in RESULTS §4 and the page footer. `FORWARD-S3596.md`
  is careful about claimed-time vs witness tiers — the page §07/§09 wording
  (item 3) is the only overclaim found.
- **S.3596 mechanics:** "$2,500 → $1" is the correct operational description —
  verified against the bill text (§2(a) strikes "$3,000"; §2(b) strikes
  §24(h)(6), the $2,500 override; effective TY2026+), and it **is** S.3596,
  119th Congress, Hassan/Young — the reintroduced bill really does carry the
  same number as its 118th-Congress predecessor, so `envelope_sweep.py`'s
  "(119th Congress)" and "currently pending" are right.
- **S.3596 conditional medians:** every number in FORWARD's table and the
  page §07 cards reproduces from `s3596_conditional_runs.jsonl` (recomputed
  here; CHECK2 item 10) — sole caveat is item 4's Δ convention.
- **Behavioral-uptake framing (the +0.2–0.3M rows):** present at every
  appearance — FORWARD's "NOT mechanical … behavioral uptake"; the page
  card's visible summary "Behavioral-uptake claim — the mechanical Δ is
  zero" and "If uptake is a fiction, this row gets scored for it"; §09's CTC
  band explicitly calls magnitude-variation the thing the lanes will score.
- **Demo page §02 widget vs substrate:** all FL·2023-12 medians, spreads,
  noise floors match `dispersion.md` exactly; the unconditioned 2.80M
  reproduces from `runs_api.jsonl`; "one dial at a time … off-axis
  combinations were not run, and this page does not invent them" is the right
  guard, and the 12:15 revision added the dispersion-ratio CIs to the chips.
- **§03 calibration numbers:** widths/coverages match `results_table.md`
  (none 309k/0.50; operative 234k/0.32; pooled shown-context 0.325→"0.33");
  under-coverage presented as failure; the new "no CRPS gain from any context
  level (60 runs per level)" chip states the skill null with its N.
- **§04 (recall) after revision:** denominators added ("cells monotone",
  "240 runs"), future-arm-never-scored disclosed twice, fable's $900-extreme
  exception disclosed in the caption, and the "0/4 effort levels" claim
  matches the A4 recomputation (CHECK2 item 5).
- **Statistical hygiene generally:** "12/12 (p=0.0005)" exact; "8/9 moving
  units (p=0.039)" exact with the right denominator wording; footer
  N-statements retained post-revision, including "State N. Always." and the
  best-arm-is-not-an-endorsement clause; bootstrap constructions are
  producible on request (`CHECK2.md`, with seeds and batch definitions).
- **PR #61 body:** dispersion-is-the-deliverable framing, no praise of weak
  models, "$374.85, PolicyEngine-verified" household delta; the closing
  forecast-api CDF-drift flag is a constructive, evidenced bug report — the
  right kind of thing to hand the hosts.
- **TWO_LEGS certification note** (household checks on 1.784.3 vs certified
  1.764.6-on-build-P): correctly scoped — keep it; fix only item 1's units.
- **§08's closing double-count paragraph** ("a model that has already priced
  the policy into its forecast double-counts any mechanical delta composed on
  top, so no backtest can validate the composition step") — the sharpest new
  sentence on the page, and it matches RESULTS §5's composition note. Keep
  verbatim through any §08 rewrite.

---

## Verification appendix (what was checked against what, today)

| Claim | Verdict | Source |
|---|---|---|
| SPM child poverty 2021 = 5.2% (record low, expanded-CTC year) | **Verified** | Census SEHSD wp2022-24; census.gov "Record Drop in Child Poverty" (2022-09) |
| SPM child poverty 2022 = 12.4% (more than doubled) | **Verified** | Census-derived reporting (Columbia CPSP; census.gov SPM pages) |
| SPM child poverty 2023 = 13.7% | **Verified** | Census 2024-09 release; CRS R48854; First Focus |
| SPM child poverty 2024 = 13.4% (no stat. change vs 13.7) | **Verified** | Census 2025-09 "Poverty in the United States: 2024"; CRS R48854; AAP/First Focus coverage |
| CTC TY2021 = 61M qualifying children | **Number real, source mislabeled** — Treasury/IRS advance-payment coverage ("more than 61 million children," Dec-2021), not an SOI return tabulation | Treasury press releases; JEC |
| CTC TY2019 = 48M qualifying children | **NOT verified as children** — best match ~48M *filers/returns* claiming CTC | Tax Foundation, "The Child Tax Credit: A Primer" |
| CTC TY2022 = 49M qualifying children | **NOT verified** — no source found; SOI TY2022 shows ACTC on 17.8M returns, $110.4B total CTC; no child count in the SOI TY2022 CTC paper (read in full) | irs.gov SOI (24rpctcunderclaims.pdf) |
| W825RC1 units = $B, seasonally adjusted annual rate, monthly, BEA | **Verified** | FRED series metadata; BEA release table conventions |
| W825RC1 Jan-2021 first print = 570.6 | **Verified** | BEA pi0121.pdf (2021-02-26), Table 3 line 26: …307.8 (Dec) → 570.6 (Jan), SAAR |
| PR #64 "child poverty −1.2%" is relative = −0.20pp | **Verified** | PR #64 body (17.02→16.82); PolicyEngine research page publishes relative ("Reduces child poverty by 0.4%", "Gini … 0.024%") |
| S.3596 = 119th Congress, Hassan/Young; strikes "$3,000"→"$1" in §24(d)(1)(B)(i) + strikes §24(h)(6); TY2026+ | **Verified** | Bill text (repo copy = clean extraction of the same §2); congress.gov 119th-Congress listing; TPC/R Street/sponsor releases for the $2,500 operational framing |
| FL·2023-12 widget numbers; S.3596 conditional medians; §09 envelope bands; B1 bake-off numbers; A3/A4 monotonicity | **Reproduced** from repo substrate (this review + `CHECK2.md`) | local recomputation |

File states at finalization: `demo_page.html` md5 a32bfb7f… (12:15),
`RESULTS.md` @ `73c8bbf9` (12:20), `TWO_LEGS_S3596.md` (11:54, unchanged),
`FORWARD-S3596.md` (11:34). If any of these move again before 17:00, items 1–4
and 9 are the ones to re-derive — they are assertions about *current* file
contents, not about the underlying runs. Nothing in this file modifies any
other file; every fix is wording, a label, a footnote, or a re-derivation at
freeze — no re-runs required.
