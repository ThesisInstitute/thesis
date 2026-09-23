"""The runner archives controlled tool traffic before sealing a forecast."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_thesis_analyst as runner  # noqa: E402
from verify_custody import verify_run  # noqa: E402

from tests.test_thesis_analyst_runner import (  # noqa: E402
    review_test_cell,
    write_fake_codex,
)


def test_tool_configuration_is_closed_and_review_does_not_fetch(tmp_path):
    output = tmp_path / "tool_evidence.json"
    config = runner.tool_evidence_mcp_config(output, allow_fetch=False)
    assert all(item.startswith("mcp_servers.thesis_tool_evidence.") for item in config)
    assert not any("fetch_source" in item for item in config)
    assert any("extract_irs_soi" in item for item in config)
    args = json.loads(
        next(item.split("=", 1)[1] for item in config if ".args=" in item)
    )
    assert args == [
        str(ROOT / "scripts/tool_evidence_mcp.py"),
        "--output",
        str(output),
        "--no-fetch",
    ]


def test_capture_note_is_part_of_prompt_only_for_instrumented_runs():
    prior, _ = runner.build_run_prompt("test.series", "2030-01", None, "fast")
    captured, _ = runner.build_run_prompt(
        "test.series", "2030-01", None, "fast", tool_evidence=True
    )
    assert captured == prior + "\n" + runner.TOOL_EVIDENCE_NOTE


@pytest.mark.parametrize("scheme", ["https", "HTTPS", "hTtPs"])
@pytest.mark.parametrize(
    "secret_part",
    [
        "?token=private-query-value",
        "?API_KEY=private-query-value",
        "#access_token=private-query-value",
    ],
)
def test_url_credentials_are_redacted_from_native_streams(scheme, secret_part):
    original = {"url": f"{scheme}://example.gov/data{secret_part}"}
    cleaned = runner.redact_stream_text(json.dumps(original))
    assert "private-query-value" not in cleaned
    assert json.loads(cleaned)["url"] == "[redacted: unsafe URL]"
    assert runner.redact_stream_text(cleaned) == cleaned


def test_structured_url_redaction_inspects_the_complete_value():
    original = {"url": "https://user\\name:private-query-value@example.gov/"}
    cleaned = runner.redact_stream_text(json.dumps(original))
    assert "private-query-value" not in cleaned
    assert json.loads(cleaned)["url"] == "[redacted: unsafe URL]"


@pytest.mark.parametrize("damaged", [b"not JSON", b'{"calls":[NaN]}', b"[]", b"null"])
def test_corrupt_capture_fails_stage_and_leaves_verifiable_failure(
    tmp_path, monkeypatch, damaged
):
    def fake_stage(**kwargs):
        output = kwargs["evidence_output"]
        assert output.parent.name.startswith("thesis-tool-evidence-")
        assert not output.is_relative_to(tmp_path)
        output.write_bytes(damaged)
        return {"returnCode": 0, "stderr": "", "codexTrace": {"effectiveReturnCode": 0}}

    monkeypatch.setattr(runner, "_run_codex_agent_command", fake_stage)
    result = runner.run_codex_agent_command(
        prompt="test",
        timeout_seconds=5,
        model="test",
        out_dir=tmp_path,
        prefix="draft_",
        search=True,
        sandbox="read-only",
        reasoning_effort=None,
    )
    assert result["returnCode"] == 1
    assert result["codexTrace"]["effectiveReturnCode"] == 1
    assert result["toolEvidence"]["artifact"] == "draft_tool_evidence.json"
    assert json.loads(result["toolEvidenceRaw"])["captureError"]
    report = result["toolEvidenceVerification"]
    assert report["valid"] is False
    assert (
        report["evidenceSha256"]
        == hashlib.sha256(result["toolEvidenceRaw"]).hexdigest()
    )


def test_native_stage_calls_real_mcp_and_seals_replay(tmp_path):
    """Fake model transport, real calculator/MCP/runner/custody verification."""
    codex = tmp_path / "codex"
    auth_home = tmp_path / "auth"
    auth_home.mkdir()
    (auth_home / "auth.json").write_text("{}\n")
    write_fake_codex(
        codex,
        review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9),
        extra_lines=[
            "import subprocess",
            "config = next(a for a in args if "
            "a.startswith('mcp_servers.thesis_tool_evidence.args='))",
            "tool_args = json.loads(config.split('=', 1)[1])",
            "request = {'jsonrpc':'2.0','id':1,'method':'tools/call',"
            "'params':{'name':'calculate','arguments':"
            "{'expression':'prior + adjustment',"
            "'inputs':{'prior':5.0,'adjustment':0.2}}}}",
            "rejected = {'jsonrpc':'2.0','id':2,'method':'tools/call',"
            "'params':{'name':'fetch_source','arguments':"
            "{'url':'https://example.gov/data?api_key=private-query-value'}}}",
            "requests = [request, rejected]",
            "completed = subprocess.run([sys.executable, *tool_args], "
            "input=''.join(json.dumps(r)+'\\n' for r in requests), "
            "capture_output=True, "
            "text=True, check=True)",
            "for request, line in zip(requests, completed.stdout.splitlines()):",
            "    reply = json.loads(line)",
            "    assert 'result' in reply, reply",
            "    print(json.dumps({'type':'item.completed','item':"
            "{'id':'mcp-'+str(request['id']),'type':'mcp_tool_call',"
            "'server':'thesis_tool_evidence','tool':request['params']['name'],"
            "'arguments':request['params']['arguments'],'result':reply['result'],"
            "'status':'completed'}}))",
        ],
    )
    out_dir = tmp_path / "run"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_thesis_analyst.py"),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "test-model",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "THESIS_CODEX_BIN": str(codex),
            "CODEX_HOME": str(auth_home),
        },
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout[-2000:]
    evidence = json.loads((out_dir / "tool_evidence.json").read_text())
    report = json.loads((out_dir / "tool_evidence_verification.json").read_text())
    assert evidence["calls"][0]["result"]["value"] == 5.2
    assert report["valid"] is True
    assert report["checks"][0]["status"] == "replayed"
    assert report["checks"][1]["status"] == "failed"
    assert verify_run(out_dir).headline_eligible
    for artifact in out_dir.iterdir():
        assert b"private-query-value" not in artifact.read_bytes(), artifact
    manifest = json.loads((out_dir / "manifest.json").read_text())
    types = {ref["artifactType"] for ref in manifest["artifacts"]}
    assert {"tool_evidence", "tool_evidence_verification"} <= types
