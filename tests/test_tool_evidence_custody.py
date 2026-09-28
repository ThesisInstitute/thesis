from __future__ import annotations

import base64
import copy
import hashlib
import json
import pathlib
import sys
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_thesis_analyst as analyst  # noqa: E402
import tool_evidence as evidence  # noqa: E402
import tool_evidence_mcp as mcp  # noqa: E402
import verify_custody as custody  # noqa: E402

CREATED = "2030-01-01T00:00:00Z"


def event_for(call: dict[str, Any]) -> dict[str, Any]:
    terminal = evidence.terminal_call(call)
    return {
        "type": "item.completed",
        "item": {
            "id": f"mcp-{call['callId']}",
            "type": "mcp_tool_call",
            "server": custody.TOOL_EVIDENCE_SERVER,
            "tool": call["tool"],
            "arguments": call["arguments"],
            "status": "completed",
            "result": {
                "structured_content": terminal,
                "content": [{"type": "text", "text": json.dumps(terminal)}],
                "is_error": call["status"] == "failed",
            },
        },
    }


def write_stage(
    run_dir: pathlib.Path,
    *,
    prefix: str = "",
    expression: str = "base + delta",
    tool: str = "calculate",
    arguments: dict[str, Any] | None = None,
    fetcher: Any = None,
    ensure_ascii: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    recorder = evidence.EvidenceRecorder(
        run_dir / f"{prefix}tool_evidence.json",
        **({"fetcher": fetcher} if fetcher is not None else {}),
    )
    call = recorder.call(
        tool,
        arguments
        if arguments is not None
        else {"expression": expression, "inputs": {"base": 1711.9, "delta": 4.9}},
    )
    raw = recorder.output.read_bytes()
    report = evidence.verify_evidence(recorder.payload)
    report["evidenceSha256"] = hashlib.sha256(raw).hexdigest()
    (run_dir / f"{prefix}tool_evidence_verification.json").write_text(
        json.dumps(report)
    )
    command = {
        "backend": "codex",
        "returnCode": 0,
        "argv": [
            "codex",
            *[
                part
                for config in analyst.tool_evidence_mcp_config(
                    pathlib.Path("/tmp/thesis-tool-evidence-fixture/tool_evidence.json")
                )
                for part in ("-c", config)
            ],
        ],
        "toolEvidence": {
            "schemaVersion": evidence.SCHEMA_VERSION,
            "artifact": f"{prefix}tool_evidence.json",
            "verificationArtifact": f"{prefix}tool_evidence_verification.json",
        },
    }
    (run_dir / f"{prefix}command.json").write_text(json.dumps(command))
    (run_dir / f"{prefix}codex_stdout.jsonl").write_text(
        analyst.redact_stream_text(
            json.dumps(event_for(call), ensure_ascii=ensure_ascii) + "\n"
        ),
        encoding="utf-8",
    )
    return command, [
        {"path": f"{prefix}{name}", "artifactType": artifact_type}
        for name, artifact_type in custody.TOOL_EVIDENCE_STAGE_INVENTORY.items()
    ]


def check(
    run_dir: pathlib.Path,
    command: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    prefix: str = "",
    run_succeeded: bool = True,
) -> set[str]:
    return custody.verify_tool_evidence_stage(
        run_dir,
        entries,
        prefix=prefix,
        command=command,
        run_succeeded=run_succeeded,
    )


@pytest.mark.parametrize("prefix", ["", "draft_", "pre_submit_review_"])
def test_capture_replays_and_binds_native_events(
    tmp_path: pathlib.Path, prefix: str
) -> None:
    command, entries = write_stage(tmp_path, prefix=prefix)
    assert check(tmp_path, command, entries, prefix=prefix) == {
        f"{prefix}tool_evidence.json",
        f"{prefix}tool_evidence_verification.json",
    }


def test_failed_tool_is_preserved_as_a_failed_tool(tmp_path: pathlib.Path) -> None:
    command, entries = write_stage(tmp_path, expression="1 / 0")
    check(tmp_path, command, entries)
    report = json.loads((tmp_path / "tool_evidence_verification.json").read_text())
    assert report["valid"] is True
    assert report["failedCount"] == 1
    assert report["succeededCount"] == 0
    assert report["checks"][0]["status"] == "failed"


@pytest.mark.parametrize(
    "source_text",
    [
        "count=1711.9\nCENSUS_API_KEY=planted-fixture-value",
        '{"count":1711.9,"api_key":"planted-fixture-value"}',
        "count=1711.9\nhttps://example.gov/?api_key=planted-fixture-value",
        "count=1711.9\nghp_" + "PlantedFixtureValue",
        "[" * 600 + r'{"api\u005fkey":"planted-fixture-value"}' + "]" * 600,
        r'{"api\u005fkey":"planted-fixture-value",',
        '{"api_key":"planted-fixture-value',
        '{"api_key":"planted-fixture-value","api_key":"[REDACTED]"}',
        r'{"api\u005fkey":"planted-fixture-value","api_key":"[REDACTED]"}',
        '{"count":1e400,"api_key":"planted-fixture-value"}',
    ],
)
def test_source_presentation_redaction_keeps_raw_capture_and_native_binding(
    tmp_path: pathlib.Path, source_text: str
) -> None:
    # Synthetic sources exercise the known asymmetric-redaction bug. The failed
    # ACTC run did not retain its native bytes, so this is not an incident replay.
    body = source_text.encode()
    response = {
        "url": "https://example.gov/series.json",
        "status": 200,
        "headers": [["content-type", "application/json"]],
        "bodyBase64": base64.b64encode(body).decode("ascii"),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }
    command, entries = write_stage(
        tmp_path,
        tool="fetch_source",
        arguments={"url": response["url"]},
        fetcher=lambda _url: response,
    )
    capture = json.loads((tmp_path / "tool_evidence.json").read_text())
    call = capture["calls"][0]
    assert call["result"]["excerpt"] == source_text
    assert call["response"] == response
    assert base64.b64decode(call["response"]["bodyBase64"]) == body
    assert evidence.verify_evidence(capture)["valid"]
    native = (tmp_path / "codex_stdout.jsonl").read_text()
    result = json.loads(native)["item"]["result"]
    terminal = result["structured_content"]
    assert terminal["result"]["excerpt"] != source_text
    assert "planted-fixture-value" not in native
    assert "PlantedFixtureValue" not in native
    assert json.loads(result["content"][0]["text"]) == terminal
    assert analyst.redact_stream_text(native) == native
    check(tmp_path, command, entries)


def test_benign_truncated_json_keeps_historical_terminal_projection(
    tmp_path: pathlib.Path,
) -> None:
    body = b'{"history":[' + b"1711.9," * 1500 + b"0]}"
    command, entries = write_stage(
        tmp_path,
        tool="fetch_source",
        arguments={"url": "https://example.gov/series.json"},
        fetcher=lambda url: {
            "url": url,
            "status": 200,
            "headers": [["content-type", "application/json"]],
            "bodyBase64": base64.b64encode(body).decode("ascii"),
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        },
    )
    capture = json.loads((tmp_path / "tool_evidence.json").read_text())
    call = capture["calls"][0]
    assert call["result"]["excerptTruncated"] is True
    assert evidence.terminal_call(call) == {
        key: value for key, value in call.items() if key != "response"
    }
    check(tmp_path, command, entries)


def test_deep_structured_result_has_an_idempotent_bounded_presentation() -> None:
    nested: Any = {"api_key": "planted-fixture-value"}
    for _ in range(600):
        nested = [nested]
    call = {
        "callId": "call-0002",
        "tool": "extract_json",
        "terminalProjectionVersion": evidence.TERMINAL_PROJECTION_VERSION,
        "arguments": {"sourceCallId": "call-0001", "pointer": ""},
        "status": "succeeded",
        "result": {"value": nested},
    }
    terminal = evidence.terminal_call(call)
    assert terminal["callId"] == call["callId"]
    assert terminal["result"] == evidence.REDACTED_JSON
    assert call["result"]["value"] is nested
    stream = json.dumps(event_for(call)) + "\n"
    assert analyst.redact_stream_text(stream) == stream
    result = json.loads(stream)["item"]["result"]
    assert json.loads(result["content"][0]["text"]) == result["structured_content"]
    shaped = evidence.redact_json_value(nested)
    for _ in range(600):
        shaped = shaped[0]
    assert shaped == {"api_key": "[REDACTED]"}
    legacy_call = dict(call)
    legacy_call.pop("terminalProjectionVersion")
    assert evidence.terminal_call(legacy_call)["result"] is call["result"]


@pytest.mark.parametrize(
    "body",
    [
        b"[" * 100 + b"1" + b"]" * 100,
        b'{"history":[' + b"1711.9," * 1500 + b"0]}",
    ],
)
def test_legacy_deep_and_truncated_excerpts_keep_the_exact_native_projection(
    tmp_path: pathlib.Path, body: bytes
) -> None:
    command, entries = write_stage(
        tmp_path,
        tool="fetch_source",
        arguments={"url": "https://example.gov/series.json"},
        fetcher=lambda url: {
            "url": url,
            "status": 200,
            "headers": [["content-type", "application/json"]],
            "bodyBase64": base64.b64encode(body).decode("ascii"),
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        },
    )
    evidence_path = tmp_path / "tool_evidence.json"
    payload = json.loads(evidence_path.read_text())
    call = payload["calls"][0]
    call.pop("terminalProjectionVersion")
    evidence_path.write_text(json.dumps(payload))
    report = evidence.verify_evidence(payload)
    report["evidenceSha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    (tmp_path / "tool_evidence_verification.json").write_text(json.dumps(report))
    legacy_terminal = {key: value for key, value in call.items() if key != "response"}
    assert evidence.terminal_call(call) == legacy_terminal
    # Historical native bytes are already archived; do not process them with
    # today's sanitizer before replaying their old presentation contract.
    (tmp_path / "codex_stdout.jsonl").write_text(json.dumps(event_for(call)) + "\n")
    check(tmp_path, command, entries)


@pytest.mark.parametrize("version", [None, False, True, 0, 2, 1.0, "1"])
def test_unknown_or_noninteger_terminal_projection_version_is_refused(
    tmp_path: pathlib.Path, version: Any
) -> None:
    write_stage(tmp_path)
    payload = json.loads((tmp_path / "tool_evidence.json").read_text())
    payload["calls"][0]["terminalProjectionVersion"] = version
    report = evidence.verify_evidence(payload)
    assert report["valid"] is False
    assert "unsupported terminal projection version" in report["errors"][0]
    with pytest.raises(evidence.EvidenceError, match="terminal projection version"):
        evidence.terminal_call(payload["calls"][0])


def test_terminal_projection_version_cannot_be_removed_from_captured_call(
    tmp_path: pathlib.Path,
) -> None:
    command, entries = write_stage(tmp_path)
    evidence_path = tmp_path / "tool_evidence.json"
    payload = json.loads(evidence_path.read_text())
    payload["calls"][0].pop("terminalProjectionVersion")
    evidence_path.write_text(json.dumps(payload))
    report = evidence.verify_evidence(payload)
    assert report["valid"] is True  # The native event must bind the producer version.
    report["evidenceSha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    (tmp_path / "tool_evidence_verification.json").write_text(json.dumps(report))
    with pytest.raises(
        custody.CustodyError,
        match=r"differs from its native event \(structuredContent, content\)",
    ):
        check(tmp_path, command, entries)


def test_mcp_text_and_structured_extraction_share_the_same_safe_projection(
    tmp_path: pathlib.Path,
) -> None:
    source = {
        "api_key": "planted-fixture-value",
        "note": "CENSUS_API_KEY=another-fixture-value",
        "observations": [1711.9, 1716.8],
    }
    body = json.dumps(source).encode()
    recorder = evidence.EvidenceRecorder(
        tmp_path / "evidence.json",
        fetcher=lambda url: {
            "url": url,
            "status": 200,
            "headers": [["content-type", "application/json"]],
            "bodyBase64": base64.b64encode(body).decode("ascii"),
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        },
    )
    recorder.call("fetch_source", {"url": "https://example.gov/series.json"})
    reply = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "extract_json",
                "arguments": {"sourceCallId": "call-0001", "pointer": ""},
            },
        },
        recorder,
    )
    call = recorder.payload["calls"][1]
    assert call["result"]["value"] == source
    assert evidence.verify_evidence(recorder.payload)["valid"]
    native = event_for(call)
    native["item"]["result"] = reply["result"]
    stream = json.dumps(native) + "\n"
    assert analyst.redact_stream_text(stream) == stream
    result = reply["result"]
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    assert result["structuredContent"]["result"]["value"] == {
        "api_key": "[REDACTED]",
        "note": "CENSUS_API_KEY=[REDACTED]",
        "observations": [1711.9, 1716.8],
    }


