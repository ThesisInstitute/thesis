from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from archive_strategy_attempt import archive_attempt  # noqa: E402


@pytest.fixture
def attempt(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    old = root / "records/thesis-analyst/old/manifest.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"ok":true}\n')
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-m", "base"],
        cwd=root, check=True, capture_output=True,
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"sourceSha": sha, "workflow": {"runId": 123, "runAttempt": 1}}))
    return root, selection, tmp_path / "archive"


def test_failed_invalid_attempt_is_retained_byte_for_byte_without_old_archive(attempt):
    root, selection, output = attempt
    directory = root / "records/thesis-analyst/new"
    directory.mkdir()
    raw = b'{"ok":false,"validationErrors":["custody mismatch"]}\n'
    (directory / "manifest.json").write_bytes(raw)
    (directory / "draft_stdout.jsonl").write_bytes(b'{invalid native output\x00\xff')
    (root / "unrelated.txt").write_text("not evidence")
    result = archive_attempt(root, selection, output, 123, 1)
    assert result["publishable"] is False
    assert len(result["files"]) == 2
    assert not result["omitted"]
    assert (output / "files/records/thesis-analyst/new/manifest.json").read_bytes() == raw
    assert not (output / "files/records/thesis-analyst/old").exists()
    assert not (output / "bundle_manifest.json").exists()
    for row in result["files"]:
        assert row["sha256"] == hashlib.sha256((output / "files" / row["path"]).read_bytes()).hexdigest()


def test_diagnostic_archive_discloses_unsafe_omissions_without_reading_symlinks(attempt):
    root, selection, output = attempt
    directory = root / "records/thesis-analyst/new"
    directory.mkdir()
    outside = root.parent / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("must never be copied")
    (directory / "linked").symlink_to(outside, target_is_directory=True)
    (directory / "file-link.txt").symlink_to(outside / "private.txt")
    (directory / "secret.log").write_text("sk-" + "a" * 40)
    executable = directory / "executable.txt"
    executable.write_text("do not execute")
    executable.chmod(0o755)
    result = archive_attempt(root, selection, output, 123, 1)
    assert result["files"] == []
    assert {row["reason"] for row in result["omitted"]} == {"symlink", "possible secret", "executable file"}
    assert "must never be copied" not in (output / "attempt_manifest.json").read_text()


def test_modified_and_deleted_record_paths_are_disclosed(attempt):
    root, selection, output = attempt
    old = root / "records/thesis-analyst/old/manifest.json"
    old.write_text("modified failed attempt")
    result = archive_attempt(root, selection, output, 123, 1)
    assert [r["path"] for r in result["files"]] == ["records/thesis-analyst/old/manifest.json"]
    old.unlink()
    result = archive_attempt(root, selection, output.with_name("deleted"), 123, 1)
    assert result["omitted"] == [{"path": "records/thesis-analyst/old/manifest.json", "reason": "deleted"}]


def test_other_invocation_or_checkout_cannot_be_mislabeled(attempt):
    root, selection, output = attempt
    with pytest.raises(ValueError, match="invocation"):
        archive_attempt(root, selection, output, 123, 2)
    value = json.loads(selection.read_text())
    value["sourceSha"] = "a" * 40
    selection.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="checkout"):
        archive_attempt(root, selection, output, 123, 1)


def test_archive_does_not_overwrite_prior_evidence(attempt):
    root, selection, output = attempt
    archive_attempt(root, selection, output, 123, 1)
    with pytest.raises(FileExistsError):
        archive_attempt(root, selection, output, 123, 1)


def test_diagnostic_retains_hidden_traces_and_distinguishes_execution_attempt(attempt):
    root, selection, output = attempt
    hidden = root / "records/thesis-analyst/new/.native/trace.jsonl"
    hidden.parent.mkdir(parents=True)
    hidden.write_bytes(b'{"native":"unchanged"}\n')
    first = archive_attempt(root, selection, output, 123, 1, execution_attempt=1)
    second = archive_attempt(root, selection, output.with_name("rerun"), 123, 1, execution_attempt=2)
    assert first["workflowRunAttempt"] == second["workflowRunAttempt"] == 1
    assert (first["executionAttempt"], second["executionAttempt"]) == (1, 2)
    assert first["files"] == second["files"]
    assert (output / "files" / first["files"][0]["path"]).read_bytes() == hidden.read_bytes()
