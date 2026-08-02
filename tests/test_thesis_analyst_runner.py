from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_thesis_analyst.py"
COMPARISON_GENERATOR = ROOT / "scripts" / "thesis_records_to_comparisons.py"
sys.path.insert(0, str(ROOT / "scripts"))
import median_rollout_ensemble as median_ensemble  # noqa: E402
import run_thesis_analyst as analyst_runner  # noqa: E402
from run_thesis_analyst import (  # noqa: E402
    interval_distribution,
)
from run_thesis_analyst import (  # noqa: E402
    ladder_distribution as runner_ladder_distribution,
)
from strategy_comparisons import (  # noqa: E402
    ladder_distribution as comparison_ladder_distribution,
)
from thesis_records_to_comparisons import comparison_run  # noqa: E402
from verify_custody import verify_run  # noqa: E402


def test_interval_distribution_matches_typescript_fixture():
    fixture = json.loads(
        (
            ROOT / "tests" / "fixtures" / "interval_anchor_v1_distribution.json"
        ).read_text()
    )
    materialized = interval_distribution(fixture["inputs"])
    actual_points = [
        {
            "value": f"{point['value']:.10f}",
            "probability": f"{point['probability']:.10f}",
        }
        for point in materialized["points"]
    ]

    assert fixture["source"].endswith("::buildNumericCdfFromInterval")
    assert materialized["pointCount"] == 201
    assert materialized["provenance"] == "interval_seeded"
    assert materialized["transformVersion"] == fixture["transformVersion"]
    assert actual_points == fixture["points"]


def test_runner_ladder_distribution_matches_strategy_builder():
    cell = {
        "pointEstimate": 5.0,
        "ciLow": 4.0,
        "ciHigh": 6.0,
        "thresholdLadder": {
            "thresholds": [3.0, 4.0, 5.0, 6.0, 7.0],
            "cumulativeProbabilities": [0.02, 0.1, 0.5, 0.9, 0.98],
        },
    }

    actual = runner_ladder_distribution(cell)
    expected = comparison_ladder_distribution(cell, 1)

    assert actual is not None
    assert expected is not None
    assert actual["points"] == expected["points"]
    assert actual["support"] == expected["support"]
    assert actual["provenance"] == "agent_reported"
    assert actual["transformVersion"] == "agent_cdf_v1"


def test_median3_requires_exactly_three_distinct_custody_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(median_ensemble, "verify_run", lambda _run_dir: None)

    def rollout(index: int, custody_root: str | None = None):
        run_dir = tmp_path / f"run-{index}"
        run_dir.mkdir()
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "custodyRootSha256": custody_root or f"root-{index}",
                }
            )
        )
        return {
            "manifestPath": str(manifest_path),
            "cell": {"runAt": f"2026-07-08T00:00:0{index}Z"},
        }

    valid = [rollout(1), rollout(2), rollout(3)]
    references = median_ensemble.validate_constituent_rollouts(valid)
    assert len(references) == 3
    assert len({ref["custodyRootSha256"] for ref in references}) == 3

    with pytest.raises(ValueError, match="exactly 3 constituent"):
        median_ensemble.validate_constituent_rollouts(valid[:2])
    with pytest.raises(ValueError, match="exactly 3 constituent"):
        median_ensemble.validate_constituent_rollouts([*valid, rollout(4)])

    duplicate = [rollout(5, "duplicate"), rollout(6, "duplicate"), rollout(7)]
    with pytest.raises(ValueError, match="3 distinct custody-verifiable"):
        median_ensemble.validate_constituent_rollouts(duplicate)


def test_comparison_run_preserves_median3_algorithm_metadata():
    constituent_runs = [
        {
            "manifestPath": f"records/run-{index}/manifest.json",
            "custodyRootSha256": f"root-{index}",
            "runAt": f"2026-07-08T00:00:0{index}Z",
        }
        for index in range(1, 4)
    ]
    manifest = {
        "promptMode": "median3",
        "aggregationAlgorithmVersion": "pointwise_median_cdf_v1",
        "constituentRuns": constituent_runs,
        "artifacts": [],
        "agent": {
            "agent": "thesis.analyst.median3",
            "model": "fixture-model",
        },
    }
    cell = {
        "runAt": "2026-07-08T01:00:00Z",
        "sourceContext": [],
        "pointEstimate": 1,
        "ciLow": 0,
        "ciHigh": 2,
        "confidence": 0.8,
        "drivers": [],
        "reasoning": [],
    }

    run = comparison_run(cell, manifest, "fixture", 1)

    assert (
        run["predictionRun"]["aggregationAlgorithmVersion"] == "pointwise_median_cdf_v1"
    )
    assert run["predictionRun"]["constituentRuns"] == constituent_runs


def test_print_prompt_contains_question_spec():
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "ons.labour.unemployment_rate",
            "--period",
            "2026-Q4",
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "# Question spec" in result.stdout
    assert "- series: ons.labour.unemployment_rate" in result.stdout
    assert "- period: 2026-Q4" in result.stdout
    assert "Produce one JSON cell per docs/cell-contract.md" in result.stdout
    assert "Default promoted practices" in result.stdout
    assert "outside-view base rate before current-news adjustments" in result.stdout


def test_fast_prompt_inlines_contract_and_allows_optional_repo_reads():
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "boe.bank_rate",
            "--period",
            "2026-06-18",
            "--prompt-mode",
            "fast",
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "# Thesis analyst fast public-release run" in result.stdout
    assert "You may inspect the local repository/workspace when useful" in (
        result.stdout
    )
    assert "This is optional, not required" in result.stdout
    assert "Treat prior forecasts as historical forecasts" in result.stdout
    assert "# Default promoted forecasting practices" in result.stdout
    assert "Anchor on the outside-view base rate before current-release" in (
        result.stdout
    )
    assert '"resolutionDate": "YYYY-MM-DD"' in result.stdout
    assert "Every tool step result must include at least one fetched numeric" in (
        result.stdout
    )
    assert "- series: boe.bank_rate" in result.stdout
    assert "Bank of England MPC" in result.stdout
    assert "docs/cell-contract.md" in result.stdout


