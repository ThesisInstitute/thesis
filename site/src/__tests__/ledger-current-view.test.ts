import { readFileSync } from "node:fs";
import { join } from "node:path";
import fc from "fast-check";
import { describe, expect, it, vi } from "vitest";
import {
  getForecastRunEntries,
  type ForecastCell,
} from "@/data/forecast-cells";
import type { TargetRegisteredLedgerEntry } from "@/data/ledger-targets";
import {
  AssertionVersionError,
  assertAppendGateAssertionVersions,
  CHRONICLE_ASSERTION_CONTENT_KEYS,
  currentLedgerView,
  effectiveAssertionId,
  effectiveCurrentRows,
  expectedAssertionVersionId,
  firstAcceptedSequence,
  firstObservedAt,
  observationViewAsOf,
  supersededAssertionId,
} from "@/data/ledger-current-view";
import {
  buildObservationResolutionEventId,
  evaluateResolvedForecastRun,
  getObservationForId,
  getResolutionForForecast,
  getResolvedObservationForForecast,
  getResolvedOutcomeForForecast,
  mapPolicyEngineLedgerRows,
  parsePolicyEngineLedgerFacts,
  type ObservationRecordedLedgerEntry,
  type PolicyEngineLedgerEntry,
} from "@/data/thesis-log";
import { ledgerHistoryAtCutoff } from "@/data/time-series-priors";

// Scoring fixtures below test the ledger view, not execution verification,
// which published-scoring-gate.test.ts exercises without mocks.
vi.mock("@/lib/forecast-publication", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/forecast-publication")>();
  return {
    ...actual,
    verifyForecastRun: () => ({
      eligible: true,
      reason: "Downstream scoring fixture",
    }),
  };
});

type Json = Record<string, unknown>;

// ---------------------------------------------------------------------------
// Differential test against receipt 0.6.2 itself.
// scripts/generate_receipt_current_view_fixture.py ran receipt over these rows
// and ledgers; tests/test_receipt_current_view_fixture.py keeps the file in
// step with the installed receipt.
// ---------------------------------------------------------------------------

interface FixtureLine {
  line: string;
  origin: string;
  isObject: boolean;
  contentAddress: string | null;
  effectiveId: string | null;
  supersedes: string | null;
  portRefuses: boolean;
  baseValid: boolean;
  siteParseable: boolean;
}

interface FixtureLedger {
  kind: "chronicle" | "gated" | "arbitrary";
  lines: number[];
  current: number[] | null;
  checkRows: "accept" | "refuse" | null;
  siteParseable: boolean;
}

interface ReceiptFixture {
  schemaVersion: string;
  receiptVersion: string;
  assertionContentKeys: string[];
  lines: FixtureLine[];
  ledgers: FixtureLedger[];
}

const FIXTURE = JSON.parse(
  readFileSync(
    join(process.cwd(), "src/__tests__/fixtures/receipt-current-view.json"),
    "utf8",
  ),
) as ReceiptFixture;

function rowsOf(ledger: FixtureLedger): unknown[] {
  // One distinct object per position, as receipt reads them.
  return ledger.lines.map((index) => JSON.parse(FIXTURE.lines[index].line));
}

function positions<T>(all: readonly T[], kept: readonly T[]): number[] {
  return kept.map((row) => all.indexOf(row));
}

