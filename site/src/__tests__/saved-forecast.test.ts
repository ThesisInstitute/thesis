import { createHash } from "node:crypto";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { gzipSync } from "node:zlib";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { buildNumericCdfFromInterval } from "@/data/prediction-distribution";
import { loadLatestSavedForecast } from "@/lib/saved-forecast";

const slug = "spm-child-poverty-2025";
let recordsDirectory: string;

function sha256(value: Buffer) {
  return createHash("sha256").update(value).digest("hex");
}

function forecast(pointEstimate = 13) {
  return {
    pointEstimate,
    ciLow: pointEstimate - 1,
    ciHigh: pointEstimate + 1,
    confidence: 0.8,
    distribution: buildNumericCdfFromInterval({
      pointEstimate,
      ciLow: pointEstimate - 1,
      ciHigh: pointEstimate + 1,
    }),
    generatedAt: "2026-09-19T17:31:01.420Z",
    source: "census_calibration_fallback",
    publicTrace: [
      "The saved explanation.",
      "The second paragraph.\nWith a newline.",
    ],
    assumptions: ["A saved assumption."],
    dataCaveats: ["A saved caveat.", "A second caveat."],
    drivers: ["Earnings"],
  };
}

function snapshot(
  runId: string,
  recordedAt: string,
  payload: Record<string, unknown> = forecast(),
) {
  const day = recordedAt.slice(0, 10);
  const dayDirectory = path.join(recordsDirectory, day);
  const artifactPath = `records/${day}/bodies-${runId}/live/${slug}.json.gz`;
  const archivePath = path.join(recordsDirectory, artifactPath.slice(8));
  mkdirSync(path.dirname(archivePath), { recursive: true });
  const raw = Buffer.from(JSON.stringify(payload));
  const compressed = gzipSync(raw);
  writeFileSync(archivePath, compressed);
  const archive = {
    archivePath: artifactPath,
    archiveSha256: sha256(compressed),
    archiveBytes: compressed.length,
    sha256: sha256(raw),
    bytes: raw.length,
    contentEncoding: "gzip",
  };
  const digest = {
    schemaVersion: "thesis_record_snapshot_v2",
    snapshotKind: "recorder_run",
    runId,
    recordedAt,
    liveForecasts: { [slug]: archive },
  };
  const name = `digest-${runId}.json`;
  const digestPath = path.join(dayDirectory, name);
  writeFileSync(digestPath, JSON.stringify(digest));
  const indexPath = path.join(dayDirectory, "index.json");
  let names: string[] = [];
  try {
    names = JSON.parse(readFileSync(indexPath, "utf8")).snapshots;
  } catch {}
  writeFileSync(
    indexPath,
    JSON.stringify({
      schemaVersion: "thesis_record_day_index_v1",
      snapshots: [...names, name],
    }),
  );
  return { archive, archivePath, artifactPath, digest, digestPath, indexPath };
}

