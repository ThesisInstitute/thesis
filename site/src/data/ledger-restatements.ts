import { createHash } from "node:crypto";
import { canonicalStringify } from "./canonical-json";
import {
  effectiveAssertionId,
  explicitAssertionId,
  supersededAssertionId,
} from "./ledger-current-view";
import {
  isScaledUnit,
  LEDGER_UNIT_SCALES,
  LedgerUnitError,
  toBase,
  type ScaledUnit,
} from "./ledger-units";
import type { Unit } from "./units";
import type { ObservationRecordedLedgerEntry } from "./thesis-log";

// How the site reads a Chronicle ledger that stores plain numbers.
//
// A registered contract keeps the unit it registered, so the site grades in
// that unit. Two row shapes carry a scaled value alongside the base one:
//
// A restatement says a scaled row in base units, and nothing else. It never
// touches an entry: the site verifies it against the row it restates and keeps
// grading that row, so the entries stay byte-identical and no score, baseline,
// event id or payload hash can move. Grading a row Chronicle's current view has
// superseded stays safe only because the two state one quantity, which
// assertRestates proves or fails the build. The export lists restatements apart
// from the entries.
//
// A base row is a new print the resolver wrote in base units, with the pair it
// recorded in source.recorded_value and source.recorded_unit. Its entry reads
// the recorded pair, as if the resolver had written the scaled row, so the
// contract gate, histories and projection checks see what they always saw.

type JsonObject = Record<string, unknown>;

function objectOf(value: unknown): JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

export const UNIT_RESTATEMENT = "unit_restatement";

/** Whether a Chronicle row restates the row it supersedes in base units. */
export function isUnitRestatement(row: unknown): boolean {
  const relation = objectOf(objectOf(row).assertionVersion).relation;
  if (relation === undefined) return false;
  if (relation !== UNIT_RESTATEMENT) {
    throw new LedgerUnitError(
      `assertionVersion.relation ${JSON.stringify(relation)} is not one the ` +
        "site reads",
    );
  }
  return true;
}

/**
 * The pair a base row recorded in its registered unit, or null for a row with
 * no pair. A restatement's pair names the row it restates, and assertRestates
 * checks it there. The site refuses a pair that does not state the row's value.
 */
export function recordedPair(
  row: unknown,
): { value: number; unit: ScaledUnit } | null {
  if (isUnitRestatement(row)) return null;
  const fact = objectOf(row);
  const source = objectOf(fact.source);
  const value = source.recorded_value;
  const unit = source.recorded_unit;
  if (value === undefined && unit === undefined) return null;
  const name = String(fact.source_record_id);
  if (typeof value !== "number" || !isScaledUnit(unit)) {
    throw new LedgerUnitError(
      `${name} records ${JSON.stringify(value)} ${JSON.stringify(unit)}, ` +
        "which is not a number in a scaled unit",
    );
  }
  const stored = objectOf(fact.measure).unit;
  if (stored !== LEDGER_UNIT_SCALES[unit].base) {
    throw new LedgerUnitError(
      `${name} records ${unit} but stores ${JSON.stringify(stored)}`,
    );
  }
  if (toBase(value, unit) !== fact.value) {
    throw new LedgerUnitError(
      `${name} records ${value} ${unit} but stores ${String(fact.value)}`,
    );
  }
  return { value, unit };
}

function without(value: unknown, keys: readonly string[]): JsonObject {
  return Object.fromEntries(
    Object.entries(objectOf(value)).filter(([key]) => !keys.includes(key)),
  );
}

// A row with every field a restatement may change taken out: the stated value
// and unit, its own provenance, and text that names the old scale.
function restatedContent(row: JsonObject): JsonObject {
  const content = without(row, [
    "value",
    "assertionVersion",
    "retrievedAt",
    "ledgerRepoSha",
    "sourceVintage",
    "responseArchive",
  ]);
  content.measure = without(row.measure, ["unit"]);
  content.source = without(row.source, [
    "recorded_value",
    "recorded_unit",
    "method_notes",
  ]);
  if ("sourceBindingProjection" in row) {
    content.sourceBindingProjection = without(row.sourceBindingProjection, [
      "unit",
      "responseSha256",
    ]);
  }
  return content;
}

