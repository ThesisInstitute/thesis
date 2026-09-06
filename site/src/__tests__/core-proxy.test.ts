// @vitest-environment node
//
// Security and correctness contract for the /api/core read proxy. The proxy is
// the only thing standing between a public page and a private core API, so the
// cases below are written as adversarial inputs, not as happy-path coverage.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CORE_API_BASE_ENV,
  CORE_COLLECTION_ENDPOINTS,
  MAX_UPSTREAM_BYTES,
  UPSTREAM_TIMEOUT_MS,
  handleCoreProxyRequest,
  isJsonMediaType,
  isStrictIsoInstant,
  resolveProxyTarget,
} from "@/lib/core-proxy";
import * as route from "@/app/api/core/[...path]/route";

const UPSTREAM = "https://core.internal.example/v1";
const ENV = { [CORE_API_BASE_ENV]: UPSTREAM };
const HEX64 = "a".repeat(64);
const OTHER_HEX64 = "b3".repeat(32);

function request(path: string): Request {
  return new Request(`https://thesis.example${path}`);
}

function jsonUpstream(
  body: unknown,
  init: { status?: number; contentType?: string | null; headers?: Record<string, string> } = {},
): Response {
  const headers = new Headers(init.headers);
  if (init.contentType !== null) {
    headers.set("content-type", init.contentType ?? "application/json");
  }
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers,
  });
}

function textUpstream(text: string, contentType: string): Response {
  return new Response(text, { status: 200, headers: { "content-type": contentType } });
}

/** A stream that hands out `chunkCount` chunks of `chunkSize` bytes, lazily. */
function chunkedUpstream(
  chunkCount: number,
  chunkSize: number,
  headers: Record<string, string> = {},
): { response: Response } {
  let emitted = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (emitted >= chunkCount) {
        controller.close();
        return;
      }
      emitted += 1;
      controller.enqueue(new Uint8Array(chunkSize).fill(0x61));
    },
  });
  const response = new Response(stream, {
    status: 200,
    headers: { "content-type": "application/json", ...headers },
  });
  return { response };
}

