/**
 * Browser-side reads of the same-origin core proxy.
 *
 * Every request is explicitly credential-free. The proxy holds the upstream
 * destination server-side and forwards nothing from the browser, so sending
 * cookies here would only widen what a same-site request could ever imply —
 * `credentials: "omit"` states that intent in the code rather than relying on
 * a default.
 */

import {
  CoreShapeError,
  isRecordObject,
  truncateForDisplay,
} from "./core-contracts";

export const CORE_PROXY_BASE = "/api/core";

/**
 * The proxy's failure codes, mapped to prose for a reader of the page. Codes
 * the client does not recognize fall back to the proxy's own bounded message.
 */
const PROXY_CODE_MESSAGES: Record<string, string> = {
  core_api_unconfigured:
    "This deployment has no core API configured, so there is nothing to read yet.",
  core_api_misconfigured:
    "The configured core API address is not usable; an operator has to fix the deployment setting.",
  invalid_path: "The page asked the proxy for a path it does not allow.",
  endpoint_not_allowed: "That endpoint is not on the proxy's read allowlist.",
  invalid_query: "The page sent a query parameter this endpoint does not accept.",
  upstream_unavailable: "The core API could not be reached.",
  upstream_timeout: "The core API did not answer within five seconds.",
  upstream_redirect:
    "The core API answered with a redirect, which the proxy never follows.",
  upstream_status: "The core API returned an error status.",
  upstream_media_type: "The core API returned something that was not JSON.",
  upstream_invalid_json: "The core API returned a body that is not valid JSON.",
  upstream_response_too_large:
    "The core API response was larger than the proxy's two-mebibyte limit.",
};

export type CoreResourceState<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "unconfigured"; message: string }
  | { state: "error"; message: string };

interface ProxyErrorBody {
  code?: string;
  message?: string;
  upstream_status?: number;
}

function readProxyError(body: unknown): ProxyErrorBody {
  if (!isRecordObject(body)) return {};
  const error = body.error;
  if (!isRecordObject(error)) return {};
  const result: ProxyErrorBody = {};
  if (typeof error.code === "string") result.code = error.code;
  if (typeof error.message === "string") result.message = error.message;
  if (typeof error.upstream_status === "number") {
    result.upstream_status = error.upstream_status;
  }
  return result;
}

export function describeProxyError(
  httpStatus: number,
  body: unknown,
): { unconfigured: boolean; message: string } {
  const error = readProxyError(body);
  const known = error.code ? PROXY_CODE_MESSAGES[error.code] : undefined;
  const base =
    known ??
    (error.message
      ? truncateForDisplay(error.message, 200)
      : `The core API request failed (HTTP ${httpStatus}).`);
  const suffix =
    error.code === "upstream_status" && typeof error.upstream_status === "number"
      ? ` Upstream status ${error.upstream_status}.`
      : "";
  return {
    unconfigured:
      error.code === "core_api_unconfigured" ||
      error.code === "core_api_misconfigured",
    message: `${base}${suffix}`,
  };
}

/**
 * Fetch one proxied endpoint and validate its shape. Never throws: every
 * outcome, including a shape mismatch, becomes a displayable state.
 */
export async function fetchCoreResource<T>(
  endpoint: string,
  parse: (value: unknown) => T,
  fetchImpl: typeof fetch = fetch,
): Promise<CoreResourceState<T>> {
  let response: Response;
  try {
    response = await fetchImpl(`${CORE_PROXY_BASE}/${endpoint}`, {
      method: "GET",
      headers: { accept: "application/json" },
      credentials: "omit",
      cache: "no-store",
    });
  } catch {
    return {
      state: "error",
      message: "The browser could not reach this site's core proxy.",
    };
  }

  let body: unknown;
  let parsedBody = true;
  try {
    body = await response.json();
  } catch {
    parsedBody = false;
  }

  if (!response.ok) {
    const described = describeProxyError(response.status, parsedBody ? body : undefined);
    return described.unconfigured
      ? { state: "unconfigured", message: described.message }
      : { state: "error", message: described.message };
  }
  if (!parsedBody) {
    return {
      state: "error",
      message: "The core proxy returned a body that is not valid JSON.",
    };
  }

  try {
    return { state: "ready", data: parse(body) };
  } catch (error) {
    const detail =
      error instanceof CoreShapeError ? ` (${truncateForDisplay(error.message, 120)})` : "";
    return {
      state: "error",
      message: `The core API returned a response this page does not recognize${detail}.`,
    };
  }
}
