import { readFileSync } from "node:fs";
import { join } from "node:path";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { formatValue } from "@/data/forecast-display";
import {
  assertAppendGateAssertionVersions,
  currentLedgerView,
  effectiveAssertionId,
  firstAcceptedSequence,
  firstObservedAt,
  observationSupersedes,
  supersedeChain,
} from "@/data/ledger-current-view";
import {
  foldLedgerRestatements,
  isUnitRestatement,
  recordedPair,
  UNIT_RESTATEMENT,
} from "@/data/ledger-restatements";
import {
  isScaledUnit,
  LEDGER_UNIT_SCALES,
  LedgerUnitError,
  shiftDecimal,
  toBase,
  type ScaledUnit,
} from "@/data/ledger-units";
import {
  buildPolicyEngineLedgerExport,
  mapPolicyEngineLedgerRows,
  parsePolicyEngineLedgerFacts,
  type ObservationRecordedLedgerEntry,
} from "@/data/thesis-log";
import { isUnit, UNITS } from "@/data/units";
import {
  baseRowOf,
  currentScaledLines,
  restatementOf,
  sha256,
  withVersion,
  type Json,
} from "./ledger-restatement-helpers";

const SCALED = Object.keys(LEDGER_UNIT_SCALES) as ScaledUnit[];

interface UnitFixture {
  table: Record<string, { base: string; power: number }>;
  cases: { value: number; unit: ScaledUnit; result: number | null }[];
}

const FIXTURE = JSON.parse(
  readFileSync(join(__dirname, "fixtures/ledger-units.json"), "utf8"),
) as UnitFixture;

describe("the unit table", () => {
  it("names only site units, and no base unit holds a scale", () => {
    for (const [unit, { base }] of Object.entries(LEDGER_UNIT_SCALES)) {
      expect(isUnit(unit)).toBe(true);
      expect(isUnit(base)).toBe(true);
      expect(isScaledUnit(base)).toBe(false);
    }
  });

  it("reads only its own keys", () => {
    for (const other of ["constructor", "__proto__", "count", "", null, 3]) {
      expect(isScaledUnit(other)).toBe(false);
    }
  });

  it("gives each new base unit a display", () => {
    expect(formatValue(2_500_000_000, "gbp")).toBe("£2,500,000,000");
    expect(formatValue(250_000, "cubic_feet")).toBe("250,000 cu ft");
    expect(UNITS).toContain("gbp");
    expect(UNITS).toContain("cubic_feet");
  });
});

describe("agreement with the resolver's conversion", () => {
  it("holds the table scripts/ledger_units.py holds", () => {
    expect(FIXTURE.table).toEqual(LEDGER_UNIT_SCALES);
  });

  it("converts and refuses every recorded value as Python did", () => {
    const refused = FIXTURE.cases.filter((row) => row.result === null);
    expect(refused.length).toBeGreaterThan(0);
    expect(refused.length).toBeLessThan(FIXTURE.cases.length);
    for (const { value, unit, result } of FIXTURE.cases) {
      if (result === null) {
        expect(() => toBase(value, unit), `${value} ${unit}`).toThrow(
          LedgerUnitError,
        );
      } else {
        expect(toBase(value, unit), `${value} ${unit}`).toBe(result);
      }
    }
  });
});