describe("receipt parity: the port against receipt 0.6.2", () => {
  it("reads the fixture receipt wrote with Chronicle's content keys", () => {
    expect(FIXTURE.schemaVersion).toBe(
      "thesis_receipt_current_view_fixture_v1",
    );
    expect(FIXTURE.receiptVersion).toBe("0.6.2");
    expect(FIXTURE.assertionContentKeys).toEqual([
      ...CHRONICLE_ASSERTION_CONTENT_KEYS,
    ]);
  });

  it("covers the cases the port exists for", () => {
    // A regenerated fixture must not quietly stop exercising the port.
    const { lines, ledgers } = FIXTURE;
    const dropping = ledgers.filter(
      (ledger) =>
        ledger.current !== null && ledger.current.length < ledger.lines.length,
    );
    const realRecordIds = new Set(
      lines
        .filter((line) => line.origin.startsWith("chronicle@"))
        .map((line) => (JSON.parse(line.line) as Json).source_record_id),
    );
    // Pre-versioning rows a gated correction supersedes by content address.
    const supersededPreVersioning = ledgers
      .filter((ledger) => ledger.kind === "gated" && ledger.current !== null)
      .flatMap((ledger) =>
        ledger.lines
          .filter((index, position) => {
            const row = JSON.parse(lines[index].line) as Json;
            return !row.assertionVersion && !ledger.current!.includes(position);
          })
          .map((index) => JSON.parse(lines[index].line) as Json),
      );
    expect(realRecordIds.size).toBe(15);
    expect(
      dropping.filter((ledger) => ledger.kind === "gated").length,
    ).toBeGreaterThanOrEqual(30);
    expect(
      dropping.filter((ledger) => ledger.kind === "arbitrary").length,
    ).toBeGreaterThanOrEqual(30);
    expect(supersededPreVersioning.length).toBeGreaterThanOrEqual(10);
    expect(
      supersededPreVersioning.filter((row) =>
        realRecordIds.has(row.source_record_id),
      ).length,
    ).toBeGreaterThanOrEqual(3);
    expect(
      ledgers.filter((ledger) => ledger.current === null).length,
    ).toBeGreaterThanOrEqual(10);
    expect(
      ledgers.filter((ledger) => ledger.checkRows === "refuse").length,
    ).toBeGreaterThanOrEqual(30);
    expect(
      lines.filter((line) => line.portRefuses).length,
    ).toBeGreaterThanOrEqual(5);
  });

  it("recomputes every row's content address and effective id", () => {
    for (const [index, fixtureLine] of FIXTURE.lines.entries()) {
      const row = JSON.parse(fixtureLine.line);
      const where = `line ${index} (${fixtureLine.origin})`;
      if (fixtureLine.contentAddress === null) {
        expect(() => expectedAssertionVersionId(row), where).toThrow(
          AssertionVersionError,
        );
      } else {
        expect(expectedAssertionVersionId(row), where).toBe(
          fixtureLine.contentAddress,
        );
      }
      if (!fixtureLine.isObject || fixtureLine.portRefuses) {
        expect(() => {
          effectiveAssertionId(row);
          supersededAssertionId(row);
        }, where).toThrow(AssertionVersionError);
        continue;
      }
      if (fixtureLine.effectiveId === null) {
        expect(() => effectiveAssertionId(row), where).toThrow(
          AssertionVersionError,
        );
      } else {
        expect(effectiveAssertionId(row), where).toBe(fixtureLine.effectiveId);
      }
      expect(supersededAssertionId(row), where).toBe(fixtureLine.supersedes);
    }
  });

  it("returns receipt's effective_current_rows on every ledger", () => {
    for (const [index, ledger] of FIXTURE.ledgers.entries()) {
      const rows = rowsOf(ledger);
      const where = `${ledger.kind} ledger ${index}`;
      const refused = ledger.lines.some(
        (line) => FIXTURE.lines[line].portRefuses,
      );
      if (ledger.current === null || refused) {
        expect(() => effectiveCurrentRows(rows), where).toThrow(
          AssertionVersionError,
        );
      } else {
        expect(positions(rows, effectiveCurrentRows(rows)), where).toEqual(
          ledger.current,
        );
      }
    }
  });

  it("agrees with check_rows's assertion-version verdict", () => {
    const judged = FIXTURE.ledgers.filter((ledger) => ledger.checkRows);
    expect(judged.length).toBeGreaterThan(100);
    for (const [index, ledger] of judged.entries()) {
      const run = () => assertAppendGateAssertionVersions(rowsOf(ledger));
      const where = `${ledger.kind} ledger ${index}`;
      if (ledger.checkRows === "accept") {
        expect(run, where).not.toThrow();
      } else {
        expect(run, where).toThrow(AssertionVersionError);
      }
    }
  });

  it("keeps receipt's current view through the site's ledger entries", () => {
    let compared = 0;
    for (const [index, ledger] of FIXTURE.ledgers.entries()) {
      const refused = ledger.lines.some(
        (line) => FIXTURE.lines[line].portRefuses,
      );
      if (!ledger.siteParseable || ledger.current === null || refused) {
        continue;
      }
      const entries = mapPolicyEngineLedgerRows(rowsOf(ledger));
      expect(
        positions(entries, currentLedgerView(entries)),
        `${ledger.kind} ledger ${index}`,
      ).toEqual(ledger.current);
      compared += 1;
    }
    expect(compared).toBeGreaterThan(100);
  });

  it("parses every gated ledger through the append-gate checks", () => {
    for (const ledger of FIXTURE.ledgers) {
      if (ledger.kind === "arbitrary") continue;
      const jsonl = ledger.lines
        .map((index) => FIXTURE.lines[index].line)
        .join("\n");
      const entries = parsePolicyEngineLedgerFacts(jsonl);
      expect(positions(entries, currentLedgerView(entries))).toEqual(
        ledger.current,
      );
    }
  });
});

