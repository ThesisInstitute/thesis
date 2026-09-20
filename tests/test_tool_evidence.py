from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import pathlib
import socket
import subprocess
import sys
from email.message import Message

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import announcement_fetch_mcp as transport  # noqa: E402
import tool_evidence as evidence  # noqa: E402
import tool_evidence_mcp as mcp  # noqa: E402

URL = "https://example.gov/series.json?period=2026-05"
BODY = b'{"count":"1711.9","history":["1700.0","1702.0","1708.0"],"a/b":{"~":[4.9]}}'


def capture(body=BODY, *, status=200, url=URL):
    return {
        "url": url,
        "status": status,
        "headers": [["content-type", "application/json"]],
        "bodyBase64": base64.b64encode(body).decode("ascii"),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }


@pytest.fixture
def recorder(tmp_path):
    return evidence.EvidenceRecorder(
        tmp_path / "tool_evidence.json", fetcher=lambda url: capture(url=url)
    )


def linked_calls(recorder):
    source = recorder.call("fetch_source", {"url": URL})
    extracted = recorder.call(
        "extract_json", {"sourceCallId": source["callId"], "pointer": "/count"}
    )
    calculated = recorder.call(
        "calculate",
        {
            "expression": "round(base + adjustment, 1)",
            "inputs": {"base": {"callId": extracted["callId"]}, "adjustment": 4.9},
        },
    )
    return source, extracted, calculated


def test_complete_body_and_replay_are_bound_to_actual_inputs(recorder):
    source, extracted, calculated = linked_calls(recorder)
    assert base64.b64decode(source["response"]["bodyBase64"]) == BODY
    assert extracted["result"] == {"value": "1711.9"}
    assert calculated["result"] == {
        "value": 1716.8,
        "resolvedInputs": {"adjustment": 4.9, "base": 1711.9},
    }
    report = evidence.verify_evidence(evidence.load_evidence(recorder.output))
    assert report["valid"]
    assert report["succeededCount"] == 3
    assert report["failedCount"] == 0
    assert [check["status"] for check in report["checks"]] == [
        "captured",
        "replayed",
        "replayed",
    ]
    assert report["checks"][0]["checks"] == [
        "response_sha256",
        "response_bytes",
        "fetch_result",
    ]
    assert len(report["evidenceCanonicalSha256"]) == 64
    assert json.loads(recorder.output.read_text()) == recorder.payload


def test_statistics_on_captured_numeric_strings(recorder):
    recorder.call("fetch_source", {"url": URL})
    recorder.call("extract_json", {"sourceCallId": "call-0001", "pointer": "/history"})
    call = recorder.call(
        "calculate",
        {
            "expression": "stdev(diff(history))",
            "inputs": {"history": {"callId": "call-0002"}},
        },
    )
    assert call["status"] == "succeeded"
    assert call["result"]["value"] == pytest.approx(2.8284271247461903)
    assert call["result"]["resolvedInputs"] == {"history": [1700.0, 1702.0, 1708.0]}
    assert evidence.verify_evidence(recorder.payload)["valid"]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("mean(values)", 3),
        ("median(values)", 3),
        ("min(values)", 1),
        ("max(values)", 5),
        ("diff(values)", [2, 2]),
        ("sqrt(9) + abs(-1)", 4),
        ("round(4.444, 2)", 4.44),
        ("-2 + 3**2 // 2 % 3", -1),
    ],
)
def test_supported_arithmetic_is_replayable(recorder, expression, expected):
    call = recorder.call(
        "calculate", {"expression": expression, "inputs": {"values": [1, 3, 5]}}
    )
    assert call["status"] == "succeeded"
    assert call["result"]["value"] == expected
    assert evidence.verify_evidence(recorder.payload)["valid"]


def test_pointer_escape_and_array_index(recorder):
    recorder.call("fetch_source", {"url": URL})
    result = recorder.call(
        "extract_json", {"sourceCallId": "call-0001", "pointer": "/a~1b/~0/0"}
    )
    assert result["result"] == {"value": 4.9}
    assert evidence.verify_evidence(recorder.payload)["valid"]


