# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Brier began as a decision-making framework that reframes subjective questions
("Should I...?") into forecasting problems with explicit KPIs, confidence
intervals, and calibration tracking. The current Thesis/Brier product direction
is broader: Thesis is an open-source, agent-only forecasting lab for
automatically resolvable public-data series, and Brier is the forecast-accuracy
agent being trained and evaluated inside that lab.

Read `AGENTS.md` and `docs/thesis-vision.md` before changing
forecast-generation, pack, resolution, scoring, or agent-run surfaces. In
short: prioritize government or similarly authoritative public series,
agent-only runs, full public activity traces, automatic first-print or
policy-state resolution, proper scoring, and comparisons across agents, prompt
modes, and pack sets.

## Commands

### Python Package

```bash
# Install for development
pip install -e ".[dev,experiments]"

# Run tests
pytest

# Run single test file
pytest tests/test_framework.py

# Run with coverage
pytest --cov=brier

# Format code
black brier tests
ruff check brier tests
```

### CLI

```bash
brier new "question"    # Create a new decision
brier new "q" --context "details"  # With context
brier list              # List all decisions
brier list --pending    # Decisions past review date
brier show <id>         # Show decision details (supports prefix match)
brier score [id]        # Score a decision's actual outcomes (interactive)
brier calibration       # Show calibration statistics
brier pending           # Alias for list --pending
brier forecast-draft <id-or-question>  # Draft a forecast/market pack (alias: market-draft)
brier setup {claude,codex}    # Install the skill + register the MCP server
brier doctor {claude,codex}   # Check skill/MCP installation health
brier uninstall {claude,codex}  # Remove skill + MCP registration
brier install-skill {claude,codex}  # Install just the packaged SKILL.md
```

### Site (Next.js)

```bash
cd site
bun install
bun run dev      # Development server
bun run build    # Build for production (standard Vercel SSG, not a static export)
bun run test     # Run vitest tests
```

Production deploys are git-integrated (2026-07-02): pushing `main` deploys
the site (Vercel project `thesis-forecasts`, root `site/`) and the API
(`thesis-api`, root `forecast-api/`); builds are skipped when the root
directory didn't change, and `[skip ci]` commits skip Vercel entirely.
Never run `vercel --prod` from any checkout or worktree — CLI deploys
capture the production alias and caused both 2026-06 incidents. The
`~/thesis-institute` scripts are break-glass only (`THESIS_BREAK_GLASS=1`).

### Paper

```bash
python3 paper/render_paper.py  # Generate figures, render HTML, sync preemptive_rigor.md and site/public/paper-raw
python3 paper/run_strongest_validation.py  # Strongest reviewer-facing validation across Claude Opus 4.6 and GPT-5.2
python3 paper/run_study1_rerun.py --models gpt-5.4  # Original Study 1 rerun with legacy prompt wording
python3 -m brier.experiments stability --strongest-validation --model gpt-5.2  # Single-model strongest validation
```

## Architecture

### Python Package (`brier/`)

- **framework.py**: Core dataclasses (`Decision`, `KPI`, `Option`, `Forecast`) with serialization. `Option.expected_value()` computes weighted expected values across KPIs. `Decision.best_option()` and `sensitivity_analysis()` for analysis.
- **storage.py**: `DecisionStore` persists decisions to `~/.brier/decisions.jsonl` in JSONL format. Supports CRUD and filtered queries (unscored, pending review, scored).
- **calibration.py**: `CalibrationTracker` computes forecast accuracy metrics: coverage (% of actuals in CIs), calibration error (coverage vs stated confidence), MAE, MRE, Brier scores.
- **cli.py**: Argparse CLI wrapping the above modules.

### Claude Code Plugin (`claude-plugin/`)

- **commands/decide.md**: Full structured decision analysis workflow (KPIs → options → forecasts → logging)
- **commands/score.md**: Score past decisions against actual outcomes
- **skills/decision-framework/SKILL.md**: Skill that detects advice-seeking patterns and reframes as forecasting problems