function assertRestates(
  prior: unknown,
  priorLine: string,
  restatement: unknown,
): void {
  const before = objectOf(prior);
  const after = objectOf(restatement);
  const name = String(after.source_record_id);
  const refuse = (why: string) =>
    new LedgerUnitError(`restatement of ${name} ${why}`);

  const unit = objectOf(before.measure).unit;
  if (!isScaledUnit(unit)) {
    throw refuse(
      `names a row in ${JSON.stringify(unit)}, which holds no scale`,
    );
  }
  if (objectOf(after.measure).unit !== LEDGER_UNIT_SCALES[unit].base) {
    throw refuse(
      `stores ${JSON.stringify(objectOf(after.measure).unit)}, not the base ` +
        `unit of ${unit}`,
    );
  }
  const source = objectOf(after.source);
  if (source.recorded_value !== before.value || source.recorded_unit !== unit) {
    throw refuse(
      `records ${JSON.stringify(source.recorded_value)} ` +
        `${JSON.stringify(source.recorded_unit)} but the row says ` +
        `${JSON.stringify(before.value)} ${unit}`,
    );
  }
  const expected = toBase(before.value as number, unit);
  if (after.value !== expected) {
    throw refuse(`stores ${String(after.value)}, not ${expected}`);
  }
  const lineSha256 = createHash("sha256")
    .update(priorLine, "utf8")
    .digest("hex");
  if (objectOf(after.responseArchive).sha256 !== lineSha256) {
    throw refuse("does not archive the exact line it restates");
  }
  if (
    canonicalStringify(restatedContent(after)) !==
    canonicalStringify(restatedContent(before))
  ) {
    throw refuse("changes more than the value and unit");
  }
}

export interface LedgerRestatement {
  dataPointId: string;
  assertionId: string;
  supersedes: string;
  value: number;
  unit: Unit;
  acceptedSequence?: number;
  acceptedAtUtc?: string;
}

/**
 * Takes entries mapped one per ledger line, with their rows and raw lines, and
 * sets each verified restatement apart from the entries. A correction that names
 * a restatement gets that row's id as gradedSupersedes, so it corrects the row
 * the site grades, and that row gets the content address the correction now
 * reaches it by. Callers run the append gate's assertion-version checks first,
 * which prove a restatement names its record's active version.
 */
export function foldLedgerRestatements(
  entries: readonly ObservationRecordedLedgerEntry[],
  rows: readonly unknown[],
  lines: readonly string[],
): {
  entries: ObservationRecordedLedgerEntry[];
  restatements: LedgerRestatement[];
} {
  const lineOfId = new Map<string, number>();
  const restatementLines = new Set<number>();
  const restatedIdOf = new Map<string, string>();
  const restatements: LedgerRestatement[] = [];
  rows.forEach((row, line) => {
    const id = effectiveAssertionId(row);
    if (isUnitRestatement(row)) {
      const replaced = supersededAssertionId(row);
      const prior = replaced === null ? undefined : lineOfId.get(replaced);
      if (replaced === null || prior === undefined) {
        throw new LedgerUnitError(
          `line ${line + 1} restates ${JSON.stringify(replaced)}, which no ` +
            "earlier row holds",
        );
      }
      assertRestates(rows[prior], lines[prior], row);
      restatementLines.add(line);
      restatedIdOf.set(id, replaced);
      const entry = entries[line];
      restatements.push({
        dataPointId: entry.dataPointId,
        assertionId: id,
        supersedes: replaced,
        value: entry.value,
        unit: entry.unit,
        acceptedSequence: entry.acceptedSequence,
        acceptedAtUtc: entry.acceptedAtUtc,
      });
    }
    lineOfId.set(id, line);
  });
  if (restatementLines.size === 0) {
    return { entries: [...entries], restatements };
  }

  const gradedSupersedes = rows.map((row) => {
    const replaced = supersededAssertionId(row);
    return replaced === null ? undefined : restatedIdOf.get(replaced);
  });
  const reached = new Set(gradedSupersedes);
  return {
    entries: entries.flatMap((entry, line) => {
      if (restatementLines.has(line)) return [];
      const id = effectiveAssertionId(rows[line]);
      const version = objectOf(rows[line]).assertionVersion;
      const graded = gradedSupersedes[line];
      return [
        {
          ...entry,
          ...(explicitAssertionId(version) === null && reached.has(id)
            ? { supersededContentAddress: id }
            : {}),
          ...(graded ? { gradedSupersedes: graded } : {}),
        },
      ];
    }),
    restatements,
  };
}
