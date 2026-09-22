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
        json.dumps(event_for(call), ensure_ascii=ensure_ascii) + "\n",
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
    with pytest.raises(custody.CustodyError, match="differs from its native event"):
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
    with pytest.raises(custody.CustodyError, match="differs from its native event"):
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
