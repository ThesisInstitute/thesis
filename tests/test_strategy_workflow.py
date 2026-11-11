from __future__ import annotations

import pathlib
import re

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
    diagnostic_start = generate.index("Archive the strategy attempt for diagnosis")
    diagnostic_end = generate.index("Stage one exact-scope strategy bundle")
    authoritative_generation = generate[:diagnostic_start] + generate[diagnostic_end:]
    assert "github.run_attempt" not in authoritative_generation
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


def test_strategy_generation_uses_the_attested_checkout_interpreter() -> None:
    generate = job_block(WORKFLOW.read_text(), "generate", "publish")
    prepare = generate.index("uv sync --locked --extra custody")
    run = generate.index(".venv/bin/python scripts/run_strategy_suite.py")
    assert prepare < run
    assert "python3 scripts/run_strategy_suite.py" not in generate
    assert "--selection-ledger-jsonl /tmp/pinned-ledger.jsonl" in generate


def test_diagnostic_attempt_upload_precedes_custody_staging_and_is_not_published() -> None:
    source = WORKFLOW.read_text()
    generate = job_block(source, "generate", "publish")
    publish = job_block(source, "publish", None)
    archive = generate.index("Archive the strategy attempt for diagnosis")
    upload = generate.index("Upload the diagnostic attempt independently of publication")
    stage = generate.index("Stage one exact-scope strategy bundle")
    assert archive < upload < stage
    for block in (generate[archive:upload], generate[upload:stage]):
        assert "always()" in block
        assert "steps.suite.outcome != 'skipped'" in block
    assert "strategy-attempt-" not in publish
    assert "strategy-attempt-diagnostic" not in publish
    assert "-execution-${{ github.run_attempt }}" in generate[upload:stage]
    assert "include-hidden-files: true" in generate[upload:stage]
    assert "overwrite: true" not in generate[upload:stage]


def test_all_strategy_replay_consumers_use_the_locked_custody_environment():
    text = WORKFLOW.read_text()
    select = text.split("  select:\n", 1)[1].split("  generate:\n", 1)[0]
    generate = text.split("  generate:\n", 1)[1].split("  publish:\n", 1)[0]
    publish = text.split("  publish:\n", 1)[1]
    path_export = 'echo "$GITHUB_WORKSPACE/.venv/bin" >> "$GITHUB_PATH"'
    for job, consumer in (
        (select, "python3 scripts/verify_custody.py"),
        (generate, "python3 scripts/archive_strategy_attempt.py"),
        (publish, "python3 scripts/strategy_publication.py validate"),
    ):
        assert job.index("uv sync --locked --extra custody") < job.index(path_export)
        assert job.index(path_export) < job.index(consumer)
    # Rebase can change the trusted dependency lock before another replay.
    rebase = publish.split("git pull --rebase origin main", 1)[1]
    assert rebase.index("uv sync --locked --extra custody") < rebase.index(
        "python3 scripts/strategy_publication.py validate"
    )


def _named_step(source: str, marker: str) -> str:
    steps = source.split("\n      - ")[1:]
    matches = [step for step in steps if marker in step.splitlines()[0]]
    assert len(matches) == 1, marker
    return matches[0]


def _step_condition(step: str) -> str | None:
    match = re.search(r"^        if: (.+)$", step, re.MULTILINE)
    return match.group(1) if match else None


def test_other_captured_replay_jobs_provision_locked_runtime_before_consumers():
    path_export = 'echo "$GITHUB_WORKSPACE/.venv/bin" >> "$GITHUB_PATH"'
    cases = [
        (
            workflow,
            job,
            next_job,
            consumers,
        )
        for workflow in ("roll-docket.yml", "prospect-docket.yml")
        for job, next_job, consumers in (
            (
                "register",
                "generate",
                ("scripts/docket_publication.py scan-staged", "scripts/verify_custody.py"),
            ),
            (
                "generate",
                "publish",
                ("scripts/run_thesis_batch.py", "scripts/docket_publication.py stage"),
            ),
            (
                "publish",
                None,
                ("scripts/docket_publication.py validate", "scripts/verify_custody.py"),
            ),
        )
    ]
    cases += [
        (
            "mint-generation-ticket.yml",
            "mint",
            None,
            ("scripts/docket_publication.py scan-staged", "scripts/verify_custody.py"),
        ),
        (
            "publish-attested.yml",
            "publish",
            None,
            ("scripts/verify_attested_bundle.py", "scripts/verify_custody.py"),
        ),
        (
            "api-canary.yml",
            "canary",
            None,
            ("scripts/run_thesis_analyst.py", "from verify_custody import verify_run"),
        ),
    ]
    assert len(cases) == 9
    for workflow, name, next_name, consumers in cases:
        source = (ROOT / ".github" / "workflows" / workflow).read_text()
        job = job_block(source, name, next_name)
        provision = _named_step(job, "name: Provision custody replay runtime")
        checkout = _named_step(job, "uses: actions/checkout@")
        setup = job.index("uses: astral-sh/setup-uv@")
        prepared = job.index("name: Provision custody replay runtime")
        exported = job.index(path_export)
        assert setup < prepared < exported, (workflow, name)
        assert job.index("uses: actions/checkout@") < prepared
        assert provision.index("uv sync --locked --extra custody") < provision.index(
            path_export
        )
        assert _step_condition(provision) == _step_condition(checkout), (
            workflow,
            name,
        )
        for consumer in consumers:
            assert exported < job.index(consumer), (workflow, name, consumer)
            # GITHUB_PATH becomes effective only in subsequent steps.
            assert consumer not in provision


def test_other_publication_rebases_resync_before_replaying_new_checkout():
    expected_rebases = {
        "roll-docket.yml": 2,
        "prospect-docket.yml": 2,
        "mint-generation-ticket.yml": 2,
        "publish-attested.yml": 1,
    }
    for workflow, expected_count in expected_rebases.items():
        source = (ROOT / ".github" / "workflows" / workflow).read_text()
        rebases = source.split("git pull --rebase origin main")[1:]
        assert len(rebases) == expected_count, workflow
        for after_rebase in rebases:
            # No Python verification or build can run against a newly rebased
            # checkout while its dependency environment still uses the old lock.
            following_lines = after_rebase.lstrip().splitlines()
            assert following_lines[0].strip() == "uv sync --locked --extra custody"
