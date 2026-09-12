/**
 * Read-only server proxy to the Thesis core API.
 *
 * The `/core` browser view is deliberately powerless: it can name an endpoint
 * out of a fixed allowlist and nothing else. The destination lives in
 * `THESIS_CORE_API_URL`, a server-only variable never exposed to the client,
 * so no browser can point this proxy at an arbitrary host. Nothing from the
 * incoming request is forwarded — no cookies, no `Authorization`, no
 * browser headers at all — because the core API is a private read surface and
 * an ambient credential riding along would be a confused-deputy hole.
 *
 * Every failure path returns a bounded same-origin JSON error carrying a code
 * and a fixed message. Upstream URLs and upstream response bodies are never
 * echoed: an error page from a private service is exactly the kind of thing
 * that leaks internal topology.
 */

/** Server-only base URL for the core API. Never `NEXT_PUBLIC_`. */
export const CORE_API_BASE_ENV = "THESIS_CORE_API_URL";

/** Path prefix this proxy is mounted at. */
export const CORE_PROXY_PREFIX = "/api/core/";

/** Upstream deadline, covering connection, headers *and* body consumption. */
export const UPSTREAM_TIMEOUT_MS = 5_000;

/** Hard cap on bytes actually read from the upstream stream. */
export const MAX_UPSTREAM_BYTES = 2 * 1024 * 1024;

export type CoreProxyErrorCode =
  | "core_api_unconfigured"
  | "core_api_misconfigured"
  | "invalid_path"
  | "endpoint_not_allowed"
  | "invalid_query"
  | "upstream_unavailable"
  | "upstream_timeout"
  | "upstream_redirect"
  | "upstream_status"
  | "upstream_media_type"
  | "upstream_invalid_json"
  | "upstream_response_too_large";

/**
 * Fixed, bounded messages. These are the only prose the proxy ever returns;
 * upstream text is never interpolated into them.
 */
const ERROR_MESSAGES: Record<CoreProxyErrorCode, string> = {
  core_api_unconfigured:
    "The core API is not configured for this deployment (THESIS_CORE_API_URL is unset).",
  core_api_misconfigured:
    "The configured core API base URL is not a usable http(s) URL.",
  invalid_path: "The requested core API path is not a valid endpoint path.",
  endpoint_not_allowed: "That core API endpoint is not on the read allowlist.",
  invalid_query: "The request carried a query parameter this endpoint does not accept.",
  upstream_unavailable: "The core API could not be reached.",
  upstream_timeout: "The core API did not respond within the proxy deadline.",
  upstream_redirect: "The core API answered with a redirect, which this proxy never follows.",
  upstream_status: "The core API returned an error status.",
  upstream_media_type: "The core API returned a response that was not application/json.",
  upstream_invalid_json: "The core API returned a body that is not valid JSON.",
  upstream_response_too_large: "The core API response exceeded the proxy size limit.",
};

const ERROR_STATUS: Record<CoreProxyErrorCode, number> = {
  core_api_unconfigured: 503,
  core_api_misconfigured: 503,
  invalid_path: 400,
  endpoint_not_allowed: 404,
  invalid_query: 400,
  upstream_unavailable: 502,
  upstream_timeout: 504,
  upstream_redirect: 502,
  upstream_status: 502,
  upstream_media_type: 502,
  upstream_invalid_json: 502,
  upstream_response_too_large: 502,
};

export type CoreQueryName = "limit" | "after" | "experiment_id" | "as_of";

/**
 * Exact collection endpoints, each with the query keys it accepts. Anything
 * absent from this table is rejected before a socket is opened, so adding a
 * core endpoint is a deliberate edit here rather than an emergent capability.
 *
 * The per-endpoint key sets mirror what `thesis_core/api.py` actually honours:
 * cursor collections take `limit`/`after`, `/rewards` takes `experiment_id`
 * and `as_of`, `/leaderboard` takes `experiment_id`, and `/health` and
 * `/pending` take nothing. Allowing a key the upstream ignores would be worse
 * than refusing it — the page would render an unfiltered list while implying a
 * filter. Widen a row here when the API starts honouring the key.
 */
export const CORE_COLLECTION_ENDPOINTS: Readonly<
  Record<string, readonly CoreQueryName[]>
> = {
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
};

/** Singular record reads are addressed by full content hash only. */
export const CORE_RECORD_COLLECTION = "records";

