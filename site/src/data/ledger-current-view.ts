import { sha256Hex } from "./canonical-json";
import type {
  ObservationRecordedLedgerEntry,
  PolicyEngineLedgerEntry,
} from "./thesis-log";

// The supersede-aware current view of the Chronicle observation ledger.
//
// This is a port of receipt 0.6.2 (receipt.append_gate):
// expected_assertion_version_id, _effective_assertion_id and
// effective_current_rows, plus the assertion-version checks of check_rows,
// with the AppendGateSpec.assertion_content_keys that PolicyEngine/chronicle
// pins in scripts/receipt_pins.py. Chronicle's append gate runs on this view,
// so it is what the ledger currently asserts: a correction row names the
// version it replaces in assertionVersion.supersedes, and the replaced row
// drops out.
//
// Every row has exactly one effective assertion id: its explicit
// assertionVersion.id, or, for a row written before assertion versioning, the
// av2 content address recomputed from its content. The recomputation must stay
// byte-identical to receipt's, so the projection below mirrors Python's
// dict.get, `or {}` and truthiness rules exactly, and serializes through
// canonical-json.ts, which receipt.canonical matches byte for byte.
// site/src/__tests__/ledger-current-view.test.ts holds the port to receipt
// itself on the fixture scripts/generate_receipt_current_view_fixture.py
// writes.
//
// The port refuses where receipt would coerce a non-string id or supersedes
// with Python's str(). check_rows refuses every such row, so none can reach a
// gated ledger.

export const CHRONICLE_ASSERTION_CONTENT_KEYS = [
  "source_record_id",
  "value",
  "observed_at",
  "period",
  "geography",
  "entity",
  "aggregation",
  "filters",
  "domain",
] as const;

export class AssertionVersionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AssertionVersionError";
  }
}

type JsonObject = Record<string, unknown>;

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// Python truthiness over parsed JSON: None, False, 0, "", [] and {} are falsy.
function isPythonTruthy(value: unknown): boolean {
  if (value === null || value === undefined || value === false) return false;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") return value.length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (isJsonObject(value)) return Object.keys(value).length > 0;
  return true;
}

// dict.get(key): the value when the key is present (null included), else None.
function pyGet(object: JsonObject, key: string): unknown {
  return Object.prototype.hasOwnProperty.call(object, key) ? object[key] : null;
}

// `row.get(name) or {}`, then `.get(...)` on the result: a falsy value reads
// as an empty mapping and a mapping reads as itself. Anything else raises
// AttributeError in receipt, so the row has no content address.
function pyMappingOrEmpty(row: JsonObject, name: string): JsonObject {
  const value = pyGet(row, name);
  if (!isPythonTruthy(value)) return {};
  if (isJsonObject(value)) return value;
  throw new AssertionVersionError(
    `${name} is ${JSON.stringify(value)}, not an object; receipt cannot ` +
      "content-address this row",
  );
}

function asRow(row: unknown): JsonObject {
  if (!isJsonObject(row)) {
    throw new AssertionVersionError("a ledger row must be a JSON object");
  }
  return row;
}

/** The av2 projection receipt hashes into a row's content address. */
export function assertionVersionProjection(row: unknown): JsonObject {
  const fact = asRow(row);
  const measure = pyMappingOrEmpty(fact, "measure");
  const source = pyMappingOrEmpty(fact, "source");
  const projection: JsonObject = {};
  for (const key of CHRONICLE_ASSERTION_CONTENT_KEYS) {
    projection[key] = pyGet(fact, key);
  }
  projection.measure = {
    concept: pyGet(measure, "concept"),
    unit: pyGet(measure, "unit"),
    source_concept: pyGet(measure, "source_concept"),
    concept_relation: pyGet(measure, "concept_relation"),
    concept_authority: pyGet(measure, "concept_authority"),
    legal_vintage: pyGet(measure, "legal_vintage"),
  };
  projection.source = {
    source_name: pyGet(source, "source_name"),
    source_table: pyGet(source, "source_table"),
    source_file: pyGet(source, "source_file"),
    url: pyGet(source, "url"),
    vintage: pyGet(source, "vintage"),
    source_sha256: pyGet(source, "source_sha256"),
  };
  projection.lineage = {
    source_row_keys: pyGet(fact, "source_row_keys"),
    source_cell_keys: pyGet(fact, "source_cell_keys"),
  };
  projection.responseArchiveSha256 = pyGet(
    pyMappingOrEmpty(fact, "responseArchive"),
    "sha256",
  );
  return projection;
}

