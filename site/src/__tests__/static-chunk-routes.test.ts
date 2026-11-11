import { describe, expect, it } from "vitest";
import {
  GET as getLogChunk,
  generateStaticParams as logParams,
  dynamicParams as logDynamicParams,
} from "@/app/log/[collection]/[chunk]/route";
import {
  GET as getTargetChunk,
  generateStaticParams as targetParams,
  dynamicParams as targetDynamicParams,
} from "@/app/forecasts/targets/[table]/[chunk]/route";
import { loadThesisLogData } from "@/data/thesis-log-runtime";
import {
  buildThesisLogManifest,
  THESIS_LOG_CHUNK_COLLECTIONS,
} from "@/data/thesis-log";
import { loadTargetArchitectureManifest } from "@/data/thesis-target-architecture-runtime";
import { buildTargetArchitectureChunkHashPayload } from "@/data/thesis-target-architecture-export";
import { sha256Hex } from "@/data/canonical-json";

// These routes must be complete at build time: production does not include the
// source execution archives needed to reconstruct publication eligibility.
describe("static projection chunks", () => {
  it("prerenders every advertised log chunk and disables runtime fallback", async () => {
    const manifest = buildThesisLogManifest(await loadThesisLogData());
    const advertised = THESIS_LOG_CHUNK_COLLECTIONS.flatMap((collection) =>
      manifest.collections[collection].chunks.map((chunk) => chunk.url),
    );
    const generated = (await logParams()).map(
      ({ collection, chunk }) => `/log/${collection}/${chunk}`,
    );
    expect(generated.sort()).toEqual(advertised.sort());
    expect(generated.length).toBeGreaterThan(0);
    expect(logDynamicParams).toBe(false);

    for (const collection of THESIS_LOG_CHUNK_COLLECTIONS) {
      const reference = manifest.collections[collection].chunks[0];
      if (!reference) continue;
      const response = await getLogChunk(
        new Request(`http://localhost${reference.url}`),
        {
          params: Promise.resolve({
            collection,
            chunk: `${reference.index}.json`,
          }),
        },
      );
      expect(response.status).toBe(200);
      expect(sha256Hex(await response.json())).toBe(reference.sha256);
    }
  });

  it("prerenders all table manifests and row chunks with matching commitments", async () => {
    const manifest = await loadTargetArchitectureManifest();
    const advertised = manifest.tables.flatMap((table) => [
      table.url,
      ...table.chunks.map((chunk) => chunk.url),
    ]);
    const generated = (await targetParams()).map(
      ({ table, chunk }) => `/forecasts/targets/${table}/${chunk}`,
    );
    expect(generated.sort()).toEqual(advertised.sort());
    expect(targetDynamicParams).toBe(false);

    const table = manifest.tables.find((entry) => entry.chunkCount > 1)!;
    expect(table).toBeDefined();
    const tableResponse = await getTargetChunk(
      new Request(`http://localhost${table.url}`),
      {
        params: Promise.resolve({ table: table.table, chunk: "manifest.json" }),
      },
    );
    expect((await tableResponse.json()).projectionRootSha256).toBe(
      manifest.projectionRootSha256,
    );
    for (const reference of [table.chunks[0], table.chunks.at(-1)!]) {
      const response = await getTargetChunk(
        new Request(`http://localhost${reference.url}`),
        {
          params: Promise.resolve({
            table: table.table,
            chunk: `${reference.index}.json`,
          }),
        },
      );
      expect(response.status).toBe(200);
      const body = await response.json();
      expect(body.projectionRootSha256).toBe(manifest.projectionRootSha256);
      expect(sha256Hex(buildTargetArchitectureChunkHashPayload(body))).toBe(
        reference.sha256,
      );
    }
  });

  it("uses explicit route params under the app-host rewrite", async () => {
    const manifest = await loadTargetArchitectureManifest();
    const table = manifest.tables.find((entry) => entry.chunkCount > 0)!;
    // A rewritten request URL does not change the canonical route params.
    const response = await getTargetChunk(
      new Request(
        `https://app.thesisinstitute.org/targets/${table.table}/0.json.json`,
      ),
      {
        params: Promise.resolve({ table: table.table, chunk: "0.json" }),
      },
    );
    expect(response.status).toBe(200);
    expect((await response.json()).table).toBe(table.table);
  });

  it("rejects malformed or out-of-range chunk params", async () => {
    for (const chunk of [
      "0",
      "00.json",
      "0.json.json",
      "-1.json",
      "999999.json",
    ]) {
      const response = await getLogChunk(
        new Request("http://localhost/unused"),
        {
          params: Promise.resolve({ collection: "runs", chunk }),
        },
      );
      expect(response.status).toBe(404);
      const targetResponse = await getTargetChunk(
        new Request("http://localhost/unused"),
        {
          params: Promise.resolve({ table: "targets", chunk }),
        },
      );
      expect(targetResponse.status).toBe(404);
    }
  });
});
