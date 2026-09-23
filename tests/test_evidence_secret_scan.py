"""Adversarial publication checks for authenticated embedded HTTP bodies.

All source responses are injected; no fixture uses a network or real credential.
The AWS-shaped base64 fixture decodes to harmless binary and exercises the
specific false positive that must not discard an otherwise intact run archive.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import archive_strategy_attempt as archive  # noqa: E402
import docket_publication as publication  # noqa: E402
import tool_evidence as evidence  # noqa: E402

URL = "https://example.gov/public-statistics.json"
INVALID = "invalid tool evidence secret-scan envelope"
AWS_SHAPED_BASE64 = b"AKIA" + b"A" * 16
HARMLESS_BINARY = base64.b64decode(AWS_SHAPED_BASE64, validate=True)
TOKEN_CASES = [
    ("GitHub token", b"ghp_" + b"a" * 36),
    ("GitHub token", b"github_pat_" + b"a" * 80),
    ("OpenAI API key", b"sk-" + b"a" * 24),
    ("OpenAI API key", b"sk-proj-" + b"a" * 24),
    ("AWS access key", b"AKIA" + b"B" * 16),
    ("AWS access key", b"ASIA" + b"C" * 16),
    ("Slack token", b"xoxb-" + b"a" * 24),
    ("private key", b"-----BEGIN " + b"PRIVATE KEY-----"),
    ("private key", b"-----BEGIN " + b"RSA PRIVATE KEY-----"),
    ("private key", b"-----BEGIN " + b"EC PRIVATE KEY-----"),
    ("private key", b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----"),
]


def encode(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()


def response(body: bytes, *, status: int = 200, headers=None) -> dict:
    return {
        "url": URL,
        "status": status,
        "headers": headers or [["content-type", "application/octet-stream"]],
        "bodyBase64": base64.b64encode(body).decode("ascii"),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }


@pytest.fixture
def capture(tmp_path):
    counter = 0

    def make(bodies=(HARMLESS_BINARY,), *, statuses=None, headers=None):
        nonlocal counter
        counter += 1
        codes = statuses or [200] * len(bodies)
        responses = iter(
            response(body, status=code, headers=headers)
            for body, code in zip(bodies, codes, strict=True)
        )
        recorder = evidence.EvidenceRecorder(
            tmp_path / f"captured-{counter}.json", fetcher=lambda _url: next(responses)
        )
        for _ in bodies:
            recorder.call("fetch_source", {"url": URL})
        assert evidence.verify_evidence(recorder.payload)["valid"]
        return recorder

    return make


def raw_hits(data: bytes) -> list[str]:
    return [
        name
        for name, pattern in publication.SECRET_PATTERNS.items()
        if pattern.search(data)
    ]


def test_authenticated_base64_coincidence_preserves_original_bytes_and_hash(capture):
    recorder = capture()
    original = recorder.output.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    payload = copy.deepcopy(recorder.payload)
    assert raw_hits(original) == ["AWS access key"]
    assert raw_hits(HARMLESS_BINARY) == []
    assert publication.scan_bytes(original) == []
    assert recorder.output.read_bytes() == original
    assert hashlib.sha256(recorder.output.read_bytes()).hexdigest() == digest
    assert recorder.payload == payload
    assert (
        recorder.payload["calls"][0]["response"]["bodyBase64"].encode()
        == AWS_SHAPED_BASE64
    )


@pytest.mark.parametrize(("kind", "token"), TOKEN_CASES)
def test_every_secret_family_is_scanned_in_complete_decoded_body(capture, kind, token):
    body = b"ordinary source text\n" + b"." * evidence.EXCERPT_BYTES + b"\n" + token
    recorder = capture((body,))
    raw = recorder.output.read_bytes()
    assert token not in raw
    assert token.decode() not in recorder.payload["calls"][0]["result"]["excerpt"]
    assert recorder.payload["calls"][0]["result"]["excerptTruncated"] is True
    assert kind in publication.scan_bytes(raw)


@pytest.mark.parametrize(("kind", "token"), TOKEN_CASES)
def test_escaped_metadata_values_are_decoded_before_scanning(capture, kind, token):
    recorder = capture(
        (b"public series 42",), headers=[["x-public-note", token.decode()]]
    )
    raw = encode(recorder.payload)
    escaped = "".join(f"\\u{byte:04x}" for byte in token).encode()
    raw = raw.replace(token, escaped)
    assert raw_hits(raw) == []
    assert evidence.verify_evidence(evidence._strict_json(raw))["valid"]
    assert kind in publication.scan_bytes(raw)


def test_escaped_metadata_keys_are_scanned_even_in_failed_calculations(capture):
    recorder = capture((b"public series 42",))
    secret_key = "ghp_" + "a" * 36
    failed = recorder.call("calculate", {secret_key: "public value"})
    assert failed["status"] == "failed"
    assert evidence.verify_evidence(recorder.payload)["valid"]
    raw = encode(recorder.payload).replace(
        secret_key.encode(),
        "".join(f"\\u{ord(char):04x}" for char in secret_key).encode(),
    )
    assert raw_hits(raw) == []
    assert "GitHub token" in publication.scan_bytes(raw)


def test_arbitrary_base64_metadata_is_not_exempt(capture):
    recorder = capture(headers=[["x-source-note", AWS_SHAPED_BASE64.decode()]])
    assert publication.scan_bytes(recorder.output.read_bytes()) == ["AWS access key"]


def test_base64_named_key_in_other_paths_is_not_exempt(capture):
    recorder = capture()
    failed = recorder.call("calculate", {"bodyBase64": AWS_SHAPED_BASE64.decode()})
    assert failed["status"] == "failed"
    assert evidence.verify_evidence(recorder.payload)["valid"]
    assert publication.scan_bytes(recorder.output.read_bytes()) == ["AWS access key"]


def test_valid_legacy_call_without_projection_marker_keeps_body_exemption(capture):
    recorder = capture()
    del recorder.payload["calls"][0]["terminalProjectionVersion"]
    assert evidence.verify_evidence(recorder.payload)["valid"]
    assert publication.scan_bytes(encode(recorder.payload)) == []


def test_valid_extraction_and_calculation_replays_keep_capture_exemption(capture):
    recorder = capture((b'{"count": 42}', HARMLESS_BINARY))
    recorder.call("extract_json", {"sourceCallId": "call-0001", "pointer": "/count"})
    recorder.call(
        "calculate",
        {"expression": "count + 1", "inputs": {"count": {"callId": "call-0003"}}},
    )
    assert evidence.verify_evidence(recorder.payload)["valid"]
    assert publication.scan_bytes(recorder.output.read_bytes()) == []


def test_unknown_schema_retains_raw_scan_and_never_exempts_capture(capture):
    recorder = capture()
    recorder.payload["schemaVersion"] = "unreviewed_evidence_v999"
    raw = encode(recorder.payload)
    assert publication.scan_bytes(raw) == raw_hits(raw) == ["AWS access key"]


@pytest.mark.parametrize("status", [200, 204, 301, 404, 500])
def test_each_embedded_response_is_checked_including_failed_http(capture, status):
    recorder = capture((HARMLESS_BINARY, HARMLESS_BINARY), statuses=[200, status])
    assert publication.scan_bytes(recorder.output.read_bytes()) == []
    if status >= 300:
        assert recorder.payload["calls"][1]["status"] == "failed"
    secret = b"sk-" + b"a" * 24
    recorder = capture(
        (HARMLESS_BINARY, b"." * evidence.EXCERPT_BYTES + secret),
        statuses=[200, status],
    )
    assert "OpenAI API key" in publication.scan_bytes(recorder.output.read_bytes())


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-hash",
        "wrong-size",
        "bool-size",
        "missing-body",
        "noncanonical-base64",
        "invalid-base64",
        "unknown-top-field",
        "unknown-call-field",
        "unknown-response-field",
        "unknown-tool",
        "unknown-capture-method",
        "unknown-projection-version",
        "bool-projection-version",
        "float-projection-version",
        "forged-result",
        "mismatched-url",
        "mismatched-call-id",
    ],
)
def test_invalid_envelopes_never_receive_any_base64_exemption(capture, mutation):
    recorder = capture((HARMLESS_BINARY, HARMLESS_BINARY))
    payload = copy.deepcopy(recorder.payload)
    call = payload["calls"][1]
    embedded = call["response"]
    if mutation == "wrong-hash":
        embedded["sha256"] = "0" * 64
    elif mutation == "wrong-size":
        embedded["bytes"] += 1
    elif mutation == "bool-size":
        embedded["bytes"] = True
    elif mutation == "missing-body":
        del embedded["bodyBase64"]
    elif mutation == "noncanonical-base64":
        embedded["bodyBase64"] += "="
    elif mutation == "invalid-base64":
        embedded["bodyBase64"] += "!"
    elif mutation == "unknown-top-field":
        payload["unexpected"] = "public"
    elif mutation == "unknown-call-field":
        call["unexpected"] = "public"
    elif mutation == "unknown-response-field":
        embedded["unexpected"] = "public"
    elif mutation == "unknown-tool":
        call["tool"] = "unregistered_fetch"
    elif mutation == "unknown-capture-method":
        payload["captureMethod"] = "uncontrolled-tools"
    elif mutation == "unknown-projection-version":
        call["terminalProjectionVersion"] = 2
    elif mutation == "bool-projection-version":
        call["terminalProjectionVersion"] = True
    elif mutation == "float-projection-version":
        call["terminalProjectionVersion"] = 1.0
    elif mutation == "forged-result":
        call["result"]["excerpt"] = "not the captured source"
    elif mutation == "mismatched-url":
        embedded["url"] = "https://example.gov/other-series"
    elif mutation == "mismatched-call-id":
        call["callId"] = "call-0001"
    assert not evidence.verify_evidence(payload)["valid"]
    assert set(publication.scan_bytes(encode(payload))) == {INVALID, "AWS access key"}


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-root",
        "duplicate-response",
        "duplicate-escaped-key",
        "trailing",
        "truncated",
    ],
)
def test_ambiguous_or_incomplete_json_receives_no_exemption(capture, mutation):
    raw = encode(capture().payload)
    if mutation == "duplicate-root":
        raw = raw.replace(b'"calls":', b'"calls": [], "calls":', 1)
    elif mutation == "duplicate-response":
        raw = raw.replace(b'"bytes":', b'"bytes": 0, "bytes":', 1)
    elif mutation == "duplicate-escaped-key":
        raw = raw.replace(b'"bytes":', b'"b\\u0079tes": 0, "bytes":', 1)
    elif mutation == "trailing":
        raw += b' {"extra": true}'
    else:
        raw = raw[:-3]
    assert set(publication.scan_bytes(raw)) == {INVALID, "AWS access key"}


@pytest.mark.parametrize("escaped_schema", [False, True])
def test_truncated_capture_cannot_hide_a_decoded_secret(capture, escaped_schema):
    secret = b"sk-" + b"a" * 24
    recorder = capture((b"." * evidence.EXCERPT_BYTES + secret,))
    raw = encode(recorder.payload)[:-3]
    if escaped_schema:
        raw = raw.replace(b'"schemaVersion"', b'"schema\\u0056ersion"').replace(
            b"thesis_tool_evidence_v1", b"thesis_tool_evidence_\\u00761"
        )
    assert raw_hits(raw) == []
    assert INVALID in publication.scan_bytes(raw)


def test_body_secret_is_scanned_even_when_its_json_characters_are_escaped(capture):
    token = b"AKIA" + b"B" * 16
    recorder = capture((b"." * evidence.EXCERPT_BYTES + token,))
    raw = encode(recorder.payload)
    embedded = recorder.payload["calls"][0]["response"]["bodyBase64"].encode()
    raw = raw.replace(embedded, "".join(f"\\u{byte:04x}" for byte in embedded).encode())
    assert evidence.verify_evidence(evidence._strict_json(raw))["valid"]
    assert "AWS access key" in publication.scan_bytes(raw)


def test_non_ascii_offsets_do_not_skip_neighboring_metadata(capture):
    headers = [["x-before", '日本語 naïve "quoted" \\ slash 🧾'], ["x-after", "fin"]]
    recorder = capture(headers=headers)
    payload = recorder.payload
    # Place the response body between multi-byte text and a second string.
    original_response = payload["calls"][0]["response"]
    payload["calls"][0]["response"] = {
        key: original_response[key]
        for key in ("headers", "bodyBase64", "url", "status", "sha256", "bytes")
    }
    raw = encode(payload)
    assert publication.scan_bytes(raw) == []
    escaped_key = raw.replace(b'"bodyBase64"', b'"body\\u0042ase64"')
    assert publication.scan_bytes(escaped_key) == []
    headers[1][1] = "sk-" + "a" * 24
    assert "OpenAI API key" in publication.scan_bytes(encode(payload))


@pytest.mark.parametrize(
    ("limit", "value"),
    [
        ("MAX_RESPONSE_BYTES", len(HARMLESS_BINARY) - 1),
        ("MAX_TOTAL_RESPONSE_BYTES", len(HARMLESS_BINARY)),
        ("MAX_ARTIFACT_BYTES", 1),
        ("MAX_CALLS", 1),
    ],
)
def test_existing_resource_bounds_are_enforced_without_large_allocations(
    capture, monkeypatch, limit, value
):
    recorder = capture((HARMLESS_BINARY, HARMLESS_BINARY))
    raw = recorder.output.read_bytes()
    monkeypatch.setattr(evidence, limit, value)
    assert set(publication.scan_bytes(raw)) == {INVALID, "AWS access key"}


def test_maximum_call_count_is_not_exempted(capture):
    payload = capture().payload
    first = payload["calls"][0]
    payload["calls"] = [copy.deepcopy(first) for _ in range(129)]
    for index, call in enumerate(payload["calls"], 1):
        call["callId"] = f"call-{index:04d}"
    assert set(publication.scan_bytes(encode(payload))) == {INVALID, "AWS access key"}


def test_oversized_escaped_envelope_cannot_hide_decoded_secret(capture, monkeypatch):
    token = b"sk-" + b"a" * 24
    payload = capture((b"." * evidence.EXCERPT_BYTES + token,)).payload
    # Put marker fields last as well as escaping their names/values. Oversized
    # candidates must block without relying on a prefix or literal marker.
    payload = {key: payload[key] for key in ("calls", "captureMethod", "schemaVersion")}
    raw = encode(payload).replace(
        b"thesis_tool_evidence_v1", b"thesis_tool_evidence_\\u00761"
    )
    raw = raw.replace(b'"captureMethod"', b'"capture\\u004dethod"')
    assert raw_hits(raw) == []
    monkeypatch.setattr(evidence, "MAX_ARTIFACT_BYTES", len(raw) - 1)
    assert publication.scan_bytes(raw) == [INVALID]


def test_oversized_unclassified_json_blocks_before_parsing(monkeypatch):
    raw = b'{"schemaVersion": "unknown", "payload": "opaque"}'
    monkeypatch.setattr(evidence, "MAX_ARTIFACT_BYTES", len(raw) - 1)
    assert publication.scan_bytes(raw) == [INVALID]


def test_oversized_non_json_keeps_raw_secret_checks(monkeypatch):
    monkeypatch.setattr(evidence, "MAX_ARTIFACT_BYTES", 1)
    assert publication.scan_bytes(b"ordinary raw source") == []
    assert publication.scan_bytes(b"ordinary " + AWS_SHAPED_BASE64) == [
        "AWS access key"
    ]


def test_iterative_offsets_handle_deep_valid_metadata_without_false_rejection(capture):
    recorder = capture()
    nested: object = "public"
    for _ in range(65):
        nested = [nested]
    recorder.call("calculate", {"unexpected": nested})
    # A failed calculation remains valid evidence. The iterative offset walk
    # must not impose a new schema restriction on its deeply nested arguments.
    assert evidence.verify_evidence(recorder.payload)["valid"]
    assert publication.scan_bytes(recorder.output.read_bytes()) == []


@pytest.mark.parametrize(
    "raw",
    [
        b"ordinary text",
        b"{not JSON",
        b'{"bodyBase64":"public"}',
        b'{"calls":[],"schemaVersion":"other"}',
    ],
)
def test_non_evidence_documents_keep_existing_raw_scan_behavior(raw):
    assert publication.scan_bytes(raw) == raw_hits(raw)
    with_token = raw + b" " + AWS_SHAPED_BASE64
    assert publication.scan_bytes(with_token) == raw_hits(with_token)


def test_nested_evidence_in_native_jsonl_does_not_gain_an_exemption(capture):
    event = {
        "type": "item.completed",
        "item": {"type": "mcp_tool_call", "structuredContent": capture().payload},
    }
    raw = encode(event) + encode({"type": "turn.completed"})
    assert publication.scan_bytes(raw) == raw_hits(raw) == ["AWS access key"]


def test_invalid_utf8_envelope_never_gains_an_exemption(capture):
    raw = encode(capture(headers=[["x-note", "valid text"]]).payload)
    raw = raw.replace(b"valid text", b"invalid \xff text")
    assert set(publication.scan_bytes(raw)) == {INVALID, "AWS access key"}


def git(root: pathlib.Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


@pytest.fixture
def diagnostic_checkout(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    (root / "README.md").write_text("diagnostic fixture\n")
    git(root, "add", "README.md")
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.org",
        "commit",
        "-m",
        "base",
    )
    selection = tmp_path / "selection.json"
    selection.write_bytes(
        encode(
            {
                "sourceSha": git(root, "rev-parse", "HEAD"),
                "workflow": {"runId": 123, "runAttempt": 1},
            }
        )
    )
    return root, selection


def test_diagnostic_archive_retains_binary_coincidence_and_omits_decoded_secret(
    capture, diagnostic_checkout, tmp_path
):
    root, selection = diagnostic_checkout
    directory = root / "records/thesis-analyst/failed-attempt"
    directory.mkdir(parents=True)
    safe = capture().output.read_bytes()
    secret = b"ghp_" + b"a" * 36
    unsafe = capture((b"." * evidence.EXCERPT_BYTES + secret,)).output.read_bytes()
    (directory / "draft_tool_evidence.json").write_bytes(safe)
    (directory / "final_tool_evidence.json").write_bytes(unsafe)
    output = tmp_path / "diagnostic"
    result = archive.archive_attempt(root, selection, output, 123, 1)
    safe_path = "records/thesis-analyst/failed-attempt/draft_tool_evidence.json"
    unsafe_path = "records/thesis-analyst/failed-attempt/final_tool_evidence.json"
    assert result["publishable"] is False
    assert result["files"] == [
        {
            "path": safe_path,
            "bytes": len(safe),
            "sha256": hashlib.sha256(safe).hexdigest(),
        }
    ]
    assert result["omitted"] == [{"path": unsafe_path, "reason": "possible secret"}]
    assert (output / "files" / safe_path).read_bytes() == safe
    assert not (output / "files" / unsafe_path).exists()
    assert secret not in (output / "attempt_manifest.json").read_bytes()
    assert (directory / "final_tool_evidence.json").read_bytes() == unsafe


def test_staged_publication_uses_decoded_scan_without_rewriting_evidence(
    capture, diagnostic_checkout, monkeypatch
):
    root, _ = diagnostic_checkout
    target = root / "evidence.json"
    raw = capture().output.read_bytes()
    target.write_bytes(raw)
    git(root, "add", "evidence.json")
    monkeypatch.setattr(publication, "ROOT", root)
    publication.scan_staged(argparse.Namespace())
    assert target.read_bytes() == raw
    assert subprocess.check_output(["git", "show", ":evidence.json"], cwd=root) == raw
    secret = b"xoxb-" + b"a" * 24
    target.write_bytes(
        capture((b"." * evidence.EXCERPT_BYTES + secret,)).output.read_bytes()
    )
    git(root, "add", "evidence.json")
    with pytest.raises(publication.PublicationError, match="Slack token"):
        publication.scan_staged(argparse.Namespace())
