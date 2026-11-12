# Agent Workflows

`brier` is not tied to one assistant. The Claude Code plugin is the most integrated path today, but the framework also works with Codex, Cursor, Windsurf, ChatGPT, and any other agent that can follow structured instructions.

For Thesis forecast-generation work, read
[`docs/thesis-vision.md`](thesis-vision.md) first. The Thesis path is narrower
than the general decision workflow: agent-only public-data forecasts, automatic
first-print or policy-state resolution, immutable activity traces, and proper
scoring for Brier.

## Core instruction

Give your agent this instruction when you want a decision analyzed with `brier`:

```text
Use the brier workflow for this decision.
1. Define the KPI or outcome that would make the decision successful.
2. Expand the option set beyond the choices already mentioned.
3. Anchor on a relevant reference class or base rate before using the inside view.
4. Show the main mechanism or decomposition that drives the forecast.
5. List the strongest disconfirming evidence, failure modes, or decision traps.
6. Give point estimates with 80% confidence intervals for each option on each KPI.
7. Recommend a review date and say what would be logged later for calibration.
Do not answer with a vague recommendation until the forecasts are explicit.
```

## Codex and other coding agents

This works well in tools like Codex because they already have the two things `brier` needs:

- access to local context
- the ability to log decisions through the CLI or Python package

Minimal workflow (the commands on this page install from this repository,
which pip checks out in full, about 2 GB; the `brier` project on PyPI belongs
to someone else and is unrelated):

```bash
python -m pip install 'brier @ git+https://github.com/ThesisInstitute/thesis'
brier new "Should we rewrite the auth layer?" --context "3 incidents this quarter; CTO prefers Rust; team is strongest in Node."
```

Then ask the agent to use the core instruction above and to read or update the decision in `~/.brier/decisions.jsonl`.

If you want Codex to pick this workflow up as a native skill, install the packaged skill:

```bash
python -m pip install 'brier[mcp] @ git+https://github.com/ThesisInstitute/thesis'
brier setup codex
brier doctor codex
```

Then restart Codex.

If the skill drifted or setup only half-worked:

```bash
brier doctor codex --fix
```

## MCP server

If you want a native tool surface instead of prompt copy-paste, `brier` ships an MCP server:

```bash
python -m pip install 'brier[mcp] @ git+https://github.com/ThesisInstitute/thesis'
brier-mcp
```

The server exposes:

- tools for creating, listing, retrieving, scoring, and saving structured decision analyses
- resources for the framework, stored decisions, pending reviews, and calibration summary
- prompts for analyzing, reviewing, and scoring stored decisions

Optional configuration:

```bash
BRIER_STORE_PATH=/path/to/decisions.jsonl brier-mcp
# or
brier-mcp --store /path/to/decisions.jsonl
```

The default transport is `stdio`, which is the right default for editor and agent integrations.

To register the local server in Codex:

```bash
brier setup codex
```

## Claude Code

Claude Code can use the same local MCP server and a local skill wrapper:

```bash
python -m pip install 'brier[mcp] @ git+https://github.com/ThesisInstitute/thesis'
brier setup claude
brier doctor claude
```

This gives Claude Code a local skill plus the `brier` MCP tools/resources/prompts.

If the skill drifted or setup only half-worked:

```bash
brier doctor claude --fix
```

The plugin path is still available if you prefer slash commands:

```bash
claude plugin marketplace add ThesisInstitute/thesis
claude plugin install brier@maxghenis-plugins
```

Then either use the local skill or run `/brier:decide` for the plugin flow.

## Python and CLI

If you do not want any agent integration, `brier` still works as a local decision log and calibration tool. The CLI does not call an LLM and does not need an API key.

Useful commands:

```bash
brier new "Should we rewrite the auth layer?"
brier list
brier show <id>
brier pending
brier calibration
```

To draft forecast questions from a standalone policy question or a stored decision:

```bash
brier forecast-draft "Will Waymo be legally permitted to offer fully driverless paid robotaxi rides in Washington, DC by 2026-12-31?" \
  --initial-prob 52 \
  --resolution-date 2026-12-31 \
  --output waymo-dc-forecast-pack.json

brier forecast-draft <decision-id> --output forecast-pack.json
```

This only writes Manifold-ready JSON. It does not publish questions, create Manifold entries,
place bets, or require a Manifold API key.

If you want to fully reset a local integration:

```bash
brier uninstall codex
brier uninstall claude
```

## Recommended prompt shape

The strongest current version of the framework is:

1. KPI definition
2. option expansion
3. reference class
4. mechanism / decomposition
5. disconfirming evidence
6. numeric forecast with confidence interval
7. review date and later scoring

That sequence is more portable across models than prompting heavily for named cognitive biases alone.
