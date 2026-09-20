import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { createHash } from "node:crypto";
import { ToolEvidence } from "@/components/ToolEvidence";
import { readCapturedToolCalls } from "@/lib/tool-evidence";
import type { CapturedToolEvidence } from "@/data/tool-evidence";

afterEach(cleanup);
const hash = (value: string | Buffer) =>
  createHash("sha256").update(value).digest("hex");

export function evidenceFixture() {
  const body = '{"value":1711.9,"note":"<img src=x onerror=alert(1)>"}';
  const timestamp = "2026-09-20T12:00:00Z";
  const evidence = {
    schemaVersion: "thesis_tool_evidence_v1",
    captureMethod: "thesis-controlled-tools-v1",
    calls: [
      {
        callId: "call-0001",
        tool: "fetch_source",
        arguments: { url: "https://example.gov/data.json" },
        startedAt: timestamp,
        completedAt: timestamp,
        status: "succeeded",
        result: { bytes: Buffer.byteLength(body) },
        response: {
          url: "https://example.gov/data.json",
          status: 200,
          headers: [["content-type", "application/json"]],
          bodyBase64: Buffer.from(body).toString("base64"),
          sha256: hash(body),
          bytes: Buffer.byteLength(body),
        },
      },
      {
        callId: "call-0002",
        tool: "extract_json",
        arguments: { sourceCallId: "call-0001", pointer: "/value" },
        startedAt: timestamp,
        completedAt: timestamp,
        status: "succeeded",
        result: { value: 1711.9 },
      },
      {
        callId: "call-0003",
        tool: "calculate",
        arguments: {
          expression: "base + change",
          inputs: { base: { callId: "call-0002" }, change: 4.9 },
        },
        startedAt: timestamp,
        completedAt: timestamp,
        status: "succeeded",
        result: {
          value: 1716.8,
          resolvedInputs: { base: 1711.9, change: 4.9 },
        },
      },
      {
        callId: "call-0004",
        tool: "fetch_source",
        arguments: { url: "https://example.gov/missing" },
        startedAt: timestamp,
        completedAt: timestamp,
        status: "failed",
        result: null,
        error: "HTTP 404",
      },
    ],
  };
  const seal = () => {
    const text = JSON.stringify(evidence);
    const report = {
      schemaVersion: "thesis_tool_evidence_verification_v1",
      captureMethod: "thesis-controlled-tools-v1",
      evidenceSha256: hash(text),
      valid: true,
      errors: [],
      callCount: 4,
      succeededCount: 3,
      failedCount: 1,
      checks: [
        {
          callId: "call-0001",
          status: "captured",
          checks: ["HTTP body matches SHA-256"],
        },
        {
          callId: "call-0002",
          status: "replayed",
          checks: ["JSON pointer result matches captured source"],
        },
        {
          callId: "call-0003",
          status: "replayed",
          checks: ["Expression result matches captured inputs"],
        },
        {
          callId: "call-0004",
          status: "failed",
          checks: ["Failed call retained"],
        },
      ],
    };
    const execution = {
      prefix: "",
      command: {
        backend: "codex",
        argv: [
          "codex",
          "exec",
          "-c",
          'mcp_servers.thesis_tool_evidence.command="python"',
        ],
        toolEvidence: {
          schemaVersion: "thesis_tool_evidence_v1",
          artifact: "tool_evidence.json",
          verificationArtifact: "tool_evidence_verification.json",
        },
      },
      stdout: evidence.calls
        .map(({ response, ...call }) =>
          JSON.stringify({
            type: "item.completed",
            item: {
              type: "mcp_tool_call",
              server: "thesis_tool_evidence",
              tool: call.tool,
              status: "completed",
              arguments: call.arguments,
              result: {
                structuredContent: call,
                content: [{ type: "text", text: JSON.stringify(call) }],
                isError: call.status === "failed",
              },
            },
          }),
        )
        .join("\n"),
    };
    return {
      text,
      report,
      verificationText: JSON.stringify(report),
      execution,
    };
  };
  return { evidence, seal, body };
}

