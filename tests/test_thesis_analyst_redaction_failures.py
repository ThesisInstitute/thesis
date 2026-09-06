"""An unsafe channel must leave a failed record without losing safe channels."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_thesis_analyst as runner  # noqa: E402

UNSAFE = 'tool output\n{"credentials":\n{"nested":"opaque-planted-refusal"\n'
SAFE = '{"forecast": 1}'


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
@pytest.mark.parametrize("timed_out", [False, True])
def test_external_refusal_preserves_observed_status_and_other_channel(
    tmp_path, monkeypatch, channel, timed_out
):
    stdout = UNSAFE if channel == "stdout" else SAFE
    stderr = UNSAFE if channel == "stderr" else "clean diagnostics"
    calls = []

    def completed(argv, **kwargs):
        calls.append(argv)
        if timed_out:
            raise subprocess.TimeoutExpired(
                argv, 10, output=stdout.encode(), stderr=stderr.encode()
            )
        return subprocess.CompletedProcess(argv, 0, stdout, stderr)

    monkeypatch.setattr(runner.subprocess, "run", completed)
    result = runner.run_agent_command("synthetic-command", "prompt", tmp_path / "p", 10)
    assert len(calls) == 1
    assert result["returnCode"] == (124 if timed_out else 1)
    assert result["timedOut"] is timed_out
    assert result["redactionFailures"] == [channel]
    assert "Output omitted" in result[channel]
    assert "opaque-planted-refusal" not in json.dumps(result)
    safe_channel = "stderr" if channel == "stdout" else "stdout"
    assert result[safe_channel].startswith(
        stderr if safe_channel == "stderr" else stdout
    )

    refs = []
    runner.append_command_artifacts(
        refs,
        tmp_path,
        prefix="",
        command_result=result,
        created_at="2030-01-01T00:00:00Z",
    )
    command = json.loads((tmp_path / "command.json").read_text())
    assert command["redactionFailures"] == [channel]
    assert command["returnCode"] != 0
    assert refs
    for path in tmp_path.iterdir():
        if path.is_file():
            assert "opaque-planted-refusal" not in path.read_text()


@pytest.mark.parametrize("channel", ["stdout", "stderr", "last_message"])
def test_codex_refusal_preserves_safe_channels_and_cleans_last_message(
    tmp_path, monkeypatch, channel
):
    event = json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message", "text": SAFE}}
    )
    fake = tmp_path / "synthetic-codex"
    stderr = UNSAFE if channel == "stderr" else "clean diagnostics"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"sys.stdout.write({(UNSAFE if channel == 'stdout' else event)!r})\n"
        f"sys.stderr.write({stderr!r})\n"
        "last = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        f"last.write_text({(UNSAFE if channel == 'last_message' else SAFE)!r})\n"
    )
    fake.chmod(0o755)
    monkeypatch.setattr(runner, "resolve_codex_cli", lambda: str(fake))
    monkeypatch.setattr(runner, "prepare_codex_home", lambda path: path)
    out_dir = tmp_path / "record"
    result = runner.run_codex_agent_command(
        prompt="synthetic prompt",
        timeout_seconds=10,
        model="synthetic",
        out_dir=out_dir,
        prefix="",
        search=False,
        sandbox="read-only",
        reasoning_effort=None,
    )
    assert result["processReturnCode"] == 0
    assert result["returnCode"] == 1
    assert result["redactionFailures"] == [channel]
    assert result["codexTrace"]["redactionFailures"] == [channel]
    assert "opaque-planted-refusal" not in json.dumps(result)
    assert (
        "opaque-planted-refusal" not in (out_dir / "codex_last_message.txt").read_text()
    )
    if channel == "stderr":
        assert result["codexStdoutRaw"] == event
        assert result["stdout"] == SAFE
    elif channel == "stdout":
        assert result["codexStderrRaw"] == "clean diagnostics"


def test_external_start_failure_redacts_diagnostic_without_throwing(
    tmp_path, monkeypatch
):
    def fail(*args, **kwargs):
        raise OSError(UNSAFE)

    monkeypatch.setattr(runner.subprocess, "run", fail)
    result = runner.run_agent_command(
        shlex.quote("missing"), "prompt", tmp_path / "p", 10
    )
    assert result["returnCode"] == 127
    assert "opaque-planted-refusal" not in json.dumps(result)
    assert "withheld" in result["stderr"]