const HEX64 = /^[0-9a-f]{64}$/;
const SEGMENT = /^[A-Za-z0-9_-]+$/;
/** 1..100 with no leading zeros, no sign, no decimal point. */
const LIMIT = /^[1-9][0-9]{0,2}$/;
const ISO_INSTANT =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$/;

/**
 * A strict RFC 3339 instant: explicit zone, real calendar date, no bare dates
 * and no lenient `Date` coercion. `as_of` selects an availability boundary, so
 * a value that silently means midnight-local would quietly change which
 * records an export claims were available.
 */
export function isStrictIsoInstant(value: string): boolean {
  const match = ISO_INSTANT.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, zone] =
    match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  if (month < 1 || month > 12 || day < 1 || day > 31) return false;
  const probe = new Date(Date.UTC(year, month - 1, day));
  if (
    probe.getUTCFullYear() !== year ||
    probe.getUTCMonth() !== month - 1 ||
    probe.getUTCDate() !== day
  ) {
    return false;
  }
  if (Number(hourText) > 23 || Number(minuteText) > 59) return false;
  // Leap seconds are not representable downstream; refuse rather than round.
  if (Number(secondText) > 59) return false;
  if (zone !== "Z") {
    if (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4, 6)) > 59) {
      return false;
    }
  }
  return true;
}

function isValidQueryValue(name: CoreQueryName, value: string): boolean {
  switch (name) {
    case "limit": {
      if (!LIMIT.test(value)) return false;
      const limit = Number(value);
      return limit >= 1 && limit <= 100;
    }
    case "after":
    case "experiment_id":
      return HEX64.test(value);
    case "as_of":
      return isStrictIsoInstant(value);
  }
}

export interface ProxyTargetRejection {
  ok: false;
  code: Extract<
    CoreProxyErrorCode,
    "invalid_path" | "endpoint_not_allowed" | "invalid_query"
  >;
  /** Internal-only reason, useful in tests and server logs; never returned. */
  reason: string;
}

export interface ProxyTarget {
  ok: true;
  /** Validated path segments, safe to join into an upstream pathname. */
  segments: string[];
  /** Canonical, re-encoded query string ("" when empty), leading "?" included. */
  search: string;
}

/**
 * Validate the browser-supplied path and query against the allowlist.
 *
 * Path checks run on the *raw* (still percent-encoded) suffix so that an
 * encoded separator can never be laundered into a path segment by decoding.
 */
export function resolveProxyTarget(
  requestUrl: string,
): ProxyTarget | ProxyTargetRejection {
  let url: URL;
  try {
    url = new URL(requestUrl);
  } catch {
    return { ok: false, code: "invalid_path", reason: "unparseable request url" };
  }

  const pathname = url.pathname;
  if (!pathname.startsWith(CORE_PROXY_PREFIX)) {
    // `new URL` has already resolved `.` / `..`; anything that walked out of
    // the mount point lands here.
    return { ok: false, code: "invalid_path", reason: "outside proxy prefix" };
  }
  const raw = pathname.slice(CORE_PROXY_PREFIX.length);

  if (raw.length === 0) {
    return { ok: false, code: "invalid_path", reason: "empty path" };
  }
  if (raw.includes("\\")) {
    return { ok: false, code: "invalid_path", reason: "backslash" };
  }
  if (/%2f|%5c/i.test(raw)) {
    return { ok: false, code: "invalid_path", reason: "encoded separator" };
  }
  if (/%2e/i.test(raw)) {
    return { ok: false, code: "invalid_path", reason: "encoded dot segment" };
  }
  if (raw.includes("%")) {
    // No allowlisted segment needs percent-encoding, so any remaining escape
    // is either an evasion attempt or a client bug. Refuse both.
    return { ok: false, code: "invalid_path", reason: "percent-encoding" };
  }
  if (raw.includes(":") || raw.startsWith("/")) {
    return { ok: false, code: "invalid_path", reason: "absolute or scheme-like path" };
  }

  const segments = raw.split("/");
  for (const segment of segments) {
    if (segment.length === 0) {
      return { ok: false, code: "invalid_path", reason: "empty segment" };
    }
    if (segment === "." || segment === "..") {
      return { ok: false, code: "invalid_path", reason: "dot segment" };
    }
    if (!SEGMENT.test(segment)) {
      return { ok: false, code: "invalid_path", reason: "unexpected characters" };
    }
  }

  let allowedQueries: readonly CoreQueryName[];
  if (segments.length === 1) {
    const allowed = Object.prototype.hasOwnProperty.call(
      CORE_COLLECTION_ENDPOINTS,
      segments[0],
    )
      ? CORE_COLLECTION_ENDPOINTS[segments[0]]
      : undefined;
    if (!allowed) {
      return { ok: false, code: "endpoint_not_allowed", reason: "unknown collection" };
    }
    allowedQueries = allowed;
  } else if (segments.length === 2 && segments[0] === CORE_RECORD_COLLECTION) {
    if (!HEX64.test(segments[1])) {
      return {
        ok: false,
        code: "endpoint_not_allowed",
        reason: "record id is not a 64-character lowercase hash",
      };
    }
    allowedQueries = [];
  } else {
    return { ok: false, code: "endpoint_not_allowed", reason: "unknown path depth" };
  }

  const params = url.searchParams;
  const seen = new Set<string>();
  for (const key of params.keys()) {
    if (seen.has(key)) continue;
    seen.add(key);
    if (params.getAll(key).length > 1) {
      return { ok: false, code: "invalid_query", reason: "repeated query key" };
    }
    if (!(allowedQueries as readonly string[]).includes(key)) {
      return { ok: false, code: "invalid_query", reason: "query key not allowed here" };
    }
    const value = params.get(key) ?? "";
    if (!isValidQueryValue(key as CoreQueryName, value)) {
      return { ok: false, code: "invalid_query", reason: "query value rejected" };
    }
  }

  // Rebuild the query from validated pairs in a fixed order rather than
  // forwarding the client's string, so nothing unvalidated survives.
  const canonical = new URLSearchParams();
  for (const key of [...allowedQueries].sort()) {
    const value = params.get(key);
    if (value !== null) canonical.set(key, value);
  }
  const search = canonical.toString();

  return { ok: true, segments, search: search ? `?${search}` : "" };
}