def test_failed_call_error_uses_the_same_bound_presentation(
    tmp_path: pathlib.Path,
) -> None:
    error = "public source diagnostic CENSUS_API_KEY=planted-fixture-value"

    def failed_fetch(_url: str) -> None:
        raise evidence.EvidenceError(error)

    command, entries = write_stage(
        tmp_path,
        tool="fetch_source",
        arguments={"url": "https://example.gov/series.json"},
        fetcher=failed_fetch,
    )
    capture = json.loads((tmp_path / "tool_evidence.json").read_text())
    assert capture["calls"][0]["status"] == "failed"
    assert capture["calls"][0]["error"] == error
    stream = (tmp_path / "codex_stdout.jsonl").read_text()
    assert "planted-fixture-value" not in stream
    native = json.loads(stream)["item"]["result"]
    assert native["is_error"] is True
    assert json.loads(native["content"][0]["text"]) == native["structured_content"]
    check(tmp_path, command, entries)


def test_credential_shaped_numeric_input_names_keep_exact_argument_binding(
    tmp_path: pathlib.Path,
) -> None:
    arguments = {"expression": "token + secret", "inputs": {"token": 1, "secret": 2}}
    command, entries = write_stage(tmp_path, arguments=arguments)
    native = json.loads((tmp_path / "codex_stdout.jsonl").read_text())["item"]
    assert native["arguments"] == arguments
    check(tmp_path, command, entries)