def test_fast_prompt_includes_target_context():
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--prompt-mode",
            "fast",
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "canonical-ledger-slug",
                    "targetUnit": "percent",
                    "dataPointId": "test.ledger_series.2030_01.first_print",
                    "resolutionDate": "2030-02-15",
                }
            ),
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "# Canonical ledger target context" in result.stdout
    assert '- catalogSlug: "canonical-ledger-slug"' in result.stdout
    assert '- targetUnit: "percent"' in result.stdout
    assert '- resolutionDate: "2030-02-15"' in result.stdout


def test_mock_run_writes_activity_artifacts(tmp_path):
    out_dir = tmp_path / "run"
    generated_ts = tmp_path / "generated.ts"

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.synthetic_rate",
            "--period",
            "2030-01",
            "--mock-cell",
            "--out-dir",
            str(out_dir),
            "--write-ts",
            str(generated_ts),
            "--const-name",
            "GENERATED_TEST_CELLS",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    printed_manifest = json.loads(result.stdout)
    assert manifest["schemaVersion"] == "thesis_analyst_run_manifest_v1"
    assert printed_manifest["ok"] is True
    assert manifest["ok"] is True
    assert manifest["series"] == "test.synthetic_rate"
    assert manifest["period"] == "2030-01"
    assert manifest["promptMode"] == "full"

    artifact_types = {artifact["artifactType"] for artifact in manifest["artifacts"]}
    assert {
        "prompt",
        "command",
        "raw_response",
        "parsed_cell",
        "normalized_cell",
        "run_distribution",
        "validation_report",
        "manifest",
    }.issubset(artifact_types)

    for artifact in manifest["artifacts"]:
        path = ROOT / artifact["path"]
        if not path.exists():
            path = Path(artifact["path"])
        assert path.exists()
        assert artifact["sha256"]
        assert artifact["bytes"] > 0

    cells = json.loads((out_dir / "cells.with_activity.json").read_text())
    assert len(cells) == 1
    cell = cells[0]
    assert cell["slug"] == "test-synthetic-rate-2030-01"
    assert cell["predictionDistribution"] == json.loads(
        (out_dir / "distribution.json").read_text()
    )
    assert cell["predictionDistribution"]["pointCount"] == 201
    assert cell["predictionDistribution"]["provenance"] == "interval_seeded"
    assert cell["predictionDistribution"]["transformVersion"] == "interval_anchor_v1"
    assert cell["activityLog"]
    activity_types = {artifact["artifactType"] for artifact in cell["activityLog"]}
    assert {
        "prompt",
        "raw_response",
        "run_distribution",
        "validation_report",
    }.issubset(activity_types)
    assert manifest["validation"]["cells"][0]["ok"] is True
    generated_text = generated_ts.read_text()
    assert '"predictionDistribution"' in generated_text
    assert '"transformVersion": "interval_anchor_v1"' in generated_text


def test_target_context_validation_rejects_drift(tmp_path):
    out_dir = tmp_path / "target-context-run"
    response_path = tmp_path / "response.json"
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["slug"] = "canonical-ledger-slug"
    cell["unit"] = "percent"
    cell["dataPointId"] = "test.ledger_series.2030_01.first_print"
    cell["resolutionDate"] = "2030-02-28"
    response_path.write_text(json.dumps(cell))

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--response-file",
            str(response_path),
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "canonical-ledger-slug",
                    "targetUnit": "percent",
                    "dataPointId": "test.ledger_series.2030_01.first_print",
                    "resolutionDate": "2030-02-15",
                }
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    errors = manifest["validation"]["cells"][0]["errors"]
    assert any("resolutionDate" in error for error in errors)
    assert manifest["ok"] is False


def test_run_record_stamps_privileged_registration_binding(tmp_path):
    out_dir = tmp_path / "registration-bound-run"
    response_path = tmp_path / "response.json"
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["slug"] = "canonical-ledger-slug"
    cell["unit"] = "percent"
    cell["dataPointId"] = "test.ledger_series.2030_01.first_print"
    response_path.write_text(json.dumps(cell))
    binding = {
        "registrationCommit": "a" * 40,
        "targetContentHash": "b" * 64,
        "targetRegistrationPath": f"records/targets/2030-01-10-{'b' * 64}.json",
        "registeredAtUtc": "2030-01-10T12:00:00Z",
    }
    target_context = {
        "catalogSlug": cell["slug"],
        "targetUnit": cell["unit"],
        "dataPointId": cell["dataPointId"],
        **binding,
    }

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--response-file",
            str(response_path),
            "--target-context-json",
            json.dumps(target_context),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    [recorded_cell] = json.loads((out_dir / "cells.with_activity.json").read_text())
    assert json.loads(result.stdout)["ok"] is True
    assert manifest["targetContext"] == target_context
    assert manifest["runStartedAt"] == manifest["createdAt"]
    assert recorded_cell["runStartedAt"] == manifest["runStartedAt"]
    for field, value in binding.items():
        assert manifest[field] == value
        assert recorded_cell[field] == value


def test_target_context_validation_rejects_identity_unit_and_source_host_drift(
    tmp_path,
):
    out_dir = tmp_path / "target-binding-run"
    response_path = tmp_path / "response.json"
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["slug"] = "canonical-ledger-slug"
    cell["unit"] = "ratio"
    cell["dataPointId"] = "wrong.series.2030_01.first_print"
    cell["resolutionDate"] = "2030-02-15"
    cell["resolutionSourceUrl"] = "https://revision.example.com/rate"
    response_path.write_text(json.dumps(cell))

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--response-file",
            str(response_path),
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "canonical-ledger-slug",
                    "targetUnit": "percent",
                    "dataPointId": "test.ledger_series.2030_01.first_print",
                    "sourceBinding": {"sourceUrl": "https://official.example.gov/rate"},
                }
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    errors = json.loads((out_dir / "manifest.json").read_text())["validation"]["cells"][
        0
    ]["errors"]
    assert any("unit" in error and "target context" in error for error in errors)
    assert any("dataPointId" in error for error in errors)
    assert any("source binding host" in error for error in errors)