interface UpstreamBase {
  ok: true;
  url: URL;
}

interface UpstreamBaseRejection {
  ok: false;
  code: Extract<CoreProxyErrorCode, "core_api_unconfigured" | "core_api_misconfigured">;
}

export function resolveUpstreamBase(
  configured: string | undefined,
): UpstreamBase | UpstreamBaseRejection {
  const trimmed = configured?.trim();
  if (!trimmed) return { ok: false, code: "core_api_unconfigured" };
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return { ok: false, code: "core_api_misconfigured" };
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return { ok: false, code: "core_api_misconfigured" };
  }
  if (url.username !== "" || url.password !== "") {
    // `fetch` refuses a URL carrying credentials, so this would otherwise fail
    // as a permanent, misleading "core API unreachable" on every request.
    return { ok: false, code: "core_api_misconfigured" };
  }
  return { ok: true, url };
}

/** Build the upstream URL. Segments are already allowlisted, so this is total. */
export function buildUpstreamUrl(base: URL, target: ProxyTarget): URL {
  const upstream = new URL(base.toString());
  const basePath = upstream.pathname.replace(/\/+$/, "");
  upstream.pathname = `${basePath}/${target.segments.join("/")}`;
  // The configured base may carry its own query or fragment; neither belongs
  // on a proxied read.
  upstream.search = target.search;
  upstream.hash = "";
  return upstream;
}

const JSON_HEADERS: Record<string, string> = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store, max-age=0",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};

export function coreProxyError(
  code: CoreProxyErrorCode,
  extra?: { upstreamStatus?: number },
): Response {
  const body: Record<string, unknown> = {
    code,
    message: ERROR_MESSAGES[code],
  };
  if (typeof extra?.upstreamStatus === "number") {
    body.upstream_status = extra.upstreamStatus;
  }
  return new Response(JSON.stringify({ error: body }), {
    status: ERROR_STATUS[code],
    headers: JSON_HEADERS,
  });
}

class UpstreamTimeout extends Error {}

/**
 * Let go of an upstream response we are not going to read. An undrained body
 * pins its socket until garbage collection, so a stream of redirects or 500s
 * would exhaust the connection pool. Cancelling is fire-and-forget: a stalled
 * source must not delay the error we already decided to return.
 */
function releaseUpstream(response: Response, controller: AbortController): void {
  void response.body?.cancel().catch(() => {});
  controller.abort();
}