def test_redacted_arguments_do_not_gain_the_result_presentation_exception(
    tmp_path: pathlib.Path,
) -> None:
    # Arguments retain exact identity; presentation redaction is not permission
    # to accept an arbitrary different input, including on a failed call.
    command, entries = write_stage(
        tmp_path,
        arguments={
            "expression": "x",
            "inputs": {"x": "ghp_" + "PlantedFixtureValue"},
        },
    )
    with pytest.raises(
        custody.CustodyError, match=r"differs from its native event \(arguments\)"
    ) as caught:
        check(tmp_path, command, entries)
    assert "PlantedFixtureValue" not in str(caught.value)


@pytest.mark.parametrize(
    "arguments",
    [
        {"url": "http://example.gov/data.json"},
        {"url": "https://example.gov/data.json", "unexpected": "fixture"},
    ],
)
def test_rejected_fetch_binds_original_native_arguments_through_redaction(
    tmp_path: pathlib.Path,
    arguments: dict[str, Any],
) -> None:
    command, entries = write_stage(tmp_path, tool="fetch_source", arguments=arguments)
    events_path = tmp_path / "codex_stdout.jsonl"
    event = json.loads(events_path.read_text())
    assert event["item"]["arguments"] == {"url": evidence.REDACTED_URL}
    event["item"]["arguments"] = arguments
    events_path.write_text(json.dumps(event) + "\n")
    check(tmp_path, command, entries)

    event["item"]["arguments"] = {"url": "https://example.gov/data.json"}
    events_path.write_text(json.dumps(event) + "\n")
    with pytest.raises(
        custody.CustodyError, match=r"differs from its native event \(arguments\)"
    ):
        check(tmp_path, command, entries)


