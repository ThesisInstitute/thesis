import { createHash } from "node:crypto";
import {
  effectiveAssertionId,
  expectedAssertionVersionId,
} from "@/data/ledger-current-view";
import { UNIT_RESTATEMENT } from "@/data/ledger-restatements";
import {
  isScaledUnit,
  LEDGER_UNIT_SCALES,
  toBase,
  type ScaledUnit,
} from "@/data/ledger-units";

export type Json = Record<string, unknown>;

export function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

/** A row's id set from its content, last, as the resolver writes it. */
export function withVersion(
  row: Json,
  supersedes: string | null,
  extra: Json = {},
): Json {
  const copy: Json = { ...row };
  delete copy.assertionVersion;
  return {
    ...copy,
    assertionVersion: {
      id: expectedAssertionVersionId(copy),
      supersedes,
      ...extra,
    },
  };
}

/** The row the resolver's restatement mode appends for a scaled row's line. */
export function restatementOf(priorLine: string): Json {
  const prior = JSON.parse(priorLine) as Json;
  const unit = (prior.measure as Json).unit;
  if (!isScaledUnit(unit)) throw new Error(`${String(unit)} holds no scale`);
  const base = LEDGER_UNIT_SCALES[unit].base;
  const digest = sha256(priorLine);
  const row: Json = {
    ...structuredClone(prior),
    value: toBase(prior.value as number, unit),
    measure: { ...(prior.measure as Json), unit: base },
    source: {
      ...(prior.source as Json),
      recorded_value: prior.value,
      recorded_unit: unit,
      method_notes: "Restated in base units; the quantity is unchanged.",
    },
    responseArchive: {
      path: `records/resolutions/test/responses/${digest.slice(0, 16)}.json.gz`,
      sha256: digest,
      bytes: Buffer.byteLength(priorLine),
      gzipSha256: "e".repeat(64),
      gzipBytes: 1,
      contentEncoding: "gzip",
    },
    retrievedAt: "2026-11-03T00:00:00Z",
    ledgerRepoSha: "d".repeat(40),
    sourceVintage: prior.sourceVintage ?? prior.observed_at,
  };
  if (prior.sourceBindingProjection) {
    row.sourceBindingProjection = {
      ...(prior.sourceBindingProjection as Json),
      unit: base,
      responseSha256: digest,
    };
  }
  return withVersion(row, effectiveAssertionId(prior), {
    relation: UNIT_RESTATEMENT,
  });
}

/** What the resolver writes in base units for a print in a scaled unit. */
export function baseRowOf(row: Json, unit: ScaledUnit): Json {
  const base = LEDGER_UNIT_SCALES[unit].base;
  const converted: Json = {
    ...structuredClone(row),
    value: toBase(row.value as number, unit),
    measure: { ...(row.measure as Json), unit: base },
    source: {
      ...(row.source as Json),
      recorded_value: row.value,
      recorded_unit: unit,
    },
  };
  if (row.sourceBindingProjection) {
    converted.sourceBindingProjection = {
      ...(row.sourceBindingProjection as Json),
      unit: base,
    };
  }
  return converted;
}

/** The current rows of a line-ordered ledger that still hold a scale word. */
export function currentScaledLines(lines: readonly string[]): string[] {
  const named = new Set<string>();
  const rows = lines.map((line) => JSON.parse(line) as Json);
  for (const row of rows) {
    const replaced = (row.assertionVersion as Json | undefined)?.supersedes;
    if (typeof replaced === "string") named.add(replaced);
  }
  return lines.filter(
    (_, index) =>
      !named.has(effectiveAssertionId(rows[index])) &&
      isScaledUnit((rows[index].measure as Json).unit),
  );
}