@pytest.mark.parametrize(
    "pointer", ["/a~2b", "/history/-1", "/history/00", "/missing", "../../etc/passwd"]
)
def test_bad_pointers_are_captured_failures(recorder, pointer):
    recorder.call("fetch_source", {"url": URL})
    call = recorder.call(
        "extract_json", {"sourceCallId": "call-0001", "pointer": pointer}
    )
    assert call["status"] == "failed"
    assert call["result"] is None
    report = evidence.verify_evidence(recorder.payload)
    assert report["valid"]
    assert report["checks"][-1]["status"] == "failed"
    assert "json_pointer_replay" not in report["checks"][-1]["checks"]


@pytest.mark.parametrize(
    "call_id", ["../../private.json", "call-0002", "/etc/passwd", "file:///etc/passwd"]
)
def test_extraction_cannot_read_files_or_future_calls(recorder, call_id):
    call = recorder.call("extract_json", {"sourceCallId": call_id, "pointer": "/count"})
    assert call["status"] == "failed"
    assert "earlier captured call" in call["error"]


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "(1).__class__",
        "[x for x in values]",
        "values[0]",
        "[0] * 1000000000",
        "2**1000000000",
        "2**(2**32)",
        "1/0",
        "sqrt(-1)",
        "True",
        "'hello'",
        "float('nan')",
        "round(1, 100000)",
        "sum(values)",
        "lambda: 1",
        "stdev(1)",
        "mean()",
        "values * 2",
        "2**(-1)**0.5",
        "1e999",
    ],
)
def test_calculator_refuses_unsafe_or_undefined_expressions(recorder, expression):
    call = recorder.call(
        "calculate", {"expression": expression, "inputs": {"values": [1, 2]}}
    )
    assert call["status"] == "failed"
    assert call["result"] is None
    assert evidence.verify_evidence(recorder.payload)["valid"]


@pytest.mark.parametrize(
    "value", [True, "1.23", [[1]], [1] * 513, {"callId": "call-0999"}]
)
def test_calculator_rejects_undeclared_types_and_missing_references(recorder, value):
    call = recorder.call("calculate", {"expression": "x", "inputs": {"x": value}})
    assert call["status"] == "failed"


@pytest.mark.parametrize(
    "source_value", [" 1.2", "1,200", "NaN", "Infinity", "1e999", "01", "1+2"]
)
def test_source_numeric_string_conversion_is_strict(tmp_path, source_value):
    recorder = evidence.EvidenceRecorder(
        tmp_path / "evidence.json",
        fetcher=lambda _url: capture(json.dumps({"count": source_value}).encode()),
    )
    _, _, call = linked_calls(recorder)
    assert call["status"] == "failed"


@pytest.mark.parametrize(
    "body", [b'{"count":1,"count":2}', b'{"count":NaN}', b"not json"]
)
def test_ambiguous_or_invalid_json_cannot_supply_extraction(tmp_path, body):
    recorder = evidence.EvidenceRecorder(
        tmp_path / "evidence.json", fetcher=lambda _url: capture(body)
    )
    recorder.call("fetch_source", {"url": URL})
    call = recorder.call(
        "extract_json", {"sourceCallId": "call-0001", "pointer": "/count"}
    )
    assert call["status"] == "failed"
    assert evidence.verify_evidence(recorder.payload)["valid"]


@pytest.mark.parametrize(
    "tamper",
    [
        "body",
        "missing_body",
        "hash",
        "byte_count",
        "excerpt",
        "extraction",
        "calculation",
        "input",
        "pointer",
        "call_order",
        "timestamp",
        "url",
        "response_path",
    ],
)
def test_offline_verifier_rejects_tampered_evidence(recorder, tamper):
    linked_calls(recorder)
    payload = copy.deepcopy(recorder.payload)
    source, extracted, calculated = payload["calls"]
    if tamper == "body":
        source["response"]["bodyBase64"] = base64.b64encode(BODY + b" ").decode()
    elif tamper == "missing_body":
        del source["response"]["bodyBase64"]
    elif tamper == "hash":
        source["response"]["sha256"] = "0" * 64
    elif tamper == "byte_count":
        source["response"]["bytes"] += 1
    elif tamper == "excerpt":
        source["result"]["excerpt"] = "Model-authored replacement"
    elif tamper == "extraction":
        extracted["result"]["value"] = "1111.1"
    elif tamper == "calculation":
        calculated["result"]["value"] = 0
    elif tamper == "input":
        calculated["result"]["resolvedInputs"]["base"] = 9999
    elif tamper == "pointer":
        extracted["arguments"]["pointer"] = "/history"
    elif tamper == "call_order":
        source["callId"] = "call-9999"
    elif tamper == "timestamp":
        source["completedAt"] = "2000-01-01T00:00:00Z"
    elif tamper == "url":
        source["response"]["url"] = "https://different.gov/"
    elif tamper == "response_path":
        del source["response"]["bodyBase64"]
        source["response"]["path"] = "../../etc/passwd"
    report = evidence.verify_evidence(payload)
    assert not report["valid"]
    assert report["errors"]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "hello",
        42,
        {},
        {"schemaVersion": "forged"},
        {"calls": []},
        {**evidence.empty_evidence(), "captureError": "missing file"},
    ],
)
def test_verifier_handles_arbitrary_json_without_crashing(payload):
    assert evidence.verify_evidence(payload)["valid"] is False


