import { canonicalStringify } from "@/data/canonical-json";

// Version 1 mirrors scripts/tool_evidence.py. This projection is recomputed
// from captured evidence; the native response never supplies its authority.
type JsonObject = Record<string, unknown>;
const REDACTED_URL = "[redacted: unsafe URL]";
const REDACTED = "[REDACTED]";
const REDACTED_JSON = "[redacted: unsafe JSON presentation]";
const MAX_DEPTH = 64;
// Python re's Unicode whitespace, excluding JavaScript's additional BOM.
const WS =
  "\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const NAME = "[a-z0-9_\\u0130\\u0131\\u017f\\u212a]*";
const SECRET =
  "(?:[k\\u212a]ey|to[k\\u212a]en|[s\\u017f]ecret|pa[s\\u017f][s\\u017f]word)";
const secretField = new RegExp(`^${NAME}${SECRET}${NAME}$`, "i");
const sensitiveNames = new Set([
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

function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function urlCredentials(value: string): boolean {
  const normalized = value
    .replace(/^[\u0000-\u0020]+/, "")
    .replace(/[\r\n\t]/g, "");
  const authority =
    /^[A-Za-z][A-Za-z0-9+.-]*:\/\/([^/?#]*)/.exec(normalized)?.[1] ?? "";
  if (authority.includes("@")) return true;
  const fragmentIndex = normalized.indexOf("#");
  const beforeFragment =
    fragmentIndex < 0 ? normalized : normalized.slice(0, fragmentIndex);
  const fragment = fragmentIndex < 0 ? "" : normalized.slice(fragmentIndex + 1);
  const queryIndex = beforeFragment.indexOf("?");
  const query = queryIndex < 0 ? "" : beforeFragment.slice(queryIndex + 1);
  for (const key of new URLSearchParams(query + "&" + fragment).keys()) {
    const name = key.toLowerCase().replace(/[^a-z0-9]/g, "");
    if (
      sensitiveNames.has(name) ||
      /(token|password|secret|signature|credential|apikey)$/.test(name)
    )
      return true;
  }
  return false;
}

function redactText(value: string): string {
  return value
    .replace(new RegExp(`http[s\\u017f]?://[^${WS}"'<>\\\\]+`, "gi"), (url) =>
      urlCredentials(url) ? REDACTED_URL : url,
    )
    .replace(
      new RegExp(
        `([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)=[^${WS}]+`,
        "g",
      ),
      `$1=${REDACTED}`,
    )
    .replace(
      new RegExp(`"(${NAME}${SECRET}${NAME})"[${WS}]*:[${WS}]*"[^"]*"`, "gi"),
      `"$1": "${REDACTED}"`,
    )
    .replace(
      /sk-(?:ant|proj|or)-[A-Za-z0-9_-]+|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|xox[bp]-[A-Za-z0-9-]+|AIza[A-Za-z0-9_-]+|eyJhbGciOi[A-Za-z0-9_.=-]+|AKIA[A-Z0-9]+/g,
      REDACTED,
    );
}

function withinPresentationDepth(value: string): boolean {
  let depth = 0;
  let quoted = false;
  let escaped = false;
  for (const char of value) {
    if (quoted) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') quoted = false;
    } else if (char === '"') quoted = true;
    else if (char === "[" || char === "{") {
      if (++depth > MAX_DEPTH) return false;
    } else if (char === "]" || char === "}") depth--;
  }
  return true;
}

function quotedEnd(value: string, start: number): number {
  for (let index = start + 1; index < value.length; index++) {
    if (value[index] === "\\") index++;
    else if (value[index] === '"') return index + 1;
  }
  throw new Error("Unfinished JSON string");
}

function strictPresentationJson(value: string): unknown {
  const parsed: unknown = JSON.parse(value);
  const containers: (Set<string> | null)[] = [];
  // JSON.parse validates grammar. This independent lexical pass rejects
  // duplicate decoded keys, matching Python's strict object_pairs_hook.
  for (let index = 0; index < value.length; index++) {
    const char = value[index];
    if (char === "{") containers.push(new Set());
    else if (char === "[") containers.push(null);
    else if (char === "}" || char === "]") containers.pop();
    else if (char === '"') {
      const end = quotedEnd(value, index);
      if (/^\s*:/.test(value.slice(end))) {
        const keys = containers.at(-1);
        const key: string = JSON.parse(value.slice(index, end));
        if (!keys || keys.has(key)) throw new Error("Duplicate JSON key");
        keys.add(key);
      }
      index = end - 1;
    }
  }
  return parsed;
}

function redactIncompleteJson(value: string): string {
  const fields = new RegExp(`("(?:[^"\\\\]|\\\\.)*")[${WS}]*:[${WS}]*`, "g");
  for (const match of value.matchAll(fields)) {
    let name: string;
    try {
      name = JSON.parse(match[1]);
    } catch {
      return REDACTED_JSON;
    }
    if (!secretField.test(name)) continue;
    const tail = value.slice(match.index! + match[0].length);
    if (!tail.startsWith('"')) continue;
    try {
      const end = quotedEnd(tail, 0);
      JSON.parse(tail.slice(0, end));
      if (match[1].includes("\\") || tail.slice(0, end).includes("\\"))
        return REDACTED_JSON;
    } catch {
      return REDACTED_JSON;
    }
  }
  return redactText(value);
}

function equalJson(left: unknown, right: unknown): boolean {
  const pending: [unknown, unknown][] = [[left, right]];
  while (pending.length) {
    const [a, b] = pending.pop()!;
    if (a === b) continue;
    if (Array.isArray(a) && Array.isArray(b) && a.length === b.length) {
      a.forEach((item, index) => pending.push([item, b[index]]));
    } else if (
      object(a) &&
      object(b) &&
      Object.keys(a).length === Object.keys(b).length
    ) {
      for (const key of Object.keys(a)) {
        if (!Object.hasOwn(b, key)) return false;
        pending.push([a[key], b[key]]);
      }
    } else return false;
  }
  return true;
}

function redactString(value: string): string {
  if ([REDACTED_URL, REDACTED, REDACTED_JSON].includes(value)) return value;
  if (/^http[s\u017f]?:\/\//i.test(value) && urlCredentials(value))
    return REDACTED_URL;
  if (new RegExp(`^[${WS}]*[\\[{]`).test(value)) {
    if (!withinPresentationDepth(value)) return REDACTED_JSON;
    let nested: unknown;
    try {
      nested = strictPresentationJson(value);
    } catch {
      return redactIncompleteJson(value);
    }
    const redacted = redactJson(nested);
    if (equalJson(redacted, nested)) return value;
    try {
      return canonicalStringify(redacted);
    } catch {
      return REDACTED_JSON;
    }
  }
  return redactText(value);
}

function redactJson(value: unknown): unknown {
  const result: unknown[] = [null];
  const pending: [unknown, any, string | number][] = [[value, result, 0]];
  while (pending.length) {
    const [item, parent, key] = pending.pop()!;
    if (typeof item === "string") parent[key] = redactString(item);
    else if (Array.isArray(item)) {
      const shaped = new Array(item.length);
      parent[key] = shaped;
      item.forEach((child, index) => pending.push([child, shaped, index]));
    } else if (object(item)) {
      const shaped = Object.create(null) as JsonObject;
      parent[key] = shaped;
      for (const [name, child] of Object.entries(item)) {
        const safeName = redactText(name);
        if (secretField.test(name) && typeof child === "string")
          shaped[safeName] = REDACTED;
        else pending.push([child, shaped, safeName]);
      }
    } else parent[key] = item;
  }
  return result[0];
}

function withinContainerDepth(value: unknown, limit: number): boolean {
  const pending: [unknown, number][] = [[value, 0]];
  while (pending.length) {
    const [item, depth] = pending.pop()!;
    if (Array.isArray(item) || object(item)) {
      if (depth + 1 > limit) return false;
      Object.values(item).forEach((child) => pending.push([child, depth + 1]));
    }
  }
  return true;
}

export function capturedTerminalProjection(call: JsonObject): JsonObject {
  const { response: _response, ...terminal } = call;
  if (!Object.hasOwn(call, "terminalProjectionVersion")) return terminal;
  if (call.terminalProjectionVersion !== 1)
    throw new Error("Unsupported terminal projection version");
  const bounded = Object.fromEntries(
    Object.entries(terminal).map(([key, value]) => [
      key,
      withinContainerDepth(value, MAX_DEPTH - 1) ? value : REDACTED_JSON,
    ]),
  );
  return redactJson(bounded) as JsonObject;
}

/** Retain Python's integer-only marker rule before JSON.parse erases 1.0. */
export function requireTerminalProjectionVersions(evidenceText: string): void {
  const stack: {
    kind: "object" | "array";
    role: "root" | "calls" | "call" | "other";
    expectingKey: boolean;
    key?: string;
  }[] = [];
  // The caller has already parsed and checked the JSON envelope. This pass
  // examines only version properties of direct root.calls[] objects.
  for (let index = 0; index < evidenceText.length; index++) {
    const char = evidenceText[index];
    const parent = stack.at(-1);
    if (char === "{" || char === "[") {
      const kind = char === "{" ? "object" : "array";
      const role =
        stack.length === 0
          ? "root"
          : kind === "array" &&
              parent?.role === "root" &&
              parent.key === "calls"
            ? "calls"
            : kind === "object" && parent?.role === "calls"
              ? "call"
              : "other";
      stack.push({ kind, role, expectingKey: kind === "object" });
    } else if (char === "}" || char === "]") stack.pop();
    else if (char === "," && parent?.kind === "object")
      parent.expectingKey = true;
    else if (char === '"') {
      const end = quotedEnd(evidenceText, index);
      if (parent?.kind === "object" && parent.expectingKey) {
        const key: string = JSON.parse(evidenceText.slice(index, end));
        parent.key = key;
        parent.expectingKey = false;
        if (parent.role === "call" && key === "terminalProjectionVersion") {
          const value = evidenceText.slice(end).replace(/^\s*:\s*/, "");
          if (!/^1(?=[\s,}])/.test(value))
            throw new Error("Unsupported terminal projection version");
        }
      }
      index = end - 1;
    }
  }
}