// ---------------------------------------------------------------------------
// Properties of the view itself, on arbitrary rows (not only gated ones).
// ---------------------------------------------------------------------------

const ID_POOL = ["av2:alpha", "av2:beta", "custom", "0", "self"];

const rawRow = fc.record(
  {
    source_record_id: fc.constantFrom("rid.a", "rid.b", "rid.c"),
    value: fc.oneof(
      fc.integer({ min: -3, max: 3 }),
      fc.double({ noNaN: true, noDefaultInfinity: true }),
    ),
    observed_at: fc.constantFrom("2026-06-01", "2026-07-01"),
    period: fc.constant({ type: "month", value: "2026-06" }),
    measure: fc.constantFrom({ unit: "percent" }, { unit: "thousands" }),
    source: fc.constant({ source_name: "test", url: "https://example.gov/x" }),
    assertionVersion: fc.option(
      fc.record({
        id: fc.option(fc.constantFrom(...ID_POOL), { nil: null }),
        supersedes: fc.option(fc.constantFrom(...ID_POOL), { nil: null }),
      }),
      { nil: undefined },
    ),
  },
  {
    requiredKeys: [
      "source_record_id",
      "value",
      "observed_at",
      "period",
      "measure",
      "source",
    ],
  },
);

// Rows as JSON.parse returns them, with extra supersedes links that name
// other rows' effective ids (content addresses included) so most ledgers drop
// something.
const rawLedger = fc
  .tuple(
    fc.array(rawRow, { maxLength: 8 }),
    fc.array(fc.tuple(fc.nat(), fc.nat()), { maxLength: 4 }),
  )
  .map(([rows, links]) => {
    const parsed = JSON.parse(JSON.stringify(rows)) as Json[];
    for (const [from, to] of links) {
      if (parsed.length === 0) break;
      const named = parsed[from % parsed.length];
      const naming = parsed[to % parsed.length];
      const version =
        typeof naming.assertionVersion === "object" &&
        naming.assertionVersion !== null
          ? (naming.assertionVersion as Json)
          : {};
      naming.assertionVersion = {
        ...version,
        supersedes: effectiveAssertionId(named),
      };
    }
    return parsed;
  });

function namedIds(rows: readonly Json[]): Set<string> {
  return new Set(
    rows.map(supersededAssertionId).filter((id): id is string => id !== null),
  );
}