describe("toBase", () => {
  it("avoids the float error multiplying would make", () => {
    expect(8.2 * 1e6).toBe(8199999.999999999);
    expect(toBase(8.2, "millions")).toBe(8_200_000);
    expect(toBase(1.1, "thousands")).toBe(1100);
    expect(toBase(7.716, "millions")).toBe(7_716_000);
    expect(toBase(395.1, "billions USD")).toBe(395_100_000_000);
    expect(toBase(-7.91746189, "usd_millions")).toBe(-7917461.89);
    expect(toBase(0, "thousands")).toBe(0);
    expect(Object.is(toBase(-0, "millions"), 0)).toBe(true);
  });

  it("refuses what has no exact form", () => {
    for (const value of [
      Number.NaN,
      Number.POSITIVE_INFINITY,
      Number.MAX_SAFE_INTEGER,
      1e300,
      0.30000000000000004,
    ]) {
      expect(() => toBase(value, "thousands"), String(value)).toThrow(
        LedgerUnitError,
      );
    }
  });

  it("converts any decimal of up to 15 digits exactly and back", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -999_999_999_999_999, max: 999_999_999_999_999 }),
        fc.integer({ min: -12, max: 0 }),
        fc.constantFrom(...SCALED),
        (digits, exponent, unit) => {
          const value = Number(`${digits}e${exponent}`);
          const { power } = LEDGER_UNIT_SCALES[unit];
          const exact = Number(`${digits}e${exponent + power}`);
          if (Math.abs(exact) > Number.MAX_SAFE_INTEGER) {
            expect(() => toBase(value, unit)).toThrow(LedgerUnitError);
            return;
          }
          expect(toBase(value, unit)).toBe(exact === 0 ? 0 : exact);
          expect(shiftDecimal(toBase(value, unit), -power)).toBe(
            value === 0 ? 0 : value,
          );
        },
      ),
    );
  });
});

const RESPONSE = "c".repeat(64);

function scaledRow(overrides: Json = {}): Json {
  return {
    source_record_id: "test.scaled.series.2026_06.first_print",
    value: 7.716,
    observed_at: "2026-07-20",
    period: { type: "month", value: "2026-06" },
    measure: { unit: "millions", concept: "test.scaled.series" },
    source: {
      source_name: "bls",
      source_table: "JOLTS",
      url: "https://example.gov/jolts",
      method_notes: "Recorded, expressed in millions.",
    },
    label: "A label",
    targetContentHash: "a".repeat(64),
    ledgerRepoSha: "b".repeat(40),
    sourceVintage: "2026-07-20",
    retrievedAt: "2026-07-20T12:30:00Z",
    responseArchive: {
      path: "records/resolutions/test/responses/test.csv.gz",
      sha256: RESPONSE,
      bytes: 100,
      gzipSha256: "e".repeat(64),
      gzipBytes: 60,
      contentEncoding: "gzip",
    },
    sourceBindingProjection: {
      series: "test.scaled.series",
      period: "2026-06",
      releasePolicy: "first_print",
      table: "JOLTS",
      field: "JTS",
      transform: { operation: "multiply", factor: 0.001 },
      unit: "millions",
      responseSha256: RESPONSE,
    },
    ...overrides,
  };
}

function ledger(...rows: Json[]): string {
  return rows.map((row) => JSON.stringify(row)).join("\n");
}

function read(jsonl: string) {
  const lines = jsonl.split("\n").filter(Boolean);
  const rows = lines.map((line) => JSON.parse(line) as unknown);
  assertAppendGateAssertionVersions(rows);
  return foldLedgerRestatements(mapPolicyEngineLedgerRows(rows), rows, lines);
}

