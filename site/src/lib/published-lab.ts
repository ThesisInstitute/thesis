/** Server-side reads of an explicitly published, hash-verified lab snapshot. */
import { createHash } from "node:crypto";
import { open } from "node:fs/promises";
import path from "node:path";
import type {
  ConditionalDetail,
  ConditionalSummary,
} from "@/data/generated/thesis-lab";
import { isUtcInstant, parseLab } from "./lab-schema";

const DIGEST = /^[0-9a-f]{64}$/;
const MAX_BLOB = 32 * 1024 * 1024;
const MAX_DETAIL = 2 * 1024 * 1024;
const MAX_DETAILS_TOTAL = 16 * 1024 * 1024;
const HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};
type BlobRef = { sha256: string; bytes: number };
type PublishedArtifact = BlobRef & { media_type: string };
export interface PublicationManifest {
  schema_version: "thesis_conditional_snapshot_v1";
  generated_at: string;
  code_revision: string;
  attempts: { id: string; detail: BlobRef }[];
  artifacts: PublishedArtifact[];
}
export interface PublicationNotice {
  generated_at: string;
  attempts: number;
}
export function snapshotEnabled(
  env?: Record<string, string | undefined>,
): boolean {
  // Keep the default access direct: Next replaces process.env.KEY at build time.
  return (
    (env ? env.THESIS_LAB_DATA_MODE : process.env.THESIS_LAB_DATA_MODE) ===
    "snapshot"
  );
}
const snapshotDirectory = () => path.join(process.cwd(), "lab-publication");
function fail(): never {
  throw new Error("Invalid lab publication");
}
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
function exact(value: Record<string, unknown>, keys: string[]): void {
  if (Object.keys(value).sort().join(",") !== keys.sort().join(",")) fail();
}
function blobRef(value: unknown, max: number): asserts value is BlobRef {
  if (
    !object(value) ||
    typeof value.sha256 !== "string" ||
    !DIGEST.test(value.sha256) ||
    !Number.isSafeInteger(value.bytes) ||
    (value.bytes as number) < 0 ||
    (value.bytes as number) > max
  )
    fail();
}
async function boundedRead(filename: string, max: number): Promise<Buffer> {
  const file = await open(filename, "r");
  try {
    const stat = await file.stat();
    if (!stat.isFile() || stat.size > max) fail();
    const buffer = Buffer.alloc(max + 1);
    let length = 0;
    while (length <= max) {
      const result = await file.read(buffer, length, max + 1 - length, null);
      if (!result.bytesRead) break;
      length += result.bytesRead;
    }
    if (length > max) fail();
    return buffer.subarray(0, length);
  } finally {
    await file.close();
  }
}
export async function readPublicationManifest(
  directory = snapshotDirectory(),
): Promise<PublicationManifest> {
  const value: unknown = JSON.parse(
    (
      await boundedRead(path.join(directory, "manifest.json"), 1024 * 1024)
    ).toString("utf8"),
  );
  if (!object(value)) fail();
  exact(value, [
    "schema_version",
    "generated_at",
    "code_revision",
    "attempts",
    "artifacts",
  ]);
  if (
    value.schema_version !== "thesis_conditional_snapshot_v1" ||
    typeof value.generated_at !== "string" ||
    !isUtcInstant(value.generated_at) ||
    typeof value.code_revision !== "string" ||
    !/^[0-9a-f]{40}$/.test(value.code_revision) ||
    !Array.isArray(value.attempts) ||
    !value.attempts.length ||
    value.attempts.length > 100 ||
    !Array.isArray(value.artifacts) ||
    value.artifacts.length > 2048
  )
    fail();
  let total = 0;
  const ids = new Set<string>();
  for (const attempt of value.attempts) {
    if (
      !object(attempt) ||
      typeof attempt.id !== "string" ||
      !DIGEST.test(attempt.id) ||
      ids.has(attempt.id)
    )
      fail();
    exact(attempt, ["id", "detail"]);
    blobRef(attempt.detail, MAX_DETAIL);
    exact(attempt.detail, ["sha256", "bytes"]);
    total += attempt.detail.bytes;
    ids.add(attempt.id);
  }
  if (total > MAX_DETAILS_TOTAL) fail();
  const hashes = new Set<string>();
  total = 0;
  for (const artifact of value.artifacts) {
    blobRef(artifact, MAX_BLOB);
    exact(artifact as unknown as Record<string, unknown>, [
      "sha256",
      "bytes",
      "media_type",
    ]);
    if (
      typeof (artifact as PublishedArtifact).media_type !== "string" ||
      hashes.has(artifact.sha256)
    )
      fail();
    hashes.add(artifact.sha256);
    total += artifact.bytes;
  }
  if (total > 64 * 1024 * 1024) fail();
  return value as unknown as PublicationManifest;
}
async function readBlob(
  directory: string,
  ref: BlobRef,
  max: number,
): Promise<Buffer> {
  const bytes = await boundedRead(
    path.join(directory, "blobs", ref.sha256),
    max,
  );
  if (
    bytes.length !== ref.bytes ||
    createHash("sha256").update(bytes).digest("hex") !== ref.sha256
  )
    fail();
  return bytes;
}
function checkArtifactReferences(
  value: unknown,
  artifacts: Map<string, PublishedArtifact>,
): void {
  if (Array.isArray(value)) {
    value.forEach((item) => checkArtifactReferences(item, artifacts));
    return;
  }
  if (!object(value)) return;
  if (
    typeof value.sha256 === "string" &&
    "bytes" in value &&
    "media_type" in value
  ) {
    const artifact = artifacts.get(value.sha256);
    if (
      !artifact ||
      artifact.bytes !== value.bytes ||
      artifact.media_type !== value.media_type
    )
      fail();
  }
  Object.values(value).forEach((item) =>
    checkArtifactReferences(item, artifacts),
  );
}
async function details(
  directory: string,
  manifest: PublicationManifest,
): Promise<ConditionalDetail[]> {
  const artifacts = new Map(manifest.artifacts.map((ref) => [ref.sha256, ref]));
  const rows: ConditionalDetail[] = [];
  for (const attempt of manifest.attempts) {
    const row = parseLab(
      "ConditionalDetail",
      JSON.parse(
        (await readBlob(directory, attempt.detail, MAX_DETAIL)).toString(
          "utf8",
        ),
      ),
    );
    if (row.id !== attempt.id || row.generated_at !== manifest.generated_at)
      fail();
    checkArtifactReferences(row, artifacts);
    rows.push(row);
  }
  const byId = new Map(rows.map((row) => [row.id, row]));
  for (const row of rows)
    for (const entry of row.revision_history) {
      const other = byId.get(entry.attempt_id);
      if (
        !other ||
        (entry.parent_attempt_id && !byId.has(entry.parent_attempt_id)) ||
        other.contract_id !== entry.contract_id ||
        other.shared_evidence_id !== entry.shared_evidence_id ||
        other.requested_model !== entry.requested_model ||
        other.started_at !== entry.started_at ||
        other.execution_state !== entry.execution_state ||
        JSON.stringify(other.arm_quantiles) !==
          JSON.stringify(entry.arm_quantiles)
      )
        fail();
      if (
        entry.triggering_review_id &&
        !byId
          .get(entry.parent_attempt_id!)
          ?.reviews.some((review) => review.id === entry.triggering_review_id)
      )
        fail();
    }
  return rows.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}