describe("current view properties", () => {
  it("is idempotent", () => {
    fc.assert(
      fc.property(rawLedger, (rows) => {
        const once = effectiveCurrentRows(rows);
        expect(effectiveCurrentRows(once)).toEqual(once);
        const entries = mapPolicyEngineLedgerRows(rows);
        const view = currentLedgerView(entries);
        expect(currentLedgerView(view)).toEqual(view);
      }),
      { numRuns: 300 },
    );
  });

  it("never contains a superseded id and drops nothing else", () => {
    fc.assert(
      fc.property(rawLedger, (rows) => {
        const named = namedIds(rows);
        const kept = new Set(effectiveCurrentRows(rows));
        for (const row of rows) {
          expect(kept.has(row)).toBe(!named.has(effectiveAssertionId(row)));
        }
      }),
      { numRuns: 300 },
    );
  });

  it("is an order-preserving subsequence, and the identity with no supersedes", () => {
    fc.assert(
      fc.property(rawLedger, (rows) => {
        const view = positions(rows, effectiveCurrentRows(rows));
        expect([...view].sort((a, b) => a - b)).toEqual(view);
        expect(new Set(view).size).toBe(view.length);
        const unlinked = rows.map((row) => {
          const copy = { ...row };
          delete copy.assertionVersion;
          return copy;
        });
        expect(effectiveCurrentRows(unlinked)).toEqual(unlinked);
        // With nothing superseded, entries are exactly the unannotated map.
        const entries = mapPolicyEngineLedgerRows(unlinked);
        expect(entries.every((entry) => !entry.supersededContentAddress)).toBe(
          true,
        );
        expect(currentLedgerView(entries)).toEqual(entries);
      }),
      { numRuns: 200 },
    );
  });

  it("matches the raw-row view through the site's lazy entry addressing", () => {
    fc.assert(
      fc.property(rawLedger, (rows) => {
        const entries = mapPolicyEngineLedgerRows(rows);
        expect(positions(entries, currentLedgerView(entries))).toEqual(
          positions(rows, effectiveCurrentRows(rows)),
        );
      }),
      { numRuns: 300 },
    );
  });

  it("passes registrations through untouched", () => {
    fc.assert(
      fc.property(rawLedger, (rows) => {
        const registration = {
          kind: "target_registered",
          dataPointId: "rid.a",
        } as TargetRegisteredLedgerEntry;
        const ledger: PolicyEngineLedgerEntry[] = [
          registration,
          ...mapPolicyEngineLedgerRows(rows),
        ];
        expect(currentLedgerView(ledger)[0]).toBe(registration);
      }),
      { numRuns: 100 },
    );
  });
});

// ---------------------------------------------------------------------------
// Gated ledgers: valid append sequences with corrections, as Chronicle's gate
// admits them.
// ---------------------------------------------------------------------------

type AppendOp =
  | { kind: "new"; preVersioning: boolean; value: number }
  | { kind: "correct"; record: number; delta: number; changeUnit: boolean };

const appendOp: fc.Arbitrary<AppendOp> = fc.oneof(
  fc.record({
    kind: fc.constant("new" as const),
    preVersioning: fc.boolean(),
    value: fc.integer({ min: -50, max: 50 }),
  }),
  fc.record({
    kind: fc.constant("correct" as const),
    record: fc.nat(),
    delta: fc.integer({ min: 1, max: 9 }),
    changeUnit: fc.boolean(),
  }),
);

// Acceptance instants start after every fixture print below is public.
const EPOCH = Date.parse("2026-08-02T00:00:00Z");

function acceptedAt(sequence: number): string {
  return new Date(EPOCH + sequence * 3_600_000).toISOString();
}

