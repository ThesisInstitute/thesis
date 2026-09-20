// Server/build-only: replay committed recorder artifacts without calling the API.
import { createHash } from "node:crypto";
import { lstatSync, readFileSync, readdirSync, realpathSync } from "node:fs";
import path from "node:path";
import { gunzipSync } from "node:zlib";
import {
  LIVE_FORECAST_SLUGS,
  type PredictionDistribution,
  type ReasoningStep,
} from "@/data/forecast-cells";
import { validateNumericCdfDistribution } from "@/data/prediction-distribution";

export interface SavedForecastRun {
  forecast: {
    pointEstimate: number;
    ciLow: number;
    ciHigh: number;
    confidence: 0.8;
    distribution?: PredictionDistribution;
    source?: string;
    model?: string;
    generatedAt: string;
    drivers: string[];
  };
  reasoning: ReasoningStep[];
  recordedAt: string;
  artifactPath: string;
}

type JsonObject = Record<string, unknown>;
const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const DIGEST_PATTERN = /^digest-[A-Za-z0-9][A-Za-z0-9._-]*\.json$/;
const MAX_FORECAST_BYTES = 4 * 1024 * 1024;

/**
 * Day indexes locate committed snapshots; they are not provenance proofs.
 * Verify both compressed and raw bytes against the snapshot commitments before
 * displaying a result. Signature/witness-chain verification remains the job of
 * the existing recorder and records CI, not a claim made by this UI loader.
 */
export function loadLatestSavedForecast(
  slug: string,
  recordsDirectory = path.join(process.cwd(), "..", "records"),
): SavedForecastRun | null {
  if (!LIVE_FORECAST_SLUGS.has(slug)) return null;
  let days: string[];
  try {
    days = readdirSync(recordsDirectory, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && DAY_PATTERN.test(entry.name))
      .map((entry) => entry.name)
      .sort()
      .reverse();
  } catch {
    return null;
  }

  for (const day of days) {
    const dayDirectory = path.join(recordsDirectory, day);
    const index = readObject(path.join(dayDirectory, "index.json"));
    if (
      index?.schemaVersion !== "thesis_record_day_index_v1" ||
      !Array.isArray(index.snapshots)
    )
      continue;

    const snapshots = index.snapshots
      .flatMap((name): JsonObject[] => {
        if (
          typeof name !== "string" ||
          !DIGEST_PATTERN.test(name) ||
          name.endsWith(".witness.json")
        )
          return [];
        const snapshot = readObject(path.join(dayDirectory, name));
        if (
          snapshot?.schemaVersion !== "thesis_record_snapshot_v2" ||
          snapshot.snapshotKind !== "recorder_run" ||
          typeof snapshot.runId !== "string" ||
          name !== `digest-${snapshot.runId}.json` ||
          !isTimestamp(snapshot.recordedAt) ||
          !snapshot.recordedAt.startsWith(`${day}T`)
        )
          return [];
        return [snapshot];
      })
      .sort(
        (a, b) =>
          Date.parse(b.recordedAt as string) -
          Date.parse(a.recordedAt as string),
      );

    for (const snapshot of snapshots) {
      const archive = isObject(snapshot.liveForecasts)
        ? snapshot.liveForecasts[slug]
        : undefined;
      if (!isObject(archive)) continue;
      const expectedPath = `records/${day}/bodies-${snapshot.runId}/live/${slug}.json.gz`;
      if (archive.archivePath !== expectedPath) continue;
      const payload = readArchive(recordsDirectory, archive);
      const run = payload && parseSavedRun(payload);
      if (run) {
        return {
          ...run,
          recordedAt: snapshot.recordedAt as string,
          artifactPath: expectedPath,
        };
      }
    }
  }
  return null;
}

function readObject(filename: string): JsonObject | null {
  try {
    if (!lstatSync(filename).isFile()) return null;
    const value: unknown = JSON.parse(readFileSync(filename, "utf8"));
    return isObject(value) ? value : null;
  } catch {
    return null;
  }
}

