# SITREP — ThesisInstitute/thesis, 2026-07-31 ~14:30 EDT (data collected 18:21–18:27Z)

Demo ~17:00 EDT. All claims sourced (PR#/commit/run/file). Where I could not determine something, I say so.

## Executive summary

1. Nothing merged to main today touches any of our five dependency files (`run_thesis_analyst.py`, `spawned_cells_to_ts.py`, `prediction-distribution.ts`, `cell-contract.md`, `thesis-log.ts`) — verified empty by `git log origin/main --since=00:00Z -- <files>`; #61/#78/#79 are all MERGEABLE against current main.
2. Our real blocker is invisible from the PR page: CI on #78 and #79 completed as `action_required` (fork PRs need a maintainer to click "Approve and run"), and Vercel previews on all three of our PRs fail as unauthorized fork deploys ("@mishmeals is attempting to deploy… a member of the Team first needs to authorize it") — so no server-side test has ever run on our work, and nobody has reviewed or commented on any of our three PRs.
3. The bills pipeline is composing on schedule: #50 (scrape + /bills UI) and #63 (registry mapper) merged; #64 (PolicyEngine tool, −$1.83B / −1.2% relative poverty on S.3596) and #75 (renders that row on /bills) are green and demo-ready; Keller's #65 (reform→draft-cell loop) is the remaining lane piece; none of them contradicts or duplicates our work, and #79 explicitly builds on #64's certification pattern.
4. Max is the sole merge gate (9 of 10 merges today, latency 5–90 min; Pavel self-merged #50) and is in an active merge burst — #73 + #76 went in at 18:25Z, which turned the Records provenance lane green after it had failed on every main push since ~14:49Z.
5. Main CI is otherwise healthy (CI workflow green on every push), but the forecast recorder failed once today (issue #74, open; succeeded on re-run 16:47Z) — and #61's forward program needs exactly one recorder run post-merge to seal our S.3596 forward cells.
6. Demo-critical unmerged work: #64, #75, #65, and our #61 (+253,735 lines, 100 files, all under `experiments/billimpact/` — verified additive-only); the #43 demo closer is "register one real cell through the privileged path so it lands on the public scoreboard with custody stamps."

## 1. Main today

First-parent merges since 14:00Z (`git log --first-parent origin/main`), all times Z:

| merged | PR | author | merged by | what |
|---|---|---|---|---|
| 14:45 | #55 | khs | MaxGhenis | U-6 onboarding submission |
| 14:49 | #56 | khs | MaxGhenis | Plainer forecasts-page copy |
| 15:46 | #62 | khs | MaxGhenis | Record three 07-22 prospects as expired unforecast |
| 16:05 | #54 | khs | MaxGhenis | Records chain verifies on Windows |
| 16:33 | #63 | MaxGhenis | MaxGhenis | Registry mapper: bill metrics → reachable/not-yet/unmapped |
| 16:34 | #69 | MaxGhenis | MaxGhenis | Challenge inbox → attested publisher |
| 17:24 | #50 | PavelMakarchuk | **PavelMakarchuk** (self) | Bill scraping + /bills frontend |
| 18:25 | #73 | MaxGhenis | MaxGhenis | Provenance audit: exempt no-op PR merges, alarm red lanes |
| 18:25 | #76 | MaxGhenis | MaxGhenis | Re-seed both ECI series for Q3 2026 |

Plus bot traffic (thesis-roller/recorder/resolver). Earlier today (pre-14:00Z): #49 (14:06Z, squash a3d3c6c8).

**Dependency check: clean.** `git log origin/main --since=2026-07-31T00:00:00Z -- scripts/run_thesis_analyst.py scripts/spawned_cells_to_ts.py site/src/data/prediction-distribution.ts docs/cell-contract.md site/src/data/thesis-log.ts` returns zero commits. #50's large ingestion landed under `scripts/bills/`, `bills/`, `site/src/app/bills/`, `site/src/data/bills.ts` — adjacent, not overlapping.

## 2. Open PRs (16 as of 18:26Z)

| PR | author | merge state | what |
|---|---|---|---|
| #82 | MaxGhenis | computing | Pre-push records guard: judge branch pushes by own contribution (new at 18:21Z) |
| #81 | khs | computing | Clearer failure messages in site CI gates (240-case trace-depth tests) |
| #80 | khs | CLEAN | Explain missing-attestation failures; was stacked on #73, auto-retargets now #73 merged (per #80 body) |
| #79 | **us** | MERGEABLE, CI **action_required** | reasoningEffort on predictionRun |
| #78 | **us** | MERGEABLE, CI **action_required** | Quantile-native cells fail closed |
| #77 | khs | computing | Clearer unforecast-target failure message |
| #75 | DTrim99 | CLEAN, CI green ×5 (17:27–17:59Z runs) | S.3596 compute row on /bills |
| #72 | khs | computing | Preregistration grace bounded by release window |
| #70 | khs | computing | Preserve validated batches when site gate fails (the 504 incident, 3 lost targets) |
| #65 | khs | computing | PolicyEngine reform → draft cell loop (minwage E2E) |
| #64 | DTrim99 | MERGEABLE, tests running 18:19Z | PolicyEngine tool + call contract + evidence audit |
| #61 | **us** | MERGEABLE (pre-#76 check; #76 touches no overlapping files) | The study |
| #60 | khs | computing | Factor agent prompts into shared components — **brier/experiments/ only** |
| #59 | MaxGhenis | tests running | Repo-root cleanup |
| #57 | MaxGhenis | tests running | Sigstore submitter signing; body says "do not merge without review" |

("computing" = GitHub recomputing mergeability after the 18:25Z merges; all showed MERGEABLE or CLEAN minutes earlier except where noted.)

### Our three PRs — the exact state

- **Zero human review activity.** No reviews, no comments from anyone but the Vercel bot and David's own 16:20:58Z progress comment on #61. This is not a snub: of the PRs I inspected (#60, #61, #64, #65, #73, #75, #78, #79), **none** has a formal review; the working mode is self-annotated PRs that Max reads and merges directly.
- **CI never ran.** Both #78 (`fix/quantile-fail-closed`, head cd8753cc) and #79 (`feat/harness-disclosure`, head 75927c0d) show CI `completed/action_required` (run list 17:30:52Z, 17:33:27Z) — the fork-contributor approval gate. #61's recent commits are all `[skip ci]`, and its rollup shows only the two Vercel failures. The Vercel failures on all three are the team-authorization gate, not build failures (bot comment on each PR). Consequence: the only test evidence on our PRs is what the bodies claim was run locally.
- **Mutual and cross conflicts: none found, at hunk level.**
  - #78 vs #79: both touch `scripts/run_thesis_analyst.py`, at opposite ends — #78 at `materialize_run_distributions` (~line 293), #79 at `collect_hygiene` (~line 2958). Merge in either order.
  - #79 vs khs #65: both touch `scripts/spawned_cells_to_ts.py`. #79 inserts 2 lines in `to_forecast_cell` (line 345); #65's four hunks are pure `encoding="utf-8"` additions (lines 85, 300, 361, 374, Windows cp1252 fix). No shared lines; no semantic interaction (#65 doesn't touch validation logic #79's test relies on).
  - #60 (prompt components): `brier/experiments/*` + `paper/` only — a different experiments universe entirely. Zero overlap with anything of ours.
  - #64/#75 (Trimmer): `scripts/tools/*`, `bills/*`, `site/src/app/bills/*`, `site/src/components/ProvisionAnalysis.tsx`, `site/src/data/bills.ts`. Zero file overlap with us.
- **#61 scope verified:** 100 files, +253,735/−0, every path under `experiments/billimpact/` (files query, no non-experiment paths). The body's "no existing scoring, runner, or site code is modified" claim checks out.
- **The branch is still moving**: 9 commits pushed 17:40–18:24Z (forest-plot rework, three-results strip, "Mechanism of the default-effort bill penalty" at head 23da0883). The other session is live.
- One oddity I cannot resolve from the repo: Vercel attributes our fork deploys to "@mishmeals" while the PR author and fork owner are davidgringras. Presumably the Vercel-linked identity on the fork; David will know.

## 3. Bills lane: the pipeline and where we slot

Composition, as actually wired (per PR bodies + issue #43 plan):

```
fetch_bill.py (#50, merged)          bill text: axiom store → Congress.gov → --url
  → bills/<slug> bill.json (#50)     provisions, goals, effects, metric cards
  → /bills, /bills/[slug] UI (#50)   metricRegistryStatus() seam in site/src/data/bills.ts
  → registry mapper (#63, merged)    bill metrics vs live docket → reachable/not-yet/unmapped,
                                     draft ledger proposals under drafts/
  → PolicyEngine leg (#64, open)     validated+certified compute; S.3596 on build P: −$1.83B,
                                     poverty 17.02%→16.82% (−1.2% relative ≈ −0.20pp absolute)
  → compute row render (#75, open)   attach_compute.py (idempotent) + ProvisionAnalysis card
  → reform→cell loop (#65, open)     pe_reform_cell.py → draft cell passing spawned_cells_to_ts.validate
  → runner + converter               run_thesis_analyst.py → spawned_cells_to_ts.py → site cells
  → recorder seals (workflow)        record-forecasts.yml → witness-verified tier
```

Ours sits at the last three stages: **#78** hardens the runner's distribution materialization (declared-but-malformed `thresholdLadder` currently degrades silently to `interval_seeded`; measured cost of exactly that re-derivation: −0.034 nCRPS [−0.068, −0.003] on 26 matched units — #78 body citing #61's CALIBRATION_LAB.md). **#79** makes the harness config auditable through the converter (`reasoningEffort` stamped harness-side, carried to `predictionRun`, documented in cell-contract.md) — and #61 is the evidence that effort is the variable worth disclosing. **#61** tells the team which harness the whole pipeline should run with: fable-5 + bill text + max effort beats naive (−0.094 nCRPS [−0.174, −0.022]) and persistence (−0.518); bill text at default effort is harmful-to-neutral (significantly harmful on fable, +0.052). Third finding, flagged-not-PRed: `forecast-api/src/lib/prediction-distribution.ts` looks like a third CDF-builder copy missing the 2026-07-10 signed-zero fix (#61 body, "Flag for maintainers").

**Contradiction/duplication check: none.** #64's S.3596 result and our forecast-leg conditionals are reconciled in `TWO_LEGS_S3596.md` (#61 body): different measure universes; read consistently the legs land within a factor of two, forecast leg attenuated in the direction the recall-anchoring mechanism predicts. #79 cites #64's certification block as pattern precedent — convergence, not collision. #65's minwage cell is a *policy-lane* draft cell, complementary to our S.3596 forward cells. Nobody else touches elicitation/harness measurement.

**One number to keep straight at the demo:** #64/#75 say "child poverty −1.2%" (relative, 17.02→16.82); our forward leg speaks in absolute pp on the Census SPM series (−0.10 to −0.30pp band across harnesses, 14/16 sign-stable... poverty delta; uptake delta 16/16 — #61 body). Presented carelessly these look inconsistent.

## 4. Team dynamics (repo-readable)

- **Max = the gate.** Merged 9 of today's 10 PR merges; latency from open to merge: 5 min (#49), 6 (#55), 9 (#56), 28 (#69), 37 (#62), 77 (#63), 86 (#54); plus his own #73/#76 in a burst at 18:25Z. He also authors the infra spine: provenance chain (#73 → #82), seed repair (#76), sigstore (#57), cleanup (#59). His demonstrated priority today: keep the attested-records regime coherent under the new PR-only branch protection (#58 closed, ruleset live) while integrating everyone's lanes.
- **Pavel = product sprint.** ~25 commits on the #50 branch through the day (UI polish, stance v1 client, S.3596 provenance, bill-artifact CI validator), self-merged at 17:24Z after 3h13m. Bill schema v2 design open as #66.
- **Keller (khs) = reliability + legibility.** Four merged (#54/#55/#56/#62), seven open (#60/#65/#70/#72/#77/#80/#81) — an error-message sweep plus the orphaned-preregistration fix chain born from today's 504 incident (#70 body: 26 min of validated analyst work dropped; three targets permanently unforecast).
- **Trimmer (DTrim99) = PolicyEngine lane**, #64+#75, meticulous self-annotation (4 own comments on #64), CI green, both demo-shaped ("demo beat 4" named in #75 body).
- **Lane assignments are formal**: issues #44 (Pavel), #45 (Trimmer), #46 (David — "harness/workflow variants for extraction and forecast elicitation… results land in experiments/harness/"; our work outgrew the issue text, which nobody has commented on), #47 (Keller), #48 (Max).
- Curiosity with a lesson in it: #63's body records "sol reported a nonexistent commit hash; work verified and committed by the integrator" — an agent lane fabricated a commit reference and Max caught it. Expect verification-mindedness at merge time.

## 5. Everything else worth knowing

- **Provenance lane: red all afternoon, green since 18:25Z.** Every main push 14:49–17:24Z failed Records provenance (run list; #73 body names #56/#62/#54 as the false-positive shape: merge commits not TREESAME to all parents demanding attestations they can't have). #73 merged 18:25:50Z; the runs on both 18:25Z merge pushes completed success. If anyone shows CI history at the demo, the red wall has an explanation and a fix with a timestamp.
- **Recorder flakiness is live**: issue #74 open ("Record forecasts failed", run 30647665578, 16:34Z), succeeded on workflow_dispatch at 16:47:51Z, another run in flight 18:08:39Z. Our forward program depends on one clean recorder run post-merge (#61 body). Don't schedule that for 16:55 EDT.
- **Unresolved asks in #50's body** (Pavel → whoever owns the Vercel dashboard): `thesis-forecasts` ignored-build-step must watch `bills/` and "include files outside root directory" must be on, else artifact-only pushes don't redeploy; fetcher needs `AXIOM_SUPABASE_ANON_KEY` + `CONGRESS_API_KEY` env. I cannot see Vercel settings from here — unverified whether done. If not, the /bills demo may be serving stale artifacts.
- **Trust-boundary gap, open**: #71 — challenge adapter doesn't enforce challenger == landing-PR opener. Known, filed, unfixed.
- **#57 explicitly requests review before merge** (trust-boundary sigstore work) — if Max asks someone to review something in the next hour, it's likely that.
- **#61 demo artifact**: `experiments/billimpact/results/demo_page.html` is self-contained and works offline (#61 body) — usable even though fork Vercel previews can't deploy.
- **The #78 body plants our post-merge diagnostic**: scan existing ladder/ladder_v2 records for `interval_seeded`-despite-declared-ladder — the "ladder-bug query" from our tracker. It runs read-only; nothing stops us running it against main *now* and carrying the count into the demo.

## ADVICE — next 3 hours, ranked

1. **Walk over to Max (or Pavel) and get the two 10-second clicks: "Approve and run" on #78/#79's held CI, and Vercel deploy authorization for the fork.** Until then our PRs carry zero server-side test evidence (`action_required` runs, 17:30/17:33Z) and look red, and no amount of pushing fixes it from our side.
2. **Pitch #61 for a merge slot now, lead with the two facts that make it safe: 100 files, all under `experiments/billimpact/`, +253,735/−0, MERGEABLE — then immediately trigger the recorder run (`gh workflow run record-forecasts.yml --ref main`) to seal the S.3596 forward cells.** Max's merge latency is 5–90 min and the recorder failed once today (#74), so the seal must not be scheduled for the demo's final minutes.
3. **Freeze the #61 branch by ~16:00 EDT and pre-open `results/demo_page.html` locally as the demo surface.** The branch took 9 commits in the last 45 minutes; a last-minute push that breaks the forest plot or the page is the classic self-inflicted demo wound, and the offline artifact removes every deploy dependency.
4. **Spend 10 minutes with Trimmer agreeing the S.3596 two-legs script: he says −$1.83B and −1.2% relative (#64/#75), we say −0.10 to −0.30pp absolute on the Census series, and one of you names `TWO_LEGS_S3596.md` as the reconciliation.** Presented unrehearsed, the audience hears −1.2% vs −0.2pp as a contradiction inside your own demo; presented together it's the strongest slide in the room — two independent methods within 2x.
5. **Run the #78 ladder-scan diagnostic read-only against main now and carry the number into the demo.** "N historical cells silently degraded to `interval_seeded` and here is the PR that makes it impossible" upgrades #78 from hygiene to finding, and it needs no merge, no approval, and no one else's time.