function buildGatedRows(ops: AppendOp[]): Json[] {
  const rows: Json[] = [];
  const latest = new Map<string, Json>();
  const records: string[] = [];
  for (const op of ops) {
    if (op.kind === "new" || records.length === 0) {
      const recordId = `gated.series.p${records.length}.first_print`;
      const row: Json = {
        source_record_id: recordId,
        value: op.kind === "new" ? op.value : 0,
        observed_at: "2026-06-15",
        period: { type: "month", value: "2026-06" },
        measure: { unit: "percent", concept: "gated.series" },
        source: { source_name: "test", url: "https://example.gov/gated" },
      };
      if (!(op.kind === "new" && op.preVersioning)) {
        row.assertionVersion = {
          id: expectedAssertionVersionId(row),
          supersedes: null,
        };
      }
      records.push(recordId);
      latest.set(recordId, row);
      rows.push(row);
      continue;
    }
    const recordId = records[op.record % records.length];
    const previous = latest.get(recordId)!;
    const correction: Json = {
      ...previous,
      value: (previous.value as number) + op.delta,
      measure: op.changeUnit
        ? { ...(previous.measure as Json), unit: "thousands" }
        : previous.measure,
    };
    delete correction.assertionVersion;
    correction.assertionVersion = {
      id: expectedAssertionVersionId(correction),
      supersedes: effectiveAssertionId(previous),
    };
    latest.set(recordId, correction);
    rows.push(correction);
  }
  return JSON.parse(JSON.stringify(rows)) as Json[];
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function withAcceptance(
  entries: ObservationRecordedLedgerEntry[],
): ObservationRecordedLedgerEntry[] {
  return entries.map((entry, sequence) => ({
    ...entry,
    acceptedSequence: sequence,
    acceptedAtUtc: acceptedAt(sequence),
  }));
}

const gatedOps = fc.array(appendOp, { minLength: 1, maxLength: 14 });

describe("gated ledgers", () => {
  it("pass the append-gate checks and keep exactly the last row per record", () => {
    fc.assert(
      fc.property(gatedOps, (ops) => {
        const rows = buildGatedRows(ops);
        expect(() => assertAppendGateAssertionVersions(rows)).not.toThrow();
        const entries = mapPolicyEngineLedgerRows(rows);
        const view = currentLedgerView(entries);
        const lastByRecord = new Map<string, ObservationRecordedLedgerEntry>();
        for (const entry of entries) lastByRecord.set(entry.dataPointId, entry);
        expect(view).toEqual(
          [...lastByRecord.values()].sort(
            (a, b) => entries.indexOf(a) - entries.indexOf(b),
          ),
        );
        for (const [dataPointId, last] of lastByRecord) {
          const forecast = { dataPointId } as ForecastCell;
          expect(getResolvedObservationForForecast(forecast, entries)).toBe(
            last,
          );
          expect(getObservationForId(`obs.${dataPointId}`, entries)).toBe(last);
        }
      }),
      { numRuns: 200 },
    );
  });

  it("views the ledger as of any cutoff exactly as the prefix accepted by then", () => {
    fc.assert(
      fc.property(gatedOps, fc.nat(), (ops, pick) => {
        const entries = withAcceptance(
          mapPolicyEngineLedgerRows(buildGatedRows(ops)),
        );
        const cutoff = pick % entries.length;
        const asOf = observationViewAsOf(
          entries,
          Date.parse(acceptedAt(cutoff)),
        );
        const prefix = entries.slice(0, cutoff + 1);
        expect(asOf).toEqual(currentLedgerView(prefix));
        // Rows accepted after the cutoff never change the view at it.
        expect(
          observationViewAsOf(prefix, Date.parse(acceptedAt(cutoff))),
        ).toEqual(asOf);
      }),
      { numRuns: 200 },
    );
  });

  it("dates and admits every row by its chain's first print", () => {
    fc.assert(
      fc.property(gatedOps, (ops) => {
        const entries = withAcceptance(
          mapPolicyEngineLedgerRows(buildGatedRows(ops)),
        );
        for (const entry of entries) {
          const first = entries.find(
            (other) => other.dataPointId === entry.dataPointId,
          )!;
          // Later rows never join a chain, whatever ledger is passed.
          expect(firstAcceptedSequence(entry, entries)).toBe(
            first.acceptedSequence,
          );
          expect(firstObservedAt(entry, entries)).toBe(first.observedAt);
        }
      }),
      { numRuns: 200 },
    );
  });

  it("refuses a tampered id, a silent duplicate, or a stale supersede", () => {
    fc.assert(
      fc.property(gatedOps, fc.nat(), (ops, pick) => {
        const rows = buildGatedRows(ops);
        const versioned = rows.filter((row) => row.assertionVersion);
        if (versioned.length > 0) {
          const tampered = clone(rows);
          const target =
            tampered[rows.indexOf(versioned[pick % versioned.length])];
          const version = target.assertionVersion as Json;
          const id = version.id as string;
          version.id = `${id.slice(0, -1)}${id.endsWith("0") ? "1" : "0"}`;
          expect(() => assertAppendGateAssertionVersions(tampered)).toThrow(
            /does not match its content/,
          );
        }
        const corrections = rows.filter(
          (row) => (row.assertionVersion as Json | undefined)?.supersedes,
        );
        if (corrections.length > 0) {
          const index = rows.indexOf(corrections[pick % corrections.length]);
          const silent = clone(rows);
          (silent[index].assertionVersion as Json).supersedes = null;
          expect(() => assertAppendGateAssertionVersions(silent)).toThrow(
            /without superseding/,
          );
          const stale = clone(rows);
          (stale[index].assertionVersion as Json).supersedes = "av2:stale";
          expect(() => assertAppendGateAssertionVersions(stale)).toThrow(
            /active version/,
          );
        }
      }),
      { numRuns: 200 },
    );
  });
});

// ---------------------------------------------------------------------------
// Scoring examples on a contract-bound target, through the real parse path.
// ---------------------------------------------------------------------------

const DATA_POINT_ID = "test.corrected.series.2026_06.first_print";
const RESPONSE_SHA256 = "c".repeat(64);
const TARGET_HASH = "a".repeat(64);

const cell: ForecastCell = {
  slug: "corrected-cell",
  country: "US",
  type: "data",
  title: "Corrected contract test",
  question: "?",
  unit: "thousands",
  pointEstimate: 220,
  ciLow: 200,
  ciHigh: 240,
  confidence: 0.8,
  resolutionDate: "2026-07-20",
  resolutionSource: "Test",
  resolutionRule: "Test",
  dataPointId: DATA_POINT_ID,
  historicalContext: [],
  drivers: [],
  predictionRun: {
    kind: "recorded-agent-run",
    runAt: "2026-07-01T00:00:00Z",
    agent: "test.agent",
    model: "test-model",
    sourceContext: [],
  },
  reasoning: [{ kind: "forecast", point: 220, ciLow: 200, ciHigh: 240 }],
};

const binding = {
  adapter: "alfred-fred" as const,
  sourceUrl: "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=TEST",
  sourceSeriesId: "TEST",
  field: "TEST",
  table: "ALFRED graph CSV",
  transform: { operation: "multiply", factor: 0.001 },
  releasePolicy: "advance_vintage" as const,
  allowedHosts: ["alfred.stlouisfed.org"],
  expectedReleaseWindow: { start: "2026-07-15", end: "2026-07-25" },
};

const registered: TargetRegisteredLedgerEntry = {
  kind: "target_registered",
  dataPointId: DATA_POINT_ID,
  observationId: `obs.${DATA_POINT_ID}`,
  country: "US",
  periodLabel: "June 2026",
  unit: "thousands",
  resolutionDate: cell.resolutionDate,
  resolutionSource: "Test",
  resolutionRule: "Test",
  resolutionPolicy: "first_print",
  sourceKind: "official_release",
  source: "Test",
  note: "fixture",
  registrationState: "preregistered",
  registeredAt: "2026-06-20T00:00:00Z",
  targetContentHash: TARGET_HASH,
  series: "test.corrected.series",
  period: "2026-06",
  catalogSlug: cell.slug,
  valueScale: 0.001,
  sourceBinding: binding,
  ledgerPinSha: "b".repeat(40),
  ledgerPinLineCount: 2,
};

// A resolver-appended row as Chronicle stores it, bound to the registration.
function boundRow(overrides: Json = {}): Json {
  const row: Json = {
    source_record_id: DATA_POINT_ID,
    value: 225,
    observed_at: "2026-07-20",
    period: { type: "month", value: "2026-06" },
    measure: { unit: "thousands", concept: "test.corrected.series" },
    source: {
      source_name: "fred",
      source_table: "ALFRED graph CSV",
      url: binding.sourceUrl,
    },
    targetContentHash: TARGET_HASH,
    ledgerRepoSha: "d".repeat(40),
    sourceVintage: "2026-07-20",
    retrievedAt: "2026-07-20T12:30:00Z",
    responseArchive: {
      path: "records/resolutions/test/responses/test.csv.gz",
      sha256: RESPONSE_SHA256,
      bytes: 100,
      gzipSha256: "e".repeat(64),
      gzipBytes: 60,
      contentEncoding: "gzip",
    },
    sourceBindingProjection: {
      series: "test.corrected.series",
      period: "2026-06",
      releasePolicy: "advance_vintage",
      table: "ALFRED graph CSV",
      field: "TEST",
      transform: { operation: "multiply", factor: 0.001 },
      unit: "thousands",
      responseSha256: RESPONSE_SHA256,
    },
    ...overrides,
  };
  return row;
}

function versioned(row: Json, supersedes: Json | null): Json {
  const copy = { ...row };
  delete copy.assertionVersion;
  return {
    ...copy,
    assertionVersion: {
      id: expectedAssertionVersionId(copy),
      supersedes: supersedes ? effectiveAssertionId(supersedes) : null,
    },
  };
}

// Parses rows as the pinned path does, then stamps acceptance in line order,
// starting after two earlier ledger lines (ledgerPinLineCount = 2).
function ledgerOf(rows: Json[], firstSequence = 2): PolicyEngineLedgerEntry[] {
  const entries = parsePolicyEngineLedgerFacts(
    rows.map((row) => JSON.stringify(row)).join("\n"),
  ) as ObservationRecordedLedgerEntry[];
  return [
    registered,
    ...entries.map((entry, index) => ({
      ...entry,
      acceptedSequence: firstSequence + index,
      acceptedAtUtc: acceptedAt(firstSequence + index),
      legacyQuarantined: false,
      resolutionRecordedAt: entry.retrievedAt,
    })),
  ];
}

const run = () => getForecastRunEntries(cell)[0];

describe("scoring on the current view", () => {
  const original = versioned(boundRow(), null);
  const correction = versioned(boundRow({ value: 231 }), original);

  it("grades an uncorrected row exactly as before, under its historical id", () => {
    const evaluation = evaluateResolvedForecastRun(
      cell,
      run(),
      ledgerOf([original]),
    );
    expect(evaluation.exclusion).toBeUndefined();
    expect(evaluation.score?.observedValue).toBe(225);
    expect(evaluation.score?.resolutionEventId).toBe(
      `resolution_event.${cell.slug}.test-corrected-series-2026-06-first-print`,
    );
  });

  it("grades the correction in place of the superseded original", () => {
    const ledger = ledgerOf([original, correction]);
    const evaluation = evaluateResolvedForecastRun(cell, run(), ledger);
    expect(evaluation.exclusion).toBeUndefined();
    expect(evaluation.score?.observedValue).toBe(231);
    expect(evaluation.score?.contractBinding).toBe("contract_bound");
    expect(getResolvedOutcomeForForecast(cell, ledger)?.value).toBe(231);
    expect(getResolvedObservationForForecast(cell, ledger)?.value).toBe(231);
  });

  it("gives the correction's resolution its own event id, shared with the projection", () => {
    const ledger = ledgerOf([original, correction]);
    const evaluation = evaluateResolvedForecastRun(cell, run(), ledger);
    const resolving = getResolvedObservationForForecast(cell, ledger)!;
    const correctionId = (correction.assertionVersion as Json).id as string;
    const expected =
      `resolution_event.${cell.slug}.test-corrected-series-2026-06-first-print.` +
      correctionId.replace(/[^A-Za-z0-9]+/g, "-");
    expect(getResolutionForForecast(cell, ledger)?.resolutionEventId).toBe(
      expected,
    );
    expect(evaluation.score?.resolutionEventId).toBe(expected);
    expect(buildObservationResolutionEventId(cell.slug, resolving)).toBe(
      expected,
    );
  });

  it("never falls back to the superseded row when the correction breaks the contract", () => {
    const wrongUnit = versioned(
      boundRow({
        value: 0.231,
        measure: { unit: "millions", concept: "test.corrected.series" },
        sourceBindingProjection: {
          ...(boundRow().sourceBindingProjection as Json),
          unit: "millions",
        },
      }),
      original,
    );
    const evaluation = evaluateResolvedForecastRun(
      cell,
      run(),
      ledgerOf([original, wrongUnit]),
    );
    expect(evaluation.score).toBeUndefined();
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toMatch(/unit "millions"/);
  });

  it("drops a pre-versioning row its content-addressed correction names", () => {
    const legacy = boundRow();
    delete legacy.targetContentHash;
    delete legacy.sourceBindingProjection;
    const fixed = versioned(boundRow({ value: 231 }), legacy);
    const ledger = ledgerOf([legacy, fixed]);
    const [, legacyEntry] = ledger as ObservationRecordedLedgerEntry[];
    expect(legacyEntry.supersededContentAddress).toBe(
      expectedAssertionVersionId(legacy),
    );
    expect(getResolvedObservationForForecast(cell, ledger)?.value).toBe(231);
    expect(
      evaluateResolvedForecastRun(cell, run(), ledger).score?.observedValue,
    ).toBe(231);
  });

  it("dates the resolution by its first print, so a late correction admits no late run", () => {
    // The run was made after the original print was public.
    const lateCell: ForecastCell = {
      ...cell,
      predictionRun: { ...cell.predictionRun!, runAt: "2026-07-25T00:00:00Z" },
    };
    const lateCorrection = versioned(
      boundRow({ value: 231, observed_at: "2026-08-01" }),
      original,
    );
    const ledger = ledgerOf([original, lateCorrection]);
    const lateRun = getForecastRunEntries(lateCell)[0];
    const alone = evaluateResolvedForecastRun(
      lateCell,
      lateRun,
      ledgerOf([original]),
    );
    const corrected = evaluateResolvedForecastRun(lateCell, lateRun, ledger);
    expect(alone.score?.chronology).toBe("violated");
    expect(corrected.score?.chronology).toBe("violated");
    expect(corrected.score?.observedAt).toBe("2026-07-20");
    expect(corrected.score?.observedValue).toBe(231);
  });

  it("keeps a correction of a pre-registration print out of grading (N5)", () => {
    // The original was already inside the pinned state (sequence 1 < 2);
    // appending a correction later must not launder it.
    const ledger = ledgerOf([original, correction], 1);
    const evaluation = evaluateResolvedForecastRun(cell, run(), ledger);
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toMatch(
      /already inside the pinned ledger state/,
    );
  });
});

describe("cutoff histories on the as-of view", () => {
  // A second registered period of the same series, graded against history.
  const nextCell: ForecastCell = {
    ...cell,
    slug: "corrected-cell-next",
    dataPointId: "test.corrected.series.2026_07.first_print",
  };
  const nextTarget: TargetRegisteredLedgerEntry = {
    ...registered,
    dataPointId: nextCell.dataPointId!,
    observationId: `obs.${nextCell.dataPointId}`,
    period: "2026-07",
    catalogSlug: nextCell.slug,
  };
  const original = versioned(boundRow(), null);
  const correction = versioned(boundRow({ value: 231 }), original);
  const history = (rows: Json[], cutoff: string) =>
    ledgerHistoryAtCutoff(
      nextCell,
      [nextTarget, ...ledgerOf(rows)],
      cutoff,
    ).map((entry) => entry.value);

  it("reads the original before the correction's acceptance and the correction after", () => {
    // original accepted at sequence 2, correction at sequence 3
    expect(history([original, correction], acceptedAt(2))).toEqual([225]);
    expect(history([original, correction], acceptedAt(3))).toEqual([231]);
  });

  it("never lets a superseded row back in when its correction fails a filter", () => {
    const wrongUnit = versioned(
      boundRow({
        value: 0.231,
        measure: { unit: "millions", concept: "test.corrected.series" },
      }),
      original,
    );
    expect(history([original, wrongUnit], acceptedAt(2))).toEqual([225]);
    expect(history([original, wrongUnit], acceptedAt(3))).toEqual([]);
  });
});
