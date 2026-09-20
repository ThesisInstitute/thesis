import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
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

type Fixture = {
  text: string;
  verificationText: string;
  execution: Parameters<typeof readCapturedToolCalls>[2];
};
let fixture: Fixture;
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