def test_target_context_validation_rejects_first_print_grace_exception(tmp_path):
    out_dir = tmp_path / "target-context-rule-run"
    response_path = tmp_path / "response.json"
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["slug"] = "canonical-ledger-slug"
    cell["unit"] = "percent"
    cell["dataPointId"] = "test.ledger_series.2030_01.first_print"
    cell["resolutionDate"] = "2030-02-15"
    cell["resolutionRule"] = (
        "Resolves to the first published official value for January 2030; "
        "same-day corrections before release day ends count."
    )
    response_path.write_text(json.dumps(cell))

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--response-file",
            str(response_path),
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "canonical-ledger-slug",
                    "targetUnit": "percent",
                    "dataPointId": "test.ledger_series.2030_01.first_print",
                    "resolutionDate": "2030-02-15",
                    "resolutionRule": (
                        "Resolves to the first published official value for "
                        "January 2030; later revisions do not count."
                    ),
                }
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    errors = manifest["validation"]["cells"][0]["errors"]
    assert any("correction/grace exception" in error for error in errors)
    assert manifest["ok"] is False


def test_fast_mock_run_records_prompt_mode(tmp_path):
    out_dir = tmp_path / "fast-run"

    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "boe.bank_rate",
            "--period",
            "2026-06-18",
            "--prompt-mode",
            "fast",
            "--mock-cell",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    prompt = (out_dir / "prompt.md").read_text()

    assert manifest["promptMode"] == "fast"
    assert "You may inspect the local repository/workspace when useful" in prompt
    assert "Do not modify files" in prompt


def test_command_start_failure_is_sealed_as_complete_failed_trace(tmp_path):
    out_dir = tmp_path / "command-start-failure"
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.start_failure",
            "--period",
            "2030-01",
            "--command",
            "/definitely/not/a/command",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    manifest = json.loads((out_dir / "manifest.json").read_text())
    command = json.loads((out_dir / "command.json").read_text())
    verification = verify_run(out_dir)
    assert command["returnCode"] == 127
    assert manifest["error"]["phase"] == "parse"
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is False
    assert verification.headline_eligible is False


def test_reviewer_start_failure_is_sealed_and_labeled_failed(tmp_path):
    out_dir = tmp_path / "review-start-failure"
    forecaster = tmp_path / "forecaster.py"
    forecaster.write_text(
        "import json, sys\n"
        "_prompt = sys.stdin.read()\n"
        f"print(json.dumps({review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)!r}))\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.review_start_failure",
            "--period",
            "2030-01",
            "--command",
            f"{shlex.quote(sys.executable)} {shlex.quote(str(forecaster))}",
            "--pre-submit-review-command",
            "/definitely/not/a/reviewer",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    manifest = json.loads((out_dir / "manifest.json").read_text())
    reviewer = json.loads((out_dir / "pre_submit_review_command.json").read_text())
    verification = verify_run(out_dir)
    assert reviewer["returnCode"] == 127
    assert manifest["preSubmitReview"]["status"] == "review_failed"
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is False
    assert verification.headline_eligible is False


def test_command_run_can_capture_pre_submit_review_loop(tmp_path):
    out_dir = tmp_path / "reviewed-run"
    forecaster_path = tmp_path / "forecaster.py"
    reviewer_path = tmp_path / "reviewer.py"
    draft_cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    final_cell = review_test_cell(
        point=5.2,
        ci_low=4.6,
        ci_high=5.9,
        review_disposition=(
            "Review disposition: accepted the reviewer request to make the "
            "interval source explicit and widened the upper tail by 0.1."
        ),
    )

    forecaster_path.write_text(
        "\n".join(
            [
                "import json, sys",
                f"draft = {json.dumps(draft_cell)!r}",
                f"final = {json.dumps(final_cell)!r}",
                "prompt = sys.stdin.read()",
                "print('model: gpt-5.5', file=sys.stderr)",
                "print(final if 'Pre-submit review loop' in prompt else draft)",
            ]
        )
    )
    reviewer_path.write_text(
        "\n".join(
            [
                "import json, sys",
                "_prompt = sys.stdin.read()",
                "print('model: gpt-5.5-reviewer', file=sys.stderr)",
                "print(json.dumps({",
                "  'summary': 'Draft is publishable after interval-source '",
                "    'clarification.',",
                "  'requiredFixes': [{",
                "    'rubricItem': 'interval',",
                "    'severity': 'warning',",
                "    'summary': 'Interval source should be explicit in the '",
                "      'public trace.',",
                "    'actionRequested': 'Name realized volatility or release '",
                "      'dispersion.'",
                "  }],",
                "  'optionalSuggestions': ['Keep the first-print resolver visible.']",
                "}))",
            ]
        )
    )

    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.reviewed_rate",
            "--period",
            "2030-01",
            "--command",
            (
                f"{shlex.quote(sys.executable)} "
                f"{shlex.quote(str(forecaster_path))} "
                "--model gpt-5.5"
            ),
            "--pre-submit-review-command",
            (
                f"{shlex.quote(sys.executable)} "
                f"{shlex.quote(str(reviewer_path))} "
                "--model gpt-5.5-reviewer"
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    cells = json.loads((out_dir / "cells.with_activity.json").read_text())
    artifact_types = {artifact["artifactType"] for artifact in manifest["artifacts"]}

    assert manifest["ok"] is True
    assert manifest["preSubmitReview"]["status"] == "completed"
    assert manifest["preSubmitReview"]["reviewer"]["model"] == "gpt-5.5-reviewer"
    assert manifest["preSubmitReview"]["findings"][0]["rubricItem"] == "interval"
    assert manifest["preSubmitReview"]["dispositions"][0]["decision"] == "accepted"
    assert {
        "draft_forecast",
        "review_prompt",
        "pre_submit_review",
        "revision_prompt",
        "raw_response",
    }.issubset(artifact_types)
    assert cells[0]["pointEstimate"] == 5.2
    assert cells[0]["preSubmitReview"]["status"] == "completed"
    assert any(
        step.get("text", "").startswith("Review disposition:")
        for step in cells[0]["reasoning"]
        if isinstance(step, dict)
    )
    assert (out_dir / "draft_stdout.txt").exists()
    assert (out_dir / "pre_submit_review_stdout.txt").exists()
    assert (out_dir / "revision_prompt.md").exists()


def test_codex_model_run_captures_full_codex_trace(tmp_path):
    out_dir = tmp_path / "codex-run"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "fake_codex.py"
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)

    fake_codex.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                "args = sys.argv[1:]",
                "last_message = pathlib.Path(args[args.index('-o') + 1])",
                "model = args[args.index('-m') + 1]",
                f"text = {json.dumps(json.dumps(cell))}",
                "last_message.write_text(text)",
                "print(json.dumps({",
                "  'type': 'item.completed',",
                "  'item': {'type': 'agent_message', 'text': text}",
                "}))",
                "print(json.dumps({",
                "  'type': 'turn.completed',",
                "  'usage': {",
                "    'input_tokens': 10,",
                "    'output_tokens': 5,",
                "    'cached_input_tokens': 2",
                "  }",
                "}))",
                "print(f'model: {model}', file=sys.stderr)",
            ]
        )
    )
    fake_codex.chmod(0o755)

    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }

    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    command = json.loads((out_dir / "command.json").read_text())
    cells = json.loads((out_dir / "cells.with_activity.json").read_text())
    artifact_types = {artifact["artifactType"] for artifact in manifest["artifacts"]}

    assert manifest["ok"] is True
    assert manifest["agent"]["model"] == "gpt-5.5"
    assert cells[0]["model"] == "gpt-5.5"
    assert command["argv"][-1] == "<prompt>"
    assert "--search" in command["argv"]
    assert "--ignore-user-config" in command["argv"]
    assert {
        "codex_stdout_jsonl",
        "codex_stderr_log",
        "codex_events_jsonl",
        "codex_last_message",
        "codex_trace",
        "stdout",
    }.issubset(artifact_types)
    trace = json.loads((out_dir / "codex_trace.json").read_text())
    assert trace["auth"] == "codex-cli-subscription"
    assert trace["backend"] == "codex-exec"
    assert trace["model"] == "gpt-5.5"
    assert trace["usage"]["input_tokens"] == 10
    assert (out_dir / "codex_events.jsonl").read_text().count("\n") == 2


