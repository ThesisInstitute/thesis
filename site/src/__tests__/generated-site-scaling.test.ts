import { describe, expect, it } from "vitest";
import { sha256Hex } from "@/data/canonical-json";
import { FORECAST_CELLS } from "@/data/forecast-cells";
import { buildForecastListing } from "@/data/forecast-listing";
import { THESIS_TARGET_LEDGER } from "@/data/ledger-targets";
import {
  buildThesisLogChunk,
  buildThesisLogData,
  buildThesisLogManifest,
  THESIS_LOG_CHUNK_COLLECTIONS,
} from "@/data/thesis-log";

describe("generated-site scaling surfaces", () => {
  it("projects the forecast catalog to compact listing-only fields", () => {
    const listing = buildForecastListing(FORECAST_CELLS);

    expect(listing).toHaveLength(FORECAST_CELLS.length);
    expect(Object.keys(listing[0]).sort()).toEqual(
      [
        "country",
        "interval",
        "overdue",
        "point",
        "publisher",
        "resolutionDate",
        "slug",
        "status",
        "title",
        "type",
      ].sort(),
    );
    expect(JSON.stringify(listing)).not.toMatch(
      /activityLog|reasoning|historicalContext|predictionDistribution/,
    );
    expect(Buffer.byteLength(JSON.stringify(listing))).toBeLessThan(
      1024 * 1024,
    );
    // The overdue notice is one sentence, never the resolver's full report.
    for (const item of listing) {
      if (!item.overdue) continue;
      expect(Object.keys(item.overdue).sort()).toEqual(["reason", "since"]);
      expect(item.overdue.reason.length).toBeLessThan(200);
      expect(item.status).toBe("pending");
    }
  });

  it("makes every v2 heavy row reachable through verified v3 chunks", () => {
    const data = buildThesisLogData(FORECAST_CELLS, THESIS_TARGET_LEDGER);
    const manifest = buildThesisLogManifest(data);

    expect(manifest.schemaVersion).toBe("thesis_log_v3");
    expect("entries" in manifest).toBe(false);
    expect("specs" in manifest).toBe(false);
    expect("runs" in manifest).toBe(false);
    expect("scores" in manifest).toBe(false);
    expect(Buffer.byteLength(JSON.stringify(manifest))).toBeLessThan(
      4 * 1024 * 1024,
    );

    for (const collection of THESIS_LOG_CHUNK_COLLECTIONS) {
      const rows: unknown[] = [];
      for (const reference of manifest.collections[collection].chunks) {
        const chunk = buildThesisLogChunk(data, collection, reference.index);
        expect(reference.sha256).toBe(sha256Hex(chunk));
        expect(reference.count).toBe(chunk.count);
        rows.push(...chunk.rows);
      }
      expect(rows).toEqual(data[collection]);
      expect(rows).toHaveLength(manifest.collections[collection].count);
    }
  });
});
