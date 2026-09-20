import { createHash } from "node:crypto";
import { isIP } from "node:net";
import { canonicalStringify } from "@/data/canonical-json";
import type { CapturedToolCall } from "@/data/tool-evidence";

type Json = Record<string, any>;
const RESPONSE_PREVIEW_BYTES = 64 * 1024;
const finiteNumber = (value: unknown): value is number =>
  typeof value === "number" &&
  Number.isFinite(value) &&
  Math.abs(value) <= 1e100;
const digest = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");
function requireValue(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}
function object(value: unknown): value is Json {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

const REDACTED_URL = "[redacted: unsafe URL]";
const sensitiveQueryNames = new Set([
  "key",
  "apikey",
  "accesskey",
  "token",
  "accesstoken",
  "refreshtoken",
  "idtoken",
  "auth",
  "authorization",
  "password",
  "passwd",
  "secret",
  "clientsecret",
  "signature",
  "sig",
  "credential",
  "credentials",
  "code",
  "session",
  "sessionid",
  "jwt",
  "xamzsecuritytoken",
  "xamzsignature",
  "xamzcredential",
  "xgoogsignature",
  "xgoogcredential",
]);

// Deliberately conservative for IP ranges: unknown/new classifications stay
// unprojected rather than letting a public native URL justify a redacted call.
function definitelyNonPublicIp(host: string): boolean {
  if (isIP(host) === 4) {
    const [a, b, c, d] = host.split(".").map(Number);
    return (
      a === 0 ||
      a === 10 ||
      a === 127 ||
      a >= 224 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 192 && b === 0 && c === 0 && (d <= 7 || d === 170 || d === 171)) ||
      (a === 192 && b === 0 && c === 2) ||
      (a === 198 && (b === 18 || b === 19)) ||
      (a === 198 && b === 51 && c === 100) ||
      (a === 203 && b === 0 && c === 113)
    );
  }
  if (isIP(host) !== 6) return false;
  let normalized = host.toLowerCase();
  if (normalized.includes(".")) {
    const split = normalized.lastIndexOf(":");
    const ipv4 = normalized
      .slice(split + 1)
      .split(".")
      .map(Number);
    normalized =
      normalized.slice(0, split + 1) +
      ((ipv4[0] << 8) | ipv4[1]).toString(16) +
      ":" +
      ((ipv4[2] << 8) | ipv4[3]).toString(16);
  }
  const [left, right] = normalized
    .split("::")
    .map((part) => (part ? part.split(":") : []));
  const words = right
    ? [...left, ...Array(8 - left.length - right.length).fill("0"), ...right]
    : left;
  const value = words.map((word) => Number.parseInt(word, 16));
  if (value.slice(0, 5).every((word) => word === 0) && value[5] === 0xffff) {
    return definitelyNonPublicIp(
      `${value[6] >> 8}.${value[6] & 255}.${value[7] >> 8}.${value[7] & 255}`,
    );
  }
  return (
    value.every((word) => word === 0) ||
    (value.slice(0, 7).every((word) => word === 0) && value[7] === 1) ||
    (value[0] & 0xfe00) === 0xfc00 ||
    (value[0] & 0xffc0) === 0xfe80 ||
    (value[0] & 0xff00) === 0xff00 ||
    (value[0] === 0x100 && value.slice(1, 4).every((word) => word === 0)) ||
    (value[0] === 0x2001 && value[1] === 0xdb8)
  );
}

