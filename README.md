# Brier

**Forecasting as a harness for decision-making.**

Brier is also the forecasting agent being developed inside Thesis: an
open-source, agent-only lab for automatically resolvable public-data forecasts.
For the current Thesis/Brier product vision, read
[`docs/thesis-vision.md`](docs/thesis-vision.md) first. Future coding agents
should start with [`AGENTS.md`](AGENTS.md).

The new experiment backend is `thesis_core`: immutable scientific records,
durable execution, source evidence, timestamp verification and a read-only API.
See the [architecture](docs/thesis-core-architecture.md),
[local runbook](docs/thesis-core-runbook.md) and
[verification report](docs/thesis-core-verification.md). It runs alongside the
existing publishing system; the site displays its experiments at `/core`.

Instead of asking "Is X good?" or "Should I do Y?", brier helps you:
1. Define what success looks like (KPIs)
2. Expand your options (including ones you didn't consider)
3. Make explicit forecasts (with confidence intervals and resolution rules)
4. Track outcomes to improve calibration over time

## Installation

```bash
python -m pip install 'brier[mcp]'
```

## Quick Start

### Codex

```bash
brier setup codex
brier doctor codex
```

Then restart Codex and use `$brier` when a decision prompt appears.

### Claude Code

```bash
brier setup claude
brier doctor claude
```

Then restart Claude Code.

### Local CLI

```bash
brier new "Should we rewrite the auth layer?" --context "3 incidents this quarter"
brier list
brier calibration
```

The CLI is local-only and does not call an LLM or require an API key.

### Python package

```python
from brier import Decision, KPI, Option, Forecast, DecisionStore
from datetime import datetime, timedelta

# Create a decision
decision = Decision(
    question="Should I take the new job offer?",
    kpis=[
        KPI(name="income", description="Total comp after 2 years", unit="$"),
        KPI(
            name="satisfaction",
            description="Job satisfaction 1-10",
            outcome_type="score",
            resolution_date=datetime.now() + timedelta(days=365),
            resolution_rule="Ask for a 1-10 retrospective self-rating 12 months after starting.",
            data_source="Follow-up self-review",
        ),
    ],
    options=[
        Option(
            name="Take new job",
            description="Accept the offer at Company X",
            forecasts={
                "income": Forecast(
                    point_estimate=300000,
                    confidence_interval=(250000, 400000),
                    reasoning="Base + equity, assuming normal vesting",
                ),
                "satisfaction": Forecast(
                    point_estimate=7.5,
                    confidence_interval=(6, 9),
                    reasoning="Interesting work, but unknown team",
                ),
            }
        ),
        Option(
            name="Stay at current job",
            description="Decline and stay",
            forecasts={
                "income": Forecast(
                    point_estimate=250000,
                    confidence_interval=(230000, 280000),
                    reasoning="Known trajectory, likely promotion",
                ),
                "satisfaction": Forecast(
                    point_estimate=6.5,
                    confidence_interval=(6, 7),
                    reasoning="Comfortable but plateauing",
                ),
            }
        ),
    ],
    review_date=datetime.now() + timedelta(days=180),
)

# Save it
store = DecisionStore()
store.save(decision)
```

### Command Line

```bash
brier new "Should we launch now?"
brier show abc123
brier pending
brier calibration
```

### Forecast Question Drafts

`brier` can turn a stored decision forecast or standalone policy question into
Manifold-ready forecast question drafts. This is draft-only: it does not publish
questions, place a bet, or require a Manifold API key.

```bash
brier forecast-draft "Will Waymo be legally permitted to offer fully driverless paid robotaxi rides in Washington, DC by 2026-12-31?" \
  --initial-prob 52 \
  --resolution-date 2026-12-31 \
  --resolution-rule "Resolve YES if official DC law, regulation, or permit approval allows Waymo to offer fully driverless paid public rides in DC by 2026-12-31." \
  --source "Waymo DC announcement|https://waymo.com/blog/2025/03/next-stop-for-waymo-one-washingtondc/" \
  --source "DC AV testing law|https://code.dccouncil.gov/us/dc/council/laws/23-156" \
  --tag waymo \
  --tag dc \
  --output waymo-dc-forecast-pack.json
```

For a stored decision with options and forecasts:

```bash
brier forecast-draft abc123 --output forecast-pack.json
```

An example Waymo/DC draft pack lives at
[`examples/waymo_dc_market_pack.json`](examples/waymo_dc_market_pack.json). It
uses an existing Manifold public-service question as the gate, then drafts
conditional aggregate 2027 safety forecasts for DC traffic fatalities and serious
injuries. These resolve N/A when the linked gate question resolves the opposite
way.

### AI Agent Workflows

`brier` is not tied to Claude. The Claude Code plugin is the most integrated path today, but the framework also works with Codex and other coding agents that can follow structured instructions or run shell commands.

For agent-agnostic setup and prompt guidance, see [`docs/agent-workflows.md`](docs/agent-workflows.md).

#### Codex and other coding agents

The default builder path is package-first:

```bash
python -m pip install 'brier[mcp]'
brier setup codex
brier doctor codex
```

For source installs during development:

```bash
python -m pip install -e /path/to/brier
```

#### MCP server

If you want a native tool interface instead of prompt copy-paste, install the package and run the MCP server locally:

```bash
python -m pip install 'brier[mcp]'
brier-mcp
```

It exposes tools for creating, listing, retrieving, saving, and scoring decisions, plus resources/prompts for the brier workflow.

To register it in Codex as a local MCP server:

```bash
brier setup codex
brier doctor codex
```

This installs the packaged Codex skill and registers the MCP server with the same Python interpreter that launched `brier`.

#### Claude Code local skill + MCP

Claude Code can use the same local MCP server and a local skill wrapper:

```bash
python -m pip install 'brier[mcp]'
brier setup claude
brier doctor claude
```

This installs the packaged Claude skill and registers the MCP server in user scope.

The plugin path still works if you prefer the slash-command workflow:

```bash
claude plugin marketplace add ThesisInstitute/thesis
claude plugin install brier@maxghenis-plugins
```

Then either use the local `brier` skill or `/brier:decide` if you installed the plugin.

#### Repair and reset

If setup drifted or a skill was modified locally:

```bash
brier doctor codex --fix
brier doctor claude --fix
```

If you want to remove the local integration and start over:

```bash
brier uninstall codex
brier setup codex
```

or:

```bash
brier uninstall claude
brier setup claude
```

## The Framework

Brier implements a structured decision process:

1. **KPI Definition** - What outcomes actually matter? Make them measurable.
   Add outcome type, resolution date, resolution rule, and data source when possible.

2. **Option Expansion** - Don't just compare A vs B. What about C? What about waiting? What about hybrid approaches?

3. **Reference Class** - Start with a relevant outside view or base rate before adjusting for specifics.

4. **Mechanism / Decomposition** - Break forecasts into estimable components and causal drivers.

5. **Disconfirming Evidence** - Surface the strongest failure modes, traps, and reasons the leading option could be wrong.

6. **Confidence Intervals** - Point estimates aren't enough. How uncertain are you?

7. **Tracking** - Log decisions and review outcomes to calibrate over time.

## Why This Works

- **Reduces sycophancy** - Harder to just agree when making numeric predictions
- **Forces mechanism thinking** - Must reason about cause and effect
- **Creates accountability** - Predictions can be scored later
- **Separates values from facts** - You pick KPIs (values), forecasts are facts
- **Builds calibration** - Track predictions over time to improve

## Development

```bash
git clone https://github.com/ThesisInstitute/thesis
cd thesis
pip install -e ".[dev,experiments]"
pytest
python -m build
python scripts/smoke_packaged_install.py dist/*.whl
python scripts/generate_demo_video.py
```

Paper build:

```bash
python3 paper/render_paper.py  # Regenerates figures, HTML, Markdown, and site/public/paper-raw
python3 paper/run_strongest_validation.py  # Runs the strongest reviewer-facing validation on Claude Opus 4.6 and GPT-5.2
python3 paper/run_study1_rerun.py --models gpt-5.4  # Reruns the original Study 1 design with legacy prompt wording
python3 -m brier.experiments stability --strongest-validation --model gpt-5.2  # Single-model equivalent
```

### Publishing to PyPI

The `publish.yml` workflow builds the package and uploads it with PyPI
Trusted Publishing when a GitHub release is published.

**Current state (verified 2026-07-25): there is no `brier` project on
PyPI.** The API returns 404 for it, so nothing is installable from PyPI
today and no trusted publisher exists to migrate after the repository
transfer. The workflow last ran for the v0.2.x tags in March 2026; treat
it as dormant rather than as evidence of a published package.

**To start publishing (only if a release is actually wanted):** the
project does not exist yet, so it needs a *pending* publisher, registered
at the account level rather than on a project page:

1. Open `https://pypi.org/manage/account/publishing/`.
2. Add a pending publisher with:
   - PyPI Project Name: `brier`
   - Owner: `ThesisInstitute`
   - Repository name: `thesis`
   - Workflow name: `publish.yml`
   - Environment name: leave blank (the publish job defines no environment)

The first release then creates the project. Note the package name still
carries the pre-Thesis `brier` naming; decide whether to rename before
claiming a name on PyPI.

**To publish a new version:**
1. Update version in `pyproject.toml`
2. Create a new release on GitHub with a tag (e.g., `v0.2.0`)
3. The GitHub Actions workflow will automatically build and publish to PyPI

The repo no longer needs a stored `PYPI_API_TOKEN` once Trusted Publishing is configured.

## License

MIT
