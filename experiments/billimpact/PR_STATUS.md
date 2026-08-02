# PR_STATUS — ThesisInstitute/thesis

Surveyed 2026-07-31. Repo slug **`ThesisInstitute/thesis`** (single remote `origin`,
`https://github.com/ThesisInstitute/thesis.git`, fetch and push identical; no fork or
second remote configured locally). All commands read-only: `git fetch --all --prune`,
`git log/show/diff/ls-files/check-ignore`, `gh pr list/view/diff`. Nothing was pulled,
merged, checked out, or written to the remote.

---

## RISKS TO OUR WORK (severity-ordered)

1. **`forecast-api/src/lib/prediction-distribution.ts` is a THIRD, stale copy of the CDF
   builder — and we have a `runs_api.jsonl`.** The 2026-07-10 signed-zero fix (`47f5a44d`)
   landed in "both CDF ports," which the commit's own file list defines as
   `site/src/data/prediction-distribution.ts` + `scripts/run_thesis_analyst.py`. The
   `forecast-api` copy was **not** included. It therefore (a) still writes
   `pointEstimate`/`median`/`interval80` without the `+ 0` unsigning and rounds via a
   `roundDistributionNumber` lacking the `+ 0`, so it can emit `-0` where the site builder
   emits `0`; and (b) does not emit `transformVersion` at all, and has no
   `INTERVAL_ANCHOR_TRANSFORM_VERSION` / `AGENT_CDF_TRANSFORM_VERSION` constants. Any
   distribution we obtain through the forecast-api path is **not** byte-identical to what
   our port reproduces. This is a live correctness question for `runs_api.jsonl`, not a
   future risk.

2. **A `git add .` would commit ~26 MB of untracked bill text.** `experiments/` is **not**
   gitignored (verified below). 22 untracked-or-modified paths sit under
   `experiments/`, totalling ~26 MB — dominated by `CAA-2021-116publ260.raw.htm` (7.76 MB),
   `CAA-2021-116publ260.txt` (7.69 MB) and `CAA-2023-117publ328.txt` (5.88 MB). The
   `.raw.htm` files are redundant intermediates sitting beside their extracted `.txt`. A
   broad sweep commits all of it permanently.

3. **PR #50 duplicates our bill-corpus work, including the same bill.** Pavel Makarchuk's
   draft PR builds a bill-text ingest pipeline at repo root (`scripts/bills/fetch_bill.py`
   → `bills/raw/<slug>.txt` + `.meta.json` provenance sidecar) and has already staged
   **S.3596 Stronger Start for Working Families Act** as `bills/raw/s3596-119.txt`. We hold
   the same bill at `experiments/billimpact/bills/S3596-stronger-start.txt`. His PR
   describes S.3596 as "one provision, tax, PolicyEngine-computable" — precisely our
   PolicyEngine tool-server target. No git conflict (disjoint paths), but the effort
   overlaps and the two corpora will diverge in provenance discipline: his carries a
   sha256 + source-URL sidecar; ours does not.

4. **Low: `pyproject.toml` / `uv.lock` are a latent collision point.** PR #50 appends a new
   `[dependency-groups] bills = [httpx, pypdf, selectolax]` block and +88 lines of
   `uv.lock`. We currently touch neither — every import across our `experiments/billimpact/*.py`
   is stdlib (verified: no third-party import anywhere in the directory). If we later add a
   dependency we collide with an unmerged draft.

**Not a risk, checked and cleared:** the scoring functions themselves have not moved
(item 1 of section 3), local `main` is only 2 commits behind on unrelated files, no open
PR touches any file we touch, and the `.githooks/pre-push` records guard is both inactive
(`core.hooksPath` unset, `.git/hooks/` holds only samples) and scoped to `records/**`.

---

## 1. Open pull requests

**One open PR.**