### Spawning new forecast cells (the thesis.analyst pipeline)

New cells are generated as recorded agent runs, never hand-authored mocks:
an agent researches the question with REAL fetches from official sources
(release calendars for resolutionDate, series history for the base rate),
derives point + 80% CI from the data, and emits JSON with a full trace and
`runAt` = actual generation time. Convert with
`python3 scripts/spawned_cells_to_ts.py site/src/data/forecast-examples/<name>.ts CONST_NAME in.json`,
which enforces the same trace-depth rubric CI does
(`site/src/__tests__/trace-depth.test.ts`): >=7 steps, >=3 real tool steps,
math derivation, base rate, disconfirming consideration. When the official
history is verifiable out-of-band, pin it: `anchors` in the target context
(`{"2024": 88.2, ...}` — period label token to official value) makes runner
validation fail closed if the run's fetched historicalContext contradicts
the anchor (wrong series/vintage/artifact lineage; the 2026-07-21 ACS
5-year-vs-1-year corruption is the motivating case). Anchors are
validation-only — never injected into the prompt, so the agent still has
to fetch the base rate itself. For targets whose official endpoint the
hosted web tool cannot fetch (all data.census.gov JSON; api.census.gov is
key-gated), spawn with `--codex-sandbox workspace-write --codex-network`
so the agent can curl the endpoint in-sandbox — the read-only sandbox
blocks all sockets, and runs that can't fetch fabricate plausible values
instead (the 2026-07-24 broadband rejection: a 65+ share series matching
neither the ACS 1-year nor 5-year file, with raw counts off by up to 2.3
million — invented, not a vintage mix-up). Resolved outcomes
are recorded as observations in PolicyEngine/ledger (formerly arch-data)
(`ledger/official_observations.jsonl`, branch `codex/thesis-ledger-facts`),
which the site fetches at build time. Deploy by pushing `main`; run the
recorder workflow (`gh workflow run record-forecasts.yml --ref main`) right
after new predictions go live so their pre-registration timestamp is tight.

The forecasts browser filters on DERIVED attributes only (publisher from
the dataPointId's agency token via `site/src/data/forecast-publishers.ts`,
plus country/status/title) — there is deliberately no hand-curated
topic/tag layer (removed 2026-07-21; `/topics/*` redirects home). New
agencies ship with no registry edits; add a display label to
`PUBLISHER_LABELS` only if the raw token is unreadable.

### Site (`site/`)

Next.js App Router site with Tailwind CSS v4, deployed to Vercel as the
`thesis-forecasts` project behind app.thesisinstitute.org (standard SSG build —
all forecast pages prerender from `src/data/forecast-cells.ts`; four live
cells stream from forecast-api at runtime).

### Ledger database (Supabase)

The target-architecture schema
(`site/supabase/migrations/20260629_thesis_target_architecture.sql`) runs in
Supabase project `thesis` (`fvzmphrwcurwikkbiduq`, PolicyEngine org). Load or
refresh it from the published projection with:

```bash
export THESIS_SUPABASE_DB_URL="postgresql://postgres.fvzmphrwcurwikkbiduq:$(agent-secret get THESIS_SUPABASE_DB_PASSWORD)@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
uv run --with "psycopg[binary]" --with requests scripts/ingest_target_architecture.py
```

Idempotent (append-only tables, ON CONFLICT DO NOTHING); exits nonzero if any
table's row count disagrees with the published manifest. The site remains the
source of truth until surfaces read from the database directly.

## Key Design Decisions

- Forecasts require both point estimates and confidence intervals
- Confidence levels are explicit (default 80%)
- Base rates and inside-view adjustments are first-class fields for outside/inside view reasoning
- Fermi decomposition supported via `Forecast.components` dict
- Decisions are append-only to JSONL; updates rewrite the file
