import { createHash } from "node:crypto";
import {
  buildUpstreamUrl,
  CORE_API_BASE_ENV,
  coreProxyError,
  resolveUpstreamBase,
  UPSTREAM_TIMEOUT_MS,
  type CoreProxyOptions,
} from "./core-proxy";

export const MAX_ARTIFACT_BYTES = 32 * 1024 * 1024;

function artifactError(
  code: "artifact_too_large" | "artifact_integrity",
  status: number,
): Response {
  return new Response(JSON.stringify({ error: { code } }), {
    status,
    headers: {
      "content-type": "application/json",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

/** Buffer and verify before returning any bytes: a refused transfer is never a partial artifact. */
export async function handleArtifactProxyRequest(
  request: Request,
  options: CoreProxyOptions = {},
): Promise<Response> {
  const url = new URL(request.url);
  const match = /^\/api\/core\/artifacts\/([0-9a-f]{64})$/.exec(url.pathname);
  if (!match || url.search) return coreProxyError("invalid_path");
  const sha = match[1];
  const base = resolveUpstreamBase(
    (options.env ?? process.env)[CORE_API_BASE_ENV],
  );
  if (!base.ok) return coreProxyError(base.code);
  const upstream = buildUpstreamUrl(base.url, {
    ok: true,
    segments: ["artifacts", sha],
    search: "",
  });
  const controller = new AbortController();
  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(new Error("deadline"));
    }, UPSTREAM_TIMEOUT_MS);
  });
  deadline.catch(() => {});
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    const response = await Promise.race([
      (options.fetchImpl ?? fetch)(upstream, {
        method: "GET",
        credentials: "omit",
        cache: "no-store",
        redirect: "manual",
        headers: { accept: "application/octet-stream" },
        signal: controller.signal,
      }),
      deadline,
    ]);
    const discard = () => {
      void response.body?.cancel().catch(() => {});
      controller.abort();
    };
    if (
      response.type === "opaqueredirect" ||
      (response.status >= 300 && response.status < 400)
    ) {
      discard();
      return coreProxyError("upstream_redirect");
    }
    if (!response.ok) {
      discard();
      return coreProxyError("upstream_status", {
        upstreamStatus: response.status,
      });
    }
    if (Number(response.headers.get("content-length")) > MAX_ARTIFACT_BYTES) {
      discard();
      return artifactError("artifact_too_large", 413);
    }
    reader = response.body?.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    const hash = createHash("sha256");
    if (reader)
      for (;;) {
        const chunk = await Promise.race([reader.read(), deadline]);
        if (chunk.done) break;
        total += chunk.value.byteLength;
        if (total > MAX_ARTIFACT_BYTES) {
          void reader.cancel().catch(() => {});
          controller.abort();
          return artifactError("artifact_too_large", 413);
        }
        hash.update(chunk.value);
        chunks.push(chunk.value);
      }
    if (hash.digest("hex") !== sha)
      return artifactError("artifact_integrity", 409);
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return new Response(bytes, {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": `attachment; filename="${sha}"`,
        "content-length": String(total),
        etag: `"${sha}"`,
        "x-content-type-options": "nosniff",
        "cache-control": "no-store",
        "referrer-policy": "no-referrer",
      },
    });
  } catch {
    void reader?.cancel().catch(() => {});
    controller.abort();
    return coreProxyError(
      timedOut ? "upstream_timeout" : "upstream_unavailable",
    );
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