function stalledUpstream(): Response {
  const stream = new ReadableStream<Uint8Array>({
    pull() {
      // Never settles: models a connection that opens and then goes quiet.
      return new Promise<void>(() => {});
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

/** Typed so `mock.calls[0][1]` stays inspectable under `tsc`. */
function okFetch(body: unknown = { items: [], next_cursor: null }) {
  return vi.fn(async (_input: unknown, _init?: RequestInit) => jsonUpstream(body));
}

async function errorBody(response: Response): Promise<{
  code?: string;
  message?: string;
  upstream_status?: number;
}> {
  const parsed = (await response.json()) as { error?: Record<string, unknown> };
  return (parsed.error ?? {}) as {
    code?: string;
    message?: string;
    upstream_status?: number;
  };
}

describe("core proxy path allowlist", () => {
  it("accepts every allowlisted collection endpoint", async () => {
    for (const endpoint of Object.keys(CORE_COLLECTION_ENDPOINTS)) {
      const fetchImpl = okFetch();
      const response = await handleCoreProxyRequest(
        request(`/api/core/${endpoint}`),
        { fetchImpl, env: ENV },
      );
      expect(response.status, endpoint).toBe(200);
      expect(String(fetchImpl.mock.calls[0][0])).toBe(`${UPSTREAM}/${endpoint}`);
    }
  });

  it("accepts a singular record read addressed by a 64-character lowercase hash", async () => {
    const fetchImpl = okFetch({ id: HEX64, kind: "experiment", payload: {} });
    const response = await handleCoreProxyRequest(
      request(`/api/core/records/${HEX64}`),
      { fetchImpl, env: ENV },
    );
    expect(response.status).toBe(200);
    expect(String(fetchImpl.mock.calls[0][0])).toBe(`${UPSTREAM}/records/${HEX64}`);
  });

  it.each([
    ["unknown collection", "/api/core/secrets"],
    ["case-variant collection", "/api/core/Experiments"],
    ["nested unknown depth", "/api/core/experiments/summary"],
    ["record id too short", `/api/core/records/${"a".repeat(63)}`],
    ["record id uppercase", `/api/core/records/${"A".repeat(64)}`],
    ["record id missing", "/api/core/records"],
    ["record id non-hex", `/api/core/records/${"g".repeat(64)}`],
  ])("rejects %s without contacting the upstream", async (_label, path) => {
    const fetchImpl = okFetch();
    const response = await handleCoreProxyRequest(request(path), {
      fetchImpl,
      env: ENV,
    });
    expect(response.status).toBe(404);
    expect((await errorBody(response)).code).toBe("endpoint_not_allowed");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it.each([
    ["encoded slash", "/api/core/experiments%2f..%2fadmin"],
    ["encoded backslash", "/api/core/experiments%5cadmin"],
    ["encoded dot segments", "/api/core/%2e%2e/%2e%2e/etc/passwd"],
    ["percent escape", "/api/core/experi%6dents"],
    ["scheme in path", "/api/core/https://evil.example/steal"],
    ["protocol-relative path", "/api/core//evil.example/steal"],
    ["empty path", "/api/core/"],
    ["trailing slash", "/api/core/experiments/"],
    ["double slash inside", "/api/core/experiments//runs"],
  ])("rejects %s as an invalid path", async (_label, path) => {
    const fetchImpl = okFetch();
    const response = await handleCoreProxyRequest(request(path), {
      fetchImpl,
      env: ENV,
    });
    expect(response.status).toBe(400);
    expect((await errorBody(response)).code).toBe("invalid_path");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects a literal backslash, which URL parsing turns into a separator", async () => {
    // WHATWG URL rewrites `\` to `/` for special schemes, so this arrives as a
    // two-segment path rather than a segment containing a backslash. Either
    // way it must not reach the upstream.
    const fetchImpl = okFetch();
    const response = await handleCoreProxyRequest(
      request("/api/core/experiments\\admin"),
      { fetchImpl, env: ENV },
    );
    expect(response.status).toBe(404);
    expect((await errorBody(response)).code).toBe("endpoint_not_allowed");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects a traversal that resolves outside the proxy mount point", async () => {
    const fetchImpl = okFetch();
    const response = await handleCoreProxyRequest(
      request("/api/core/../../etc/passwd"),
      { fetchImpl, env: ENV },
    );
    expect(response.status).toBe(400);
    expect((await errorBody(response)).code).toBe("invalid_path");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("never lets the client choose the upstream host", async () => {
    const fetchImpl = okFetch();
    const response = await handleCoreProxyRequest(
      request("/api/core/experiments?url=https://evil.example"),
      { fetchImpl, env: ENV },
    );
    expect(response.status).toBe(400);
    expect((await errorBody(response)).code).toBe("invalid_query");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("core proxy query rules", () => {
  it.each([
    ["/api/core/experiments?limit=1", `${UPSTREAM}/experiments?limit=1`],
    ["/api/core/experiments?limit=100", `${UPSTREAM}/experiments?limit=100`],
    [
      `/api/core/rewards?experiment_id=${HEX64}&as_of=2026-09-04T12:00:00Z`,
      `${UPSTREAM}/rewards?as_of=2026-09-04T12%3A00%3A00Z&experiment_id=${HEX64}`,
    ],
    [
      `/api/core/experiments?after=${OTHER_HEX64}`,
      `${UPSTREAM}/experiments?after=${OTHER_HEX64}`,
    ],
    [
      "/api/core/rewards?as_of=2026-09-04T12:00:00Z",
      `${UPSTREAM}/rewards?as_of=2026-09-04T12%3A00%3A00Z`,
    ],
    [
      `/api/core/leaderboard?experiment_id=${HEX64}`,
      `${UPSTREAM}/leaderboard?experiment_id=${HEX64}`,
    ],
  ])("forwards %s as a canonical query", async (path, expected) => {
    const fetchImpl = okFetch();
    const response = await handleCoreProxyRequest(request(path), {
      fetchImpl,
      env: ENV,
    });
    expect(response.status).toBe(200);
    expect(String(fetchImpl.mock.calls[0][0])).toBe(expected);
  });

  it.each([
    ["limit below range", "/api/core/experiments?limit=0"],
    ["limit above range", "/api/core/experiments?limit=101"],
    ["limit with leading zero", "/api/core/experiments?limit=007"],
    ["limit non-integer", "/api/core/experiments?limit=1.5"],
    ["limit negative", "/api/core/experiments?limit=-1"],
    ["limit non-numeric", "/api/core/experiments?limit=all"],
    ["limit empty", "/api/core/experiments?limit="],
    ["after wrong length", "/api/core/experiments?after=abc"],
    ["after uppercase hex", `/api/core/experiments?after=${"A".repeat(64)}`],
    ["experiment_id wrong shape", "/api/core/rewards?experiment_id=1"],
    ["as_of date only", "/api/core/rewards?as_of=2026-09-04"],
    ["as_of without zone", "/api/core/rewards?as_of=2026-09-04T12:00:00"],
    ["as_of impossible day", "/api/core/rewards?as_of=2026-02-30T00:00:00Z"],
    ["as_of impossible month", "/api/core/rewards?as_of=2026-13-01T00:00:00Z"],
    ["as_of where the upstream ignores it", "/api/core/observations?as_of=2026-09-04T12:00:00Z"],
    ["a filter the upstream would silently ignore", `/api/core/runs?experiment_id=${HEX64}`],
    ["pagination on pending", "/api/core/pending?limit=5"],
    ["unknown key", "/api/core/experiments?fields=*"],
    ["key not allowed on this endpoint", "/api/core/experiments?experiment_id=" + HEX64],
    ["cursor on a summary endpoint", `/api/core/rewards?after=${HEX64}`],
    ["pagination on health", "/api/core/health?limit=5"],
    ["pagination on leaderboard", "/api/core/leaderboard?limit=5"],
    ["query on a record read", `/api/core/records/${HEX64}?limit=1`],
    ["repeated key", "/api/core/experiments?limit=1&limit=2"],
  ])("rejects %s without contacting the upstream", async (_label, path) => {
    const fetchImpl = okFetch();
    const response = await handleCoreProxyRequest(request(path), {
      fetchImpl,
      env: ENV,
    });
    expect(response.status).toBe(400);
    expect((await errorBody(response)).code).toBe("invalid_query");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("accepts strict instants and refuses lenient date strings", () => {
    expect(isStrictIsoInstant("2026-09-04T12:00:00Z")).toBe(true);
    expect(isStrictIsoInstant("2026-09-04T12:00:00.123456Z")).toBe(true);
    expect(isStrictIsoInstant("2026-09-04T12:00:00-04:00")).toBe(true);
    expect(isStrictIsoInstant("2026-02-29T00:00:00Z")).toBe(false);
    expect(isStrictIsoInstant("2024-02-29T00:00:00Z")).toBe(true);
    expect(isStrictIsoInstant("2026-09-04T24:00:00Z")).toBe(false);
    expect(isStrictIsoInstant("2026-09-04T23:59:60Z")).toBe(false);
    expect(isStrictIsoInstant("2026-09-04 12:00:00Z")).toBe(false);
    expect(isStrictIsoInstant("2026-09-04T12:00:00+25:00")).toBe(false);
    expect(isStrictIsoInstant("")).toBe(false);
  });

  it("rebuilds the query rather than forwarding the client string", () => {
    const target = resolveProxyTarget(
      `https://thesis.example/api/core/runs?limit=10&after=${OTHER_HEX64}`,
    );
    expect(target.ok).toBe(true);
    if (!target.ok) return;
    expect(target.segments).toEqual(["runs"]);
    expect(target.search).toBe(`?after=${OTHER_HEX64}&limit=10`);
  });

  it("allows only the query keys the landed core API honours", () => {
    // Mirrors thesis_core/api.py; a key the upstream ignores must not be
    // accepted, or the page would imply a filter that never happened.
    expect(CORE_COLLECTION_ENDPOINTS).toEqual({
      health: [],
      experiments: ["limit", "after"],
      tasks: ["limit", "after"],
      runs: ["limit", "after"],
      proofs: ["limit", "after"],
      observations: ["limit", "after"],
      pending: [],
      resolutions: ["limit", "after"],
      rewards: ["experiment_id", "as_of"],
      leaderboard: ["experiment_id"],
    });
  });
});

describe("core proxy configuration", () => {
  it("returns a clear 503 when the base URL is unset, without fetching", async () => {
    const fetchImpl = okFetch();
    const response = await handleCoreProxyRequest(request("/api/core/health"), {
      fetchImpl,
      env: {},
    });
    expect(response.status).toBe(503);
    expect((await errorBody(response)).code).toBe("core_api_unconfigured");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("treats a blank base URL as unconfigured", async () => {
    const response = await handleCoreProxyRequest(request("/api/core/health"), {
      fetchImpl: okFetch(),
      env: { [CORE_API_BASE_ENV]: "   " },
    });
    expect((await errorBody(response)).code).toBe("core_api_unconfigured");
  });

  it.each(["not a url", "ftp://core.internal.example", "file:///etc/passwd"])(
    "refuses a non-http base URL (%s)",
    async (value) => {
      const fetchImpl = okFetch();
      const response = await handleCoreProxyRequest(request("/api/core/health"), {
        fetchImpl,
        env: { [CORE_API_BASE_ENV]: value },
      });
      expect(response.status).toBe(503);
      expect((await errorBody(response)).code).toBe("core_api_misconfigured");
      expect(fetchImpl).not.toHaveBeenCalled();
    },
  );

  it("joins a base path and drops any query or fragment configured on it", async () => {
    const fetchImpl = okFetch();
    await handleCoreProxyRequest(request("/api/core/experiments?limit=3"), {
      fetchImpl,
      env: { [CORE_API_BASE_ENV]: "https://core.internal.example/base/?token=x#frag" },
    });
    expect(String(fetchImpl.mock.calls[0][0])).toBe(
      "https://core.internal.example/base/experiments?limit=3",
    );
  });

  it("reads the base URL from the process environment by default", async () => {
    const fetchImpl = okFetch();
    process.env[CORE_API_BASE_ENV] = "https://core.env.example";
    try {
      const response = await handleCoreProxyRequest(request("/api/core/health"), {
        fetchImpl,
      });
      expect(response.status).toBe(200);
      expect(String(fetchImpl.mock.calls[0][0])).toBe(
        "https://core.env.example/health",
      );
    } finally {
      delete process.env[CORE_API_BASE_ENV];
    }
  });
});

describe("core proxy upstream request", () => {
  it("forwards no browser headers, cookies or credentials", async () => {
    const fetchImpl = okFetch();
    const incoming = new Request("https://thesis.example/api/core/experiments", {
      headers: {
        cookie: "session=super-secret",
        authorization: "Bearer super-secret",
        "x-forwarded-for": "203.0.113.9",
        "user-agent": "Mozilla/5.0",
      },
    });
    await handleCoreProxyRequest(incoming, { fetchImpl, env: ENV });

    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(Object.keys(headers)).toEqual(["accept"]);
    expect(JSON.stringify(init)).not.toContain("super-secret");
    expect(init.credentials).toBe("omit");
  });

  it("uses GET with no store, manual redirects and an abort signal", async () => {
    const fetchImpl = okFetch();
    await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl,
      env: ENV,
    });
    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("GET");
    expect(init.cache).toBe("no-store");
    expect(init.redirect).toBe("manual");
    expect(init.body ?? null).toBeNull();
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("returns the parsed body with a fixed JSON content type and no caching", async () => {
    const body = { items: [{ id: HEX64, kind: "experiment", payload: { mode: "replay" } }], next_cursor: null };
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: okFetch(body),
      env: ENV,
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("application/json; charset=utf-8");
    expect(response.headers.get("cache-control")).toBe("no-store, max-age=0");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    await expect(response.json()).resolves.toEqual(body);
  });
});

describe("core proxy upstream failures", () => {
  it("never follows a redirect", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(null, {
        status: 302,
        headers: { location: "https://evil.example/steal" },
      }),
    );
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl,
      env: ENV,
    });
    expect(response.status).toBe(502);
    const body = await errorBody(response);
    expect(body.code).toBe("upstream_redirect");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(body)).not.toContain("evil.example");
  });

  it("rejects a browser-shaped opaque redirect", async () => {
    const opaque = new Response(null, { status: 200 });
    Object.defineProperty(opaque, "type", { value: "opaqueredirect" });
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () => opaque),
      env: ENV,
    });
    expect((await errorBody(response)).code).toBe("upstream_redirect");
  });

  it.each([400, 401, 403, 404, 500, 503])(
    "reports upstream status %s without echoing its body",
    async (status) => {
      const fetchImpl = vi.fn(async () =>
        jsonUpstream({ detail: "internal stack trace with /srv/core secrets" }, { status }),
      );
      const response = await handleCoreProxyRequest(request("/api/core/runs"), {
        fetchImpl,
        env: ENV,
      });
      expect(response.status).toBe(502);
      const body = await errorBody(response);
      expect(body.code).toBe("upstream_status");
      expect(body.upstream_status).toBe(status);
      expect(JSON.stringify(body)).not.toContain("stack trace");
      expect(JSON.stringify(body)).not.toContain("core.internal.example");
    },
  );

  it.each([
    ["text/html", "<html>internal error page</html>"],
    ["application/xml", "<error>internal</error>"],
    ["text/json", "{}"],
    ["application/jsonx", "{}"],
    ["application/json-seq", "{}"],
  ])("rejects a %s upstream body", async (contentType, payload) => {
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () => textUpstream(payload, contentType)),
      env: ENV,
    });
    expect(response.status).toBe(502);
    const body = await errorBody(response);
    expect(body.code).toBe("upstream_media_type");
    expect(JSON.stringify(body)).not.toContain("internal");
  });

  it("rejects an upstream body with no content type at all", async () => {
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () => jsonUpstream({ items: [] }, { contentType: null })),
      env: ENV,
    });
    expect((await errorBody(response)).code).toBe("upstream_media_type");
  });

  it.each([
    "application/json; charset=utf-8",
    "APPLICATION/JSON",
    "Application/Json ;charset=UTF-8",
    'application/json;charset="utf-8"',
  ])("accepts the JSON media type %s", async (contentType) => {
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () =>
        textUpstream('{"items":[],"next_cursor":null}', contentType),
      ),
      env: ENV,
    });
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ items: [], next_cursor: null });
  });

  it("parses the media type independently of its parameters", () => {
    expect(isJsonMediaType("application/json")).toBe(true);
    expect(isJsonMediaType("application/json; charset=utf-16")).toBe(true);
    expect(isJsonMediaType("text/html; x=application/json")).toBe(false);
    expect(isJsonMediaType(null)).toBe(false);
  });

  it("rejects a JSON-typed body that is not valid JSON", async () => {
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () =>
        textUpstream("{ items: [ truncated internal dump", "application/json"),
      ),
      env: ENV,
    });
    expect(response.status).toBe(502);
    const body = await errorBody(response);
    expect(body.code).toBe("upstream_invalid_json");
    expect(JSON.stringify(body)).not.toContain("truncated internal dump");
  });

  it("reports an unreachable upstream without leaking the address", async () => {
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () => {
        throw new TypeError("fetch failed: connect ECONNREFUSED core.internal.example:443");
      }),
      env: ENV,
    });
    expect(response.status).toBe(502);
    const body = await errorBody(response);
    expect(body.code).toBe("upstream_unavailable");
    expect(JSON.stringify(body)).not.toContain("core.internal.example");
  });
});

