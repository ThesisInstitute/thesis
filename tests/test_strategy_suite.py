from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import pytest
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_strategy_suite as suite_runner  # noqa: E402


def test_bounded_suite_requires_pinned_selection_ledger(tmp_path) -> None:
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_strategy_selection_v1",
                "request": {"suite": "ladder"},
                "targets": [{"resolutionDateBasis": "resolve-by-bound"}],
            }
        )
    )
    with pytest.raises(
        suite_runner.StrategySuiteError, match="pinned selection ledger"
    ):
        suite_runner.run_suite(
            selection_path=selection,
            run_id=123,
            run_attempt=1,
            output_path=None,
            model="gpt-5.5",
            timeout_seconds=1,
        )


def test_suite_runner_emits_exact_lane_inventory(tmp_path, monkeypatch) -> None:
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    selection_path = tmp_path / "strategy-targets.json"
    selection = {
        "schemaVersion": "thesis_strategy_selection_v1",
        "sourceSha": source_sha,
        "selectedAtUtc": "2030-01-01T00:00:00Z",
        "selectionPath": (
            "records/thesis-analyst/strategy-selections/2030-01-01/"
            "strategy-123-a1.json"
        ),
        "selectionSetHash": "a" * 64,
        "request": {"suite": "both"},
        "targets": [{"catalogSlug": "fixture-target"}],
    }
    selection_path.write_text(json.dumps(selection) + "\n")

    batches: list[tuple[str, bool]] = []

    def fake_batch(**kwargs):
        batches.append((kwargs["prompt_mode"], kwargs["reviewed"]))
        return {
            "schemaVersion": "thesis_batch_manifest_v1",
            "results": [
                {
                    "ok": True,
                    "target": {"catalogSlug": "fixture-target"},
                }
            ],
        }

    monkeypatch.setattr(suite_runner, "run_batch", fake_batch)
    monkeypatch.setattr(
        suite_runner,
        "derive_medians",
        lambda targets, rollouts: [
            {
                "catalogSlug": targets[0]["catalogSlug"],
                "ok": True,
                "manifestPath": "records/derived/manifest.json",
                "error": None,
            }
        ],
    )
    monkeypatch.setattr(
        suite_runner,
        "batch_path",
        lambda day, run_id, attempt, lane: tmp_path / f"{lane}.json",
    )
    output = tmp_path / "strategy-suites" / "2030-01-02" / "strategy-123-a1.json"
    monkeypatch.setattr(
        suite_runner,
        "suite_path",
        lambda day, run_id, attempt: output,
    )
    monkeypatch.setattr(
        suite_runner,
        "repo_relative",
        lambda path: f"records/fixture/{path.name}",
    )
    monkeypatch.setattr(suite_runner, "utc_now", lambda: "2030-01-02T00:00:00Z")

    payload = suite_runner.run_suite(
        selection_path=selection_path,
        run_id=123,
        run_attempt=1,
        output_path=None,
        model="fixture-model",
        timeout_seconds=1,
    )

    assert batches == [("ladder", True), *[("fast", False)] * 3]
    assert payload["lanes"]["ladder"] == {
        "batchManifest": "records/fixture/ladder.json",
        "promptMode": "ladder",
    }
    assert [row["index"] for row in payload["lanes"]["rollouts"]] == [1, 2, 3]
    assert payload["lanes"]["median3"][0]["ok"] is True
    assert (
        payload["selectionSha256"]
        == hashlib.sha256(selection_path.read_bytes()).hexdigest()
    )
    assert json.loads(output.read_text()) == payload


def test_suite_runner_honors_trusted_ladder_prompt_mode(tmp_path, monkeypatch) -> None:
    # ladder_v2 comes from the TRUSTED selection request; the ladder lane
    # runs under it and the manifest records it.
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    selection_path = tmp_path / "strategy-targets.json"
    selection = {
        "schemaVersion": "thesis_strategy_selection_v1",
        "sourceSha": source_sha,
        "selectedAtUtc": "2030-01-01T00:00:00Z",
        "selectionPath": (
            "records/thesis-analyst/strategy-selections/2030-01-01/"
            "strategy-124-a1.json"
        ),
        "selectionSetHash": "a" * 64,
        "request": {"suite": "ladder", "ladderPromptMode": "ladder_v2"},
        "targets": [{"catalogSlug": "fixture-target"}],
    }
    selection_path.write_text(json.dumps(selection) + "\n")

    batches: list[tuple[str, bool]] = []

    def fake_batch(**kwargs):
        batches.append((kwargs["prompt_mode"], kwargs["reviewed"]))
        return {
            "schemaVersion": "thesis_batch_manifest_v1",
            "results": [{"ok": True, "target": {"catalogSlug": "fixture-target"}}],
        }

    monkeypatch.setattr(suite_runner, "run_batch", fake_batch)
    monkeypatch.setattr(
        suite_runner,
        "batch_path",
        lambda day, run_id, attempt, lane: tmp_path / f"{lane}.json",
    )
    output = tmp_path / "strategy-suites" / "2030-01-02" / "strategy-124-a1.json"
    monkeypatch.setattr(suite_runner, "suite_path", lambda day, run_id, attempt: output)
    monkeypatch.setattr(
        suite_runner, "repo_relative", lambda path: f"records/fixture/{path.name}"
    )
    monkeypatch.setattr(suite_runner, "utc_now", lambda: "2030-01-02T00:00:00Z")

    payload = suite_runner.run_suite(
        selection_path=selection_path,
        run_id=124,
        run_attempt=1,
        output_path=None,
        model="fixture-model",
        timeout_seconds=1,
    )
    assert batches == [("ladder_v2", True)]
    assert payload["lanes"]["ladder"]["promptMode"] == "ladder_v2"

    # An unknown mode in the selection fails closed.
    bad = dict(selection)
    bad["request"] = {"suite": "ladder", "ladderPromptMode": "ladder_v3"}
    selection_path.write_text(json.dumps(bad) + "\n")
    with pytest.raises(suite_runner.StrategySuiteError, match="ladder prompt mode"):
        suite_runner.run_suite(
            selection_path=selection_path,
            run_id=124,
            run_attempt=1,
            output_path=None,
            model="fixture-model",
            timeout_seconds=1,
        )