describe("reading a restatement", () => {
  const prior = withVersion(scaledRow(), null);
  const priorLine = JSON.stringify(prior);

  it("leaves the entries byte-identical and lists it apart", () => {
    const restatement = restatementOf(priorLine);
    const before = parsePolicyEngineLedgerFacts(ledger(prior));
    const { entries, restatements } = read(ledger(prior, restatement));
    expect(JSON.stringify(entries)).toBe(JSON.stringify(before));
    expect(restatements).toEqual([
      {
        dataPointId: prior.source_record_id,
        assertionId: effectiveAssertionId(restatement),
        supersedes: effectiveAssertionId(prior),
        value: 7_716_000,
        unit: "count",
      },
    ]);
  });

  it("restates a pre-versioning row without giving it an address", () => {
    const legacy = scaledRow();
    delete legacy.assertionVersion;
    const before = parsePolicyEngineLedgerFacts(ledger(legacy));
    const { entries } = read(ledger(legacy, restatementOf(ledger(legacy))));
    expect(JSON.stringify(entries)).toBe(JSON.stringify(before));
    expect(
      (entries[0] as ObservationRecordedLedgerEntry).supersededContentAddress,
    ).toBeUndefined();
  });

  it("publishes the restatement in the export and nowhere on an entry", () => {
    const { entries, restatements } = read(
      ledger(prior, restatementOf(priorLine)),
    );
    const published = buildPolicyEngineLedgerExport(entries, restatements);
    expect(published.counts.observations).toBe(1);
    expect(published.restatements).toEqual(restatements);
    expect(buildPolicyEngineLedgerExport(entries)).not.toHaveProperty(
      "restatements",
    );
  });

  // Each change breaks one thing the parser proves. The id stays honest, so the
  // append gate passes each one and only the restatement's check can refuse it.
  const tamperings: [string, (row: Json) => Json, RegExp][] = [
    [
      "a different value",
      (row) => ({ ...row, value: 7_716_001 }),
      /stores 7716001, not 7716000/,
    ],
    [
      "another base unit",
      (row) => ({ ...row, measure: { ...(row.measure as Json), unit: "usd" } }),
      /stores "usd", not the base unit of millions/,
    ],
    [
      "a still-scaled unit",
      (row) => ({
        ...row,
        measure: { ...(row.measure as Json), unit: "thousands" },
      }),
      /stores "thousands", not the base unit of millions/,
    ],
    [
      "a different recorded value",
      (row) => ({
        ...row,
        source: { ...(row.source as Json), recorded_value: 7.717 },
      }),
      /records 7\.717 "millions" but the row says 7\.716 millions/,
    ],
    [
      "a different recorded unit",
      (row) => ({
        ...row,
        source: { ...(row.source as Json), recorded_unit: "thousands" },
      }),
      /records 7\.716 "thousands" but the row says/,
    ],
    [
      "no recorded pair",
      (row) => {
        const source = { ...(row.source as Json) };
        delete source.recorded_value;
        delete source.recorded_unit;
        return { ...row, source };
      },
      /records undefined undefined/,
    ],
    [
      "an archive of something else",
      (row) => ({
        ...row,
        responseArchive: {
          ...(row.responseArchive as Json),
          sha256: "0".repeat(64),
        },
      }),
      /does not archive the exact line/,
    ],
    [
      "a different publisher date",
      (row) => ({ ...row, observed_at: "2026-07-21" }),
      /changes more than the value and unit/,
    ],
    [
      "a different period",
      (row) => ({ ...row, period: { type: "month", value: "2026-07" } }),
      /changes more than the value and unit/,
    ],
    [
      "a different concept",
      (row) => ({
        ...row,
        measure: { ...(row.measure as Json), concept: "test.other" },
      }),
      /changes more than the value and unit/,
    ],
    [
      "a different source url",
      (row) => ({
        ...row,
        source: { ...(row.source as Json), url: "https://example.gov/other" },
      }),
      /changes more than the value and unit/,
    ],
    [
      "a different contract hash",
      (row) => ({ ...row, targetContentHash: "9".repeat(64) }),
      /changes more than the value and unit/,
    ],
    [
      "a different transform",
      (row) => ({
        ...row,
        sourceBindingProjection: {
          ...(row.sourceBindingProjection as Json),
          transform: { operation: "identity" },
        },
      }),
      /changes more than the value and unit/,
    ],
    [
      "a dropped projection",
      (row) => {
        const copy = { ...row };
        delete copy.sourceBindingProjection;
        return copy;
      },
      /changes more than the value and unit/,
    ],
    [
      "a new field",
      (row) => ({ ...row, extra: true }),
      /changes more than the value and unit/,
    ],
    [
      "a different label",
      (row) => ({ ...row, label: "Another label" }),
      /changes more than the value and unit/,
    ],
  ];

  it.each(tamperings)("refuses %s", (_name, change, message) => {
    const honest = restatementOf(priorLine);
    const tampered = withVersion(change(honest), effectiveAssertionId(prior), {
      relation: UNIT_RESTATEMENT,
    });
    expect(() => read(ledger(prior, honest))).not.toThrow();
    expect(() => read(ledger(prior, tampered))).toThrow(message);
    expect(() => parsePolicyEngineLedgerFacts(ledger(prior, tampered))).toThrow(
      LedgerUnitError,
    );
  });

  it("refuses to restate a row that holds no scale", () => {
    const percent = withVersion(
      scaledRow({
        measure: { unit: "percent", concept: "test.scaled.series" },
      }),
      null,
    );
    const restatement = withVersion(
      {
        ...percent,
        source: {
          ...(percent.source as Json),
          recorded_value: 7.716,
          recorded_unit: "percent",
        },
        responseArchive: {
          ...(percent.responseArchive as Json),
          sha256: sha256(JSON.stringify(percent)),
        },
      },
      effectiveAssertionId(percent),
      { relation: UNIT_RESTATEMENT },
    );
    expect(() => read(ledger(percent, restatement))).toThrow(
      /names a row in "percent", which holds no scale/,
    );
  });

  it("refuses to restate a restatement", () => {
    const first = restatementOf(priorLine);
    const firstLine = JSON.stringify(first);
    const second = withVersion(
      {
        ...first,
        responseArchive: {
          ...(first.responseArchive as Json),
          sha256: sha256(firstLine),
        },
        retrievedAt: "2026-11-04T00:00:00Z",
      },
      effectiveAssertionId(first),
      { relation: UNIT_RESTATEMENT },
    );
    expect(() => read(ledger(prior, first, second))).toThrow(
      /names a row in "count", which holds no scale/,
    );
  });

  it("refuses a restatement of nothing, and an unknown relation", () => {
    const orphan = withVersion(restatementOf(priorLine), null, {
      relation: UNIT_RESTATEMENT,
    });
    const rows = [orphan];
    const lines = rows.map((row) => JSON.stringify(row));
    expect(() =>
      foldLedgerRestatements(mapPolicyEngineLedgerRows(rows), rows, lines),
    ).toThrow(/restates null, which no earlier row holds/);

    const unknown = withVersion(
      restatementOf(priorLine),
      effectiveAssertionId(prior),
      { relation: "unit_restatment" },
    );
    expect(isUnitRestatement(restatementOf(priorLine))).toBe(true);
    expect(() => isUnitRestatement(unknown)).toThrow(
      /relation "unit_restatment"/,
    );
    expect(() => parsePolicyEngineLedgerFacts(ledger(prior, unknown))).toThrow(
      LedgerUnitError,
    );
  });
});