describe("core proxy response size cap", () => {
  it("aborts a chunked oversize body that declares no length", async () => {
    const oversize = chunkedUpstream(3, 1024 * 1024);
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () => oversize.response),
      env: ENV,
    });
    expect(response.status).toBe(502);
    expect((await errorBody(response)).code).toBe("upstream_response_too_large");
  });

  it("still rejects when the content-length header understates the body", async () => {
    const oversize = chunkedUpstream(3, 1024 * 1024, { "content-length": "12" });
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () => oversize.response),
      env: ENV,
    });
    expect((await errorBody(response)).code).toBe("upstream_response_too_large");
  });

  it("uses an oversized content-length as an early exit before consuming the body", async () => {
    // The body never produces a byte: if the proxy tried to read it instead of
    // exiting on the header, this test would hang rather than fail.
    const stalled = new Response(
      new ReadableStream<Uint8Array>({
        pull() {
          return new Promise<void>(() => {});
        },
      }),
      {
        status: 200,
        headers: {
          "content-type": "application/json",
          "content-length": String(MAX_UPSTREAM_BYTES + 1),
        },
      },
    );
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () => stalled),
      env: ENV,
    });
    expect((await errorBody(response)).code).toBe("upstream_response_too_large");
    // ...and the abandoned body is released rather than pinning its socket.
    expect(stalled.bodyUsed).toBe(true);
  });

  it.each([
    [
      "redirect",
      () => new Response(null, { status: 302, headers: { location: "/elsewhere" } }),
    ],
    ["non-2xx", () => jsonUpstream({ detail: "nope" }, { status: 500 })],
    ["wrong media type", () => textUpstream("<html></html>", "text/html")],
  ])("releases the upstream body on the %s path", async (_label, make) => {
    const upstream = make();
    await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () => upstream),
      env: ENV,
    });
    // An undrained body holds its socket until GC; every early return must
    // cancel it.
    expect(upstream.body === null || upstream.bodyUsed).toBe(true);
  });

  it("refuses a base URL carrying credentials rather than failing every request", async () => {
    const fetchImpl = okFetch();
    const response = await handleCoreProxyRequest(request("/api/core/health"), {
      fetchImpl,
      env: { [CORE_API_BASE_ENV]: "https://user:secret@core.internal.example" },
    });
    expect(response.status).toBe(503);
    const body = await response.text();
    expect(JSON.parse(body).error.code).toBe("core_api_misconfigured");
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(body).not.toContain("secret");
  });

  it("accepts a body exactly at the cap", async () => {
    const padding = "a".repeat(MAX_UPSTREAM_BYTES - '{"pad":""}'.length);
    const payload = `{"pad":"${padding}"}`;
    expect(payload.length).toBe(MAX_UPSTREAM_BYTES);
    const response = await handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () => textUpstream(payload, "application/json")),
      env: ENV,
    });
    expect(response.status).toBe(200);
  });
});

