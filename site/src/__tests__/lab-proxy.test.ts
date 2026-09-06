// @vitest-environment node
import { createHash } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveProxyTarget, handleCoreProxyRequest } from "@/lib/core-proxy";
import {
  handleArtifactProxyRequest,
  MAX_ARTIFACT_BYTES,
} from "@/lib/artifact-proxy";
import { ids } from "./lab-fixtures";

const request = (path: string) =>
  new Request(`http://localhost/api/core/${path}`);
const env = { THESIS_CORE_API_URL: "https://private.example/core" };
const digest = (bytes: Uint8Array) =>
  createHash("sha256").update(bytes).digest("hex");
afterEach(() => vi.useRealTimers());

describe("exact lab proxy routes", () => {
  it.each([
    "lab/forecasts?limit=20",
    `lab/forecasts/${ids.target}`,
    `lab/forecasts/${ids.target}/experiments?after=${ids.experiment}`,
    `lab/forecasts/${ids.target}/comparisons?experiment_id=${ids.experiment}`,
    `lab/tasks/${ids.task}/attempts`,
    `lab/experiments/${ids.experiment}/matrix?limit=20&method_limit=10&method_after=${ids.agent}`,
    `lab/experiments/${ids.experiment}/results`,
    `lab/agents/${ids.agent}/experiments`,
    "lab/operations",
  ])("allows %s", (path) =>
    expect(resolveProxyTarget(request(path).url).ok).toBe(true),
  );
  it.each([
    `lab/forecasts/${ids.target}/comparisons`,
    `lab/forecasts/${ids.target}/comparisons?experiment_id=${ids.experiment}&experiment_id=${ids.agent}`,
    `lab/experiments/${ids.experiment}/matrix?limit=21`,
    `lab/experiments/${ids.experiment}/matrix?method_limit=11`,
    "lab/operations?worker=private",
    "lab/agents?limit=1e2",
    `lab/agents/${ids.agent}/attempts`,
    `lab/forecasts/${ids.target}/unknown`,
    "lab/forecasts?as_of=2026-01-01T00:00:00Z",
    `artifacts/${ids.artifact}`,
  ])("rejects %s", (path) =>
    expect(resolveProxyTarget(request(path).url).ok).toBe(false),
  );
  it("retains no credentials and fixed upstream destination for lab JSON", async () => {
    const fetchImpl = vi.fn<typeof fetch>(
      async () =>
        new Response("{}", { headers: { "content-type": "application/json" } }),
    );
    await handleCoreProxyRequest(
      new Request("http://localhost/api/core/lab/forecasts", {
        headers: { cookie: "private", authorization: "private" },
      }),
      { env, fetchImpl },
    );
    expect(String(fetchImpl.mock.calls[0][0])).toBe(
      "https://private.example/core/lab/forecasts",
    );
    expect(fetchImpl.mock.calls[0][1]).toMatchObject({
      credentials: "omit",
      redirect: "manual",
      headers: { accept: "application/json" },
    });
  });
});

describe("atomic artifact downloads", () => {
  it("preserves exact bytes, verifies digest and forces attachment headers", async () => {
    const bytes = new TextEncoder().encode(
      "<script>never execute this archived HTML</script>\u0000",
    );
    const sha = digest(bytes);
    const fetchImpl = vi.fn<typeof fetch>(
      async () =>
        new Response(bytes, {
          headers: { "content-type": "text/html", "set-cookie": "private" },
        }),
    );
    const response = await handleArtifactProxyRequest(
      request(`artifacts/${sha}`),
      { env, fetchImpl },
    );
    expect(response.status).toBe(200);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes);
    expect(response.headers.get("content-type")).toBe(
      "application/octet-stream",
    );
    expect(response.headers.get("content-disposition")).toContain("attachment");
    expect(response.headers.get("etag")).toBe(`"${sha}"`);
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(fetchImpl.mock.calls[0][1]).toMatchObject({
      credentials: "omit",
      redirect: "manual",
    });
  });
  it("rejects a mismatched content hash", async () => {
    const response = await handleArtifactProxyRequest(
      request(`artifacts/${ids.artifact}`),
      { env, fetchImpl: async () => new Response("corrupt") },
    );
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({
      error: { code: "artifact_integrity" },
    });
  });
  it("refuses declared oversized artifacts without reading a byte", async () => {
    const cancel = vi.fn();
    const response = await handleArtifactProxyRequest(
      request(`artifacts/${ids.artifact}`),
      {
        env,
        fetchImpl: async () =>
          new Response(new ReadableStream({ cancel }), {
            headers: { "content-length": String(MAX_ARTIFACT_BYTES + 1) },
          }),
      },
    );
    expect(response.status).toBe(413);
    expect(await response.json()).toEqual({
      error: { code: "artifact_too_large" },
    });
    expect(cancel).toHaveBeenCalled();
  });
  it.each([undefined, "1"])(
    "counts actual bytes despite Content-Length %s",
    async (length) => {
      let pulls = 0;
      const cancel = vi.fn();
      const body = new ReadableStream({
        pull(controller) {
          pulls++;
          controller.enqueue(new Uint8Array(MAX_ARTIFACT_BYTES / 2 + 1));
        },
        cancel,
      });
      const response = await handleArtifactProxyRequest(
        request(`artifacts/${ids.artifact}`),
        {
          env,
          fetchImpl: async () =>
            new Response(body, {
              headers: length ? { "content-length": length } : {},
            }),
        },
      );
      expect(response.status).toBe(413);
      expect(response.headers.get("content-disposition")).toBeNull();
      expect(await response.json()).toEqual({
        error: { code: "artifact_too_large" },
      });
      expect(cancel).toHaveBeenCalled();
      expect(pulls).toBeLessThanOrEqual(3);
    },
  );
  it("accepts the exact 32 MiB boundary", async () => {
    const bytes = new Uint8Array(MAX_ARTIFACT_BYTES);
    const sha = digest(bytes);
    const response = await handleArtifactProxyRequest(
      request(`artifacts/${sha}`),
      { env, fetchImpl: async () => new Response(bytes) },
    );
    expect(response.status).toBe(200);
    expect((await response.arrayBuffer()).byteLength).toBe(MAX_ARTIFACT_BYTES);
  });
  it("never follows redirects", async () => {
    const response = await handleArtifactProxyRequest(
      request(`artifacts/${ids.artifact}`),
      {
        env,
        fetchImpl: async () =>
          new Response(null, {
            status: 302,
            headers: { location: "https://elsewhere.example" },
          }),
      },
    );
    expect(response.status).toBe(502);
    expect(await response.text()).not.toContain("elsewhere");
  });
  it("times out a stalled stream without returning a partial attachment", async () => {
    vi.useFakeTimers();
    const result = handleArtifactProxyRequest(
      request(`artifacts/${ids.artifact}`),
      {
        env,
        fetchImpl: async () =>
          new Response(
            new ReadableStream({
              start(controller) {
                controller.enqueue(new Uint8Array([1]));
              },
            }),
          ),
      },
    );
    await vi.advanceTimersByTimeAsync(5100);
    const response = await result;
    expect(response.status).toBe(504);
    expect(response.headers.get("content-disposition")).toBeNull();
  });
  it.each([
    `artifacts/${ids.artifact}?url=https://private`,
    "artifacts/UPPERCASE",
    `artifacts/${ids.artifact}/extra`,
  ])("rejects %s before network access", async (path) => {
    const fetchImpl = vi.fn();
    const response = await handleArtifactProxyRequest(request(path), {
      env,
      fetchImpl,
    });
    expect(response.status).toBe(400);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