def write_fake_codex(
    path: Path, cell: dict, extra_lines: list[str] | None = None
) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                "args = sys.argv[1:]",
                "last_message = pathlib.Path(args[args.index('-o') + 1])",
                f"text = {json.dumps(json.dumps(cell))}",
                *(extra_lines or []),
                "last_message.write_text(text)",
                "print(json.dumps({",
                "  'type': 'item.completed',",
                "  'item': {'type': 'agent_message', 'text': text}",
                "}))",
                "print(json.dumps({",
                "  'type': 'turn.completed',",
                "  'usage': {",
                "    'input_tokens': 10,",
                "    'output_tokens': 5,",
                "    'cached_input_tokens': 2",
                "  }",
                "}))",
            ]
        )
    )
    path.chmod(0o755)


def test_codex_network_requires_workspace_write_sandbox(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--codex-network",
            "--out-dir",
            str(tmp_path / "run"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "workspace-write" in completed.stderr


def test_codex_network_run_records_grant_and_clean_guard(tmp_path):
    out_dir = tmp_path / "codex-network-run"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "fake_codex.py"
    write_fake_codex(
        fake_codex, review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    )

    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }
    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--codex-sandbox",
            "workspace-write",
            "--codex-network",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    command = json.loads((out_dir / "command.json").read_text())
    argv = command["argv"]
    assert manifest["ok"] is True
    assert command["networkAccess"] is True
    assert command["workspaceMutations"] == []
    assert "sandbox_workspace_write.network_access=true" in argv
    assert argv[argv.index("-s") + 1] == "workspace-write"
    assert manifest["workspaceHygiene"] == {"guarded": True, "mutations": []}
    trace = json.loads((out_dir / "codex_trace.json").read_text())
    assert trace["networkAccess"] is True
    assert trace["sandbox"] == "workspace-write"
    assert "Outbound network access is enabled" in (
        out_dir / "prompt.md"
    ).read_text()


def test_codex_network_run_fails_closed_on_workspace_mutation(tmp_path):
    out_dir = tmp_path / "codex-mutating-run"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "fake_codex.py"
    write_fake_codex(
        fake_codex,
        review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8),
        extra_lines=[
            "run_dir = last_message.parent",
            "(run_dir / 'planted.txt').write_text('agent wrote this')",
            "prompt_md = run_dir / 'prompt.md'",
            "prompt_md.write_text(prompt_md.read_text() + 'tampered')",
        ],
    )

    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--codex-sandbox",
            "workspace-write",
            "--codex-network",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    manifest = json.loads((out_dir / "manifest.json").read_text())
    command = json.loads((out_dir / "command.json").read_text())
    assert manifest["ok"] is False
    mutations = command["workspaceMutations"]
    assert any("planted.txt" in mutation for mutation in mutations)
    assert any("prompt.md" in mutation for mutation in mutations)
    assert manifest["workspaceHygiene"]["guarded"] is True
    assert manifest["workspaceHygiene"]["mutations"] == mutations


def test_fast_prompt_network_note_is_gated_and_census_notes_name_endpoint():
    series = "census.acs.broadband_subscription_65_plus.share"
    prompt_with, _ = analyst_runner.build_run_prompt(
        series, "2025", None, "fast", None, network_tools=True
    )
    prompt_without, _ = analyst_runner.build_run_prompt(
        series, "2025", None, "fast", None
    )
    assert "Outbound network access is enabled" in prompt_with
    assert "Outbound network access is enabled" not in prompt_without
    for prompt in (prompt_with, prompt_without):
        assert "data.census.gov/api/access/" in prompt
        assert "ACSDT1Y" in prompt
        assert "api.census.gov requires an API key" in prompt