@pytest.mark.parametrize("missing", ["tool_evidence", "tool_evidence_verification"])
def test_declared_capture_requires_both_rooted_artifacts(
    tmp_path: pathlib.Path, missing: str
) -> None:
    command, entries = write_stage(tmp_path)
    entries = [entry for entry in entries if entry["artifactType"] != missing]
    with pytest.raises(
        custody.CustodyError, match="missing required inventory artifacts"
    ):
        check(tmp_path, command, entries)


def test_declaration_cannot_borrow_other_stage_artifacts(
    tmp_path: pathlib.Path,
) -> None:
    command, entries = write_stage(tmp_path, prefix="draft_")
    command["toolEvidence"]["artifact"] = "tool_evidence.json"
    with pytest.raises(custody.CustodyError, match="invalid tool evidence declaration"):
        check(tmp_path, command, entries, prefix="draft_")


@pytest.mark.parametrize("surviving", ["artifacts", "argv", "events"])
def test_deleting_declaration_does_not_downgrade_capture(
    tmp_path: pathlib.Path, surviving: str
) -> None:
    command, entries = write_stage(tmp_path)
    command.pop("toolEvidence")
    if surviving != "artifacts":
        entries = []
    if surviving != "argv":
        command["argv"] = ["codex"]
    if surviving != "events":
        (tmp_path / "codex_stdout.jsonl").write_text("")
    with pytest.raises(custody.CustodyError, match="undeclared tool evidence"):
        check(tmp_path, command, entries)


def test_legacy_stage_without_capture_keeps_existing_contract(
    tmp_path: pathlib.Path,
) -> None:
    assert check(tmp_path, {"backend": "codex", "argv": ["codex"]}, []) == set()