/** Media type comparison ignores case and every parameter, including charset. */
export function isJsonMediaType(headerValue: string | null): boolean {
  if (headerValue === null) return false;
  const mediaType = headerValue.split(";", 1)[0].trim().toLowerCase();
  return mediaType === "application/json";
}

export interface CoreProxyOptions {
  /** Injectable for tests; defaults to the runtime `fetch`. */
  fetchImpl?: typeof fetch;
  /** Injectable for tests; defaults to `process.env`. */
  env?: Record<string, string | undefined>;
}

/**
 * Handle one proxied GET. Returns a same-origin JSON response in every case,
 * success or failure.
 */
export async function handleCoreProxyRequest(
  request: Request,
  options: CoreProxyOptions = {},
): Promise<Response> {
  const target = resolveProxyTarget(request.url);
  if (!target.ok) return coreProxyError(target.code);

  const env = options.env ?? process.env;
  const base = resolveUpstreamBase(env[CORE_API_BASE_ENV]);
  if (!base.ok) return coreProxyError(base.code);

  const upstream = buildUpstreamUrl(base.url, target);
  const doFetch = options.fetchImpl ?? globalThis.fetch;

  const controller = new AbortController();
  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(new UpstreamTimeout());
    }, UPSTREAM_TIMEOUT_MS);
  });
  // The losing side of every race below is never awaited again.
  deadline.catch(() => {});

  try {
    let response: Response;
    try {
      response = await Promise.race([
        doFetch(upstream, {
          method: "GET",
          // Nothing from the browser is forwarded: no cookies, no
          // Authorization, no client-controlled headers of any kind.
          headers: { accept: "application/json" },
          credentials: "omit",
          cache: "no-store",
          redirect: "manual",
          signal: controller.signal,
        }),
        deadline,
      ]);
    } catch (error) {
      if (timedOut || error instanceof UpstreamTimeout) {
        return coreProxyError("upstream_timeout");
      }
      // Network error messages routinely embed the target URL; drop them.
      return coreProxyError("upstream_unavailable");
    }

    // `redirect: "manual"` surfaces the 3xx (Node) or an opaque redirect
    // (browser-shaped fetch). Neither is followed.
    if (
      response.type === "opaqueredirect" ||
      (response.status >= 300 && response.status < 400)
    ) {
      releaseUpstream(response, controller);
      return coreProxyError("upstream_redirect");
    }
    if (!response.ok) {
      releaseUpstream(response, controller);
      return coreProxyError("upstream_status", { upstreamStatus: response.status });
    }
    if (!isJsonMediaType(response.headers.get("content-type"))) {
      releaseUpstream(response, controller);
      return coreProxyError("upstream_media_type");
    }

    // Content-Length is an optional early exit only; the real bound is the
    // count of bytes read below, so an understated or absent header cannot
    // buy the upstream any extra bytes.
    const declaredLength = Number(response.headers.get("content-length"));
    if (Number.isFinite(declaredLength) && declaredLength > MAX_UPSTREAM_BYTES) {
      releaseUpstream(response, controller);
      return coreProxyError("upstream_response_too_large");
    }

    const body = response.body;
    let text: string;
    if (!body) {
      text = "";
    } else {
      const reader = body.getReader();
      const decoder = new TextDecoder("utf-8");
      let total = 0;
      let decoded = "";
      try {
        for (;;) {
          const chunk = await Promise.race([reader.read(), deadline]);
          if (chunk.done) break;
          const value = chunk.value;
          if (!value) continue;
          total += value.byteLength;
          if (total > MAX_UPSTREAM_BYTES) {
            // Fire-and-forget: a stalled source must not delay the rejection.
            void reader.cancel().catch(() => {});
            controller.abort();
            return coreProxyError("upstream_response_too_large");
          }
          decoded += decoder.decode(value, { stream: true });
        }
        decoded += decoder.decode();
      } catch (error) {
        void reader.cancel().catch(() => {});
        if (timedOut || error instanceof UpstreamTimeout) {
          return coreProxyError("upstream_timeout");
        }
        return coreProxyError("upstream_unavailable");
      }
      text = decoded;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      return coreProxyError("upstream_invalid_json");
    }

    // Re-serialize what was parsed: the client is guaranteed valid JSON with
    // a media type this proxy controls.
    return new Response(JSON.stringify(parsed), {
      status: 200,
      headers: JSON_HEADERS,
    });
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
