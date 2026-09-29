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
from tests.test_tool_evidence_custody import event_for  # noqa: E402


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
    assert result["toolEvidenceFailure"] == "Tool evidence verification failed"
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


@pytest.mark.parametrize("bound", [True, False])
def test_stage_binds_recorded_calls_to_native_events_before_sealing(
    tmp_path, monkeypatch, bound
):
    """A recorded call without its native completion event fails the stage at
    generation time, from the same redacted stream the publisher will bind
    against, instead of surfacing as a docket-wide publication failure."""
    import tool_evidence as evidence

    def fake_stage(**kwargs):
        recorder = evidence.EvidenceRecorder(kwargs["evidence_output"])
        call = recorder.call(
            "calculate",
            {"expression": "base + delta", "inputs": {"base": 1.5, "delta": 0.5}},
        )
        stream = json.dumps(event_for(call)) + "\n" if bound else ""
        return {
            "returnCode": 0,
            "stderr": "",
            "codexStdoutRaw": stream,
            "codexTrace": {"effectiveReturnCode": 0, "lastError": None},
        }

    monkeypatch.setattr(runner, "_run_codex_agent_command", fake_stage)
    result = runner.run_codex_agent_command(
        prompt="test",
        timeout_seconds=5,
        model="test",
        out_dir=tmp_path,
        prefix="",
        search=True,
        sandbox="read-only",
        reasoning_effort=None,
    )
    assert result["toolEvidenceVerification"]["valid"] is True
    if bound:
        assert result["returnCode"] == 0
        assert result["codexTrace"]["effectiveReturnCode"] == 0
        assert "toolEvidenceFailure" not in result
    else:
        assert result["returnCode"] == 1
        assert result["codexTrace"]["effectiveReturnCode"] == 1
        assert result["codexTrace"]["lastError"] == (
            "Tool evidence native binding failed: tool evidence calls lack "
            "native completion events: call-0001"
        )
        assert result["toolEvidenceFailure"] == result["codexTrace"]["lastError"]
        assert result["stderr"].endswith("native completion events: call-0001.")



