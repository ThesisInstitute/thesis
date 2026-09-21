from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/strategy-docket.yml"


def job_block(source: str, name: str, next_name: str | None) -> str:
    start = source.index(f"\n  {name}:\n")
    end = source.index(f"\n  {next_name}:\n", start) if next_name else len(source)
    return source[start:end]


def test_strategy_workflow_has_three_phase_data_only_boundary() -> None:
    source = WORKFLOW.read_text()

    assert "workflow_dispatch:" in source
    assert "schedule:" not in source
    assert "group: docket-writers" in source
    assert "permissions:\n  contents: read" in source
    assert "  select:" in source
    assert "  generate:" in source
    assert "  publish:" in source
    assert "needs: select" in source
    assert "needs: [select, generate]" in source
    assert "if: ${{ always() }}" in source
    assert "contents: write" in source
    assert "OPENAI_API_KEY" in source

    assert "scripts/strategy_targets.py select" in source
    assert "scripts/run_strategy_suite.py" in source
    assert "scripts/strategy_publication.py stage" in source
    assert "scripts/strategy_publication.py validate" in source
    assert "scripts/strategy_comparisons.py --all-records" in source
    assert "--allow-path" not in source
    assert "register_targets.py" not in source
    assert "needs.generate.outputs" not in source
    assert "Resolve the invocation-scoped suite from the bundle header" in source


def test_strategy_workflow_reuses_trusted_attempt_on_failed_job_reruns() -> None:
    source = WORKFLOW.read_text()
    generate = job_block(source, "generate", "publish")
    publish = job_block(source, "publish", None)

    assert generate.count("Resolve the trusted invocation identity") == 1
    assert publish.count("Resolve the trusted invocation identity") == 1
    assert '--run-attempt "${{ steps.invocation.outputs.run_attempt }}"' in generate
    assert "name: ${{ steps.invocation.outputs.publication_artifact }}" in generate
    assert "name: ${{ steps.invocation.outputs.publication_artifact }}" in publish
    assert "RUN_ATTEMPT: ${{ steps.invocation.outputs.run_attempt }}" in publish
    assert "GITHUB_RUN_ATTEMPT" not in generate
    assert "github.run_attempt" not in generate
    assert "github.run_attempt" not in publish


def test_strategy_workflow_pins_tools_and_witnesses_run_window() -> None:
    source = WORKFLOW.read_text()

    assert "actions/checkout@v5" in source
    assert "actions/upload-artifact@v7" in source
    assert "actions/download-artifact@v8" in source
    assert "oven-sh/setup-bun@v2" in source
    assert "@openai/codex@0.144.0" in source
    assert "PolicyEngine/chronicle" in source
    assert "application/vnd.github.raw+json" in source
    assert "artifactCreatedAtUtc" not in source  # stamped by trusted selector code
    assert "verify-artifact" in source
    assert "--publish-validated-at-utc" in source
    assert "record-forecasts.yml" in source
    assert "for attempt in 1 2 3; do" in source


def test_final_push_rechecks_deadlines_after_potentially_slow_builds() -> None:
    publish = job_block(WORKFLOW.read_text(), "publish", None)
    push_loop = publish[publish.index("- name: Rebase, reverify, and push") :]
    build = push_loop.index("bun run build")
    push = push_loop.index('push origin main; then')
    before_push = push_loop[build:push]
    assert 'gh api "repos/$LEDGER_REPOSITORY/commits/$LEDGER_BRANCH"' in before_push
    assert 'scripts/strategy_targets.py ensure-open' in before_push
    assert '--checked-at-utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)"' in before_push
