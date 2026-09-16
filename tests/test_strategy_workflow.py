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


def workflow_document() -> dict:
    import yaml  # a hard dependency here: structure, not substrings

    document = yaml.safe_load(WORKFLOW.read_text())
    return document


def dispatch_inputs(document: dict) -> dict:
    # PyYAML reads the bare `on:` key as the boolean True (YAML 1.1).
    triggers = document.get("on", document.get(True))
    return triggers["workflow_dispatch"]["inputs"]


def named_step(job: dict, name: str) -> dict:
    for entry in job["steps"]:
        if entry.get("name") == name:
            return entry
    raise AssertionError(f"workflow job has no step named {name!r}")


def test_strategy_workflow_dispatches_the_system_one_forecaster() -> None:
    document = workflow_document()
    inputs = dispatch_inputs(document)

    assert inputs["suite"]["options"] == ["ladder", "median3", "both", "system_one"]
    assert inputs["system_one_backend"]["options"] == ["adapter", "typesafe"]
    assert inputs["system_one_backend"]["default"] == "adapter"
    assert inputs["system_one_model"]["default"] == ""

    provisional = named_step(
        document["jobs"]["select"], "Resolve comparison targets with trusted code"
    )
    assert (
        provisional["env"]["SYSTEM_ONE_BACKEND"]
        == "${{ inputs.system_one_backend || 'adapter' }}"
    )
    assert provisional["env"]["SYSTEM_ONE_MODEL"] == "${{ inputs.system_one_model }}"
    assert '--system-one-backend "$SYSTEM_ONE_BACKEND"' in provisional["run"]
    assert '--system-one-model "$SYSTEM_ONE_MODEL"' in provisional["run"]


def test_strategy_workflow_runs_system_one_without_the_codex_toolchain() -> None:
    document = workflow_document()
    generate = document["jobs"]["generate"]

    assert generate["env"] == {
        "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
        "TYPESAFE_API_KEY": "${{ secrets.TYPESAFE_API_KEY }}",
    }
    uses = [step.get("uses") for step in generate["steps"]]
    assert "astral-sh/setup-uv@v5" in uses

    # The suite comes from the TRUSTED selection, never from the dispatch
    # input, and the codex steps are skipped when it is the System One lane.
    invocation = named_step(generate, "Resolve the trusted invocation identity")
    assert 'suite = (selection.get("request") or {}).get("suite")' in invocation["run"]
    assert 'print(f"suite={suite}")' in invocation["run"]
    skipped = "${{ steps.invocation.outputs.suite != 'system_one' }}"
    for name in ("Enable the agent sandbox", "Install codex CLI", "Authenticate codex"):
        assert named_step(generate, name)["if"] == skipped

    suite_step = named_step(generate, "Run the selected strategy suite")
    assert suite_step["env"]["SUITE"] == "${{ steps.invocation.outputs.suite }}"
    run = suite_step["run"]
    assert "uv run --locked --extra system-one" in run
    assert "python scripts/run_strategy_suite.py" in run
    assert "python3 scripts/run_strategy_suite.py" in run
    assert "--ledger-jsonl /tmp/pinned-ledger.jsonl" in run


def test_strategy_workflow_publish_counts_the_system_one_lane() -> None:
    document = workflow_document()
    regenerate = named_step(
        document["jobs"]["publish"],
        "Verify custody and regenerate all strategy comparisons",
    )
    run = regenerate["run"]
    assert 'system_one = suite["lanes"].get("systemOne")' in run
    assert 'batches.append(system_one["batchManifest"])' in run