@pytest.mark.parametrize("status", [302, 404, 503])
def test_http_error_responses_are_preserved_as_failed_calls(tmp_path, status):
    recorder = evidence.EvidenceRecorder(
        tmp_path / "evidence.json", fetcher=lambda _url: capture(status=status)
    )
    call = recorder.call("fetch_source", {"url": URL})
    assert call["status"] == "failed"
    assert call["response"]["status"] == status
    assert base64.b64decode(call["response"]["bodyBase64"]) == BODY
    report = evidence.verify_evidence(recorder.payload)
    assert report["valid"]
    assert report["failedCount"] == 1
    assert report["checks"][0]["status"] == "failed"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.gov/",
        "file:///etc/passwd",
        "https://user:SECRET@example.gov/",
        "https://example.gov/?api_key=SECRET",
        "https://example.gov/?access-token=SECRET",
        "https://example.gov/?%61uthorization=SECRET",
        "https://example.gov/?X-Amz-Credential=SECRET",
        "https://127.0.0.1/",
        "https://[::ffff:127.0.0.1]/",
        "https://localhost/",
        "https://example.gov:8443/",
        "https://example.gov/#SECRET",
        "https://example.gov/\r\nSECRET",
    ],
)
def test_unsafe_urls_are_refused_without_persisting_sensitive_values(tmp_path, url):
    recorder = evidence.EvidenceRecorder(
        tmp_path / "evidence.json", fetcher=lambda _url: pytest.fail("must not fetch")
    )
    call = recorder.call("fetch_source", {"url": url})
    assert call["status"] == "failed"
    assert call["arguments"] == {"url": evidence.REDACTED_URL}
    assert "SECRET" not in recorder.output.read_text()
    assert evidence.verify_evidence(recorder.payload)["valid"]


def test_fetch_arguments_cannot_smuggle_headers_into_archive(recorder):
    call = recorder.call("fetch_source", {"url": URL, "Authorization": "SECRET"})
    assert call["status"] == "failed"
    assert "SECRET" not in recorder.output.read_text()


def test_public_argument_projection_matches_only_actually_refused_requests(recorder):
    secret_args = {"url": "https://example.gov/?api_key=SECRET"}
    call = recorder.call("fetch_source", secret_args)
    assert call["arguments"] == evidence.captured_arguments("fetch_source", secret_args)
    # The public native trace can replace the secret value without affecting the
    # deterministic credential-refusal projection; the query name stays visible.
    redacted_native = {"url": "https://example.gov/?api_key=[REDACTED]"}
    assert call["arguments"] == evidence.captured_arguments(
        "fetch_source", redacted_native
    )
    assert call["arguments"] != evidence.captured_arguments(
        "fetch_source", {"url": URL}
    )
    assert evidence.captured_arguments(
        "fetch_source", {"url": URL, "header": "SECRET"}
    ) == {"url": evidence.REDACTED_URL}
    calculate = {"expression": "x+1", "inputs": {"x": 2}}
    assert evidence.captured_arguments("calculate", calculate) == calculate


@pytest.mark.parametrize(
    "url",
    [
        "https://example.gov/?api_key=SECRET",
        "https://user:SECRET@example.gov/",
        "https://user:SECRET@[malformed/",
        "https://example.gov/?%61uthorization=SECRET",
        "https://example.gov/?X-Amz-Credential=SECRET",
    ],
)
def test_credential_url_rule_is_shared_with_native_trace_redaction(url):
    assert evidence.url_contains_credentials(url)
    assert evidence.captured_arguments("fetch_source", {"url": url}) == {
        "url": evidence.REDACTED_URL
    }