function refusedSourceUrl(value: unknown): boolean {
  if (
    typeof value !== "string" ||
    value.length > 4096 ||
    /[^\x21-\x7e]/.test(value)
  )
    return true;
  // This marker can also be substituted by the runner when it removes a
  // credential-bearing URL from a native event before archiving it.
  if (value === REDACTED_URL) return true;
  const authority = /^[^:]+:\/\/([^/?#]*)/.exec(value)?.[1];
  if (!authority) return true;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    // WHATWG rejects some hostname spellings accepted by Python urlsplit.
    // A parse disagreement must never authorize redacting a native request.
    return false;
  }
  const host = (
    authority.startsWith("[")
      ? authority.slice(1, authority.indexOf("]"))
      : authority.split(":")[0]
  ).toLowerCase();
  if (
    url.protocol !== "https:" ||
    !url.hostname ||
    url.username ||
    url.password ||
    url.hash ||
    (url.port && url.port !== "443") ||
    host.includes("%") ||
    host.replace(/\.+$/, "") === "localhost"
  )
    return true;
  for (const key of url.searchParams.keys()) {
    const normalized = key.toLowerCase().replace(/[^a-z0-9]/g, "");
    if (
      sensitiveQueryNames.has(normalized) ||
      /(token|password|secret|signature|credential|apikey)$/.test(normalized)
    )
      return true;
  }
  return definitelyNonPublicIp(host);
}

function nativeArguments(call: Json, arguments_: unknown): unknown {
  if (
    call.tool !== "fetch_source" ||
    call.status !== "failed" ||
    !object(call.arguments) ||
    Object.keys(call.arguments).length !== 1 ||
    call.arguments.url !== REDACTED_URL ||
    !object(arguments_)
  )
    return arguments_;
  if (
    Object.keys(arguments_).length !== 1 ||
    !Object.hasOwn(arguments_, "url") ||
    refusedSourceUrl(arguments_.url)
  ) {
    return { url: REDACTED_URL };
  }
  return arguments_;
}

/** Validate captured bytes and their bound runner replay report, not model prose. */
export function readCapturedToolCalls(
  evidenceText: string,
  verificationText: string,
  execution: { command: Json; stdout: string; prefix: string },
): CapturedToolCall[] {
  const evidence = JSON.parse(evidenceText);
  const verification = JSON.parse(verificationText);
  requireValue(
    object(evidence) &&
      evidence.schemaVersion === "thesis_tool_evidence_v1" &&
      evidence.captureMethod === "thesis-controlled-tools-v1" &&
      Array.isArray(evidence.calls) &&
      evidence.calls.length <= 128,
    "Unsupported tool evidence",
  );
  requireValue(
    object(verification) &&
      verification.schemaVersion === "thesis_tool_evidence_verification_v1" &&
      verification.captureMethod === "thesis-controlled-tools-v1" &&
      verification.evidenceSha256 === digest(Buffer.from(evidenceText)) &&
      verification.valid === true &&
      Array.isArray(verification.errors) &&
      verification.errors.length === 0 &&
      Array.isArray(verification.checks) &&
      verification.callCount === evidence.calls.length &&
      verification.checks.length === evidence.calls.length,
    "Tool replay report is invalid or does not bind these evidence bytes",
  );
  requireValue(
    verification.succeededCount ===
      evidence.calls.filter((call: Json) => call.status === "succeeded")
        .length &&
      verification.failedCount ===
        evidence.calls.filter((call: Json) => call.status === "failed").length,
    "Tool replay counts disagree with captured calls",
  );
  const declaration = {
    schemaVersion: "thesis_tool_evidence_v1",
    artifact: `${execution.prefix}tool_evidence.json`,
    verificationArtifact: `${execution.prefix}tool_evidence_verification.json`,
  };
  requireValue(
    execution.command.backend === "codex" &&
      canonicalStringify(execution.command.toolEvidence ?? null) ===
        canonicalStringify(declaration) &&
      Array.isArray(execution.command.argv) &&
      execution.command.argv.some(
        (value: unknown) =>
          typeof value === "string" &&
          value.startsWith("mcp_servers.thesis_tool_evidence."),
      ),
    "Command does not declare this controlled tool capture",
  );
  const completed = execution.stdout
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line))
    .filter(
      (event) =>
        event?.type === "item.completed" &&
        event.item?.type === "mcp_tool_call" &&
        event.item.server === "thesis_tool_evidence",
    );
  requireValue(
    completed.length === evidence.calls.length,
    "Captured calls lack matching native completion events",
  );
  const matched = new Set<string>();
  for (const event of completed) {
    const item = event.item;
    const structured =
      item.result?.structured_content ?? item.result?.structuredContent;
    const call = evidence.calls.find(
      (candidate: Json) => candidate?.callId === structured?.callId,
    );
    requireValue(
      call && !matched.has(call.callId),
      "Unknown or duplicate native tool completion",
    );
    const { response: _response, ...terminal } = call;
    const content = item.result?.content;
    const textResult =
      Array.isArray(content) &&
      content.length === 1 &&
      content[0]?.type === "text"
        ? JSON.parse(content[0].text)
        : null;
    const nativeStatusMatches =
      call.status === "succeeded"
        ? item.status === "completed"
        : ["completed", "failed"].includes(item.status);
    const errorFlagsMatch = ["isError", "is_error"].every(
      (key) =>
        !Object.hasOwn(item.result, key) ||
        item.result[key] === (call.status === "failed"),
    );
    requireValue(
      item.tool === call.tool &&
        nativeStatusMatches &&
        errorFlagsMatch &&
        canonicalStringify(textResult) === canonicalStringify(terminal) &&
        canonicalStringify(nativeArguments(call, item.arguments) ?? null) ===
          canonicalStringify(call.arguments) &&
        canonicalStringify(structured ?? null) === canonicalStringify(terminal),
      "Captured call differs from its native completion event",
    );
    matched.add(call.callId);
  }
  const seen = new Map<string, Json>();
  return evidence.calls.map((call: Json, index: number) => {
    requireValue(
      object(call) &&
        call.callId === `call-${String(index + 1).padStart(4, "0")}` &&
        ["fetch_source", "extract_json", "calculate"].includes(call.tool) &&
        object(call.arguments) &&
        timestamp(call.startedAt) &&
        timestamp(call.completedAt) &&
        Date.parse(call.completedAt) >= Date.parse(call.startedAt) &&
        ["succeeded", "failed"].includes(call.status) &&
        Object.hasOwn(call, "result") &&
        (call.error === undefined || typeof call.error === "string"),
      "Malformed captured call",
    );
    const check = verification.checks[index];
    const expectedStatus =
      call.status === "failed"
        ? "failed"
        : call.tool === "fetch_source"
          ? "captured"
          : "replayed";
    requireValue(
      object(check) &&
        check.callId === call.callId &&
        check.status === expectedStatus &&
        Array.isArray(check.checks) &&
        check.checks.every((item: unknown) => typeof item === "string"),
      "Replay check does not match the captured call",
    );
    if (call.status === "succeeded" && call.tool === "extract_json") {
      requireValue(
        typeof call.arguments.pointer === "string" &&
          seen.get(call.arguments.sourceCallId)?.tool === "fetch_source" &&
          seen.get(call.arguments.sourceCallId)?.status === "succeeded",
        "Extraction refers to a missing or failed captured source",
      );
    }
    if (call.status === "succeeded" && call.tool === "calculate") {
      requireValue(
        typeof call.arguments.expression === "string" &&
          object(call.arguments.inputs),
        "Malformed calculation inputs",
      );
      for (const input of Object.values(call.arguments.inputs)) {
        requireValue(
          finiteNumber(input) ||
            (Array.isArray(input) &&
              input.length <= 512 &&
              input.every(finiteNumber)) ||
            (object(input) &&
              typeof input.callId === "string" &&
              seen.get(input.callId)?.status === "succeeded" &&
              ["extract_json", "calculate"].includes(
                seen.get(input.callId)?.tool,
              )),
          "Calculation refers to a missing or failed captured value",
        );
      }
    }
    let response: CapturedToolCall["response"];
    if (call.response !== undefined) {
      const raw = call.response;
      requireValue(
        call.tool === "fetch_source" &&
          object(raw) &&
          typeof raw.url === "string" &&
          /^https?:\/\//.test(raw.url) &&
          Number.isInteger(raw.status) &&
          raw.status >= 100 &&
          raw.status <= 599 &&
          Array.isArray(raw.headers) &&
          raw.headers.every(
            (entry: unknown) =>
              Array.isArray(entry) &&
              entry.length === 2 &&
              entry.every((value) => typeof value === "string") &&
              entry[0] === entry[0].toLowerCase() &&
              !["set-cookie", "set-cookie2"].includes(entry[0]),
          ) &&
          typeof raw.bodyBase64 === "string" &&
          /^[a-f0-9]{64}$/.test(raw.sha256) &&
          Number.isSafeInteger(raw.bytes) &&
          raw.bytes >= 0 &&
          raw.bytes <= 8 * 1024 * 1024,
        "Malformed captured HTTP response",
      );
      const body = Buffer.from(raw.bodyBase64, "base64");
      requireValue(
        body.toString("base64") === raw.bodyBase64 &&
          body.length === raw.bytes &&
          digest(body) === raw.sha256,
        "Captured HTTP response bytes do not match their commitment",
      );
      const contentType = raw.headers.find(
        ([name]: [string, string]) => name === "content-type",
      )?.[1] as string | undefined;
      response = {
        url: raw.url,
        status: raw.status,
        headers: raw.headers,
        sha256: raw.sha256,
        bytes: raw.bytes,
        ...(contentType &&
        /^(text\/|application\/(?:[^;]+\+)?(?:json|xml|javascript))/i.test(
          contentType,
        )
          ? {
              bodyText: body
                .subarray(0, RESPONSE_PREVIEW_BYTES)
                .toString("utf8"),
              bodyTextTruncated: body.length > RESPONSE_PREVIEW_BYTES,
            }
          : {}),
      };
    }
    requireValue(
      call.tool !== "fetch_source" || call.status !== "succeeded" || response,
      "Successful source call has no captured response bytes",
    );
    seen.set(call.callId, call);
    return {
      callId: call.callId,
      tool: call.tool,
      arguments: call.arguments,
      startedAt: call.startedAt,
      completedAt: call.completedAt,
      status: call.status,
      result: call.result,
      ...(call.error ? { error: call.error } : {}),
      ...(response ? { response } : {}),
      replay: check.status,
      replayChecks: check.checks,
    };
  });
}
