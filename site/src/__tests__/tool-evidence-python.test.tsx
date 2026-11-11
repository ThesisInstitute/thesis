import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { readCapturedToolCalls } from "@/lib/tool-evidence";
import { ToolEvidence } from "@/components/ToolEvidence";

// Exercise the real recorder, MCP response envelope, and offline verifier.
// Only public HTTP transport is replaced with deterministic fixture bytes.
const generate = `
import base64, hashlib, json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from tool_evidence import EvidenceRecorder, verify_evidence
from tool_evidence_mcp import handle_request

def fetch(url):
    body = json.dumps({"history": ["1711.9", "1716.8", "1720.0"], "note": "<script>alert(1)</script>", "padding": "x" * 96000}).encode()
    status = 200
    if url.endswith("/missing"):
        body, status = b"Not found", 404
    return {"url": url, "status": status, "headers": [["content-type", "application/json"], ["x-example", "first"], ["x-example", "second"]], "bodyBase64": base64.b64encode(body).decode(), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}

output = pathlib.Path(sys.argv[2]) / "tool_evidence.json"
recorder = EvidenceRecorder(output, fetcher=fetch)
requests = [
    ("fetch_source", {"url": "https://example.gov/data.json"}),
    ("extract_json", {"sourceCallId": "call-0001", "pointer": "/history"}),
    ("calculate", {"expression": "mean(history)", "inputs": {"history": {"callId": "call-0002"}}}),
    ("calculate", {"expression": "mean(values) + median(values) + stdev(values) + mean(diff(values))", "inputs": {"values": [1, 2, 3]}}),
    ("fetch_source", {"url": "https://example.gov/missing"}),
    ("fetch_source", {"url": "http://www.ons.gov.uk"}),
    ("fetch_source", {"url": "https://127.0.0.1/data"}),
    ("fetch_source", {"url": "https://localhost/data"}),
    ("fetch_source", {"url": "https://[::1]/data"}),
    ("fetch_source", {"url": "https://example.gov/data?token=fixture-value"}),
    ("fetch_source", {"url": "https://user:fixture-value@example.gov/data"}),
    ("fetch_source", {"url": "https://example.gov/data#fragment"}),
    ("fetch_source", {"url": "https://example.gov:8443/data"}),
]
events = []
for index, (tool, arguments) in enumerate(requests):
    response = handle_request({"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}, recorder)
    events.append({"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "thesis_tool_evidence", "tool": tool, "arguments": arguments, "status": "completed", "result": response["result"]}})
text = output.read_text()
report = verify_evidence(json.loads(text))
assert report["valid"], report
report["evidenceSha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
print(json.dumps({"text": text, "verificationText": json.dumps(report), "execution": {"prefix": "", "command": {"backend": "codex", "argv": ["codex", "exec", "-c", 'mcp_servers.thesis_tool_evidence.command="python3"'], "toolEvidence": {"schemaVersion": "thesis_tool_evidence_v1", "artifact": "tool_evidence.json", "verificationArtifact": "tool_evidence_verification.json"}}, "stdout": "\\n".join(json.dumps(event) for event in events)}}))
`;