def review_test_cell(
    *,
    point: float,
    ci_low: float,
    ci_high: float,
    review_disposition: str | None = None,
) -> dict:
    reasoning = [
        {"kind": "heading", "text": "Reviewed synthetic rate forecast"},
        {
            "kind": "text",
            "text": (
                "The first-print resolver is the official synthetic January "
                "2030 release on 2030-01-15."
            ),
        },
        {
            "kind": "tool",
            "tool": "official.lookup",
            "call": "official.lookup(series='test.reviewed_rate')",
            "result": "Fetched t-3 4.9, t-2 5.0, t-1 5.2.",
        },
        {
            "kind": "tool",
            "tool": "calendar.lookup",
            "call": "calendar.lookup(series='test.reviewed_rate')",
            "result": "Fetched release date 2030-01-15 from official calendar.",
        },
        {
            "kind": "tool",
            "tool": "volatility.lookup",
            "call": "volatility.lookup(series='test.reviewed_rate')",
            "result": "Fetched first-print absolute errors 0.2, 0.3, 0.4.",
        },
        {
            "kind": "text",
            "text": (
                "Base rate prior from the reference class of the last 3 "
                "prints is the recent center near 5.1 before the small "
                "current-release adjustment."
            ),
        },
        {
            "kind": "math",
            "text": (
                f"Point {point} uses the recent center plus a 0.1 update; "
                f"realized dispersion sigma = 0.45, so the 80% interval "
                f"[{ci_low}, {ci_high}] is point \u00b1 1.28 \u00d7 sigma."
            ),
        },
        {
            "kind": "text",
            "text": (
                "Outside the interval if the synthetic release breaks from "
                "recent first-print dispersion."
            ),
        },
        {"kind": "forecast", "point": point, "ciLow": ci_low, "ciHigh": ci_high},
    ]
    if review_disposition:
        reasoning.insert(7, {"kind": "text", "text": review_disposition})
    return {
        "slug": "test-reviewed-rate-2030-01",
        "country": "US",
        "type": "data",
        "title": "Reviewed synthetic rate forecast",
        "question": (
            "What will the first-print value of the reviewed synthetic rate "
            "be for January 2030?"
        ),
        "unit": "percent",
        "pointEstimate": point,
        "ciLow": ci_low,
        "ciHigh": ci_high,
        "confidence": 0.8,
        "resolutionDate": "2030-01-15",
        "resolutionSource": "Official synthetic release",
        "resolutionSourceUrl": "https://example.com/reviewed-rate",
        "resolutionRule": (
            "Resolves to the first official synthetic release value for "
            "January 2030; later revisions do not count."
        ),
        "dataPointId": "test.reviewed_rate.january_2030.first_print",
        "historicalContext": [
            {"label": "t-3", "value": 4.9},
            {"label": "t-2", "value": 5.0},
            {"label": "t-1", "value": 5.2},
        ],
        "drivers": [
            "recent reference class",
            "reviewed interval calibration",
            "synthetic release volatility",
        ],
        "sourceContext": [
            "https://example.com/reviewed-rate",
            "https://example.com/reviewed-rate-calendar",
        ],
        "runAt": "2026-06-17T12:00:00Z",
        "reasoning": reasoning,
    }


def test_collision_exclusion_ignores_only_the_exact_generated_wave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_data = tmp_path / "site" / "src" / "data"
    examples = site_data / "forecast-examples"
    examples.mkdir(parents=True)
    (site_data / "forecast-cells.ts").write_text("export {};\n")
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    own_wave = examples / "auto-2030-01-10-deadbeef.ts"
    own_wave.write_text(f'export const wave = [{{ slug: "{cell["slug"]}" }}];\n')
    monkeypatch.setattr(analyst_runner, "ROOT", tmp_path)

    blocked = analyst_runner.validate_cells([cell])
    assert any(
        "slug collides" in error
        for error in blocked["cells"][0]["errors"]
    )

    allowed = analyst_runner.validate_cells(
        [cell], collision_exclusion=own_wave
    )
    assert allowed["ok"] is True

    (examples / "competing-wave.ts").write_text(
        f'export const wave = [{{ slug: "{cell["slug"]}" }}];\n'
    )
    still_blocked = analyst_runner.validate_cells(
        [cell], collision_exclusion=own_wave
    )
    assert any(
        "slug collides" in error
        for error in still_blocked["cells"][0]["errors"]
    )