@pytest.mark.parametrize(
    "url", [URL, "http://example.gov/data", "https://127.0.0.1/", evidence.REDACTED_URL]
)
def test_noncredential_refusals_are_not_misclassified_as_secrets(url):
    assert not evidence.url_contains_credentials(url)


def test_fetch_errors_do_not_echo_arbitrary_exception_messages(tmp_path):
    def raises(_url):
        raise RuntimeError("SECRET")

    recorder = evidence.EvidenceRecorder(tmp_path / "evidence.json", fetcher=raises)
    call = recorder.call("fetch_source", {"url": URL})
    assert call["error"] == "tool execution failed (RuntimeError)"
    assert "SECRET" not in recorder.output.read_text()


def test_complete_body_is_retained_when_excerpt_is_shorter(recorder, monkeypatch):
    monkeypatch.setattr(evidence, "EXCERPT_BYTES", 10)
    call = recorder.call("fetch_source", {"url": URL})
    assert call["result"]["excerpt"] == BODY[:10].decode()
    assert call["result"]["excerptTruncated"]
    assert base64.b64decode(call["response"]["bodyBase64"]) == BODY
    assert evidence.verify_evidence(recorder.payload)["valid"]


def test_total_capture_limit_fails_instead_of_truncating(recorder, monkeypatch):
    monkeypatch.setattr(evidence, "MAX_TOTAL_RESPONSE_BYTES", len(BODY))
    first = recorder.call("fetch_source", {"url": URL})
    second = recorder.call("fetch_source", {"url": URL})
    assert first["status"] == "succeeded"
    assert second["status"] == "failed"
    assert "response" not in second
    assert "limit" in second["error"]
    assert evidence.verify_evidence(recorder.payload)["valid"]


def test_hard_call_limit_preserves_existing_calls(recorder, monkeypatch):
    monkeypatch.setattr(evidence, "MAX_CALLS", 1)
    recorder.call("calculate", {"expression": "1+1", "inputs": {}})
    with pytest.raises(evidence.EvidenceError, match="call limit"):
        recorder.call("calculate", {"expression": "1+2", "inputs": {}})
    assert len(evidence.load_evidence(recorder.output)["calls"]) == 1


def test_output_is_incremental_and_session_cannot_overwrite_prior_calls(recorder):
    assert evidence.load_evidence(recorder.output) == evidence.empty_evidence()
    recorder.call("calculate", {"expression": "1+1", "inputs": {}})
    assert len(evidence.load_evidence(recorder.output)["calls"]) == 1
    recorder.call("calculate", {"expression": "1+2", "inputs": {}})
    assert len(evidence.load_evidence(recorder.output)["calls"]) == 2
    assert not list(recorder.output.parent.glob(".tool-evidence-*"))
    with pytest.raises(evidence.EvidenceError, match="previous evidence session"):
        evidence.EvidenceRecorder(recorder.output)


def test_initial_empty_artifact_can_be_used(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence.empty_evidence()))
    assert evidence.EvidenceRecorder(path).payload == evidence.empty_evidence()


def test_symlink_output_and_load_are_refused(tmp_path):
    source, link = tmp_path / "source.json", tmp_path / "link.json"
    source.write_text(json.dumps(evidence.empty_evidence()))
    link.symlink_to(source)
    with pytest.raises(evidence.EvidenceError, match="symlink"):
        evidence.EvidenceRecorder(link)
    with pytest.raises(evidence.EvidenceError, match="symlink"):
        evidence.load_evidence(link)


def test_mcp_terminal_payload_is_exact_and_excludes_body(recorder):
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "fetch_source", "arguments": {"url": URL}},
    }
    reply = mcp.handle_request(request, recorder)
    assert reply["result"]["structuredContent"] == evidence.terminal_call(
        recorder.payload["calls"][0]
    )
    assert "response" not in reply["result"]["structuredContent"]
    assert reply["result"]["isError"] is False
    assert (
        json.loads(reply["result"]["content"][0]["text"])
        == reply["result"]["structuredContent"]
    )