// The redacted native stream goes through the actual runner hygiene path,
// rather than constructing a TS-only projection that could hide drift.
const generateProjections = String.raw`
import base64, hashlib, json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from tool_evidence import EvidenceRecorder, verify_evidence
from tool_evidence_mcp import handle_request
from run_thesis_analyst import redact_stream_text

cases = [
    ("plain-env", "count=1711.9\nCENSUS_API_KEY=planted-fixture-value", False),
    ("nested-json", '{"count":1.0,"api_key":"planted-fixture-value","note":"é"}', True),
    ("escaped-key", r'{"api\u005fkey":"planted-fixture-value","count":3}', True),
    ("escaped-value", r'{"api_key":"planted\\fixture-value","count":3}', True),
    ("duplicate-key", '{"api_key":"planted-fixture-value","api_key":"[REDACTED]"}', False),
    ("truncated-escaped", r'{"api\u005fkey":"planted-fixture-value",', False),
    ("truncated-value", '{"api_key":"planted-fixture-value', False),
    ("benign-truncated", '{"note":"ordinary unfinished public text', False),
    ("deep-encoded", "[" * 600 + r'{"api\u005fkey":"planted-fixture-value"}' + "]" * 600, True),
    ("depth-boundary", "[" * 61 + '1' + "]" * 61, True),
    ("overflow", '{"count":1e400,"api_key":"planted-fixture-value"}', False),
    ("credential-url", 'https://example.gov/data?access_token=planted-fixture-value', False),
    ("fragment-url", 'https://example.gov/data#token=planted-fixture-value', False),
    ("userinfo-url", 'https://user:planted-fixture-value@example.gov/data', False),
    ("non-ascii-scheme", 'httpſ://user:public-example@example.gov/data', False),
]
result = {}
for name, source, extract in cases:
    directory = pathlib.Path(sys.argv[2]) / name
    directory.mkdir()
    def fetch(url):
        body = source.encode()
        return {"url": url, "status": 200, "headers": [["content-type", "application/json"]], "bodyBase64": base64.b64encode(body).decode(), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    output = directory / "tool_evidence.json"
    recorder = EvidenceRecorder(output, fetcher=fetch)
    requests = [("fetch_source", {"url": "https://example.gov/fixture"})]
    if extract:
        requests.append(("extract_json", {"sourceCallId": "call-0001", "pointer": ""}))
    events = []
    for index, (tool, arguments) in enumerate(requests):
        response = handle_request({"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}, recorder)
        events.append({"type": "item.completed", "item": {"type": "mcp_tool_call", "id": str(index), "server": "thesis_tool_evidence", "tool": tool, "arguments": arguments, "status": "completed", "result": response["result"]}})
    text = output.read_text()
    report = verify_evidence(json.loads(text))
    assert report["valid"], report
    report["evidenceSha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    stdout = redact_stream_text("\n".join(json.dumps(event) for event in events))
    result[name] = {"text": text, "verificationText": json.dumps(report), "execution": {"prefix": "", "command": {"backend": "codex", "argv": ["codex", "exec", "-c", 'mcp_servers.thesis_tool_evidence.command="python3"'], "toolEvidence": {"schemaVersion": "thesis_tool_evidence_v1", "artifact": "tool_evidence.json", "verificationArtifact": "tool_evidence_verification.json"}}, "stdout": stdout}}
print(json.dumps(result))
`;

// Reuse a committed official workbook through the real adapter, recorder, MCP
// response and offline replay. The site never parses BIFF or fetches a source.
const generateWorkbook = String.raw`
import base64, hashlib, json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from tool_evidence import EvidenceRecorder, verify_evidence
from tool_evidence_mcp import handle_request
from run_thesis_analyst import redact_stream_text

body = (pathlib.Path(sys.argv[1]).parent / "tests/fixtures/irs_soi_pub1304/23in33ar.xls").read_bytes()
url = "https://www.irs.gov/pub/irs-soi/23in33ar.xls"
def fetch(requested_url):
    assert requested_url == url
    return {"url": url, "status": 200, "headers": [["content-type", "application/vnd.ms-excel"]], "bodyBase64": base64.b64encode(body).decode(), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}

output = pathlib.Path(sys.argv[2]) / "workbook_tool_evidence.json"
recorder = EvidenceRecorder(output, fetcher=fetch)
requests = [
    ("fetch_source", {"url": url}),
    ("extract_irs_soi", {"sourceCallId": "call-0001", "seriesId": "irs.actc.total_claims", "year": "2023"}),
    ("extract_irs_soi", {"sourceCallId": "call-0001", "seriesId": "irs.actc.total_credit_amount", "year": "2023"}),
    ("calculate", {"expression": "claims + 1", "inputs": {"claims": {"callId": "call-0002"}}}),
    ("extract_irs_soi", {"sourceCallId": "call-0001", "seriesId": "irs.actc.total_claims", "year": "2021"}),
]
events = []
for index, (tool, arguments) in enumerate(requests):
    response = handle_request({"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}, recorder)
    events.append({"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "thesis_tool_evidence", "tool": tool, "arguments": arguments, "status": "completed", "result": response["result"]}})
text = output.read_text()
report = verify_evidence(json.loads(text))
assert report["valid"], report
assert report["succeededCount"] == 4 and report["failedCount"] == 1, report
report["evidenceSha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
stdout = redact_stream_text("\n".join(json.dumps(event) for event in events))
print(json.dumps({"text": text, "verificationText": json.dumps(report), "execution": {"prefix": "", "command": {"backend": "codex", "argv": ["codex", "exec", "-c", 'mcp_servers.thesis_tool_evidence.command="python3"'], "toolEvidence": {"schemaVersion": "thesis_tool_evidence_v1", "artifact": "tool_evidence.json", "verificationArtifact": "tool_evidence_verification.json"}}, "stdout": stdout}}))
`;