| # | Title | Author | Branch | State | Created | Updated | Files | +/- |
|---|---|---|---|---|---|---|---|---|
| [50](https://github.com/ThesisInstitute/thesis/pull/50) | Bill scraping + /bills frontend (#44) | PavelMakarchuk | `hack/pavel-bills` → `main` | **DRAFT** (`mergeStateStatus: BLOCKED`, `mergeable: MERGEABLE`) | 2026-07-31 14:11:43Z | 2026-07-31 14:15:18Z | 14 | +26248 / −0 |

**What it does:** adds an input-side bill fetcher (`scripts/bills/fetch_bill.py`, 422 lines
— resolves federal bill text axiom-first from a Supabase store, falling back to the
Congress.gov API, plus a `--url` mode for committee discussion drafts, writing
`bills/raw/<slug>.txt` with a `.meta.json` provenance sidecar) and a `/bills` +
`/bills/[slug]` Next.js surface rendering `bill.json` artifacts, with Farm Bill 2.0 ported
as entry #1 and S.3596 cached as the staged second bill.

Files touched: `bills/farm-bill-2-0.json`, `bills/raw/{farm-bill-2-0.{meta.json,pdf,txt},
s3596-119.{html,meta.json,txt}}`, `pyproject.toml`, `scripts/bills/{fetch_bill.py,
port_farm_bill.py}`, `site/src/app/bills/{page.tsx,[slug]/page.tsx}`,
`site/src/data/bills.ts`, `uv.lock`. Two commits, both co-authored `Claude Fable 5`.

The PR body contains three open questions addressed to reviewers (Vercel ignored-build-step
configuration, whether `provisions[].context` survives the contract, and two required env
vars `AXIOM_SUPABASE_ANON_KEY` / `CONGRESS_API_KEY`). Recorded here as observed content
only — no action taken on them.

---

## 2. Recently merged PRs and commits

### Merged PRs

Exactly one merge in the last three days:

| # | Title | Author | Merged | Files |
|---|---|---|---|---|
| 49 | Challenge inbox: pavel — jolts-hires-rate (`bls.jolts.hires_rate.2026_06.first_print`) | PavelMakarchuk | 2026-07-31 14:06:17Z | 1 |

The next-most-recent merges are #33 and #31 on 2026-07-22 — outside the window and
unrelated (custody env, producer signing).

### Commits on `origin/main`, last 3 days

Ten commits since 2026-07-28; eight are automation (`thesis-recorder`, `thesis-resolver`,
`thesis-prospector`) writing daily forecast surfaces and resolution ledgers under
`records/`. The two human-authored ones are `c7a3f57e` (PavelMakarchuk) and `a3d3c6c8`
(Max Ghenis), which together add exactly one file:
`challenge/inbox/pavel/jolts-hires-rate.json`.

### Dependency-path audit

`git log origin/main --since=2026-07-27` filtered to
`site/src/data/prediction-distribution.ts`, `scripts/run_thesis_analyst.py`,
`scripts/resolve_pending.py`, `site/src/data/thesis-log.ts`, `brier/experiments`,
`forecast-api`, `agents`, `AGENTS.md`, `ANCHORS.md` returns **zero commits**. None of the
files our work depends on has changed in the survey window.

All four spot-checked dependency files are byte-identical between our working tree and
`origin/main` (`git diff --quiet origin/main -- <path>` clean for
`prediction-distribution.ts`, `run_thesis_analyst.py`, `resolve_pending.py`,
`thesis-log.ts`).

---

## 3. Conflict / risk assessment

### 3.1 Have the scoring functions changed recently? — **No.**

`site/src/data/prediction-distribution.ts` has three commits in its entire history:

| Commit | Date | Author | Subject |
|---|---|---|---|
| `d086102c` | 2026-06-11 | Max Ghenis | Catalog→ledger migration: forecast cells, prediction specs, scored CDFs, log/ledger surfaces |
| `316a7996` | 2026-07-09 | Max Ghenis | Exact CRPS, strict CDF validation, and distribution provenance |
| `47f5a44d` | 2026-07-10 | Max Ghenis | Normalize IEEE signed zeros at cell intake and in both CDF ports |

All three are ancestors of `origin/main` **and** already present in our local `HEAD`
(`git merge-base --is-ancestor` → YES for each). The most recent is three weeks old.
**Our Python port is not stale with respect to `origin/main`.**

What the two relevant commits did, exactly:

- **`316a7996`** introduced the current scorer: `scoreNumericCdfDistribution` (CRPS +
  probability integral transform), `validateNumericCdfDistribution`,
  `assertValidNumericCdfDistribution`, the `DistributionProvenance` type and the
  `interval_anchor_v1` / `agent_cdf_v1` transform-version constants (+148 lines in this
  file; also +196 in `scripts/run_thesis_analyst.py`, plus 141 lines of new tests in
  `site/src/__tests__/prediction-distribution.test.ts` and a
  `interval_anchor_v1_distribution.json` fixture).
- **`47f5a44d`** is the signed-zero unification. In TS: `pointEstimate`, `median`,
  `interval80.lower/upper` each gained `+ 0`, and `roundDistributionNumber` became
  `Number(value.toPrecision(12)) + 0`. In Python: the rounding helper became
  `float(format(value, ".12g")) + 0.0`, a new `unsign_zero()` helper was added, and the
  summary/points writers route through it. Trigger was a real `-0.0` forecast from a
  `gpt-5.6-sol` strategy run splitting the publish gate's `Object.is` check.

**Our port inherits both fixes structurally.** `experiments/billimpact/scoring.py` does not
re-implement CDF construction — it loads `scripts/run_thesis_analyst.py` by file path
(`importlib.util.spec_from_file_location`) and calls its `interval_distribution`, which is
one of the two normalized ports. Only the scorer (`score_numeric_cdf`,
`_integrate_squared_linear`, `_linear_probability_at`, `_coalesce`,
`_interpolate_cdf_probability`) is our own code, and
`experiments/billimpact/pin_against_typescript.py` exists to pin it against the TS original.

**The exception, and the reason risk #1 is ranked first:**
`forecast-api/src/lib/prediction-distribution.ts` is a fourth implementation that the
signed-zero commit never touched. Diffing its `buildNumericCdfFromInterval` against the
site's shows it lacks all five `+ 0` normalizations and omits the `transformVersion` field
entirely. It also has no `scoreNumericCdfDistribution` — it is builder-plus-zod-schema
only, and additionally carries `normalizeNumericCdfDistribution`,
`summarizeNumericCdfDistribution` and `inverseCdf`, which the site copy does not. Treat
site TS and `scripts/run_thesis_analyst.py` as the pinned pair; treat anything arriving via
forecast-api as a different vintage.

Full inventory of files referencing the CDF functions (excluding `node_modules`):
`site/src/data/prediction-distribution.ts`, `forecast-api/src/lib/prediction-distribution.ts`,
`scripts/run_thesis_analyst.py`, `scripts/median_rollout_ensemble.py`,
`site/src/__tests__/prediction-distribution.test.ts`, `tests/test_thesis_analyst_runner.py`,
`site/src/data/{thesis-log,forecast-cells,prediction-series,strategy-lab,time-series-priors}.ts`,
`forecast-api/src/{lib/forecast.ts,app/forecasts/[slug]/stream/route.ts}`, `SOL-F8-NOTES.md`,
and our own `experiments/billimpact/{scoring.py,pin_against_typescript.py,ts_driver.mjs,PREREGISTRATION.md}`.

### 3.2 Is `experiments/` gitignored? — **No. Files are tracked.**

`git check-ignore -v` returns exit 1 (no matching ignore rule) for all three probes:
`experiments/billimpact/scoring.py`, `experiments/billimpact/runs.jsonl`,
`experiments/billimpact/bills/CAA-2021-116publ260.txt`. The repo `.gitignore` covers only
Python build artefacts, virtualenvs, IDE files, pytest/coverage, Quarto output
(`paper/_book/`, `site/public/paper/`), one skill workspace, and `.DS_Store` — no
`experiments/` entry.

**Currently tracked under `experiments/`: 2457 files.**

| Path | Tracked files |
|---|---|
| `experiments/decision_usefulness/` | 1140 |
| `experiments/stability_results/` | 657 |
| `experiments/stability_validation/` | 409 |
| `experiments/reframing_results/` | 243 |
| `experiments/billimpact/` | **7** |
| `experiments/prompts.json` | 1 |

The 7 already-tracked `billimpact` files: `PREREGISTRATION.md`,
`bills/FRA-2023-118publ5.txt`, `corpus_spec.json`, `fetch_ground_truth.py`,
`ground_truth.json`, `harness.py`, `provisions.json`.

**Untracked or modified under `experiments/`: 22 paths, ~26 MB.** One modification
(`harness.py`) and 21 new files: `analyze.py`, `ctc_harness.py`, `ctc_sweep.py`,
`pe_server.py`, `pin_against_typescript.py`, `requarantine.py`, `runs.jsonl`,
`runs_api.jsonl`, `scoring.py`, `sweep.py`, `tools.py`, `ts_driver.mjs`, and ten files
under `bills/`.

A broad `git add` stages all of it. CI would not object on content grounds —
`.github/workflows/ci.yml` runs `uv run pytest tests/ -q` (not `experiments/`), and the
size-budget gate is `site/scripts/check-size-budgets.mjs`, scoped to the generated site —
but 26 MB of bill text becomes permanent repo history.

### 3.3 Open PRs touching files we would touch? — **None.**

`comm -12` between PR #50's changed-file set and our full untracked-plus-modified set
returns empty. PR #50 lives in `bills/`, `scripts/bills/`, `site/src/app/bills/`,
`site/src/data/bills.ts`, `pyproject.toml`, `uv.lock`; we live entirely in
`experiments/billimpact/` plus one root markdown file. The overlap is conceptual
(risk #3), not textual.

### 3.4 Is local `main` behind? — **2 behind, 1 ahead.**

`git rev-list --left-right --count origin/main...HEAD` → `2  1`.

- **Ahead (1):** `f95c4b6c` "Preregister bill-impact harness ablation (Leg B) before first
  run" — our own, unpushed.
- **Behind (2):** `c7a3f57e` and `a3d3c6c8`, both "Challenge inbox: pavel —
  jolts-hires-rate," adding exactly one file between them:
  `challenge/inbox/pavel/jolts-hires-rate.json`.

**Neither incoming commit touches any file our work depends on.** Merging them is a
no-op for the harness; no rebase urgency.

`git fetch --all --prune` also revealed two new remote branches:
`origin/challenge/pavel-onboarding` (merged as PR #49) and `origin/hack/pavel-bills`
(PR #50). `origin/scoring-integrity`, despite its "WIP: chronology gate + target-scale
CRPS (F1+F2)" tip subject, is a **fully merged ancestor** of `origin/main` with zero
unmerged commits — checked because the name suggested pending scorer changes; it has none.