def _run_fake_codex_stage(
    tmp_path: Path, out_dir: Path, extra_lines: list[str]
) -> subprocess.CompletedProcess:
    """Run the real runner, whose fake codex runs ``extra_lines`` against the
    real MCP server before it answers with a valid cell."""
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
            *extra_lines,
        ],
    )
    return subprocess.run(
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


def _run_unbound_stage(tmp_path: Path, out_dir: Path) -> subprocess.CompletedProcess:
    """Run the real runner and MCP server on a model stream that completes only
    the first of two recorded calls."""
    return _run_fake_codex_stage(
        tmp_path,
        out_dir,
        [
            "requests = [{'jsonrpc':'2.0','id':i,'method':'tools/call',"
            "'params':{'name':'calculate','arguments':"
            "{'expression':'prior + adjustment',"
            "'inputs':{'prior':5.0,'adjustment':0.2}}}} for i in (1, 2)]",
            "completed = subprocess.run([sys.executable, *tool_args], "
            "input=''.join(json.dumps(r)+'\\n' for r in requests), "
            "capture_output=True, text=True, check=True)",
            "request, line = requests[0], completed.stdout.splitlines()[0]",
            "print(json.dumps({'type':'item.completed','item':"
            "{'id':'mcp-1','type':'mcp_tool_call',"
            "'server':'thesis_tool_evidence','tool':'calculate',"
            "'arguments':request['params']['arguments'],"
            "'result':json.loads(line)['result'],'status':'completed'}}))",
        ],
    )


def _validate_single_failed_run(
    staged: Path, run_relative: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish one failed run as a batch through the real custody check."""
    import docket_publication

    batch_relative = "records/thesis-analyst/batches/2030-01-10/run.json"
    batch_path = staged / batch_relative
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_batch_manifest_v1",
                "promptMode": "fast",
                "startedAt": "2030-01-10T12:00:00Z",
                "finishedAt": "2030-01-10T12:02:00Z",
                "results": [
                    {
                        "ok": False,
                        "cellsPath": None,
                        "manifestPath": f"{run_relative}/manifest.json",
                        "target": {},
                        "startedAt": "2030-01-10T12:00:00Z",
                        "finishedAt": "2030-01-10T12:01:00Z",
                    }
                ],
            }
        )
        + "\n"
    )
    # Registration binding and the repo-relative file inventory need a
    # registered target and repo-relative artifact paths (this run lives
    # outside the checkout). Custody and the validator replay stay real.
    monkeypatch.setattr(
        docket_publication, "validate_run_file_inventory", lambda *_args: None
    )
    monkeypatch.setattr(
        docket_publication, "validate_run_binding", lambda *_args, **_kwargs: None
    )
    docket_publication.validate_cells(staged, batch_relative)


def test_unbound_stage_is_a_failed_trace_the_publisher_retains(
    tmp_path, monkeypatch
):
    """End to end: the real MCP server records two calls, the model's stream
    completes only the first, and the run must fail on its own as a
    tool_evidence failure that custody verifies and the publisher retains,
    instead of sealing ok:false beside cells that validate (which refuses the
    whole batch as a validator status mismatch)."""
    staged = tmp_path / "staged"
    run_relative = "records/thesis-analyst/2030-01-10/2030-01-10t12-00-00z-unbound"
    out_dir = staged / run_relative
    completed = _run_unbound_stage(tmp_path, out_dir)
    assert completed.returncode == 1, completed.stderr + completed.stdout[-2000:]
    evidence = json.loads((out_dir / "tool_evidence.json").read_text())
    assert [call["callId"] for call in evidence["calls"]] == [
        "call-0001",
        "call-0002",
    ]
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["cellsPath"] is None
    assert manifest["validation"] is None
    assert manifest["error"] == {
        "phase": "tool_evidence",
        "message": "Tool evidence native binding failed: tool evidence calls "
        "lack native completion events: call-0002",
        "command": {"returnCode": 1, "timedOut": False},
    }
    command = json.loads((out_dir / "command.json").read_text())
    assert command["returnCode"] == 1
    assert "toolEvidenceFailure" not in command
    # The model's output survives as the raw response; nothing downstream of
    # parsing is sealed.
    assert (out_dir / "raw_response.txt").is_file()
    assert not (out_dir / "parsed_cells.json").exists()
    assert not (out_dir / "cells.with_activity.json").exists()
    verification = verify_run(out_dir)
    assert verification.inventory_status == "complete"
    assert not verification.headline_eligible

    _validate_single_failed_run(staged, run_relative, monkeypatch)


# The fake codex sends ``requests`` to the real MCP server and writes each
# reply the way Codex does: a started event, then a completion whose result is
# the server's result, or, for a JSON-RPC error, no result and Codex's error
# message (verbatim examples in tests/fixtures/codex_mcp_errors).
REFUSED_CALL_LINES = [
    "def request(i, arguments):",
    "    return {'jsonrpc':'2.0','id':i,'method':'tools/call',"
    "'params':{'name':'calculate','arguments':arguments}}",
    "oversized = {'expression':'1'+'+1'*20000,'inputs':{}}",
    "if VARIANT == 'call_limit':",
    "    requests = [request(i, {'expression':'a+1','inputs':{'a':i}})"
    " for i in range(1, 130)]",
    "elif VARIANT == 'oversized_only':",
    "    requests = [request(1, oversized)]",
    "else:",
    "    requests = [request(1, {'expression':'a+1','inputs':{'a':1}}),"
    " request(2, oversized)]",
    "completed = subprocess.run([sys.executable, *tool_args], "
    "input=''.join(json.dumps(r)+'\\n' for r in requests), "
    "capture_output=True, text=True, check=True)",
    "for request, line in zip(requests, completed.stdout.splitlines()):",
    "    reply = json.loads(line)",
    "    item = {'id':'item_'+str(request['id']),'type':'mcp_tool_call',"
    "'server':'thesis_tool_evidence','tool':'calculate',"
    "'arguments':request['params']['arguments']}",
    "    print(json.dumps({'type':'item.started','item':"
    "{**item,'result':None,'error':None,'status':'in_progress'}}))",
    "    if 'result' in reply:",
    "        result = reply['result']",
    "        print(json.dumps({'type':'item.completed','item':{**item,"
    "'result':{'content':result['content'],"
    "'structured_content':result['structuredContent']},'error':None,"
    "'status':'failed' if result['isError'] else 'completed'}}))",
    "    else:",
    "        message = ('tool call error: tool call failed for "
    "`thesis_tool_evidence/calculate`\\n\\nCaused by:\\n    Mcp error: '"
    " + str(reply['error']['code']) + ': ' + reply['error']['message'])",
    "        print(json.dumps({'type':'item.completed','item':{**item,"
    "'result':None,'error':{'message':message},'status':'failed'}}))",
]


def _run_refused_call_stage(
    tmp_path: Path, out_dir: Path, variant: str
) -> subprocess.CompletedProcess:
    return _run_fake_codex_stage(
        tmp_path, out_dir, [f"VARIANT = {variant!r}", *REFUSED_CALL_LINES]
    )


@pytest.mark.parametrize(
    ("variant", "recorded"),
    [("call_limit", 128), ("oversized_arguments", 1), ("oversized_only", 0)],
)
def test_refused_call_is_a_failed_trace_the_publisher_retains(
    tmp_path, monkeypatch, variant, recorded
):
    """End to end: the model makes a 129th call, or sends arguments over 32 KiB.
    The real MCP server refuses it with a JSON-RPC error and records nothing,
    and Codex writes a failed completion with no result. The runner fails the
    stage on its own; custody must then keep the failed trace rather than
    refuse it and, with it, the whole docket."""
    staged = tmp_path / "staged"
    run_relative = "records/thesis-analyst/2030-01-10/2030-01-10t12-00-00z-refused"
    out_dir = staged / run_relative
    completed = _run_refused_call_stage(tmp_path, out_dir, variant)
    assert completed.returncode == 1, completed.stderr + completed.stdout[-2000:]
    evidence = json.loads((out_dir / "tool_evidence.json").read_text())
    assert len(evidence["calls"]) == recorded
    stream = (out_dir / "codex_stdout.jsonl").read_text(encoding="utf-8")
    errors = [
        event["item"]
        for event in map(json.loads, stream.splitlines())
        if event.get("type") == "item.completed"
        and event["item"].get("type") == "mcp_tool_call"
        and event["item"]["result"] is None
    ]
    assert len(errors) == 1
    assert errors[0]["status"] == "failed"
    assert errors[0]["error"]["message"].endswith(
        "Mcp error: -32602: invalid or exhausted evidence tool call"
    )
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["cellsPath"] is None
    assert manifest["error"] == {
        "phase": "tool_evidence",
        "message": "Tool evidence native binding failed: tool evidence has "
        "native tool errors that bind to no recorded call",
        "command": {"returnCode": 1, "timedOut": False},
    }
    assert not (out_dir / "parsed_cells.json").exists()
    verification = verify_run(out_dir)
    assert verification.inventory_status == "complete"
    assert not verification.headline_eligible
    _validate_single_failed_run(staged, run_relative, monkeypatch)


def test_failed_trace_whose_unbound_event_carries_a_result_still_blocks(
    tmp_path, monkeypatch
):
    """Negative control for the relaxation: the same failed trace, re-sealed
    after its refused call's event is given a result claiming an unrecorded
    call ID, is refused by custody and blocks the batch. Only a result-free
    error may go unbound."""
    import docket_publication
    from verify_custody import CustodyError

    staged = tmp_path / "staged"
    run_relative = "records/thesis-analyst/2030-01-10/2030-01-10t12-00-00z-forged"
    out_dir = staged / run_relative
    completed = _run_refused_call_stage(tmp_path, out_dir, "oversized_arguments")
    assert completed.returncode == 1
    verify_run(out_dir)
    forged = {"callId": "call-0002", "result": {"value": 42}}
    lines = []
    for line in (out_dir / "codex_stdout.jsonl").read_text().splitlines():
        event = json.loads(line)
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("id") == "item_2":
            item["result"] = {
                "content": [{"type": "text", "text": json.dumps(forged)}],
                "structured_content": forged,
            }
            line = json.dumps(event)
        lines.append(line + "\n")
    manifest = json.loads((out_dir / "manifest.json").read_text())
    manifest.pop("custodyRootSha256", None)
    refs = [
        ref
        for ref in manifest["artifacts"]
        if Path(str(ref["path"])).name != "manifest.json"
    ]
    for index, ref in enumerate(refs):
        if Path(str(ref["path"])).name == "codex_stdout.jsonl":
            refs[index] = runner.write_artifact(
                out_dir,
                ref["artifactType"],
                "codex_stdout.jsonl",
                "".join(lines),
                ref["createdAt"],
            )
    manifest["artifacts"] = refs
    runner.finalize_manifest(out_dir, manifest["runStartedAt"], manifest, refs)
    with pytest.raises(CustodyError, match="unknown or repeated event call ID"):
        verify_run(out_dir)
    with pytest.raises(
        docket_publication.PublicationError,
        match="custody verification failed: .*unknown or repeated event call ID",
    ):
        _validate_single_failed_run(staged, run_relative, monkeypatch)


@pytest.mark.parametrize("forgery", ["presents_complete", "post_parse_artifact"])
def test_custody_refuses_a_forged_tool_evidence_failure(tmp_path, forgery):
    """The tool_evidence phase gets the parse-failure inventory and nothing
    lighter: it cannot present as complete or carry post-parse artifacts."""
    from verify_custody import CustodyError

    out_dir = tmp_path / "run"
    assert _run_unbound_stage(tmp_path, out_dir).returncode == 1
    verify_run(out_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["error"]["phase"] == "tool_evidence"
    manifest.pop("custodyRootSha256", None)
    refs = [
        ref
        for ref in manifest["artifacts"]
        if Path(str(ref["path"])).name != "manifest.json"
    ]
    if forgery == "presents_complete":
        manifest["ok"] = True
        manifest["validation"] = {"ok": True}
        expected = "does not present as failed"
    else:
        refs.append(
            runner.write_artifact(
                out_dir,
                "parsed_cell",
                "parsed_cells.json",
                "[]\n",
                manifest["runStartedAt"],
            )
        )
        expected = "tool_evidence-failure inventory contains post-parse artifacts"
    manifest["artifacts"] = refs
    # Re-seal so the forgery is hash-consistent and the semantic guard, not
    # an integrity mismatch, is what refuses it.
    runner.finalize_manifest(out_dir, manifest["runStartedAt"], manifest, refs)
    with pytest.raises(CustodyError, match=expected):
        verify_run(out_dir)