describe("correcting a restated row", () => {
  function stamped(rows: Json[]): ObservationRecordedLedgerEntry[] {
    const lines = rows.map((row) => JSON.stringify(row));
    return foldLedgerRestatements(
      mapPolicyEngineLedgerRows(rows).map((entry, index) => ({
        ...entry,
        acceptedSequence: index,
        acceptedAtUtc: new Date(
          Date.parse("2026-08-02T00:00:00Z") + index * 3_600_000,
        ).toISOString(),
      })),
      rows,
      lines,
    ).entries;
  }

  for (const preVersioning of [false, true]) {
    const kind = preVersioning ? "pre-versioning" : "versioned";

    it(`grades the correction once, as if it corrected the ${kind} row`, () => {
      const prior = preVersioning
        ? scaledRow()
        : withVersion(scaledRow(), null);
      const restatement = restatementOf(JSON.stringify(prior));
      const corrected = baseRowOf(
        { ...scaledRow(), value: 7.8, observed_at: "2026-08-01" },
        "millions",
      );
      const correction = withVersion(
        corrected,
        effectiveAssertionId(restatement),
      );
      const rows = [prior, restatement, correction];
      assertAppendGateAssertionVersions(rows);
      const entries = stamped(rows);

      expect(entries).toHaveLength(2);
      const [original, fix] = entries;
      expect(observationSupersedes(fix)).toBe(effectiveAssertionId(prior));
      expect(fix.gradedSupersedes).toBe(effectiveAssertionId(prior));
      expect(currentLedgerView(entries)).toEqual([fix]);
      expect(fix).toMatchObject({ value: 7.8, unit: "millions" });
      expect(supersedeChain(fix, entries)).toEqual([fix, original]);
      expect(firstAcceptedSequence(fix, entries)).toBe(0);
      expect(firstObservedAt(fix, entries)).toBe("2026-07-20");
      expect(original.supersededContentAddress).toBe(
        preVersioning ? effectiveAssertionId(prior) : undefined,
      );
    });

    it(`publishes no internal field when correcting a ${kind} row`, () => {
      const prior = preVersioning
        ? scaledRow()
        : withVersion(scaledRow(), null);
      const restatement = restatementOf(JSON.stringify(prior));
      const correction = withVersion(
        baseRowOf({ ...scaledRow(), value: 7.8 }, "millions"),
        effectiveAssertionId(restatement),
      );
      const published = JSON.stringify(
        buildPolicyEngineLedgerExport(
          stamped([prior, restatement, correction]),
        ),
      );
      expect(published).not.toContain("gradedSupersedes");
      expect(published).not.toContain("supersededContentAddress");
    });
  }

  it("restates a correction of a scaled row, and keeps the chain", () => {
    const prior = withVersion(scaledRow(), null);
    const correction = withVersion(
      scaledRow({ value: 7.8 }),
      effectiveAssertionId(prior),
    );
    const restatement = restatementOf(JSON.stringify(correction));
    const rows = [prior, correction, restatement];
    assertAppendGateAssertionVersions(rows);
    const entries = stamped(rows);
    expect(entries).toHaveLength(2);
    expect(currentLedgerView(entries).map((entry) => entry.value)).toEqual([
      7.8,
    ]);
    expect(entries.every((entry) => !entry.gradedSupersedes)).toBe(true);
  });
});