function readArchive(
  recordsDirectory: string,
  archive: JsonObject,
): JsonObject | null {
  try {
    if (
      archive.contentEncoding !== "gzip" ||
      !isByteCount(archive.archiveBytes) ||
      !isByteCount(archive.bytes)
    )
      return null;
    const root = realpathSync(recordsDirectory);
    const filename = path.join(
      root,
      (archive.archivePath as string).slice("records/".length),
    );
    const resolved = realpathSync(filename);
    if (
      !resolved.startsWith(`${root}${path.sep}`) ||
      resolved !== path.resolve(filename)
    )
      return null;
    const stat = lstatSync(filename);
    if (!stat.isFile() || stat.size !== archive.archiveBytes) return null;
    const compressed = readFileSync(filename);
    if (sha256(compressed) !== archive.archiveSha256) return null;
    const raw = gunzipSync(compressed, { maxOutputLength: MAX_FORECAST_BYTES });
    if (raw.length !== archive.bytes || sha256(raw) !== archive.sha256) {
      return null;
    }
    const value: unknown = JSON.parse(raw.toString("utf8"));
    return isObject(value) ? value : null;
  } catch {
    return null;
  }
}

function parseSavedRun(
  payload: JsonObject,
): Pick<SavedForecastRun, "forecast" | "reasoning"> | null {
  const { pointEstimate, ciLow, ciHigh, generatedAt } = payload;
  if (
    "error" in payload ||
    !isFiniteNumber(pointEstimate) ||
    !isFiniteNumber(ciLow) ||
    !isFiniteNumber(ciHigh) ||
    ciLow > pointEstimate ||
    pointEstimate > ciHigh ||
    payload.confidence !== 0.8 ||
    !isTimestamp(generatedAt) ||
    !isStringArray(payload.publicTrace) ||
    payload.publicTrace.length === 0 ||
    !isStringArray(payload.assumptions ?? []) ||
    !isStringArray(payload.dataCaveats ?? []) ||
    !isStringArray(payload.drivers ?? []) ||
    (payload.source !== undefined && typeof payload.source !== "string") ||
    (payload.model !== undefined && typeof payload.model !== "string")
  )
    return null;

  const distribution = payload.distribution as
    | PredictionDistribution
    | undefined;
  if (distribution !== undefined) {
    try {
      if (
        distribution.format !== "numeric_cdf_v1" ||
        distribution.pointCount !== 201 ||
        validateNumericCdfDistribution(distribution).length > 0 ||
        !isFiniteNumber(distribution.support.lower) ||
        !isFiniteNumber(distribution.support.upper) ||
        distribution.support.lower >= distribution.support.upper ||
        distribution.summary.pointEstimate !== pointEstimate ||
        distribution.summary.median !== pointEstimate ||
        distribution.summary.interval80.lower !== ciLow ||
        distribution.summary.interval80.upper !== ciHigh
      )
        return null;
    } catch {
      return null;
    }
  }

  const reasoning: ReasoningStep[] = [];
  for (const [heading, paragraphs] of [
    ["Explanation", payload.publicTrace],
    ["Assumptions", payload.assumptions ?? []],
    ["Data caveats", payload.dataCaveats ?? []],
  ] as [string, string[]][]) {
    if (paragraphs.length === 0) continue;
    reasoning.push({ kind: "heading", text: heading });
    for (const text of paragraphs) reasoning.push({ kind: "text", text });
  }
  reasoning.push({ kind: "forecast", point: pointEstimate, ciLow, ciHigh });
  return {
    forecast: {
      pointEstimate,
      ciLow,
      ciHigh,
      confidence: 0.8,
      generatedAt,
      drivers: (payload.drivers ?? []) as string[],
      ...(distribution !== undefined && { distribution }),
      ...(typeof payload.source === "string" && { source: payload.source }),
      ...(typeof payload.model === "string" && { model: payload.model }),
    },
    reasoning,
  };
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function isStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.every((item) => typeof item === "string" && item.trim().length > 0)
  );
}

function isByteCount(value: unknown): value is number {
  return (
    Number.isSafeInteger(value) &&
    (value as number) > 0 &&
    (value as number) <= MAX_FORECAST_BYTES
  );
}

function sha256(value: Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}