function summary(row: ConditionalDetail): ConditionalSummary {
  const {
    id,
    title,
    question,
    unit,
    measurement_period,
    status,
    scoring_status,
    trust_class,
    requested_model,
    provider_metadata,
    observed_model,
    execution_state,
    started_at,
    finished_at,
    error_code,
  } = row;
  return {
    id,
    title,
    question,
    unit,
    measurement_period,
    status,
    scoring_status,
    trust_class,
    requested_model,
    provider_metadata,
    observed_model,
    execution_state,
    started_at,
    finished_at,
    error_code,
  };
}
function error(status: number): Response {
  return new Response(
    JSON.stringify({
      error: {
        code: status === 404 ? "not_in_publication" : "publication_unavailable",
        message:
          status === 404
            ? "This record is not included in the shared snapshot."
            : "The shared snapshot could not be verified.",
      },
    }),
    { status, headers: HEADERS },
  );
}
export async function publicationNotice(): Promise<PublicationNotice | null> {
  if (!snapshotEnabled()) return null;
  try {
    const manifest = await readPublicationManifest();
    return {
      generated_at: manifest.generated_at,
      attempts: manifest.attempts.length,
    };
  } catch {
    return null;
  }
}
/** Called only after the proxy's shared route/query validator accepts the URL. */
export async function handlePublishedLabRequest(
  segments: string[],
  search: string,
  directory = snapshotDirectory(),
): Promise<Response> {
  if (
    segments[0] !== "lab" ||
    segments[1] !== "conditionals" ||
    ![2, 3].includes(segments.length)
  )
    return error(404);
  try {
    const manifest = await readPublicationManifest(directory);
    const rows = await details(directory, manifest);
    if (segments.length === 3) {
      const row = rows.find((item) => item.id === segments[2]);
      return row
        ? new Response(JSON.stringify(row), { headers: HEADERS })
        : error(404);
    }
    const params = new URLSearchParams(search);
    const model = params.get("requested_model");
    const filtered = rows.filter(
      (row) => !model || row.requested_model === model,
    );
    const after = params.get("after");
    const limit = Number(params.get("limit") ?? 20);
    const available = filtered.filter((row) => !after || row.id > after);
    const items = available.slice(0, limit).map(summary);
    const page = parseLab("ConditionalPage", {
      schema_version: "thesis_lab_v1",
      generated_at: manifest.generated_at,
      requested_models: [
        ...new Set(rows.map((row) => row.requested_model)),
      ].sort(),
      items,
      total: filtered.length,
      next_cursor: available.length > limit ? items.at(-1)!.id : null,
    });
    return new Response(JSON.stringify(page), { headers: HEADERS });
  } catch {
    return error(503);
  }
}
export async function handlePublishedArtifactRequest(
  sha256: string,
  directory = snapshotDirectory(),
): Promise<Response> {
  if (!DIGEST.test(sha256)) return error(404);
  try {
    const manifest = await readPublicationManifest(directory);
    const ref = manifest.artifacts.find((item) => item.sha256 === sha256);
    if (!ref) return error(404);
    const bytes = await readBlob(directory, ref, MAX_BLOB);
    return new Response(new Uint8Array(bytes), {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": `attachment; filename="${sha256}"`,
        "content-length": String(bytes.length),
        etag: `"${sha256}"`,
        "x-content-type-options": "nosniff",
        "cache-control": "no-store",
        "referrer-policy": "no-referrer",
      },
    });
  } catch {
    return error(503);
  }
}
