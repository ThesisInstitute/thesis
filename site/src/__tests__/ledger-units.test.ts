import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { formatValue } from "@/data/forecast-display";
import {
  isObservationRecordedLedgerEntry,
  parsePolicyEngineLedgerFacts,
} from "@/data/thesis-log";
import { UNITS, isUnit } from "@/data/units";

// 2026-10-17: the resolver appended the first ledger row in the registered
// unit "billions USD" (Chronicle dd929cba, line 234). The Unit type admitted
// it, but thesis-log.ts checked ledger rows against its own shorter list, so
// every production build at that pin failed in page-data collection.

const DOD_ROW = readFileSync(
  join(__dirname, "fixtures/ledger-row-dod-prime-contract-obligations-fy2026.jsonl"),
  "utf8",
);

// mulberry32: a seeded generator, so a failure replays exactly.
function generator(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function factWithUnit(unit: unknown): string {
  return JSON.stringify({
    source_record_id: "series.test.2026",
    observed_at: "2026-10-17",
    value: 1,
    period: { type: "year", value: "2026" },
    measure: { unit },
    source: { source_name: "bls", source_table: "t", url: "https://x.test" },
  });
}

// Strings that are not units: near misses of every unit plus random text.
function nonUnits(): string[] {
  const random = generator(20261017);
  const alphabet = "abcdefghijklmnopqrstuvwxyz_ USDB0123456789";
  const out: string[] = ["", "billions usd", "USD billions", "billions_usd"];
  for (const unit of UNITS) {
    out.push(unit.toUpperCase(), ` ${unit}`, `${unit} `, `${unit}s`);
    out.push(unit.slice(0, -1), unit.replace("_", " "));
  }
  for (let i = 0; i < 500; i += 1) {
    const length = 1 + Math.floor(random() * 16);
    let text = "";
    for (let j = 0; j < length; j += 1) {
      text += alphabet[Math.floor(random() * alphabet.length)];
    }
    out.push(text);
  }
  const units = new Set<string>(UNITS);
  return out.filter((text) => !units.has(text));
}

describe("ledger fact units", () => {
  it("accepts the real DoD row appended at Chronicle dd929cba", () => {
    const [entry] = parsePolicyEngineLedgerFacts(DOD_ROW);
    if (!isObservationRecordedLedgerEntry(entry)) {
      throw new Error("expected an observation_recorded entry");
    }
    expect(entry).toMatchObject({
      dataPointId:
        "usaspending.dod.prime_contract_obligations.fy2026.registered_query_snapshot",
      unit: "billions USD",
      value: 395.1,
    });
    expect(formatValue(entry.value, entry.unit)).toBe("$395.1B");
  });

  it("accepts a ledger row in every unit the Unit type admits", () => {
    for (const unit of UNITS) {
      const [entry] = parsePolicyEngineLedgerFacts(factWithUnit(unit));
      expect(entry.unit).toBe(unit);
    }
  });

  it("refuses a ledger row in any other unit, naming it", () => {
    for (const unit of [...nonUnits(), null, 3, undefined]) {
      expect(() => parsePolicyEngineLedgerFacts(factWithUnit(unit))).toThrow(
        `has unsupported unit ${String(unit)}`,
      );
    }
  });

  it("isUnit holds exactly for members of UNITS", () => {
    for (const unit of UNITS) expect(isUnit(unit)).toBe(true);
    for (const text of nonUnits()) expect(isUnit(text)).toBe(false);
    for (const value of [null, undefined, 0, {}, ["percent"]]) {
      expect(isUnit(value)).toBe(false);
    }
  });

  it("lists each unit once", () => {
    expect(new Set(UNITS).size).toBe(UNITS.length);
  });
});

describe("unit display", () => {
  it('shows "billions USD" exactly as "usd_billions"', () => {
    const random = generator(395);
    const values = [0, -0, 0.04, 0.05, 395.1, -12.34, 1e6, 123456.789];
    for (let i = 0; i < 500; i += 1) {
      values.push((random() - 0.5) * 10 ** Math.floor(random() * 9));
    }
    for (const value of values) {
      expect(formatValue(value, "billions USD")).toBe(
        formatValue(value, "usd_billions"),
      );
    }
  });

  it("gives every unit its own format, not the raw-number fallback", () => {
    for (const unit of UNITS) {
      expect(formatValue(1234.5, unit), unit).not.toBe(String(1234.5));
    }
  });
});