/** receipt's expected_assertion_version_id: the row's av2 content address. */
export function expectedAssertionVersionId(row: unknown): string {
  return `av2:${sha256Hex(assertionVersionProjection(row))}`;
}

function stringOrRefuse(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new AssertionVersionError(
      `assertionVersion.${field} is ${JSON.stringify(value)}, not a string; ` +
        "receipt would coerce it with str(), which the port refuses",
    );
  }
  return value;
}

/** An assertionVersion value's explicit id, or null when it sets none. */
export function explicitAssertionId(version: unknown): string | null {
  if (!isJsonObject(version)) return null;
  const id = pyGet(version, "id");
  return isPythonTruthy(id) ? stringOrRefuse(id, "id") : null;
}

/** The version an assertionVersion value supersedes, or null for none. */
export function supersededAssertionIdOf(version: unknown): string | null {
  if (!isJsonObject(version)) return null;
  const supersedes = pyGet(version, "supersedes");
  return isPythonTruthy(supersedes)
    ? stringOrRefuse(supersedes, "supersedes")
    : null;
}

/**
 * receipt's _effective_assertion_id: the explicit assertionVersion.id when it
 * is set, else the recomputed av2 content address of a pre-versioning row.
 */
export function effectiveAssertionId(row: unknown): string {
  const fact = asRow(row);
  return (
    explicitAssertionId(pyGet(fact, "assertionVersion")) ??
    expectedAssertionVersionId(fact)
  );
}

/** The assertion version a Chronicle row supersedes, or null for none. */
export function supersededAssertionId(row: unknown): string | null {
  return supersededAssertionIdOf(pyGet(asRow(row), "assertionVersion"));
}

/**
 * receipt's effective_current_rows over any row type: every row whose
 * effective id no row supersedes, in ledger order. A row drops out when ANY
 * row names it, wherever that row sits, exactly as receipt reads it. A row
 * with no id (null) is one nothing can name, so it always stays.
 */
export function currentRows<T>(
  rows: readonly T[],
  effectiveIdOf: (row: T) => string | null,
  supersedesOf: (row: T) => string | null,
): T[] {
  const superseded = new Set<string>();
  for (const row of rows) {
    const replaced = supersedesOf(row);
    if (replaced !== null) superseded.add(replaced);
  }
  return rows.filter((row) => {
    const id = effectiveIdOf(row);
    return id === null || !superseded.has(id);
  });
}

/** effective_current_rows over parsed Chronicle rows. */
export function effectiveCurrentRows<T>(rows: readonly T[]): T[] {
  return currentRows(rows, effectiveAssertionId, supersededAssertionId);
}

/**
 * The assertion-version checks of receipt's check_rows, over parsed rows in
 * ledger order. Chronicle's gate already ran them on every pinned state; the
 * site repeats them so a drifted port fails the build instead of grading a
 * superseded row. They hold the port to receipt on live data: every explicit
 * id must equal its recomputed content address. They also make the current
 * view well-formed: effective ids are unique, and a row that repeats a
 * source_record_id must supersede that record's active version, so the view
 * holds exactly one row per record, its last. Row validity (value, date, unit)
 * is the site parser's job, and the record id must be a string, which the
 * site requires and check_rows's str() does not.
 */