describe("reading a base row", () => {
  it("reads the recorded pair, as if the old writer wrote it", () => {
    const old = withVersion(scaledRow(), null);
    const written = withVersion(baseRowOf(scaledRow(), "millions"), null);
    const [oldEntry] = parsePolicyEngineLedgerFacts(ledger(old));
    const [entry] = parsePolicyEngineLedgerFacts(ledger(written));
    const { ledgerValue, ledgerUnit, assertionVersion, ...view } =
      entry as ObservationRecordedLedgerEntry;
    expect(ledgerValue).toBe(7_716_000);
    expect(ledgerUnit).toBe("count");
    expect(assertionVersion?.id).toBe(effectiveAssertionId(written));
    const { assertionVersion: _oldVersion, ...oldView } =
      oldEntry as ObservationRecordedLedgerEntry;
    expect(view).toEqual(oldView);
  });

  it("leaves a row with no recorded pair as it stands", () => {
    const percent = withVersion(
      scaledRow({ value: 4.3, measure: { unit: "percent", concept: "x" } }),
      null,
    );
    const [entry] = parsePolicyEngineLedgerFacts(ledger(percent));
    expect(entry).toMatchObject({ value: 4.3, unit: "percent" });
    expect(entry).not.toHaveProperty("ledgerValue");
    expect(recordedPair(percent)).toBeNull();

    // A base-unit row with no pair reads raw, so a scaled contract refuses it.
    const count = withVersion(
      scaledRow({ value: 7_716_000, measure: { unit: "count", concept: "x" } }),
      null,
    );
    expect(parsePolicyEngineLedgerFacts(ledger(count))[0]).toMatchObject({
      value: 7_716_000,
      unit: "count",
    });
  });

  it("publishes what Chronicle stores beside what the site grades", () => {
    const written = withVersion(baseRowOf(scaledRow(), "millions"), null);
    const entries = parsePolicyEngineLedgerFacts(ledger(written));
    const [row] = buildPolicyEngineLedgerExport(entries).entries;
    expect(row).toMatchObject({
      value: 7.716,
      unit: "millions",
      ledgerValue: 7_716_000,
      ledgerUnit: "count",
      sourceBindingProjection: { unit: "millions" },
    });
  });

  const refusals: [string, (row: Json) => Json, RegExp][] = [
    [
      "half a pair",
      (row) => {
        const source = { ...(row.source as Json) };
        delete source.recorded_unit;
        return { ...row, source };
      },
      /records 7\.716 undefined/,
    ],
    [
      "an unscaled recorded unit",
      (row) => ({
        ...row,
        source: { ...(row.source as Json), recorded_unit: "percent" },
      }),
      /records 7\.716 "percent"/,
    ],
    [
      "a recorded value that is no number",
      (row) => ({
        ...row,
        source: { ...(row.source as Json), recorded_value: "7.716" },
      }),
      /records "7\.716" "millions"/,
    ],
    [
      "a stored value the pair does not state",
      (row) => ({ ...row, value: 7_716_001 }),
      /records 7\.716 millions but stores 7716001/,
    ],
    [
      "a stored unit outside the pair's base",
      (row) => ({ ...row, measure: { ...(row.measure as Json), unit: "usd" } }),
      /records millions but stores "usd"/,
    ],
    [
      "a scaled stored unit",
      (row) => ({
        ...row,
        measure: { ...(row.measure as Json), unit: "millions" },
      }),
      /records millions but stores "millions"/,
    ],
  ];

  it.each(refusals)("refuses %s", (_name, change, message) => {
    const written = baseRowOf(scaledRow(), "millions");
    const tampered = withVersion(change(written), null);
    expect(() => parsePolicyEngineLedgerFacts(ledger(tampered))).toThrow(
      message,
    );
  });
});