describe("core proxy limits match the plan, not just the implementation", () => {
  it("pins the five-second deadline and two-mebibyte cap as literals", () => {
    // Every other limit test advances or sizes itself from these constants, so
    // without this one the suite would follow the implementation anywhere.
    expect(UPSTREAM_TIMEOUT_MS).toBe(5_000);
    expect(MAX_UPSTREAM_BYTES).toBe(2 * 1024 * 1024);
  });
});

describe("core proxy deadline", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("times out an upstream that never answers", async () => {
    const fetchImpl = vi.fn(() => new Promise<Response>(() => {}));
    const pending = handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      env: ENV,
    });
    await vi.advanceTimersByTimeAsync(UPSTREAM_TIMEOUT_MS);
    const response = await pending;
    expect(response.status).toBe(504);
    expect((await errorBody(response)).code).toBe("upstream_timeout");
  });

  it("times out an upstream that answers headers and then stalls the body", async () => {
    const pending = handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: vi.fn(async () => stalledUpstream()),
      env: ENV,
    });
    await vi.advanceTimersByTimeAsync(UPSTREAM_TIMEOUT_MS);
    const response = await pending;
    expect(response.status).toBe(504);
    expect((await errorBody(response)).code).toBe("upstream_timeout");
  });

  it("aborts the upstream request when the deadline fires", async () => {
    let signal: AbortSignal | undefined;
    const fetchImpl = vi.fn((_input: unknown, init?: RequestInit) => {
      signal = init?.signal ?? undefined;
      return new Promise<Response>(() => {});
    });
    const pending = handleCoreProxyRequest(request("/api/core/experiments"), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      env: ENV,
    });
    await vi.advanceTimersByTimeAsync(UPSTREAM_TIMEOUT_MS);
    await pending;
    expect(signal?.aborted).toBe(true);
  });
});