def test_no_fetch_stage_omits_tool_and_refuses_direct_call(tmp_path):
    recorder = evidence.EvidenceRecorder(
        tmp_path / "evidence.json",
        allow_fetch=False,
        fetcher=lambda _url: pytest.fail("must not fetch"),
    )
    reply = mcp.handle_request({"id": 1, "method": "tools/list"}, recorder)
    assert {tool["name"] for tool in reply["result"]["tools"]} == {
        "extract_json",
        "calculate",
    }
    call = recorder.call("fetch_source", {"url": URL})
    assert call["status"] == "failed"
    assert "disabled" in call["error"]


def test_mcp_stdio_and_verifier_cli_run_end_to_end(tmp_path):
    path = tmp_path / "evidence.json"
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "calculate",
                "arguments": {"expression": "1+2", "inputs": {}},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "calculate",
                "arguments": {"expression": "1/0", "inputs": {}},
            },
        },
    ]
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/tool_evidence_mcp.py"),
            "--output",
            str(path),
            "--no-fetch",
        ],
        input="\n".join(json.dumps(message) for message in messages) + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(replies) == 3
    assert replies[-2]["result"]["structuredContent"]["result"]["value"] == 3
    assert replies[-1]["result"]["isError"] is True
    verified = subprocess.run(
        [sys.executable, str(ROOT / "scripts/tool_evidence.py"), "--verify", str(path)],
        text=True,
        capture_output=True,
        check=True,
    )
    report = json.loads(verified.stdout)
    assert report["valid"] and report["failedCount"] == 1
    payload = json.loads(path.read_text())
    payload["calls"][0]["result"]["value"] = 99
    path.write_text(json.dumps(payload))
    invalid = subprocess.run(
        [sys.executable, str(ROOT / "scripts/tool_evidence.py"), "--verify", str(path)],
        text=True,
        capture_output=True,
    )
    assert invalid.returncode == 1
    assert json.loads(invalid.stdout)["valid"] is False


class FakeResponse:
    def __init__(self, body=BODY, *, status=200, length=None):
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self.headers["Set-Cookie"] = "session=SECRET"
        if length is not None:
            self.headers["Content-Length"] = str(length)
        self._body = io.BytesIO(body)

    def read(self, size):
        return self._body.read(size)


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.closed = False

    def request(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def fake_transport(monkeypatch, response):
    monkeypatch.setattr(
        transport,
        "_resolve_public_destinations",
        lambda url: [(socket.AF_INET, socket.SOCK_STREAM, 6, ("8.8.8.8", 443))],
    )
    connection = FakeConnection(response)
    monkeypatch.setattr(
        transport, "_PinnedHTTPSConnection", lambda *args, **kwargs: connection
    )
    return connection


def test_fetch_uses_pinned_transport_no_proxy_or_credentials(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://localhost:9")
    connection = fake_transport(monkeypatch, FakeResponse(length=len(BODY)))
    result = evidence.fetch_public_https(URL)
    assert connection.args == ("GET", "/series.json?period=2026-05")
    assert connection.kwargs["headers"] == evidence.REQUEST_HEADERS
    assert not any(
        name in connection.kwargs["headers"] for name in ("Cookie", "Authorization")
    )
    assert connection.closed
    assert result["bodyBase64"] == base64.b64encode(BODY).decode()
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "224.0.0.1"]
)
def test_fetch_dns_is_vetted_before_any_connection(monkeypatch, address):
    monkeypatch.setattr(
        transport.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
        ],
    )
    monkeypatch.setattr(
        transport,
        "_PinnedHTTPSConnection",
        lambda *args, **kwargs: pytest.fail("private destination must not connect"),
    )
    with pytest.raises(transport.FetchError, match="non-public"):
        evidence.fetch_public_https(URL)


def test_fetch_refuses_body_larger_than_limit(monkeypatch):
    monkeypatch.setattr(evidence, "MAX_RESPONSE_BYTES", 10)
    connection = fake_transport(monkeypatch, FakeResponse())
    with pytest.raises(evidence.EvidenceError, match="complete-body limit"):
        evidence.fetch_public_https(URL)
    assert connection.closed


def test_fetch_refuses_incomplete_content_length(monkeypatch):
    connection = fake_transport(monkeypatch, FakeResponse(length=len(BODY) + 1))
    with pytest.raises(evidence.EvidenceError, match="Content-Length"):
        evidence.fetch_public_https(URL)
    assert connection.closed