type Fixture = {
  text: string;
  verificationText: string;
  execution: Parameters<typeof readCapturedToolCalls>[2];
};
let fixture: Fixture;
let projectionFixtures: Record<string, Fixture>;
let workbookFixture: Fixture;
beforeAll(() => {
  const directory = fs.mkdtempSync(
    path.join(os.tmpdir(), "thesis-evidence-interop-"),
  );
  try {
    fixture = JSON.parse(
      execFileSync(
        "python3",
        ["-", path.resolve(process.cwd(), "../scripts"), directory],
        {
          input: generate,
          encoding: "utf8",
          maxBuffer: 2 * 1024 * 1024,
        },
      ),
    );
    projectionFixtures = JSON.parse(
      execFileSync(
        "python3",
        ["-", path.resolve(process.cwd(), "../scripts"), directory],
        {
          input: generateProjections,
          encoding: "utf8",
          maxBuffer: 4 * 1024 * 1024,
        },
      ),
    );
    workbookFixture = JSON.parse(
      execFileSync(
        "python3",
        ["-", path.resolve(process.cwd(), "../scripts"), directory],
        {
          input: generateWorkbook,
          encoding: "utf8",
          maxBuffer: 2 * 1024 * 1024,
        },
      ),
    );
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
afterEach(cleanup);
const read = () =>
  readCapturedToolCalls(
    fixture.text,
    fixture.verificationText,
    fixture.execution,
  );

describe("Python recorder to public evidence integration", () => {
  it("accepts real workbook extraction, separate units and referenced calculations", () => {
    const calls = readCapturedToolCalls(
      workbookFixture.text,
      workbookFixture.verificationText,
      workbookFixture.execution,
    );
    expect(calls).toHaveLength(5);
    expect(calls[1]).toMatchObject({
      tool: "extract_irs_soi",
      replay: "replayed",
      replayChecks: ["irs_soi_workbook_replay"],
      result: {
        value: 17.626084,
        rawValue: 17626084,
        unit: "millions",
        sourceCallId: "call-0001",
        sourceSha256: calls[0].response?.sha256,
        sourceUrl: "https://www.irs.gov/pub/irs-soi/23in33ar.xls",
        seriesId: "irs.actc.total_claims",
        year: "2023",
        transform: { operation: "multiply", factor: 0.000001 },
      },
    });
    // A binary multiplication produces 34533.251000000004; the runner's
    // decimal unit conversion and the public consistency check must agree.
    expect(calls[2].result).toMatchObject({
      value: 34533.251,
      rawValue: 34533251,
      unit: "usd_millions",
      transform: { operation: "multiply", factor: 0.001 },
    });
    expect(calls[3].result).toMatchObject({
      value: 18.626084,
      resolvedInputs: { claims: 17.626084 },
    });
    expect(calls[4]).toMatchObject({ status: "failed", replay: "failed" });
    render(
      <ToolEvidence
        evidence={{
          status: "available",
          artifacts: [
            {
              stage: "forecast",
              artifactPath: "records/thesis-analyst/test/tool_evidence.json",
              artifactSha256: createHash("sha256")
                .update(workbookFixture.text)
                .digest("hex"),
              verificationPath:
                "records/thesis-analyst/test/tool_evidence_verification.json",
              calls,
            },
          ],
        }}
      />,
    );
    expect(screen.getAllByText("extract_irs_soi")).toHaveLength(3);
    expect(
      screen.getAllByText("Succeeded · runner replay passed"),
    ).toHaveLength(3);
    expect(
      screen.getByText(/replay results below were recorded by the runner/),
    ).toBeInTheDocument();
  });

  it.each([
    "source-reference",
    "non-fetch-reference",
    "source-http-status",
    "extra-argument",
    "year",
    "source-hash",
    "source-url",
    "series",
    "raw-value",
    "value",
    "transform",
    "extra-result",
    "replay-check",
    "calculation-reference",
  ])("rejects inconsistent workbook provenance even with rebound metadata: %s", (field) => {
    const value = structuredClone(workbookFixture);
    const evidence = JSON.parse(value.text);
    const call = evidence.calls[field === "non-fetch-reference" ? 2 : 1];
    const verification = JSON.parse(value.verificationText);
    if (field === "source-reference") call.arguments.sourceCallId = "call-9999";
    else if (field === "non-fetch-reference")
      call.arguments.sourceCallId = "call-0002";
    else if (field === "source-http-status")
      evidence.calls[0].response.status = 404;
    else if (field === "extra-argument") call.arguments.path = "/tmp/untrusted.xls";
    else if (field === "year") call.arguments.year = call.result.year = "2021";
    else if (field === "source-hash") call.result.sourceSha256 = "0".repeat(64);
    else if (field === "source-url") call.result.sourceUrl += "?download=1";
    else if (field === "series")
      call.result.seriesId = "irs.actc.total_credit_amount";
    else if (field === "raw-value") call.result.rawValue = -1;
    else if (field === "value") call.result.value += 1;
    else if (field === "transform") call.result.transform.factor = 0.001;
    else if (field === "extra-result") call.result.row = 7;
    else if (field === "replay-check") verification.checks[1].checks = [];
    else evidence.calls[3].arguments.inputs.claims.callId = "call-0005";
    const events = value.execution.stdout
      .split("\n")
      .map((line) => JSON.parse(line));
    for (const index of [1, 2, 3]) {
      const { response, ...terminal } = evidence.calls[index];
      events[index].item.arguments = terminal.arguments;
      events[index].item.result.structuredContent = terminal;
      delete events[index].item.result.structured_content;
      events[index].item.result.content[0].text = JSON.stringify(terminal);
    }
    value.text = JSON.stringify(evidence);
    verification.evidenceSha256 = createHash("sha256")
      .update(value.text)
      .digest("hex");
    expect(() =>
      readCapturedToolCalls(value.text, JSON.stringify(verification), {
        ...value.execution,
        stdout: events.map((event) => JSON.stringify(event)).join("\n"),
      }),
    ).toThrow(/IRS extraction|Calculation refers/);
  });

  it.each(["arguments", "result"])(
    "rejects altered native workbook %s",
    (field) => {
      const execution = structuredClone(workbookFixture.execution);
      const events = execution.stdout
        .split("\n")
        .map((line) => JSON.parse(line));
      if (field === "arguments") events[1].item.arguments.year = "2019";
      else {
        const result = events[1].item.result;
        const structured = result.structuredContent ?? result.structured_content;
        structured.result.value += 1;
        result.content[0].text = JSON.stringify(structured);
      }
      execution.stdout = events.map((event) => JSON.stringify(event)).join("\n");
      expect(() =>
        readCapturedToolCalls(
          workbookFixture.text,
          workbookFixture.verificationText,
          execution,
        ),
      ).toThrow(/differs from its native/);
    },
  );

  it.each([
    "plain-env",
    "nested-json",
    "escaped-key",
    "escaped-value",
    "duplicate-key",
    "truncated-escaped",
    "truncated-value",
    "benign-truncated",
    "deep-encoded",
    "depth-boundary",
    "overflow",
    "credential-url",
    "fragment-url",
    "userinfo-url",
    "non-ascii-scheme",
  ])(
    "binds Python version-1 presentation after real runner hygiene: %s",
    (name) => {
      const value = projectionFixtures[name];
      const calls = readCapturedToolCalls(
        value.text,
        value.verificationText,
        value.execution,
      );
      expect(calls.length).toBeGreaterThan(0);
      expect(JSON.parse(value.text).calls[0].terminalProjectionVersion).toBe(1);
      expect(value.execution.stdout).not.toContain("planted-fixture-value");
    },
  );

  it.each([undefined, true, false, 0, 2, null])(
    "rejects a changed or downgraded projection version: %s",
    (version) => {
      const value = structuredClone(projectionFixtures["nested-json"]);
      const evidence = JSON.parse(value.text);
      for (const call of evidence.calls) {
        if (version === undefined) delete call.terminalProjectionVersion;
        else call.terminalProjectionVersion = version;
      }
      value.text = JSON.stringify(evidence);
      const verification = JSON.parse(value.verificationText);
      verification.evidenceSha256 = createHash("sha256")
        .update(value.text)
        .digest("hex");
      expect(() =>
        readCapturedToolCalls(
          value.text,
          JSON.stringify(verification),
          value.execution,
        ),
      ).toThrow(/projection version|differs from its native/);
    },
  );

  it.each(["1.0", "1e0"])(
    "rejects a floating-point projection marker: %s",
    (literal) => {
      const value = projectionFixtures["nested-json"];
      const text = value.text.replace(
        /("terminalProjectionVersion"\s*:\s*)1\b/g,
        `$1${literal}`,
      );
      const verification = JSON.parse(value.verificationText);
      verification.evidenceSha256 = createHash("sha256")
        .update(text)
        .digest("hex");
      expect(() =>
        readCapturedToolCalls(
          text,
          JSON.stringify(verification),
          value.execution,
        ),
      ).toThrow(/projection version/);
    },
  );

  it("retains exact legacy raw terminal binding when the version is absent", () => {
    const value = structuredClone(fixture);
    const evidence = JSON.parse(value.text);
    for (const call of evidence.calls) delete call.terminalProjectionVersion;
    const events = value.execution.stdout
      .split("\n")
      .map((line) => JSON.parse(line));
    for (const event of events) {
      const result = event.item.result;
      const structured = result.structuredContent ?? result.structured_content;
      delete structured.terminalProjectionVersion;
      const text = JSON.parse(result.content[0].text);
      delete text.terminalProjectionVersion;
      result.content[0].text = JSON.stringify(text);
    }
    value.text = JSON.stringify(evidence);
    const verification = JSON.parse(value.verificationText);
    verification.evidenceSha256 = createHash("sha256")
      .update(value.text)
      .digest("hex");
    value.execution.stdout = events
      .map((event) => JSON.stringify(event))
      .join("\n");
    expect(
      readCapturedToolCalls(
        value.text,
        JSON.stringify(verification),
        value.execution,
      ),
    ).toHaveLength(13);
  });

  it.each(["result", "arguments"])(
    "rejects altered native version-1 %s",
    (field) => {
      const value = structuredClone(projectionFixtures["nested-json"]);
      const events = value.execution.stdout
        .split("\n")
        .map((line) => JSON.parse(line));
      if (field === "arguments")
        events[0].item.arguments.url = "https://example.gov/different";
      else {
        const result = events[0].item.result;
        const structured =
          result.structuredContent ?? result.structured_content;
        structured.result.excerpt = "invented public source text";
        result.content[0].text = JSON.stringify(structured);
      }
      value.execution.stdout = events
        .map((event) => JSON.stringify(event))
        .join("\n");
      expect(() =>
        readCapturedToolCalls(
          value.text,
          value.verificationText,
          value.execution,
        ),
      ).toThrow(/differs from its native/);
    },
  );

  it("accepts real ordered headers, numeric source strings, literal arrays and statistics", () => {
    const calls = read();
    expect(calls).toHaveLength(13);
    expect(calls[0].response?.headers).toEqual([
      ["content-type", "application/json"],
      ["x-example", "first"],
      ["x-example", "second"],
    ]);
    expect(calls[2].result).toMatchObject({
      value: 1716.2333333333333,
      resolvedInputs: { history: [1711.9, 1716.8, 1720] },
    });
    expect(calls[3].result).toMatchObject({ value: 6 });
    expect(calls[4]).toMatchObject({
      status: "failed",
      replay: "failed",
      response: { status: 404 },
    });
  });

  it("preserves actual refused HTTP requests after the recorder redacts their URL", () => {
    const calls = read();
    const events = fixture.execution.stdout
      .split("\n")
      .map((line) => JSON.parse(line));
    expect(events[5].item.arguments).toEqual({ url: "http://www.ons.gov.uk" });
    for (const call of calls.slice(5)) {
      expect(call).toMatchObject({
        status: "failed",
        arguments: { url: "[redacted: unsafe URL]" },
      });
    }
  });

  it.each([
    "https://example.gov/data.json",
    "https://www.ons.gov.uk",
    "https://8.8.8.8/data",
    "https://999.2.3.4/data",
    "https://[2606:4700:4700::1111]/data",
  ])(
    "does not allow an accepted native URL to justify a redacted failure: %s",
    (url) => {
      const execution = structuredClone(fixture.execution);
      const events = execution.stdout
        .split("\n")
        .map((line) => JSON.parse(line));
      events[5].item.arguments = { url };
      execution.stdout = events
        .map((event) => JSON.stringify(event))
        .join("\n");
      expect(() =>
        readCapturedToolCalls(
          fixture.text,
          fixture.verificationText,
          execution,
        ),
      ).toThrow(/differs from its native/);
    },
  );

  it("accepts the runner's exact URL redaction marker in a failed native event", () => {
    const execution = structuredClone(fixture.execution);
    const events = execution.stdout.split("\n").map((line) => JSON.parse(line));
    events[5].item.arguments = { url: "[redacted: unsafe URL]" };
    execution.stdout = events.map((event) => JSON.stringify(event)).join("\n");
    expect(
      readCapturedToolCalls(
        fixture.text,
        fixture.verificationText,
        execution,
      )[5].status,
    ).toBe("failed");
  });

  it("caps embedded response text at 64 KiB and links complete evidence separately", () => {
    const calls = read();
    expect(calls[0].response?.bytes).toBeGreaterThan(64 * 1024);
    expect(Buffer.byteLength(calls[0].response!.bodyText!)).toBe(64 * 1024);
    expect(calls[0].response?.bodyTextTruncated).toBe(true);
    const { container } = render(
      <ToolEvidence
        evidence={{
          status: "available",
          artifacts: [
            {
              stage: "forecast",
              artifactPath: "records/thesis-analyst/test/tool_evidence.json",
              artifactSha256: "a".repeat(64),
              verificationPath:
                "records/thesis-analyst/test/tool_evidence_verification.json",
              calls,
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("Response text preview")).toBeInTheDocument();
    expect(
      screen.getByText(/Preview limited to the first 64 KiB/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Raw evidence ↗" }),
    ).toHaveAttribute("href", expect.stringContaining("tool_evidence.json"));
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });

  it.each(["status", "isError", "is_error", "text"])(
    "rejects contradictory native %s",
    (field) => {
      const execution = structuredClone(fixture.execution);
      const events = execution.stdout
        .split("\n")
        .map((line) => JSON.parse(line));
      if (field === "status") events[0].item.status = "failed";
      else if (field === "text")
        events[0].item.result.content[0].text = '{"invented":true}';
      else events[0].item.result[field] = true;
      execution.stdout = events
        .map((event) => JSON.stringify(event))
        .join("\n");
      expect(() =>
        readCapturedToolCalls(
          fixture.text,
          fixture.verificationText,
          execution,
        ),
      ).toThrow(/differs from its native/);
    },
  );
});
