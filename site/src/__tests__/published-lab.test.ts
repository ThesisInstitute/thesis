// @vitest-environment node
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { conditional } from "./conditional-fixtures";
import type { ConditionalDetail } from "@/data/generated/thesis-lab";
import {
  handlePublishedArtifactRequest,
  handlePublishedLabRequest,
  readPublicationManifest,
  snapshotEnabled,
  type PublicationManifest,
} from "@/lib/published-lab";
import { handleCoreProxyRequest } from "@/lib/core-proxy";
import { handleArtifactProxyRequest } from "@/lib/artifact-proxy";

const directories: string[] = [];
afterEach(async () => {
  for (const dir of directories.splice(0))
    await rm(dir, { recursive: true, force: true });
  vi.unstubAllEnvs();
});
const hash = (bytes: Uint8Array | string) =>
  createHash("sha256").update(bytes).digest("hex");
type Mutable<T> = { -readonly [P in keyof T]: Mutable<T[P]> };
async function fixture(models = ["synthetic-a", "synthetic-b", "synthetic-a"]) {
  const directory = await mkdtemp(
    path.join(os.tmpdir(), "thesis-publication-"),
  );
  directories.push(directory);
  await mkdir(path.join(directory, "blobs"));
  const bytes = Buffer.from("hello source");
  const sha256 = hash(bytes);
  const oldSha = conditional.contract.sources[0].artifact.sha256;
  const rows = models.map((model, index) => {
    const row = JSON.parse(
      JSON.stringify(conditional).replaceAll(oldSha, sha256),
    ) as Mutable<ConditionalDetail>;
    row.id = String(index + 1).repeat(64);
    row.requested_model = model;
    row.revision_history[0].attempt_id = row.id;
    row.revision_history[0].requested_model = model;
    return row;
  });
  const manifest: PublicationManifest = {
    schema_version: "thesis_conditional_snapshot_v1",
    generated_at: conditional.generated_at,
    code_revision: "a".repeat(40),
    attempts: [],
    artifacts: [{ sha256, bytes: bytes.length, media_type: "text/plain" }],
  };
  await writeFile(path.join(directory, "blobs", sha256), bytes);
  const save = async () => {
    manifest.attempts = [];
    for (const row of rows) {
      const raw = JSON.stringify(row);
      const ref = { sha256: hash(raw), bytes: Buffer.byteLength(raw) };
      manifest.attempts.push({ id: row.id, detail: ref });
      await writeFile(path.join(directory, "blobs", ref.sha256), raw);
    }
    await writeFile(
      path.join(directory, "manifest.json"),
      JSON.stringify(manifest),
    );
  };
  await save();
  return { directory, rows, manifest, save, sha256, bytes };
}
describe("published lab snapshots", () => {
  it("filters before pagination and preserves global model options and frozen timestamps", async () => {
    const { directory, rows } = await fixture();
    const first = await handlePublishedLabRequest(
      ["lab", "conditionals"],
      "?requested_model=synthetic-a&limit=1",
      directory,
    );
    expect(first.status).toBe(200);
    const page = await first.json();
    expect(page).toMatchObject({
      total: 2,
      next_cursor: rows[0].id,
      generated_at: conditional.generated_at,
      requested_models: ["synthetic-a", "synthetic-b"],
    });
    expect(page.items.map((item: { id: string }) => item.id)).toEqual([
      rows[0].id,
    ]);
    const next = await (
      await handlePublishedLabRequest(
        ["lab", "conditionals"],
        `?requested_model=synthetic-a&limit=1&after=${rows[0].id}`,
        directory,
      )
    ).json();
    expect(next).toMatchObject({ total: 2, next_cursor: null });
    expect(next.items[0].id).toBe(rows[2].id);
    const detail = await handlePublishedLabRequest(
      ["lab", "conditionals", rows[0].id],
      "",
      directory,
    );
    expect(await detail.json()).toEqual(rows[0]);
  });
  it("serves original allowlisted bytes as attachments and never exposes unlisted blobs", async () => {
    const { directory, manifest, sha256, bytes } = await fixture();
    const response = await handlePublishedArtifactRequest(sha256, directory);
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe(
      "application/octet-stream",
    );
    expect(response.headers.get("content-disposition")).toContain(
      "attachment;",
    );
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(Buffer.from(await response.arrayBuffer())).toEqual(bytes);
    // The detail blob exists but is not an exported raw artifact.
    expect(
      (
        await handlePublishedArtifactRequest(
          manifest.attempts[0].detail.sha256,
          directory,
        )
      ).status,
    ).toBe(404);
    await writeFile(path.join(directory, "blobs", sha256), "different source");
    expect(
      (await handlePublishedArtifactRequest(sha256, directory)).status,
    ).toBe(503);
  });
  it("refuses corrupted detail bytes, inconsistent identities and dangling history", async () => {
    const { directory, rows, manifest, save } = await fixture();
    const filename = path.join(
      directory,
      "blobs",
      manifest.attempts[0].detail.sha256,
    );
    await writeFile(
      filename,
      (await readFile(filename, "utf8")).replace(
        "Synthetic policy",
        "Fabricated policy",
      ),
    );
    expect(
      (await handlePublishedLabRequest(["lab", "conditionals"], "", directory))
        .status,
    ).toBe(503);
    await save();
    rows[0].revision_history.push({
      ...rows[0].revision_history[0],
      attempt_id: "f".repeat(64),
    });
    await save();
    expect(
      (await handlePublishedLabRequest(["lab", "conditionals"], "", directory))
        .status,
    ).toBe(503);
  });
  it("refuses unmanifested evidence and malformed or oversized manifest claims", async () => {
    const { directory, manifest, save } = await fixture();
    manifest.artifacts = [];
    await save();
    expect(
      (await handlePublishedLabRequest(["lab", "conditionals"], "", directory))
        .status,
    ).toBe(503);
    manifest.attempts[0].detail.bytes = 3 * 1024 * 1024;
    await writeFile(
      path.join(directory, "manifest.json"),
      JSON.stringify(manifest),
    );
    await expect(readPublicationManifest(directory)).rejects.toThrow();
  });
  it("never falls back to a private live API when publication mode is selected", async () => {
    const fetchImpl = vi.fn();
    const env = {
      THESIS_LAB_DATA_MODE: "snapshot",
      THESIS_CORE_API_URL: "http://private.invalid",
    };
    expect(
      (
        await handleCoreProxyRequest(
          new Request("https://app.test/api/core/lab/forecasts"),
          { env, fetchImpl },
        )
      ).status,
    ).toBe(404);
    expect(
      (
        await handleCoreProxyRequest(
          new Request(
            "https://app.test/api/core/lab/conditionals?requested_model=bad%20model",
          ),
          { env, fetchImpl },
        )
      ).status,
    ).toBe(400);
    expect(
      (
        await handleArtifactProxyRequest(
          new Request("https://app.test/api/core/artifacts/nope"),
          { env, fetchImpl },
        )
      ).status,
    ).toBe(400);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(snapshotEnabled({ THESIS_LAB_DATA_MODE: "live" })).toBe(false);
    vi.stubEnv("THESIS_LAB_DATA_MODE", "snapshot");
    expect(snapshotEnabled()).toBe(true);
  });
});