export function assertAppendGateAssertionVersions(
  rows: readonly unknown[],
): void {
  const versions = new Map<string, number>();
  const activeByRecordId = new Map<string, { line: number; id: string }>();
  rows.forEach((row, index) => {
    const line = index + 1;
    const fact = asRow(row);
    const recordId = pyGet(fact, "source_record_id");
    if (typeof recordId !== "string" || recordId.length === 0) {
      throw new AssertionVersionError(
        `line ${line} lacks a string source_record_id`,
      );
    }
    // A versioned row's id must equal its content address, and a
    // pre-versioning row is addressed by it, so every row's effective id is
    // the recomputed address.
    const effectiveId = expectedAssertionVersionId(fact);
    const version = pyGet(fact, "assertionVersion");
    let supersedes: unknown = null;
    if (version !== null) {
      if (!isJsonObject(version)) {
        throw new AssertionVersionError(
          `line ${line} assertionVersion is not an object`,
        );
      }
      const versionId = pyGet(version, "id");
      if (versionId !== effectiveId) {
        throw new AssertionVersionError(
          `line ${line} (${recordId}) assertionVersion.id does not match ` +
            `its content (${JSON.stringify(versionId)} != ${effectiveId})`,
        );
      }
      supersedes = pyGet(version, "supersedes");
    }
    const restated = versions.get(effectiveId);
    if (restated !== undefined) {
      throw new AssertionVersionError(
        `line ${line} restates assertion version ${effectiveId} from line ` +
          `${restated}`,
      );
    }
    versions.set(effectiveId, line);
    const previous = activeByRecordId.get(recordId);
    if (previous) {
      if (supersedes === null) {
        throw new AssertionVersionError(
          `line ${line} duplicates ${recordId} (line ${previous.line}) ` +
            "without superseding an assertion version",
        );
      }
      if (supersedes !== previous.id) {
        throw new AssertionVersionError(
          `line ${line} supersedes ${JSON.stringify(supersedes)} but the ` +
            `active version of ${recordId} is ${previous.id}`,
        );
      }
    } else if (supersedes !== null) {
      throw new AssertionVersionError(
        `line ${line} supersedes ${JSON.stringify(supersedes)} but ` +
          `${recordId} has no earlier row`,
      );
    }
    activeByRecordId.set(recordId, { line, id: effectiveId });
  });
}

/**
 * The content address a pre-versioning row needs as an entry field: only
 * when some row in the same ledger supersedes it. A row with an explicit id
 * is addressed by that id, and a pre-versioning row nothing names cannot drop
 * out of any view of this ledger, so neither carries anything new. With no
 * corrections in a ledger, its entries are exactly what they were before the
 * current view existed.
 */
export function supersededContentAddresses(
  rows: readonly unknown[],
): (string | undefined)[] {
  const named = new Set<string>();
  for (const row of rows) {
    const replaced = supersededAssertionId(row);
    if (replaced !== null) named.add(replaced);
  }
  return rows.map((row) => {
    if (named.size === 0) return undefined;
    const fact = asRow(row);
    if (explicitAssertionId(pyGet(fact, "assertionVersion")) !== null) {
      return undefined;
    }
    const address = expectedAssertionVersionId(fact);
    return named.has(address) ? address : undefined;
  });
}

function isObservation(
  entry: PolicyEngineLedgerEntry,
): entry is ObservationRecordedLedgerEntry {
  return entry.kind === "observation_recorded";
}

/** An observation's effective assertion id, when anything could name it. */
export function observationAssertionId(
  entry: ObservationRecordedLedgerEntry,
): string | null {
  return (
    explicitAssertionId(entry.assertionVersion) ??
    entry.supersededContentAddress ??
    null
  );
}

/** The assertion version an observation supersedes, or null for none. */
export function observationSupersedes(
  entry: ObservationRecordedLedgerEntry,
): string | null {
  return supersededAssertionIdOf(entry.assertionVersion);
}

/**
 * The ledger as Chronicle currently asserts it: every registration, and every
 * observation no observation supersedes. Grading reads this view, so a
 * superseded row never grades and its correction grades in its place.
 */