def test_command_model_override_is_stamped_in_manifest_and_cells(tmp_path):
    out_dir = tmp_path / "model-run"
    response_path = tmp_path / "response.json"
    response_path.write_text(
        json.dumps(
            [
                {
                    "slug": "test-runtime-model-2030-01",
                    "country": "US",
                    "type": "data",
                    "title": "Runtime model test forecast",
                    "question": (
                        "What will the first-print value of the synthetic "
                        "runtime-model test series be for January 2030?"
                    ),
                    "unit": "percent",
                    "pointEstimate": 5.1,
                    "ciLow": 4.7,
                    "ciHigh": 5.8,
                    "confidence": 0.8,
                    "resolutionDate": "2030-01-15",
                    "resolutionSource": "Official synthetic release",
                    "resolutionSourceUrl": "https://example.com/runtime-model",
                    "resolutionRule": (
                        "Resolves to the first official synthetic release "
                        "value for January 2030; later revisions do not count."
                    ),
                    "dataPointId": "test.runtime_model.january_2030.first_print",
                    "historicalContext": [
                        {"label": "t-3", "value": 4.9},
                        {"label": "t-2", "value": 5.0},
                        {"label": "t-1", "value": 5.2},
                    ],
                    "drivers": [
                        "recent reference class",
                        "stable monthly series",
                        "synthetic release volatility",
                    ],
                    "sourceContext": [
                        "https://example.com/runtime-model",
                        "https://example.com/runtime-model-calendar",
                    ],
                    "runAt": "2026-06-17T10:00:00Z",
                    "reasoning": [
                        {"kind": "heading", "text": "Runtime model forecast"},
                        {
                            "kind": "text",
                            "text": (
                                "The base-rate reference class is the last "
                                "three synthetic prints around 5.0 percent."
                            ),
                        },
                        {
                            "kind": "tool",
                            "tool": "official.lookup",
                            "call": "lookup synthetic latest values",
                            "result": "Fetched t-3 4.9, t-2 5.0, t-1 5.2.",
                        },
                        {
                            "kind": "tool",
                            "tool": "calendar.lookup",
                            "call": "lookup synthetic release date",
                            "result": "Fetched release date 2030-01-15.",
                        },
                        {
                            "kind": "math",
                            "text": (
                                "Center on the 5.1 recent mean; sigma = "
                                "0.43 so 1.28 \u00d7 sigma gives the 80% "
                                "interval from 4.7 to 5.8."
                            ),
                        },
                        {
                            "kind": "text",
                            "text": (
                                "Outside the interval if the synthetic series "
                                "breaks from its recent stable pattern."
                            ),
                        },
                        {
                            "kind": "forecast",
                            "point": 5.1,
                            "ciLow": 4.7,
                            "ciHigh": 5.8,
                        },
                    ],
                }
            ]
        )
    )

    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.runtime_model",
            "--period",
            "2030-01",
            "--command",
            (
                f"{sys.executable} -c 'import pathlib, sys; "
                "print(pathlib.Path(sys.argv[1]).read_text())' "
                f"{response_path} --model gpt-5.5"
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    cells = json.loads((out_dir / "cells.with_activity.json").read_text())

    assert manifest["agent"]["model"] == "gpt-5.5"
    assert manifest["agent"]["configuredModel"] == "claude-fable-5"
    assert cells[0]["model"] == "gpt-5.5"


def test_command_timeout_writes_failure_manifest(tmp_path):
    out_dir = tmp_path / "timeout-run"
    binding = {
        "registrationCommit": "c" * 40,
        "targetContentHash": "d" * 64,
        "targetRegistrationPath": f"records/targets/2030-01-10-{'d' * 64}.json",
        "registeredAtUtc": "2030-01-10T12:00:00Z",
    }

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.synthetic_rate",
            "--period",
            "2030-01",
            "--command",
            f"{sys.executable} -c 'import time; time.sleep(2)'",
            "--timeout-seconds",
            "1",
            "--target-context-json",
            json.dumps(binding),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    command = json.loads((out_dir / "command.json").read_text())
    manifest = json.loads((out_dir / "manifest.json").read_text())
    error = json.loads((out_dir / "error.json").read_text())

    assert command["returnCode"] == 124
    assert command["timedOut"] is True
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "parse"
    assert error["command"]["timedOut"] is True
    assert manifest["targetContext"] == binding
    assert manifest["runStartedAt"] == manifest["createdAt"]
    for field, value in binding.items():
        assert manifest[field] == value


def test_comparison_generator_maps_and_scales_claims_record(tmp_path):
    record_dir = tmp_path / "record"
    record_dir.mkdir()
    cells_path = record_dir / "cells.with_activity.json"
    command_path = record_dir / "command.json"
    manifest_path = record_dir / "manifest.json"
    out_ts = tmp_path / "live-comparisons.ts"

    command_path.write_text(
        json.dumps({"argv": ["codex", "exec", "-m", "gpt-5.5", "-"]})
    )
    cells_path.write_text(
        json.dumps(
            [
                {
                    "slug": ("us-dol-initial-claims-sa-week-2026-06-13-first-print"),
                    "pointEstimate": 225000,
                    "ciLow": 209000,
                    "ciHigh": 243000,
                    "confidence": 0.8,
                    "drivers": ["latest print rose to 229000"],
                    "sourceContext": ["https://www.dol.gov/ui/data.pdf"],
                    "runAt": "2026-06-16T12:33:22Z",
                    "reasoning": [
                        {"kind": "heading", "text": "Claims"},
                        {
                            "kind": "forecast",
                            "point": 225000,
                            "ciLow": 209000,
                            "ciHigh": 243000,
                        },
                    ],
                }
            ]
        )
    )
    manifest_path.write_text(
        json.dumps(
            {
                "ok": True,
                "promptMode": "fast",
                "cellsPath": str(cells_path),
                "agent": {
                    "agent": "thesis.analyst",
                    "model": "claude-fable-5",
                    "agentVersion": "2.0.0",
                    "promptHash": "prompt-hash",
                    "toolPolicyHash": "tool-hash",
                },
                "artifacts": [
                    {
                        "artifactType": "command",
                        "path": str(command_path),
                        "sha256": "abc",
                        "bytes": 1,
                        "createdAt": "2026-06-16T12:33:11Z",
                    }
                ],
            }
        )
    )

    subprocess.run(
        [
            sys.executable,
            str(COMPARISON_GENERATOR),
            str(out_ts),
            "LIVE_RUNS",
            str(manifest_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    output = out_ts.read_text()
    assert '"initial-claims-week-2026-06-13"' in output
    assert '"pointEstimate": 225' in output
    assert '"ciLow": 209' in output
    assert '"model": "gpt-5.5"' in output
    assert '"promptMode": "fast"' in output


def test_comparison_generator_uses_batch_manifest_catalog_slug(tmp_path):
    record_dir = tmp_path / "record"
    record_dir.mkdir()
    cells_path = record_dir / "cells.with_activity.json"
    command_path = record_dir / "command.json"
    manifest_path = record_dir / "manifest.json"
    batch_manifest_path = tmp_path / "batch.json"
    out_ts = tmp_path / "live-comparisons.ts"

    command_path.write_text(
        json.dumps({"argv": ["codex", "exec", "-m", "gpt-5.5", "-"]})
    )
    cells_path.write_text(
        json.dumps(
            [
                {
                    "slug": "agent-emitted-near-duplicate-slug",
                    "pointEstimate": 4.2,
                    "ciLow": 3.6,
                    "ciHigh": 4.8,
                    "confidence": 0.8,
                    "drivers": ["official monthly indicator is noisy"],
                    "sourceContext": ["https://www.abs.gov.au/statistics"],
                    "runAt": "2026-06-17T02:10:00Z",
                    "reasoning": [
                        {"kind": "heading", "text": "ABS CPI"},
                        {
                            "kind": "forecast",
                            "point": 4.2,
                            "ciLow": 3.6,
                            "ciHigh": 4.8,
                        },
                    ],
                }
            ]
        )
    )
    manifest_path.write_text(
        json.dumps(
            {
                "ok": True,
                "promptMode": "fast",
                "cellsPath": str(cells_path),
                "agent": {
                    "agent": "thesis.analyst",
                    "model": "claude-fable-5",
                    "agentVersion": "2.0.0",
                    "promptHash": "prompt-hash",
                    "toolPolicyHash": "tool-hash",
                },
                "artifacts": [
                    {
                        "artifactType": "command",
                        "path": str(command_path),
                        "sha256": "abc",
                        "bytes": 1,
                        "createdAt": "2026-06-17T02:10:00Z",
                    }
                ],
            }
        )
    )
    batch_manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_batch_manifest_v1",
                "results": [
                    {
                        "ok": True,
                        "manifestPath": str(manifest_path),
                        "target": {
                            "series": "abs.cpi.all_groups.yoy",
                            "period": "2026-05",
                            "catalogSlug": "australia-cpi-annual-rate-may-2026",
                        },
                    }
                ],
            }
        )
    )

    subprocess.run(
        [
            sys.executable,
            str(COMPARISON_GENERATOR),
            str(out_ts),
            "LIVE_RUNS",
            str(manifest_path),
            "--batch-manifest",
            str(batch_manifest_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    output = out_ts.read_text()
    assert '"australia-cpi-annual-rate-may-2026"' in output
    assert '"agent-emitted-near-duplicate-slug"' not in output
    assert '"pointEstimate": 4.2' in output


def test_comparison_generator_does_not_rescale_matching_target_unit(tmp_path):
    record_dir = tmp_path / "record"
    record_dir.mkdir()
    cells_path = record_dir / "cells.with_activity.json"
    command_path = record_dir / "command.json"
    manifest_path = record_dir / "manifest.json"
    batch_manifest_path = tmp_path / "batch.json"
    out_ts = tmp_path / "live-comparisons.ts"

    command_path.write_text(
        json.dumps({"argv": ["codex", "exec", "-m", "gpt-5.5", "-"]})
    )
    cells_path.write_text(
        json.dumps(
            [
                {
                    "slug": "us-dol-initial-claims-sa-week-2026-06-20",
                    "unit": "thousands",
                    "pointEstimate": 225,
                    "ciLow": 208,
                    "ciHigh": 243,
                    "confidence": 0.8,
                    "drivers": ["latest print was 245 thousand"],
                    "sourceContext": ["https://www.dol.gov/ui/data.pdf"],
                    "runAt": "2026-06-21T15:11:54Z",
                    "reasoning": [
                        {"kind": "heading", "text": "Claims"},
                        {
                            "kind": "forecast",
                            "point": 225,
                            "ciLow": 208,
                            "ciHigh": 243,
                        },
                    ],
                }
            ]
        )
    )
    manifest_path.write_text(
        json.dumps(
            {
                "ok": True,
                "promptMode": "fast",
                "cellsPath": str(cells_path),
                "agent": {
                    "agent": "thesis.analyst",
                    "model": "gpt-5.5",
                    "agentVersion": "2.0.0",
                    "promptHash": "prompt-hash",
                    "toolPolicyHash": "tool-hash",
                },
                "artifacts": [
                    {
                        "artifactType": "command",
                        "path": str(command_path),
                        "sha256": "abc",
                        "bytes": 1,
                        "createdAt": "2026-06-21T15:11:48Z",
                    }
                ],
            }
        )
    )
    batch_manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_batch_manifest_v1",
                "results": [
                    {
                        "ok": True,
                        "manifestPath": str(manifest_path),
                        "target": {
                            "series": "us.dol.initial_claims.sa",
                            "period": "week_2026-06-20",
                            "catalogSlug": "initial-claims-week-2026-06-20",
                            "valueScale": 0.001,
                            "targetUnit": "thousands",
                        },
                    }
                ],
            }
        )
    )

    subprocess.run(
        [
            sys.executable,
            str(COMPARISON_GENERATOR),
            str(out_ts),
            "LIVE_RUNS",
            str(manifest_path),
            "--batch-manifest",
            str(batch_manifest_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    output = out_ts.read_text()
    assert '"initial-claims-week-2026-06-20"' in output
    assert '"pointEstimate": 225' in output
    assert '"ciLow": 208' in output
    assert '"pointEstimate": 0.225' not in output


def test_pin_comparison_contract_pins_resolver_but_not_units() -> None:
    from run_thesis_analyst import pin_comparison_contract

    context = {
        "comparisonTarget": True,
        "catalogSlug": "australia-cpi-annual-rate-july-2026",
        "country": "AU",
        "resolutionDate": "2026-08-26",
        "resolutionSource": "Australian Bureau of Statistics",
        "resolutionSourceUrl": "https://www.abs.gov.au/statistics",
        "resolutionRule": "First print of the all groups CPI annual rate.",
        "targetUnit": "percent",
    }
    cell = {
        "slug": "abs-cpi-all-groups-yoy-2026-07",
        "country": "AU",
        "unit": "index points",
        "resolutionDate": "2026-08-27",
        "resolutionSource": "ABS",
        "resolutionSourceUrl": "https://www.abs.gov.au/other",
        "resolutionRule": "First print, unless corrected the same day.",
    }
    pin_comparison_contract(cell, context)
    assert cell["slug"] == context["catalogSlug"]
    assert cell["resolutionDate"] == context["resolutionDate"]
    assert cell["resolutionSource"] == context["resolutionSource"]
    assert cell["resolutionSourceUrl"] == context["resolutionSourceUrl"]
    assert cell["resolutionRule"] == context["resolutionRule"]
    assert cell["unit"] == "index points"

    unpinned = {"slug": "model-slug", "resolutionRule": "model words"}
    pin_comparison_contract(unpinned, {**context, "comparisonTarget": False})
    pin_comparison_contract(unpinned, None)
    assert unpinned == {"slug": "model-slug", "resolutionRule": "model words"}


def _find_negative_zeros(value, path="$"):
    import math

    hits = []
    if isinstance(value, float):
        if value == 0.0 and math.copysign(1.0, value) < 0:
            hits.append(path)
    elif isinstance(value, dict):
        for key, item in value.items():
            hits.extend(_find_negative_zeros(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_find_negative_zeros(item, f"{path}[{index}]"))
    return hits


def test_signed_zeros_never_reach_sealed_artifacts(tmp_path: Path) -> None:
    # An agent may legitimately forecast "-0.0" (zero approached from below).
    # Python's json keeps the sign while JSON.stringify drops it, so a signed
    # zero anywhere in a sealed record splits the Python-written sidecars from
    # the regenerated TS surfaces. The intake normalizer must scrub it.
    from normalize_spawn_json import scrub_signed_zeros

    payload = {
        "pointEstimate": -0.0,
        "ciLow": -0.1,
        "ciHigh": 0.1,
        "thresholdLadder": {
            "thresholds": [-0.1, -0.0, 0.1],
            "cumulativeProbabilities": [0.1, 0.5, 0.9],
        },
        "historicalContext": [{"label": "May 2026", "value": -0.0}],
        "count": 30,
    }
    scrubbed = scrub_signed_zeros(payload)
    assert _find_negative_zeros(scrubbed) == []
    # Ints and ordinary floats pass through untouched.
    assert scrubbed["count"] == 30 and isinstance(scrubbed["count"], int)
    assert scrubbed["ciLow"] == -0.1

    cell = {
        "pointEstimate": -0.0,
        "ciLow": -0.1,
        "ciHigh": 0.1,
    }
    interval = analyst_runner.interval_distribution(cell)
    assert _find_negative_zeros(interval) == []

    ladder_cell = {
        **cell,
        "thresholdLadder": {
            "thresholds": [-0.2, -0.0, 0.2],
            "cumulativeProbabilities": [0.1, 0.5, 0.9],
        },
    }
    ladder = analyst_runner.ladder_distribution(ladder_cell)
    assert ladder is not None
    assert _find_negative_zeros(ladder) == []

    assert json.dumps(analyst_runner.round_distribution_number(-0.0)) == "0.0"
    assert analyst_runner.unsign_zero(240) == 240
    assert isinstance(analyst_runner.unsign_zero(240), int)


def test_ladder_v2_prompt_swaps_the_derivation_contract() -> None:
    meta = {
        "agent": "thesis.analyst",
        "agentVersion": "1.0.0",
        "promptHash": "a" * 64,
        "toolPolicyHash": "b" * 64,
        "model": "gpt-5.5",
    }
    v1 = analyst_runner.build_ladder_prompt("s", "2026-07", None, meta)
    v2 = analyst_runner.build_ladder_v2_prompt("s", "2026-07", None, meta)

    # v1 keeps the parametric discipline; v2 replaces it with the
    # quantile-native contract and never demands the sigma idiom.
    assert 'sigma = X' in v1 and "1.28*sigma" in v1
    assert 'sigma = X' not in v2 and "1.28*sigma" not in v2
    assert "10th percentile at X" in v2
    assert "90th percentile at Z" in v2
    assert "promptMode ladder_v2" in v2
    # Both elicit the identical ladder mechanics.
    for phrase in (
        "11-15 strictly increasing thresholds",
        "'P(X <= t) = p' pairs",
        "thresholdLadder",
    ):
        assert phrase in v1 and phrase in v2

    prompt, run_meta = analyst_runner.build_run_prompt(
        "s", "2026-07", None, "ladder_v2"
    )
    assert run_meta["agent"] == "thesis.analyst.ladder_v2"
    assert "promptMode ladder_v2" in prompt


def test_canonical_steps_are_stripped_to_contract_keys(tmp_path: Path) -> None:
    # A forecast step decorated with commentary text broke the typed publish
    # build (2026-07-15 APEL wave): canonical kinds must keep only the
    # contract's keys.
    from normalize_spawn_json import norm_steps

    cell = {
        "pointEstimate": 5,
        "ciLow": 4,
        "ciHigh": 6,
        "reasoning": [
            {"kind": "math", "text": "sigma = 1", "confidence": 0.9},
            {
                "kind": "tool",
                "tool": "data.fetch",
                "call": "GET x",
                "result": "42",
                "url": "https://example.gov",
            },
            {
                "kind": "forecast",
                "point": 5,
                "ciLow": 4,
                "ciHigh": 6,
                "text": "final answer commentary",
            },
        ],
    }
    steps = norm_steps(cell)
    assert steps[0] == {"kind": "math", "text": "sigma = 1"}
    assert steps[1] == {
        "kind": "tool",
        "tool": "data.fetch",
        "call": "GET x",
        "result": "42",
    }
    assert steps[2] == {"kind": "forecast", "point": 5, "ciLow": 4, "ciHigh": 6}


def test_history_anchor_gate_passes_matching_values() -> None:
    cell = {
        "historicalContext": [
            {"label": "2023 ACS 1-year U.S. B28005 65+ broadband share", "value": 86.5},
            {
                "label": "2024 ACS 1-year U.S. B28005 65+ broadband share",
                "value": 88.24,
            },
            {"label": "2024 ACS all-household broadband share", "value": 91.0},
        ]
    }
    errors = analyst_runner.history_anchor_errors(
        cell, {"anchors": {"2023": 86.5, "2024": 88.2}}
    )
    assert errors == []


def test_history_anchor_gate_refuses_wrong_vintage() -> None:
    # The corrupted lineage: 5-year values labeled as the 1-year series.
    cell = {
        "historicalContext": [
            {"label": "2024 ACS 1-year U.S. B28005 65+ broadband share", "value": 84.8},
        ]
    }
    errors = analyst_runner.history_anchor_errors(
        cell, {"anchors": {"2024": 88.2}}
    )
    assert len(errors) == 1
    assert "contradict" in errors[0] and "88.2" in errors[0]


def test_history_anchor_gate_requires_anchored_periods() -> None:
    cell = {"historicalContext": [{"label": "2022 share", "value": 84.8}]}
    errors = analyst_runner.history_anchor_errors(
        cell, {"anchors": {"2024": 88.2}}
    )
    assert len(errors) == 1 and "no historicalContext entry" in errors[0]


def test_history_anchor_gate_flows_through_target_context_validation() -> None:
    cell = {
        "historicalContext": [{"label": "2024 first print", "value": 84.8}],
    }
    errors = analyst_runner.target_context_validation_errors(
        cell, {"anchors": {"2024": 88.2}}
    )
    assert any("anchor" in error for error in errors)


def _quantile_cell(ladder: object) -> dict:
    return {
        "pointEstimate": 100.0,
        "ciLow": 90.0,
        "ciHigh": 110.0,
        "thresholdLadder": ladder,
    }


def test_declared_ladder_must_promote_or_fail_closed() -> None:
    # A cell that DECLARES a quantile contract but carries a malformed ladder
    # must fail promotion, not silently degrade to the interval_seeded CDF
    # (which both mislabels provenance and re-derives a distribution the run
    # already authored).
    malformed = _quantile_cell({"thresholds": [90.0, 100.0]})  # missing probs
    with pytest.raises(ValueError, match="thresholdLadder"):
        analyst_runner.materialize_run_distributions([malformed])


def test_wellformed_ladder_still_promotes_agent_reported() -> None:
    cell = _quantile_cell(
        {
            "thresholds": [90.0, 100.0, 110.0],
            "cumulativeProbabilities": [0.1, 0.5, 0.9],
        }
    )
    distribution = analyst_runner.materialize_run_distributions([cell])
    assert distribution["provenance"] == "agent_reported"


def test_cell_without_ladder_keeps_interval_path() -> None:
    cell = {"pointEstimate": 100.0, "ciLow": 90.0, "ciHigh": 110.0}
    distribution = analyst_runner.materialize_run_distributions([cell])
    assert distribution["provenance"] == "interval_seeded"