// ---------------------------------------------------------------------------
// Gated ledgers holding scaled rows: valid append sequences, restated.
// ---------------------------------------------------------------------------

type Op =
  | { kind: "new"; preVersioning: boolean; value: number; unit: string }
  | { kind: "correct"; record: number; delta: number };

const op: fc.Arbitrary<Op> = fc.oneof(
  fc.record({
    kind: fc.constant("new" as const),
    preVersioning: fc.boolean(),
    value: fc.integer({ min: -9_999, max: 9_999 }).map((n) => n / 10),
    unit: fc.constantFrom(...SCALED, "percent", "count", "usd"),
  }),
  fc.record({
    kind: fc.constant("correct" as const),
    record: fc.nat(),
    delta: fc.integer({ min: 1, max: 9 }),
  }),
);

function build(ops: Op[]): Json[] {
  const rows: Json[] = [];
  const latest = new Map<string, Json>();
  const records: string[] = [];
  for (const step of ops) {
    if (step.kind === "new" || records.length === 0) {
      const id = `gated.p${records.length}.first_print`;
      const row = scaledRow({
        source_record_id: id,
        value: step.kind === "new" ? step.value : 1,
        measure: {
          unit: step.kind === "new" ? step.unit : "thousands",
          concept: "gated",
        },
      });
      delete row.sourceBindingProjection;
      const stored =
        step.kind === "new" && step.preVersioning
          ? row
          : withVersion(row, null);
      records.push(id);
      latest.set(id, stored);
      rows.push(stored);
      continue;
    }
    const id = records[step.record % records.length];
    const previous = latest.get(id)!;
    const correction = withVersion(
      {
        ...previous,
        value: Math.round(((previous.value as number) + step.delta) * 10) / 10,
      },
      effectiveAssertionId(previous),
    );
    latest.set(id, correction);
    rows.push(correction);
  }
  return JSON.parse(JSON.stringify(rows)) as Json[];
}

describe("restating any gated ledger", () => {
  const ops = fc.array(op, { minLength: 1, maxLength: 14 });

  it("leaves the entries byte-identical", () => {
    fc.assert(
      fc.property(ops, (steps) => {
        const rows = build(steps);
        const lines = rows.map((row) => JSON.stringify(row));
        assertAppendGateAssertionVersions(rows);
        const restated = currentScaledLines(lines);
        const restatements = restated.map((line) => restatementOf(line));
        const all = [...rows, ...restatements];
        assertAppendGateAssertionVersions(all);
        const before = read(lines.join("\n"));
        const after = read(
          [...lines, ...restatements.map((row) => JSON.stringify(row))].join(
            "\n",
          ),
        );
        expect(JSON.stringify(after.entries)).toBe(
          JSON.stringify(before.entries),
        );
        expect(after.restatements).toHaveLength(restated.length);
      }),
    );
  });

  it("leaves nothing to restate the second time", () => {
    fc.assert(
      fc.property(ops, (steps) => {
        const lines = build(steps).map((row) => JSON.stringify(row));
        const restated = currentScaledLines(lines).map((line) =>
          JSON.stringify(restatementOf(line)),
        );
        expect(currentScaledLines([...lines, ...restated])).toEqual([]);
      }),
    );
  });
});