export function currentLedgerView<T extends PolicyEngineLedgerEntry>(
  ledger: readonly T[],
): T[] {
  return currentRows(
    ledger,
    (entry) => (isObservation(entry) ? observationAssertionId(entry) : null),
    (entry) => (isObservation(entry) ? observationSupersedes(entry) : null),
  );
}

/**
 * The ledger's current view as of a cutoff: the observations Chronicle had
 * accepted by then, with only the supersedes accepted by then applied. A row
 * accepted later never enters, so it cannot rewrite a history, baseline or
 * normalization scale frozen at the cutoff. Acceptance is not monotone in line
 * order (rows rewritten in place carry their rewrite time), so this filters on
 * acceptedAtUtc rather than slicing a prefix. Rows with no acceptance record
 * fail closed.
 */
export function observationViewAsOf(
  ledger: readonly PolicyEngineLedgerEntry[],
  cutoffTime: number,
): ObservationRecordedLedgerEntry[] {
  return currentLedgerView(
    ledger.filter(
      (entry): entry is ObservationRecordedLedgerEntry =>
        isObservation(entry) &&
        typeof entry.acceptedAtUtc === "string" &&
        Date.parse(entry.acceptedAtUtc) <= cutoffTime,
    ),
  );
}

/**
 * An observation and every observation it replaced, directly or through
 * earlier corrections, following receipt's reading of supersedes. Under the
 * append gate this is every row of its source_record_id.
 */
export function supersedeChain(
  entry: ObservationRecordedLedgerEntry,
  ledger: readonly PolicyEngineLedgerEntry[],
): ObservationRecordedLedgerEntry[] {
  const chain = [entry];
  const seen = new Set<ObservationRecordedLedgerEntry>(chain);
  // Only a correction has predecessors; every other row is its own chain
  // without a ledger scan.
  let observations: ObservationRecordedLedgerEntry[] | null = null;
  for (let index = 0; index < chain.length; index += 1) {
    const replaced = observationSupersedes(chain[index]);
    if (replaced === null) continue;
    observations ??= ledger.filter(isObservation);
    for (const candidate of observations) {
      if (
        !seen.has(candidate) &&
        observationAssertionId(candidate) === replaced
      ) {
        seen.add(candidate);
        chain.push(candidate);
      }
    }
  }
  return chain;
}

/**
 * When the ledger first accepted this observation's print: the lowest
 * acceptedSequence in its supersede chain, or null if any row in the chain
 * lacks an acceptance record. A correction appended after a registration is
 * still the print the registration's pinned state already held, so ledger
 * membership (finding N5) is judged on the first acceptance, never the
 * correction's own.
 */
export function firstAcceptedSequence(
  entry: ObservationRecordedLedgerEntry,
  ledger: readonly PolicyEngineLedgerEntry[],
): number | null {
  let first = Number.POSITIVE_INFINITY;
  for (const row of supersedeChain(entry, ledger)) {
    if (typeof row.acceptedSequence !== "number") return null;
    first = Math.min(first, row.acceptedSequence);
  }
  return first;
}

/**
 * The earliest publisher instant in this observation's supersede chain. The
 * outcome was public from the first print, so a correction dated later cannot
 * move the ex-ante boundary a forecast run must precede; one dated earlier
 * moves it earlier. Unparseable instants never win over parseable ones.
 */
export function firstObservedAt(
  entry: ObservationRecordedLedgerEntry,
  ledger: readonly PolicyEngineLedgerEntry[],
): string {
  let first = entry.observedAt;
  let firstTime = Date.parse(first);
  for (const row of supersedeChain(entry, ledger)) {
    const time = Date.parse(row.observedAt);
    if (
      Number.isFinite(time) &&
      (!Number.isFinite(firstTime) || time < firstTime)
    ) {
      first = row.observedAt;
      firstTime = time;
    }
  }
  return first;
}