describe("saved forecast loader", () => {
  beforeEach(() => {
    recordsDirectory = mkdtempSync(
      path.join(tmpdir(), "thesis-saved-forecast-"),
    );
  });
  afterEach(() => rmSync(recordsDirectory, { recursive: true, force: true }));

  it("loads the latest saved result and preserves every explanation paragraph verbatim", () => {
    snapshot("late", "2026-09-19T19:00:00Z", forecast(13));
    snapshot("early", "2026-09-19T18:00:00Z", forecast(13.1));
    snapshot("older", "2026-09-18T20:00:00Z", forecast(12.9));
    const run = loadLatestSavedForecast(slug, recordsDirectory)!;
    expect(run.forecast.pointEstimate).toBe(13);
    expect(run.forecast.distribution).toEqual(forecast().distribution);
    expect(run.recordedAt).toBe("2026-09-19T19:00:00Z");
    expect(run.artifactPath).toContain("bodies-late/live/");
    expect(
      run.reasoning
        .filter((step) => step.kind === "text")
        .map((step) => step.text),
    ).toEqual([
      ...forecast().publicTrace,
      ...forecast().assumptions,
      ...forecast().dataCaveats,
    ]);
    expect(run.reasoning.some((step) => step.kind === "tool")).toBe(false);
    expect(run.reasoning.at(-1)).toEqual({
      kind: "forecast",
      point: 13,
      ciLow: 12,
      ciHigh: 14,
    });
  });

  it.each([
    { error: "no forecast event captured" },
    { ...forecast(), publicTrace: [] },
    { ...forecast(), publicTrace: [null] },
    { ...forecast(), assumptions: "missing array" },
    { ...forecast(), dataCaveats: [42] },
    { ...forecast(), confidence: 0.9 },
    { ...forecast(), generatedAt: "invalid" },
    { ...forecast(), pointEstimate: null },
    { ...forecast(), ciLow: 14 },
    { ...forecast(), distribution: {} },
    {
      ...forecast(),
      distribution: {
        ...forecast().distribution,
        summary: {
          ...forecast().distribution.summary,
          pointEstimate: 14,
        },
      },
    },
  ])("skips incomplete or malformed results (%#)", (payload) => {
    snapshot("old", "2026-09-18T18:00:00Z");
    snapshot("bad", "2026-09-19T18:00:00Z", payload);
    expect(loadLatestSavedForecast(slug, recordsDirectory)?.recordedAt).toBe(
      "2026-09-18T18:00:00Z",
    );
  });

  it.each([
    "archiveSha256",
    "archiveBytes",
    "sha256",
    "bytes",
    "contentEncoding",
  ])("rejects a mismatched %s commitment", (field) => {
    const sample = snapshot("bad", "2026-09-19T18:00:00Z");
    Object.assign(sample.archive, {
      [field]: field.endsWith("Bytes") || field === "bytes" ? 1 : "bad",
    });
    writeFileSync(sample.digestPath, JSON.stringify(sample.digest));
    expect(loadLatestSavedForecast(slug, recordsDirectory)).toBeNull();
  });

  it("rejects corrupted gzip bytes even if the compressed commitment matches", () => {
    const sample = snapshot("bad", "2026-09-19T18:00:00Z");
    const bytes = Buffer.from("not gzip");
    writeFileSync(sample.archivePath, bytes);
    Object.assign(sample.archive, {
      archiveSha256: sha256(bytes),
      archiveBytes: bytes.length,
    });
    writeFileSync(sample.digestPath, JSON.stringify(sample.digest));
    expect(loadLatestSavedForecast(slug, recordsDirectory)).toBeNull();
  });

  it("rejects archive references that escape the run's body directory", () => {
    const sample = snapshot("bad", "2026-09-19T18:00:00Z");
    sample.archive.archivePath = "records/../outside.json.gz";
    writeFileSync(sample.digestPath, JSON.stringify(sample.digest));
    expect(loadLatestSavedForecast(slug, recordsDirectory)).toBeNull();
  });

  it("rejects symlink archives", () => {
    const sample = snapshot("bad", "2026-09-19T18:00:00Z");
    const target = path.join(recordsDirectory, "outside.json.gz");
    copyFileSync(sample.archivePath, target);
    rmSync(sample.archivePath);
    symlinkSync(target, sample.archivePath);
    expect(loadLatestSavedForecast(slug, recordsDirectory)).toBeNull();
  });

  it("uses only indexed snapshots and the four known API slugs", () => {
    const sample = snapshot("unlisted", "2026-09-19T18:00:00Z");
    writeFileSync(
      sample.indexPath,
      JSON.stringify({
        schemaVersion: "thesis_record_day_index_v1",
        snapshots: ["../../outside.json"],
      }),
    );
    expect(loadLatestSavedForecast(slug, recordsDirectory)).toBeNull();
    expect(
      loadLatestSavedForecast("../../outside", recordsDirectory),
    ).toBeNull();
    expect(loadLatestSavedForecast("unknown", recordsDirectory)).toBeNull();
  });

  it("returns null when no saved completed result is available", () => {
    expect(loadLatestSavedForecast(slug, recordsDirectory)).toBeNull();
    expect(
      loadLatestSavedForecast(slug, path.join(recordsDirectory, "missing")),
    ).toBeNull();
  });

  it("loads the committed September 19 SPM result with its own saved explanation", () => {
    const actualRecords = path.join(process.cwd(), "..", "records");
    const day = "2026-09-19";
    const name = "digest-35457525637-1.json";
    const digest = JSON.parse(
      readFileSync(path.join(actualRecords, day, name), "utf8"),
    );
    const artifactPath = digest.liveForecasts[slug].archivePath.slice(8);
    mkdirSync(path.dirname(path.join(recordsDirectory, artifactPath)), {
      recursive: true,
    });
    copyFileSync(
      path.join(actualRecords, artifactPath),
      path.join(recordsDirectory, artifactPath),
    );
    writeFileSync(
      path.join(recordsDirectory, day, name),
      JSON.stringify(digest),
    );
    writeFileSync(
      path.join(recordsDirectory, day, "index.json"),
      JSON.stringify({
        schemaVersion: "thesis_record_day_index_v1",
        snapshots: [name],
      }),
    );

    const run = loadLatestSavedForecast(slug, recordsDirectory)!;
    expect(run.forecast).toMatchObject({
      pointEstimate: 13,
      ciLow: 11.9,
      ciHigh: 14.3,
      generatedAt: "2026-09-19T17:31:01.420Z",
      source: "census_calibration_fallback",
    });
    expect(run.reasoning.filter((step) => step.kind === "text")).toHaveLength(
      10,
    );
    expect(run.reasoning.at(-1)).toEqual({
      kind: "forecast",
      point: 13,
      ciLow: 11.9,
      ciHigh: 14.3,
    });
  });
});