describe("core proxy never leaks its configuration", () => {
  const cases: Array<[string, () => Promise<Response>]> = [
    [
      "redirect",
      () =>
        handleCoreProxyRequest(request("/api/core/experiments"), {
          fetchImpl: vi.fn(async () =>
            new Response(null, { status: 307, headers: { location: UPSTREAM } }),
          ),
          env: ENV,
        }),
    ],
    [
      "non-2xx",
      () =>
        handleCoreProxyRequest(request("/api/core/experiments"), {
          fetchImpl: vi.fn(async () => jsonUpstream({ url: UPSTREAM }, { status: 500 })),
          env: ENV,
        }),
    ],
    [
      "wrong media type",
      () =>
        handleCoreProxyRequest(request("/api/core/experiments"), {
          fetchImpl: vi.fn(async () => textUpstream(UPSTREAM, "text/plain")),
          env: ENV,
        }),
    ],
    [
      "bad JSON",
      () =>
        handleCoreProxyRequest(request("/api/core/experiments"), {
          fetchImpl: vi.fn(async () => textUpstream(`{${UPSTREAM}`, "application/json")),
          env: ENV,
        }),
    ],
    [
      "network error",
      () =>
        handleCoreProxyRequest(request("/api/core/experiments"), {
          fetchImpl: vi.fn(async () => {
            throw new Error(`connect failed to ${UPSTREAM}`);
          }),
          env: ENV,
        }),
    ],
    [
      "oversize",
      () =>
        handleCoreProxyRequest(request("/api/core/experiments"), {
          fetchImpl: vi.fn(async () => chunkedUpstream(3, 1024 * 1024).response),
          env: ENV,
        }),
    ],
  ];

  it.each(cases)("keeps the upstream URL out of the %s error", async (_label, run) => {
    const response = await run();
    const text = await response.text();
    expect(text).not.toContain("core.internal.example");
    expect(text).not.toContain(UPSTREAM);
    // Error bodies stay small enough to be safe to render.
    expect(text.length).toBeLessThan(500);
    expect(response.headers.get("content-type")).toBe("application/json; charset=utf-8");
  });
});