def test_report_cannot_claim_checks_that_replay_did_not_perform(
    tmp_path: pathlib.Path,
) -> None:
    command, entries = write_stage(tmp_path)
    report_path = tmp_path / "tool_evidence_verification.json"
    report = json.loads(report_path.read_text())
    report["checks"][0]["checks"].append("source_authenticity")
    report_path.write_text(json.dumps(report))
    with pytest.raises(custody.CustodyError, match="differs from trusted replay"):
        check(tmp_path, command, entries)


def test_rehashed_wrong_result_still_fails_replay(tmp_path: pathlib.Path) -> None:
    command, entries = write_stage(tmp_path)
    evidence_path = tmp_path / "tool_evidence.json"
    payload = json.loads(evidence_path.read_text())
    payload["calls"][0]["result"]["value"] += 1
    evidence_path.write_text(json.dumps(payload))
    report = evidence.verify_evidence(payload)
    report["evidenceSha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    (tmp_path / "tool_evidence_verification.json").write_text(json.dumps(report))
    with pytest.raises(
        custody.CustodyError, match="failed verification on a successful"
    ):
        check(tmp_path, command, entries)


@pytest.mark.parametrize(
    "failure", ["arguments", "result", "content", "status", "error"]
)
def test_native_event_must_agree_with_captured_call(
    tmp_path: pathlib.Path, failure: str
) -> None:
    command, entries = write_stage(tmp_path)
    events_path = tmp_path / "codex_stdout.jsonl"
    event = json.loads(events_path.read_text())
    item = event["item"]
    if failure == "arguments":
        item["arguments"]["inputs"]["base"] = 0
    elif failure == "result":
        item["result"]["structured_content"]["result"]["value"] = 0
    elif failure == "content":
        item["result"]["content"][0]["text"] = "{}"
    elif failure == "status":
        item["status"] = "failed"
    else:
        item["result"]["is_error"] = True
    events_path.write_text(json.dumps(event) + "\n")
    field = {"result": "structuredContent", "error": "isError"}.get(failure, failure)
    with pytest.raises(
        custody.CustodyError, match=rf"differs from its native event \({field}\)"
    ):
        check(tmp_path, command, entries)


def test_unknown_or_duplicate_native_call_is_refused(tmp_path: pathlib.Path) -> None:
    command, entries = write_stage(tmp_path)
    events_path = tmp_path / "codex_stdout.jsonl"
    events_path.write_text(events_path.read_text() * 2)
    with pytest.raises(custody.CustodyError, match="repeats a native completion event"):
        check(tmp_path, command, entries)


def test_unacknowledged_capture_only_survives_as_failed_run(
    tmp_path: pathlib.Path,
) -> None:
    command, entries = write_stage(tmp_path)
    (tmp_path / "codex_stdout.jsonl").write_text("")
    with pytest.raises(custody.CustodyError, match="lack native completion events"):
        check(tmp_path, command, entries)
    command["returnCode"] = 1
    check(tmp_path, command, entries, run_succeeded=False)
    with pytest.raises(custody.CustodyError, match="lack native completion events"):
        check(tmp_path, command, entries, run_succeeded=True)


def test_started_native_call_cannot_disappear_from_successful_capture(
    tmp_path: pathlib.Path,
) -> None:
    command, entries = write_stage(tmp_path)
    events_path = tmp_path / "codex_stdout.jsonl"
    started = json.loads(events_path.read_text())
    started["type"] = "item.started"
    started["item"]["id"] = "unfinished-call"
    started["item"]["status"] = "in_progress"
    started["item"].pop("result")
    events_path.write_text(events_path.read_text() + json.dumps(started) + "\n")
    with pytest.raises(custody.CustodyError, match="incomplete native calls"):
        check(tmp_path, command, entries)


def test_recorded_native_stage_cannot_switch_to_legacy_capture_mode(
    tmp_path: pathlib.Path,
) -> None:
    _command, entries = write_stage(tmp_path, prefix="draft_")
    _review, review_entries = write_stage(tmp_path, prefix="pre_submit_review_")
    command, final_entries = write_stage(tmp_path)
    command.pop("toolEvidence")
    (tmp_path / "command.json").write_text(json.dumps(command))
    with pytest.raises(custody.CustodyError, match="downgraded between native stages"):
        custody._verify_invocation_stages(
            tmp_path, {"ok": True}, entries + review_entries + final_entries
        )


def test_broken_capture_can_be_archived_only_as_failed_stage_and_run(
    tmp_path: pathlib.Path,
) -> None:
    command, entries = write_stage(tmp_path)
    payload = {**evidence.empty_evidence(), "captureError": "capture was malformed"}
    evidence_path = tmp_path / "tool_evidence.json"
    evidence_path.write_text(json.dumps(payload))
    report = evidence.verify_evidence(payload)
    report["evidenceSha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    (tmp_path / "tool_evidence_verification.json").write_text(json.dumps(report))
    command["returnCode"] = 1
    check(tmp_path, command, entries, run_succeeded=False)
    with pytest.raises(
        custody.CustodyError, match="failed verification on a successful"
    ):
        check(tmp_path, command, entries, run_succeeded=True)
    command["returnCode"] = 0
    with pytest.raises(
        custody.CustodyError, match="failed verification on a successful"
    ):
        check(tmp_path, command, entries, run_succeeded=False)


def test_receipt_custody_roots_evidence_and_replay_report(
    tmp_path: pathlib.Path,
) -> None:
    command, evidence_entries = write_stage(tmp_path)
    refs = []

    def artifact(kind: str, name: str, value: Any) -> None:
        text = value if isinstance(value, str) else json.dumps(value)
        refs.append(analyst.write_artifact(tmp_path, kind, name, text, CREATED))

    artifact("prompt", "prompt.md", "Synthetic fixture, never published")
    artifact("command", "command.json", command)
    artifact("stdout", "stdout.txt", "[]")
    artifact("stderr", "stderr.txt", "")
    for name, kind in custody.CODEX_STAGE_INVENTORY.items():
        if name == "codex_stdout.jsonl":
            value = (tmp_path / name).read_text()
        else:
            value = "{}" if name.endswith(".json") else ""
        artifact(kind, name, value)
    for entry in evidence_entries:
        artifact(
            entry["artifactType"], entry["path"], (tmp_path / entry["path"]).read_text()
        )
    artifact("raw_response", "raw_response.txt", "[]")
    artifact("parsed_cell", "parsed_cells.json", [{"slug": "fixture"}])
    artifact("normalized_cell", "normalized_cells.json", [{"slug": "fixture"}])
    artifact("run_distribution", "distribution.json", {"points": []})
    artifact("validation_report", "validation.json", {"ok": True})
    artifact(
        "cells_with_activity",
        "cells.with_activity.json",
        [{"slug": "fixture", "activityLog": copy.deepcopy(refs)}],
    )
    manifest = {
        "schemaVersion": "thesis_analyst_run_manifest_v1",
        "createdAt": CREATED,
        "ok": True,
        "preSubmitReview": None,
        "validation": {"ok": True},
        "cellsPath": str(tmp_path / "cells.with_activity.json"),
        "artifacts": refs,
    }
    analyst.finalize_manifest(tmp_path, CREATED, manifest, refs)
    assert custody.verify_run(tmp_path).run_succeeded
    (tmp_path / "tool_evidence.json").write_text("{}")
    with pytest.raises(custody.CustodyError, match="raw SHA-256 mismatch"):
        custody.verify_run(tmp_path)


def test_native_event_lines_with_unicode_line_separators_still_bind(
    tmp_path: pathlib.Path,
) -> None:
    # Codex writes JSON events with non-ASCII characters unescaped. A fetched
    # PDF excerpt carried U+0085 (NEL), which str.splitlines() treats as a
    # line break, so the verifier fragmented the completion event into two
    # unparseable pieces and reported "calls lack native completion events"
    # for a call whose event was present (roll-docket run 35526068252, draft
    # call-0009). Only newline characters delimit the JSONL stream.
    body = "line one\u0085line two\u2028line three\u2029\x0b\x0c\x1c%PDF".encode(
        "utf-8"
    )
    response = {
        "url": "https://example.gov/report.pdf",
        "status": 200,
        "headers": [["content-type", "application/pdf"]],
        "bodyBase64": base64.b64encode(body).decode("ascii"),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }
    command, entries = write_stage(
        tmp_path,
        tool="fetch_source",
        arguments={"url": response["url"]},
        fetcher=lambda _url: response,
        ensure_ascii=False,
    )
    payload = json.loads((tmp_path / "tool_evidence.json").read_text())
    assert payload["calls"][0]["status"] == "succeeded"
    assert "\u0085" in payload["calls"][0]["result"]["excerpt"]
    stream = (tmp_path / "codex_stdout.jsonl").read_text(encoding="utf-8")
    assert stream.count("\n") == 1
    assert len(stream.splitlines()) > 1  # the trap this test guards against

    assert check(tmp_path, command, entries) == {
        "tool_evidence.json",
        "tool_evidence_verification.json",
    }