describe("captured tool evidence", () => {
  it("checks archived response bytes and retains a runner-bound replay verdict", () => {
    const { text, verificationText, execution } = evidenceFixture().seal();
    const calls = readCapturedToolCalls(text, verificationText, execution);
    expect(calls).toHaveLength(4);
    expect(calls[0].response?.bodyText).toContain('"value":1711.9');
    expect(calls[1].replay).toBe("replayed");
    expect(calls[3].status).toBe("failed");
  });

  it("rejects a replay report bound to different bytes", () => {
    const f = evidenceFixture();
    const previous = f.seal();
    f.evidence.calls[1].result = { value: 999 };
    expect(() =>
      readCapturedToolCalls(
        f.seal().text,
        previous.verificationText,
        previous.execution,
      ),
    ).toThrow(/does not bind/);
  });

  it("rejects altered HTTP bytes even when the enclosing report is rebound", () => {
    const f = evidenceFixture();
    f.evidence.calls[0].response!.bodyBase64 =
      Buffer.from("changed").toString("base64");
    const { text, verificationText, execution } = f.seal();
    expect(() =>
      readCapturedToolCalls(text, verificationText, execution),
    ).toThrow(/response bytes/);
  });

  it("rejects extraction and calculation references to missing source calls", () => {
    for (const index of [1, 2]) {
      const f = evidenceFixture();
      if (index === 1) f.evidence.calls[1].arguments.sourceCallId = "call-9999";
      else f.evidence.calls[2].arguments.inputs!.base.callId = "call-9999";
      const { text, verificationText, execution } = f.seal();
      expect(() =>
        readCapturedToolCalls(text, verificationText, execution),
      ).toThrow(/missing or failed/);
    }
  });

  it("rejects a captured call absent from or different from its native tool event", () => {
    const f = evidenceFixture();
    const { text, verificationText, execution } = f.seal();
    expect(() =>
      readCapturedToolCalls(text, verificationText, {
        ...execution,
        stdout: "",
      }),
    ).toThrow(/completion events/);
    const events = execution.stdout.split("\n").map((line) => JSON.parse(line));
    events[0].item.result.structuredContent.result = { value: "invented" };
    expect(() =>
      readCapturedToolCalls(text, verificationText, {
        ...execution,
        stdout: events.map((event) => JSON.stringify(event)).join("\n"),
      }),
    ).toThrow(/differs from its native/);
  });

  it("does not label a fetch as independently replayed", () => {
    const { text, report, execution } = evidenceFixture().seal();
    report.checks[0].status = "replayed";
    expect(() =>
      readCapturedToolCalls(text, JSON.stringify(report), execution),
    ).toThrow(/Replay check/);
  });

  it("renders captured inputs, outputs, failures, and escaped full response text", () => {
    const f = evidenceFixture();
    const { text, verificationText, execution } = f.seal();
    const artifact: CapturedToolEvidence = {
      stage: "forecast",
      artifactPath: "records/thesis-analyst/test/tool_evidence.json",
      artifactSha256: hash(text),
      verificationPath:
        "records/thesis-analyst/test/tool_evidence_verification.json",
      calls: readCapturedToolCalls(text, verificationText, execution),
    };
    const { container } = render(
      <ToolEvidence
        evidence={{ status: "available", artifacts: [artifact] }}
      />,
    );
    expect(
      screen.getByRole("region", { name: "Tool evidence" }),
    ).toHaveTextContent("Archive integrity checked");
    expect(screen.getByText(f.body)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("Failed · retained for audit")).toBeInTheDocument();
    expect(screen.getByText("HTTP 404")).toBeInTheDocument();
    expect(
      screen.getAllByText("Succeeded · runner replay passed"),
    ).toHaveLength(2);
    expect(
      screen.getByRole("link", { name: "Raw evidence ↗" }),
    ).toHaveAttribute("href", expect.stringContaining("tool_evidence.json"));
  });

  it("clearly distinguishes missing historical responses and rejected evidence", () => {
    const { rerender } = render(<ToolEvidence />);
    expect(
      screen.getByRole("region", { name: "Tool evidence" }),
    ).toHaveTextContent("no captured tool responses");
    expect(screen.queryByText("Archive integrity checked")).toBeNull();
    rerender(<ToolEvidence evidence={{ status: "invalid" }} />);
    expect(
      screen.getByRole("region", { name: "Tool evidence" }),
    ).toHaveTextContent("could not be verified");
    expect(screen.queryByRole("link", { name: "Raw evidence ↗" })).toBeNull();
  });
});