describe("core proxy server-only configuration", () => {
  it("keeps the upstream base URL out of every client-side module", async () => {
    const { readFile, readdir } = await import("node:fs/promises");
    const { join } = await import("node:path");
    const dir = join(process.cwd(), "src", "app", "core");
    for (const entry of await readdir(dir)) {
      if (!/\.(ts|tsx)$/.test(entry)) continue;
      const source = await readFile(join(dir, entry), "utf8");
      expect(source, entry).not.toContain(CORE_API_BASE_ENV);
      expect(source, entry).not.toContain("process.env");
      // The browser addresses the same-origin proxy, never an upstream host.
      expect(source, entry).not.toMatch(/https?:\/\//);
    }
  });
});

describe("core proxy route module", () => {
  it("is a dynamic Node runtime route that never caches", () => {
    expect(route.dynamic).toBe("force-dynamic");
    expect(route.runtime).toBe("nodejs");
    expect(route.fetchCache).toBe("force-no-store");
    expect(route.revalidate).toBe(0);
    expect(typeof route.GET).toBe("function");
  });

  it("answers unconfigured deployments through the exported GET handler", async () => {
    const previous = process.env[CORE_API_BASE_ENV];
    delete process.env[CORE_API_BASE_ENV];
    try {
      const response = await route.GET(request("/api/core/health"));
      expect(response.status).toBe(503);
      expect((await errorBody(response)).code).toBe("core_api_unconfigured");
    } finally {
      if (previous !== undefined) process.env[CORE_API_BASE_ENV] = previous;
    }
  });
});
